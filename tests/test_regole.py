from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from pmo.db.models import Sollecito, StatoPratica, StatoSollecito, StatoVerifica, TipoEvento
from pmo.rules.engine import esegui_regole
from pmo.services import pratiche as svc
from pmo.services.digest import componi_digest


def _pratica(db, titolo, stato, giorni_in_stato=0, **kw):
    p = svc.crea_pratica(db, titolo, stato=stato, **kw)
    p.stato_dal = datetime.now(UTC) - timedelta(days=giorni_in_stato)
    p.ultimo_evento_at = p.stato_dal
    db.flush()
    return p


def _solleciti(db, pratica):
    return {s.regola: s for s in db.scalars(select(Sollecito).where(Sollecito.pratica_id == pratica.id)).all()}


def test_ordine_senza_specifiche_e_risoluzione_automatica(db):
    p = _pratica(db, "Ordine fermo", StatoPratica.ORDINE, giorni_in_stato=20)
    esegui_regole(db)
    s = _solleciti(db, p)
    assert "ordine_senza_specifiche" in s and s["ordine_senza_specifiche"].stato == StatoSollecito.APERTO
    assert s["ordine_senza_specifiche"].gravita == "avviso"
    # arrivano le specifiche: la pratica avanza e il sollecito si risolve da solo
    svc.aggiungi_evento(db, p, tipo=TipoEvento.SPECIFICHE_RICEVUTE, titolo="Specifiche ricevute")
    esegui_regole(db)
    s = _solleciti(db, p)
    assert s["ordine_senza_specifiche"].stato == StatoSollecito.RISOLTO and s["ordine_senza_specifiche"].risolto_da == "sistema"


def test_scadenze(db):
    vicina = _pratica(db, "Scade presto", StatoPratica.SVILUPPO, data_scadenza=date.today() + timedelta(days=3))
    superata = _pratica(db, "Scaduta", StatoPratica.SVILUPPO, data_scadenza=date.today() - timedelta(days=2))
    esegui_regole(db)
    assert "scadenza_vicina" in _solleciti(db, vicina)
    assert _solleciti(db, superata)["scadenza_superata"].gravita == "critico"
    assert "scadenza_vicina" not in _solleciti(db, superata)


def test_consegnato_non_fatturato_e_differenza_importi(db):
    consegnata = _pratica(db, "Consegnata", StatoPratica.CONSEGNA, giorni_in_stato=45)
    fatturata = _pratica(db, "Fatturata male", StatoPratica.FATTURAZIONE, importo_ordine=Decimal("10000"))
    fatturata.importo_fatturato = Decimal("9000")
    esegui_regole(db)
    assert _solleciti(db, consegnata)["consegnato_non_fatturato"].gravita == "critico"
    diff = _solleciti(db, fatturata)["fatturato_diverso_da_ordinato"]
    assert diff.dati["differenza"] == -1000.0


def test_offerta_stima_inattiva(db):
    offerta = _pratica(db, "Offerta vecchia", StatoPratica.OFFERTA, giorni_in_stato=40)
    stima = _pratica(db, "Stima mai inviata", StatoPratica.STIMA, giorni_in_stato=10)
    ferma = _pratica(db, "Ferma", StatoPratica.SPECIFICHE, giorni_in_stato=35)
    fresca = _pratica(db, "Fresca", StatoPratica.SPECIFICHE, giorni_in_stato=1)
    esegui_regole(db)
    assert "offerta_senza_risposta" in _solleciti(db, offerta)
    assert "stima_in_attesa" in _solleciti(db, stima)
    assert "pratica_inattiva" in _solleciti(db, ferma)
    assert _solleciti(db, fresca) == {}


def test_pratica_proposta_e_snooze(db):
    p = _pratica(db, "Proposta IA", StatoPratica.ORDINE, giorni_in_stato=30, origine="ai", stato_verifica=StatoVerifica.PROPOSTO)
    p.created_at = datetime.now(UTC) - timedelta(days=5)
    esegui_regole(db)
    s = _solleciti(db, p)
    assert list(s) == ["da_verificare"]  # per le proposte vale solo questa regola
    sollecito = s["da_verificare"]
    sollecito.stato = StatoSollecito.SILENZIATO
    sollecito.snooze_fino = date.today() + timedelta(days=3)
    db.flush()
    esegui_regole(db)
    assert sollecito.stato == StatoSollecito.SILENZIATO
    sollecito.snooze_fino = date.today() - timedelta(days=1)
    db.flush()
    esegui_regole(db)
    assert sollecito.stato == StatoSollecito.APERTO and sollecito.occorrenze == 2


def test_pratiche_chiuse_non_generano_solleciti(db):
    p = _pratica(db, "Chiusa", StatoPratica.CHIUSA, giorni_in_stato=100, data_scadenza=date.today() - timedelta(days=50))
    esegui_regole(db)
    assert _solleciti(db, p) == {}


def test_digest_elenca_i_solleciti(db, settings):
    p = _pratica(db, "Ordine fermo", StatoPratica.ORDINE, giorni_in_stato=20)
    esegui_regole(db)
    contenuto = componi_digest(db, settings)
    assert p.codice in contenuto.testo and "senza specifiche" in contenuto.testo
    assert contenuto.contatori["solleciti"] == 1 and contenuto.contatori["nuovi"] == 1
    assert "<h2>" in contenuto.html
