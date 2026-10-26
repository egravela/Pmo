"""Filtro "Azioni da fare" dell'elenco pratiche: richieste del cliente, solleciti aperti, scadenze."""

from __future__ import annotations

from datetime import date, timedelta

from tests.test_classificazione import _account
from tests.test_date_e_richieste import _pratica_con_richiesta
from tests.test_design_system import _login, client  # noqa: F401

from pmo.db.models import Sollecito, StatoPratica, StatoSollecito, StatoVerifica
from pmo.services import pratiche as svc
from pmo.services.richieste import GIORNI_SCADENZA_VICINA, pratiche_con_azioni, scadenze_vicine


def _scenario(db):
    acc = _account(db)
    con_richiesta, _ = _pratica_con_richiesta(db, acc, giorni_fa=6)
    con_sollecito = svc.crea_pratica(db, "Pratica con sollecito", stato_verifica=StatoVerifica.CONFERMATO)
    db.add(Sollecito(pratica_id=con_sollecito.id, regola="ordine_senza_specifiche", chiave=f"{con_sollecito.id}:osp", titolo="Ordine senza specifiche"))
    scaduta = svc.crea_pratica(db, "Pratica scaduta", stato_verifica=StatoVerifica.CONFERMATO, data_scadenza=date.today() - timedelta(days=3))
    lontana = svc.crea_pratica(db, "Scadenza lontana", stato_verifica=StatoVerifica.CONFERMATO, data_scadenza=date.today() + timedelta(days=GIORNI_SCADENZA_VICINA + 30))
    tranquilla = svc.crea_pratica(db, "Nessuna azione", stato_verifica=StatoVerifica.CONFERMATO)
    # pratica ancora proposta dall'IA: la scadenza sta solo nell'evento estratto dalla mail, non sulla pratica
    da_evento = svc.crea_pratica(db, "Scadenza da una mail", origine="ai", stato_verifica=StatoVerifica.PROPOSTO)
    svc.aggiungi_evento(
        db, da_evento, tipo="scadenza", titolo="Rilascio entro il", scadenza=date.today() + timedelta(days=5),
        fonte_tipo="email", stato_verifica=StatoVerifica.PROPOSTO,
    )
    # scadenza già passata indicata da un evento: non si sa se sia stata rispettata, quindi non conta
    passata = svc.crea_pratica(db, "Scadenza passata da una mail", origine="ai", stato_verifica=StatoVerifica.PROPOSTO)
    svc.aggiungi_evento(
        db, passata, tipo="scadenza", titolo="Era entro il", scadenza=date.today() - timedelta(days=5),
        fonte_tipo="email", stato_verifica=StatoVerifica.PROPOSTO,
    )
    db.flush()
    return con_richiesta, con_sollecito, scaduta, lontana, tranquilla, da_evento, passata


def test_azioni_da_fare_per_motivo(db, settings):
    richiesta, sollecito, scaduta, lontana, tranquilla, da_evento, passata = _scenario(db)
    azioni = pratiche_con_azioni(db)
    assert azioni["risposta"] == {richiesta.id}
    assert azioni["solleciti"] == {sollecito.id}
    # contano la scadenza già superata e quella vicina indicata da una mail; non quella lontana né quella passata di una mail
    assert azioni["scadenza"] == {scaduta.id, da_evento.id}
    assert azioni["qualsiasi"] == {richiesta.id, sollecito.id, scaduta.id, da_evento.id}
    assert not {lontana.id, tranquilla.id, passata.id} & azioni["qualsiasi"]


def test_il_promemoria_di_conferma_non_e_un_azione_da_fare(db, settings):
    _, _, _, _, tranquilla, *_ = _scenario(db)
    db.add(Sollecito(pratica_id=tranquilla.id, regola="da_verificare", chiave=f"{tranquilla.id}:dv", gravita="info", titolo="Pratica proposta dall'IA da confermare"))
    db.flush()
    azioni = pratiche_con_azioni(db)
    assert tranquilla.id not in azioni["solleciti"] and tranquilla.id not in azioni["qualsiasi"]


def test_scadenza_piu_urgente_per_pratica(db, settings):
    _, _, scaduta, _, _, da_evento, passata = _scenario(db)
    scadenze = scadenze_vicine(db)
    assert scadenze[scaduta.id] == date.today() - timedelta(days=3)
    assert scadenze[da_evento.id] == date.today() + timedelta(days=5)
    assert passata.id not in scadenze


def test_sollecito_rimandato_o_risolto_e_pratica_chiusa_non_contano(db, settings):
    _, sollecito, scaduta, *_ = _scenario(db)
    s = db.query(Sollecito).filter_by(pratica_id=sollecito.id).one()
    s.snooze_fino = date.today() + timedelta(days=5)
    scaduta.stato = StatoPratica.CHIUSA.value
    db.flush()
    azioni = pratiche_con_azioni(db)
    assert sollecito.id not in azioni["solleciti"]  # rimandato a una data futura
    assert scaduta.id not in azioni["scadenza"]  # pratica chiusa
    s.snooze_fino = None
    s.stato = StatoSollecito.RISOLTO.value
    db.flush()
    assert sollecito.id not in pratiche_con_azioni(db)["solleciti"]


def test_elenco_filtra_per_azione(client, db):  # noqa: F811
    richiesta, sollecito, scaduta, lontana, tranquilla, da_evento, passata = _scenario(db)
    db.commit()
    _login(client)
    tutte = {p.codice for p in (richiesta, sollecito, scaduta, lontana, tranquilla, da_evento, passata)}

    def presenti(percorso: str) -> set[str]:
        html = client.get(percorso).text
        return {codice for codice in tutte if codice in html}

    assert presenti("/pratiche?azione=risposta") == {richiesta.codice}
    assert presenti("/pratiche?azione=solleciti") == {sollecito.codice}
    assert presenti("/pratiche?azione=scadenza") == {scaduta.codice, da_evento.codice}
    assert presenti("/pratiche?azione=qualsiasi") == {richiesta.codice, sollecito.codice, scaduta.codice, da_evento.codice}
    assert presenti("/pratiche?richieste=1") == {richiesta.codice}  # vecchio nome, usato dai link già esistenti
    assert presenti("/pratiche") == tutte
    assert presenti("/pratiche?azione=inesistente") == tutte  # un valore sconosciuto non nasconde le pratiche
