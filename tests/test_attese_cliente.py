"""Noi aspettiamo il cliente: mail nostre con un'offerta o una richiesta, senza risposta; e cambio di fase dalla scheda."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.test_classificazione import _account, _messaggio
from tests.test_design_system import _login, client  # noqa: F401

from pmo.db.models import Pratica, StatoMessaggio, StatoPratica, StatoVerifica, TipoEvento, TipoFonte
from pmo.services import pratiche as svc
from pmo.services.richieste import attese_cliente, pratiche_con_azioni, richieste_in_attesa

CLIENTE = "stefano@hsangiovanni.roma.it"
NOI = "egravela@latraccia.it"


def _offerta_inviata(db, acc, giorni_fa=10, tipo=TipoEvento.OFFERTA_INVIATA.value, a=CLIENTE):
    """Una pratica con una nostra mail a `a` che contiene un evento di `tipo`."""
    pratica = svc.crea_pratica(db, "Offerta di prova", origine="ai", stato_verifica=StatoVerifica.PROPOSTO, account_id=acc.id)
    m = _messaggio(db, acc, f"o{pratica.id}", f"to{pratica.id}", "Offerta", "In allegato l'offerta", giorni_fa=giorni_fa, from_email=NOI)
    m.pratica_id = pratica.id
    m.to_emails = [a]
    svc.aggiungi_evento(
        db, pratica, tipo=tipo, titolo="Offerta inviata al cliente", data_evento=m.data,
        fonte_tipo=TipoFonte.EMAIL, messaggio_id=m.id, stato_verifica=StatoVerifica.PROPOSTO,
    )
    db.flush()
    return pratica, m


def test_offerta_senza_risposta_del_cliente_e_in_attesa(db, settings):
    acc = _account(db)
    pratica, m = _offerta_inviata(db, acc, giorni_fa=12)
    trovate = attese_cliente(db)
    assert list(trovate) == [pratica.id]
    a = trovate[pratica.id][0]
    assert a.messaggio_id == m.id and a.controparte == CLIENTE and a.giorni in (11, 12)
    assert richieste_in_attesa(db) == {}  # è una nostra mail: non è una richiesta del cliente


def test_una_mail_del_cliente_successiva_chiude_l_attesa(db, settings):
    acc = _account(db)
    pratica, _ = _offerta_inviata(db, acc, giorni_fa=10)
    risposta = _messaggio(db, acc, "rc1", "trc1", "Re: Offerta", "Va bene", giorni_fa=4, from_email=CLIENTE)
    risposta.pratica_id = pratica.id
    db.flush()
    assert attese_cliente(db) == {}


def test_una_mail_del_cliente_precedente_non_chiude_l_attesa(db, settings):
    acc = _account(db)
    pratica, _ = _offerta_inviata(db, acc, giorni_fa=3)
    prima = _messaggio(db, acc, "rp1", "trp1", "Richiesta", "Mandateci un'offerta", giorni_fa=20, from_email=CLIENTE)
    prima.pratica_id = pratica.id
    db.flush()
    assert list(attese_cliente(db)) == [pratica.id]


def test_un_ordine_arrivato_senza_mail_chiude_l_attesa(db, settings):
    acc = _account(db)
    pratica, _ = _offerta_inviata(db, acc, giorni_fa=10)
    svc.aggiungi_evento(
        db, pratica, tipo=TipoEvento.ORDINE_RICEVUTO.value, titolo="Ordine firmato (Drive)",
        data_evento=datetime.now(UTC) - timedelta(days=2), fonte_tipo=TipoFonte.DRIVE, stato_verifica=StatoVerifica.PROPOSTO,
    )
    db.flush()
    assert attese_cliente(db) == {}


def test_nostra_mail_solo_interna_non_aspetta_il_cliente_e_altri_casi_esclusi(db, settings):
    acc = _account(db)
    _offerta_inviata(db, acc, a="ploizzo@latraccia.it")  # per un collega, non per il cliente
    _offerta_inviata(db, acc, tipo=TipoEvento.NOTA.value)  # nessuna offerta o richiesta
    chiusa, _ = _offerta_inviata(db, acc)
    chiusa.stato = StatoPratica.CHIUSA.value
    scartata, m = _offerta_inviata(db, acc)
    m.stato = StatoMessaggio.IGNORATO
    db.flush()
    assert attese_cliente(db) == {}
    assert attese_cliente(db, []) == {}


def test_le_azioni_distinguono_i_due_sensi(db, settings):
    acc = _account(db)
    aspettiamo, _ = _offerta_inviata(db, acc)
    from tests.test_date_e_richieste import _pratica_con_richiesta

    aspetta_noi, _ = _pratica_con_richiesta(db, acc)
    azioni = pratiche_con_azioni(db)
    assert azioni["risposta"] == {aspetta_noi.id}
    assert azioni["attesa_cliente"] == {aspettiamo.id}
    assert azioni["attese"] == {aspetta_noi.id, aspettiamo.id}
    assert azioni["qualsiasi"] == {aspetta_noi.id}  # l'attesa del cliente non è un'azione che spetta a noi


def test_elenco_filtra_e_mostra_le_attese(client, db):  # noqa: F811
    acc = _account(db)
    aspettiamo, _ = _offerta_inviata(db, acc)
    from tests.test_date_e_richieste import _pratica_con_richiesta

    aspetta_noi, _ = _pratica_con_richiesta(db, acc)
    db.commit()
    _login(client)

    def presenti(percorso: str) -> set[str]:
        html = client.get(percorso).text
        return {p.codice for p in (aspettiamo, aspetta_noi) if p.codice in html}

    assert presenti("/pratiche?azione=attesa_cliente") == {aspettiamo.codice}
    assert presenti("/pratiche?azione=risposta") == {aspetta_noi.codice}
    assert presenti("/pratiche?azione=attese") == {aspettiamo.codice, aspetta_noi.codice}
    pagina = client.get("/pratiche").text
    assert "Aspettiamo il cliente" in pagina and "Il cliente aspetta noi" in pagina
    assert client.get(f"/pratiche/{aspettiamo.id}").text.count("Aspettiamo una risposta dal cliente") == 1


def test_cambio_di_fase_dalla_scheda_torna_all_elenco_con_i_filtri(client, db):  # noqa: F811
    pratica = svc.crea_pratica(db, "Pratica da spostare", stato_verifica=StatoVerifica.CONFERMATO)
    db.commit()
    _login(client)
    pagina = client.get("/pratiche?q=spostare").text
    assert f'action="/pratiche/{pratica.id}/stato"' in pagina  # ogni scheda ha il suo modulo
    assert 'name="ritorno" value="/pratiche?q=spostare"' in pagina

    csrf = pagina.split('name="csrf_token" value="')[1].split('"')[0]
    risposta = client.post(
        f"/pratiche/{pratica.id}/stato", data={"stato": "ordine", "ritorno": "/pratiche?q=spostare&pagina=1", "csrf_token": csrf}
    )
    assert risposta.status_code == 303 and risposta.headers["location"] == "/pratiche?q=spostare&pagina=1"
    db.expire_all()
    assert db.get(Pratica, pratica.id).stato == "ordine"


def test_il_ritorno_non_porta_fuori_dalle_pratiche(client, db):  # noqa: F811
    pratica = svc.crea_pratica(db, "Pratica sicura", stato_verifica=StatoVerifica.CONFERMATO)
    db.commit()
    _login(client)
    csrf = client.get("/pratiche").text.split('name="csrf_token" value="')[1].split('"')[0]
    for ritorno in ("https://example.com/", "//example.com", "/solleciti", "/pratiche\\evil"):
        risposta = client.post(f"/pratiche/{pratica.id}/stato", data={"stato": "sviluppo", "ritorno": ritorno, "csrf_token": csrf})
        assert risposta.status_code == 303
        assert risposta.headers["location"] == f"/pratiche/{pratica.id}", ritorno
