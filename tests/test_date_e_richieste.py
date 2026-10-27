"""Le date della pratica sono quelle delle fonti, non dell'importazione; e le richieste del cliente senza risposta."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tests.test_classificazione import ClassificatoreFinto, _account, _messaggio

from pmo.db.models import (
    Pratica,
    StatoMessaggio,
    StatoPratica,
    StatoVerifica,
    TipoEvento,
    TipoFonte,
)
from pmo.ingest.catalogo import carica_catalogo
from pmo.ingest.classifier import (
    EventoEstratto,
    PraticaProposta,
    RisultatoMessaggio,
)
from pmo.ingest.gmail_sync import classifica_messaggi
from pmo.services import pratiche as svc
from pmo.services.richieste import richieste_in_attesa


def _in_utc(valore: datetime) -> datetime:
    return valore if valore.tzinfo is not None else valore.replace(tzinfo=UTC)


def test_pratica_proposta_nasce_alla_data_della_mail(db, settings):
    acc = _account(db)
    m = _messaggio(db, acc, "v1", "tv1", "Richiesta stima", "Vorremmo una stima per il modulo X", giorni_fa=90)
    risposta = RisultatoMessaggio(
        id="v1",
        rilevante=True,
        motivo="richiesta di stima",
        collegamento="nuova",
        pratica_codice=None,
        pratica_nuova=PraticaProposta(titolo="Modulo X - stima", cliente=None, prodotto=None, descrizione="", stato_iniziale="stima"),
        confidenza_collegamento=0.9,
        eventi=[EventoEstratto(tipo="stima_richiesta", data=None, titolo="Stima richiesta", descrizione="", importo_eur=None, scadenza=None, confidenza=0.9)],
        riferimenti=[],
    )
    classifica_messaggi(db, acc, settings, classificatore=ClassificatoreFinto({"v1": risposta}), catalogo=carica_catalogo(db, settings))
    db.refresh(m)
    pratica = m.pratica
    assert pratica is not None
    # non la data di oggi (quella dell'importazione) ma quella della mail di novanta giorni fa
    assert pratica.data_apertura == _in_utc(m.data).date()
    assert abs(_in_utc(pratica.stato_dal) - _in_utc(m.data)) < timedelta(seconds=1)
    # l'evento è ancora solo proposto, ma l'ultima attività si conosce lo stesso
    assert pratica.ultimo_evento_at is not None
    assert abs(_in_utc(pratica.ultimo_evento_at) - _in_utc(m.data)) < timedelta(seconds=1)


def test_ricalcola_date_corregge_le_pratiche_gia_importate(db, settings):
    acc = _account(db)
    adesso = datetime.now(UTC)
    pratica = svc.crea_pratica(db, "Vecchia pratica", origine="ai", stato_verifica=StatoVerifica.PROPOSTO, account_id=acc.id)
    assert pratica.data_apertura == adesso.date()  # il difetto: nasce oggi
    m = _messaggio(db, acc, "r1", "tr1", "Oggetto", "testo", giorni_fa=60)
    m.pratica_id = pratica.id
    svc.aggiungi_evento(
        db, pratica, tipo=TipoEvento.NOTA.value, titolo="Mail di due mesi fa", data_evento=m.data,
        fonte_tipo=TipoFonte.EMAIL, stato_verifica=StatoVerifica.PROPOSTO,
    )
    svc.aggiungi_evento(
        db, pratica, tipo=TipoEvento.SCADENZA.value, titolo="Scadenza tra dieci giorni", data_evento=adesso + timedelta(days=10),
        fonte_tipo=TipoFonte.EMAIL, stato_verifica=StatoVerifica.PROPOSTO,
    )
    pratica.ultimo_evento_at = None  # come nelle pratiche importate prima della correzione
    db.flush()
    db.refresh(pratica)

    esito = svc.ricalcola_date(db)
    assert esito["apertura"] == 1
    assert pratica.data_apertura == _in_utc(m.data).date()
    assert abs(_in_utc(pratica.ultimo_evento_at) - _in_utc(m.data)) < timedelta(seconds=1)  # la scadenza futura non conta
    assert svc.ricalcola_date(db)["apertura"] == 0  # idempotente


def _pratica_con_richiesta(db, acc, giorni_fa=10, tipo=TipoEvento.RICHIESTA_INFORMAZIONI.value, **kw) -> tuple[Pratica, object]:
    pratica = svc.crea_pratica(db, "Pratica di prova", origine="ai", stato_verifica=StatoVerifica.PROPOSTO, account_id=acc.id)
    m = _messaggio(db, acc, f"q{pratica.id}", f"tq{pratica.id}", "Richiesta", "Potete inviarci il DURC?", giorni_fa=giorni_fa, **kw)
    m.pratica_id = pratica.id
    svc.aggiungi_evento(
        db, pratica, tipo=tipo, titolo="Il cliente chiede il DURC", data_evento=m.data,
        fonte_tipo=TipoFonte.EMAIL, messaggio_id=m.id, stato_verifica=StatoVerifica.PROPOSTO,
    )
    db.flush()
    return pratica, m


def test_richiesta_del_cliente_senza_risposta_e_in_attesa(db, settings):
    acc = _account(db)
    pratica, m = _pratica_con_richiesta(db, acc, giorni_fa=10)
    trovate = richieste_in_attesa(db)
    assert list(trovate) == [pratica.id]
    r = trovate[pratica.id][0]
    assert r.messaggio_id == m.id and r.giorni in (9, 10) and "DURC" in r.titolo and r.mittente


def test_una_nostra_mail_successiva_chiude_la_richiesta(db, settings):
    acc = _account(db)
    pratica, _ = _pratica_con_richiesta(db, acc, giorni_fa=10)
    risposta = _messaggio(db, acc, "ris1", "tris1", "Re: Richiesta", "Inviato il DURC", giorni_fa=5, from_email="egravela@latraccia.it")
    risposta.pratica_id = pratica.id
    risposta.to_emails = ["stefano@hsangiovanni.roma.it"]  # una risposta va al cliente, non a un collega
    db.flush()
    assert richieste_in_attesa(db) == {}


def test_un_inoltro_interno_non_chiude_la_richiesta(db, settings):
    acc = _account(db)
    pratica, _ = _pratica_con_richiesta(db, acc, giorni_fa=10)
    inoltro = _messaggio(db, acc, "fwd1", "tfwd1", "Fwd: Richiesta", "Pasquale, ci pensi tu?", giorni_fa=9, from_email="egravela@latraccia.it")
    inoltro.pratica_id = pratica.id
    inoltro.to_emails = ["ploizzo@latraccia.it"]  # solo interna: nessuno ha risposto al cliente
    db.flush()
    assert list(richieste_in_attesa(db)) == [pratica.id]


def test_una_nostra_mail_precedente_non_chiude_la_richiesta(db, settings):
    acc = _account(db)
    pratica, _ = _pratica_con_richiesta(db, acc, giorni_fa=3)
    prima = _messaggio(db, acc, "pri1", "tpri1", "Offerta", "In allegato l'offerta", giorni_fa=20, from_email="egravela@latraccia.it")
    prima.pratica_id = pratica.id
    db.flush()
    assert list(richieste_in_attesa(db)) == [pratica.id]


def test_richiesta_ignorata_se_pratica_chiusa_o_evento_di_altro_tipo(db, settings):
    acc = _account(db)
    chiusa, _ = _pratica_con_richiesta(db, acc)
    chiusa.stato = StatoPratica.CHIUSA.value
    _pratica_con_richiesta(db, acc, tipo=TipoEvento.NOTA.value)
    db.flush()
    assert richieste_in_attesa(db) == {}
    assert richieste_in_attesa(db, []) == {}


def test_mail_scartata_non_genera_richieste(db, settings):
    acc = _account(db)
    pratica, m = _pratica_con_richiesta(db, acc)
    m.stato = StatoMessaggio.IGNORATO
    db.flush()
    assert richieste_in_attesa(db, [pratica.id]) == {}
