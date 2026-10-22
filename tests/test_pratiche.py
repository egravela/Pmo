from datetime import UTC, date, datetime
from decimal import Decimal

from pmo.db.models import Cliente, StatoPratica, StatoVerifica, TipoEvento, TipoFonte
from pmo.services import pratiche as svc


def test_codici_progressivi(db):
    p1 = svc.crea_pratica(db, "Prima")
    p2 = svc.crea_pratica(db, "Seconda")
    anno = date.today().year
    assert p1.codice == f"PMO-{anno}-0001" and p2.codice == f"PMO-{anno}-0002"
    assert p1.tag == f"[PMO-{anno}-0001]"
    assert svc.trova_per_codice(db, p2.codice.lower()) is p2


def test_eventi_avanzano_lo_stato_e_gli_importi(db):
    cliente = Cliente(nome="ASL Test", domini=["asltest.it"])
    db.add(cliente)
    p = svc.crea_pratica(db, "Cartella nefrologica", cliente=cliente, stato=StatoPratica.STIMA)
    svc.aggiungi_evento(db, p, tipo=TipoEvento.OFFERTA_INVIATA, titolo="Offerta inviata", importo=12000, fonte_tipo=TipoFonte.EMAIL, fonte_id="m1", chiave="email:1:m1:offerta_inviata")
    assert p.stato == StatoPratica.OFFERTA and p.importo_offerta == Decimal("12000")
    svc.aggiungi_evento(db, p, tipo=TipoEvento.ORDINE_RICEVUTO, titolo="Ordine", importo=11500, scadenza=date(2027, 1, 31))
    assert p.stato == StatoPratica.ORDINE and p.importo_ordine == Decimal("11500") and p.data_scadenza == date(2027, 1, 31)
    # un evento di fase precedente non fa regredire lo stato
    svc.aggiungi_evento(db, p, tipo=TipoEvento.STIMA_INVIATA, titolo="Stima tardiva")
    assert p.stato == StatoPratica.ORDINE
    # due fatture sommano il fatturato
    svc.aggiungi_evento(db, p, tipo=TipoEvento.FATTURA_EMESSA, titolo="Fattura 1", importo=5000)
    svc.aggiungi_evento(db, p, tipo=TipoEvento.FATTURA_EMESSA, titolo="Fattura 2", importo=6500)
    assert p.stato == StatoPratica.FATTURAZIONE and p.importo_fatturato == Decimal("11500")
    tipi = [e.tipo for e in p.eventi]
    assert tipi.count(TipoEvento.CAMBIO_STATO) == 3  # stima→offerta, offerta→ordine, ordine→fatturazione


def test_evento_idempotente_per_chiave(db):
    p = svc.crea_pratica(db, "X")
    e1 = svc.aggiungi_evento(db, p, tipo=TipoEvento.NOTA, titolo="a", chiave="k1")
    e2 = svc.aggiungi_evento(db, p, tipo=TipoEvento.NOTA, titolo="b", chiave="k1")
    assert e1.id == e2.id


def test_eventi_proposti_non_cambiano_stato_finche_confermati(db):
    p = svc.crea_pratica(db, "Y", stato=StatoPratica.OFFERTA)
    e = svc.aggiungi_evento(db, p, tipo=TipoEvento.ORDINE_RICEVUTO, titolo="Ordine", importo=100, stato_verifica=StatoVerifica.PROPOSTO, confidenza=0.6)
    assert p.stato == StatoPratica.OFFERTA and p.importo_ordine is None
    svc.conferma_evento(db, e, user_id=None)
    assert p.stato == StatoPratica.ORDINE and p.importo_ordine == Decimal("100")


def test_cambia_stato_manuale_e_chiusura(db):
    p = svc.crea_pratica(db, "Z", stato=StatoPratica.CONSEGNA)
    svc.cambia_stato(db, p, StatoPratica.CHIUSA, motivo="fatturato e pagato")
    assert p.stato == StatoPratica.CHIUSA and p.data_chiusura == date.today()
    # dopo la chiusura gli eventi non riaprono la pratica
    svc.aggiungi_evento(db, p, tipo=TipoEvento.FATTURA_EMESSA, titolo="Fattura tardiva", importo=1)
    assert p.stato == StatoPratica.CHIUSA


def test_unisci_pratiche(db):
    a = svc.crea_pratica(db, "Doppione", stato=StatoPratica.ORDINE, importo_ordine=Decimal("500"))
    b = svc.crea_pratica(db, "Originale", stato=StatoPratica.OFFERTA)
    svc.aggiungi_evento(db, a, tipo=TipoEvento.ORDINE_RICEVUTO, titolo="Ordine", chiave="k-ord", data_evento=datetime(2026, 10, 1, tzinfo=UTC))
    svc.unisci_pratiche(db, a, b)
    db.flush()
    assert a.stato == StatoPratica.ANNULLATA
    assert b.stato == StatoPratica.ORDINE and b.importo_ordine == Decimal("500")
    assert any(e.tipo == TipoEvento.ORDINE_RICEVUTO for e in b.eventi)


def test_trova_cliente_per_alias(db):
    db.add(Cliente(nome="Policlinico San Matteo Pavia", alias=["San Matteo"], domini=["smatteo.pv.it"]))
    db.flush()
    assert svc.trova_cliente(db, "san matteo") is not None
    assert svc.trova_cliente(db, "Sconosciuto") is None
    nuovo = svc.trova_cliente(db, "Nuovo Ente", crea=True)
    assert nuovo is not None and nuovo.nome == "Nuovo Ente"
