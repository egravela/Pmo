"""Filtro "Azioni da fare" dell'elenco pratiche: richieste del cliente, solleciti aperti, scadenze."""

from __future__ import annotations

from datetime import date, timedelta

from tests.test_classificazione import _account
from tests.test_date_e_richieste import _pratica_con_richiesta
from tests.test_design_system import _login, client  # noqa: F401

from pmo.db.models import Sollecito, StatoPratica, StatoSollecito, StatoVerifica
from pmo.services import pratiche as svc
from pmo.services.richieste import GIORNI_SCADENZA_VICINA, pratiche_con_azioni


def _scenario(db):
    acc = _account(db)
    con_richiesta, _ = _pratica_con_richiesta(db, acc, giorni_fa=6)
    con_sollecito = svc.crea_pratica(db, "Pratica con sollecito", stato_verifica=StatoVerifica.CONFERMATO)
    db.add(Sollecito(pratica_id=con_sollecito.id, regola="ordine_senza_specifiche", chiave=f"{con_sollecito.id}:osp", titolo="Ordine senza specifiche"))
    scaduta = svc.crea_pratica(db, "Pratica scaduta", stato_verifica=StatoVerifica.CONFERMATO, data_scadenza=date.today() - timedelta(days=3))
    lontana = svc.crea_pratica(db, "Scadenza lontana", stato_verifica=StatoVerifica.CONFERMATO, data_scadenza=date.today() + timedelta(days=GIORNI_SCADENZA_VICINA + 30))
    tranquilla = svc.crea_pratica(db, "Nessuna azione", stato_verifica=StatoVerifica.CONFERMATO)
    db.flush()
    return con_richiesta, con_sollecito, scaduta, lontana, tranquilla


def test_azioni_da_fare_per_motivo(db, settings):
    richiesta, sollecito, scaduta, lontana, tranquilla = _scenario(db)
    azioni = pratiche_con_azioni(db)
    assert azioni["risposta"] == {richiesta.id}
    assert azioni["solleciti"] == {sollecito.id}
    assert azioni["scadenza"] == {scaduta.id}  # la scadenza lontana e la pratica tranquilla non contano
    assert azioni["qualsiasi"] == {richiesta.id, sollecito.id, scaduta.id}
    assert lontana.id not in azioni["qualsiasi"] and tranquilla.id not in azioni["qualsiasi"]


def test_sollecito_rimandato_o_risolto_e_pratica_chiusa_non_contano(db, settings):
    _, sollecito, scaduta, _, _ = _scenario(db)
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
    richiesta, sollecito, scaduta, lontana, tranquilla = _scenario(db)
    db.commit()
    _login(client)

    def presenti(percorso: str) -> set[str]:
        html = client.get(percorso).text
        return {p.codice for p in (richiesta, sollecito, scaduta, lontana, tranquilla) if p.codice in html}

    assert presenti("/pratiche?azione=risposta") == {richiesta.codice}
    assert presenti("/pratiche?azione=solleciti") == {sollecito.codice}
    assert presenti("/pratiche?azione=scadenza") == {scaduta.codice}
    assert presenti("/pratiche?azione=qualsiasi") == {richiesta.codice, sollecito.codice, scaduta.codice}
    assert presenti("/pratiche?richieste=1") == {richiesta.codice}  # vecchio nome, usato dai link già esistenti
    tutte = {p.codice for p in (richiesta, sollecito, scaduta, lontana, tranquilla)}
    assert presenti("/pratiche") == tutte
    assert presenti("/pratiche?azione=inesistente") == tutte  # un valore sconosciuto non nasconde le pratiche
