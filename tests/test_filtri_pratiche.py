"""Filtri e ricerca dell'elenco pratiche: campi vuoti del modulo, ricerca per parole, cliente e prodotto."""

from __future__ import annotations

from tests.test_design_system import _login, client  # noqa: F401

from pmo.db.models import Cliente, Prodotto, StatoPratica, StatoVerifica
from pmo.services import pratiche as svc


def _scenario(db):
    # la fixture `client` ha già caricato l'anagrafica di config/seed.yaml
    gemelli = db.query(Cliente).filter(Cliente.nome.like("%Gemelli%")).one()
    aria = db.query(Cliente).filter_by(nome="ARIA SpA").one()
    lurto = db.query(Prodotto).filter_by(nome="LURTO").one()
    a = svc.crea_pratica(db, "Stima deploy nuovo ambiente Media Hub", cliente=aria, stato_verifica=StatoVerifica.CONFERMATO)
    b = svc.crea_pratica(db, "Cartella trapianti, evolutiva", cliente=gemelli, prodotto=lurto, stato_verifica=StatoVerifica.PROPOSTO)
    c = svc.crea_pratica(db, "Manutenzione 50% annuale_2026", descrizione="Rinnovo", stato_verifica=StatoVerifica.CONFERMATO)
    chiusa = svc.crea_pratica(db, "Vecchio lavoro ARIA", cliente=aria, stato_verifica=StatoVerifica.CONFERMATO)
    chiusa.stato = StatoPratica.CHIUSA.value
    db.commit()
    return a, b, c, chiusa, gemelli, aria, lurto


def _presenti(client, db, percorso: str, pratiche) -> set[str]:  # noqa: ANN001, F811
    risposta = client.get(percorso)
    assert risposta.status_code == 200, f"{percorso} -> {risposta.status_code}"
    return {p.codice for p in pratiche if p.codice in risposta.text}


def test_campi_vuoti_del_modulo_non_sono_un_errore(client, db):  # noqa: F811
    a, b, c, chiusa, *_ = _scenario(db)
    _login(client)
    # il browser manda i menu lasciati su "Tutti" come stringhe vuote
    vuoto = "/pratiche?q=&stato=&cliente_id=&prodotto_id=&responsabile_id=&verifica=&azione="
    assert _presenti(client, db, vuoto, (a, b, c, chiusa)) == {a.codice, b.codice, c.codice}
    assert _presenti(client, db, "/pratiche?q=Gemelli&cliente_id=&prodotto_id=", (a, b, c)) == {b.codice}
    assert _presenti(client, db, "/pratiche?pagina=&tutte=&richieste=", (a, b, c)) == {a.codice, b.codice, c.codice}
    assert client.get("/pratiche?cliente_id=abc").status_code == 200  # un valore senza senso non rompe la pagina


def test_ricerca_per_parole_anche_non_contigue_e_per_cliente_o_prodotto(client, db):  # noqa: F811
    a, b, c, chiusa, *_ = _scenario(db)
    _login(client)
    tutte = (a, b, c, chiusa)
    assert _presenti(client, db, "/pratiche?q=media+deploy", tutte) == {a.codice}  # parole non contigue, maiuscole irrilevanti
    assert _presenti(client, db, "/pratiche?q=aria", tutte) == {a.codice}  # nome del cliente (la chiusa è nascosta di default)
    assert _presenti(client, db, "/pratiche?q=aria&tutte=1", tutte) == {a.codice, chiusa.codice}
    assert _presenti(client, db, "/pratiche?q=gemelli+trapianti", tutte) == {b.codice}
    assert _presenti(client, db, "/pratiche?q=lurto", tutte) == {b.codice}  # nome del prodotto
    assert _presenti(client, db, "/pratiche?q=gemelli+aria", tutte) == set()  # tutte le parole devono comparire
    assert _presenti(client, db, f"/pratiche?q={a.codice}", tutte) == {a.codice}  # il codice


def test_la_ricerca_non_tratta_percentuale_e_trattino_basso_come_jolly(client, db):  # noqa: F811
    a, b, c, chiusa, *_ = _scenario(db)
    _login(client)
    tutte = (a, b, c, chiusa)
    assert _presenti(client, db, "/pratiche?q=50%25", tutte) == {c.codice}
    assert _presenti(client, db, "/pratiche?q=annuale_2026", tutte) == {c.codice}
    assert _presenti(client, db, "/pratiche?q=%25", tutte) == {c.codice}  # cerca il carattere: non vale "tutto"
    assert _presenti(client, db, "/pratiche?q=_", tutte) == {c.codice}  # cerca davvero il carattere


def test_filtri_verifica_responsabile_cliente_e_prodotto(client, db):  # noqa: F811
    a, b, c, chiusa, gemelli, aria, lurto = _scenario(db)
    _login(client)
    tutte = (a, b, c, chiusa)
    assert _presenti(client, db, "/pratiche?verifica=proposte", tutte) == {b.codice}
    assert _presenti(client, db, "/pratiche?verifica=confermate", tutte) == {a.codice, c.codice}
    assert _presenti(client, db, "/pratiche?responsabile_id=nessuno", tutte) == {a.codice, b.codice, c.codice}
    assert _presenti(client, db, "/pratiche?responsabile_id=9999", tutte) == set()
    assert _presenti(client, db, f"/pratiche?cliente_id={aria.id}", tutte) == {a.codice}
    assert _presenti(client, db, f"/pratiche?prodotto_id={lurto.id}", tutte) == {b.codice}
    assert _presenti(client, db, "/pratiche?stato=chiusa", tutte) == {chiusa.codice}


def test_i_link_delle_pagine_conservano_i_filtri_anche_vuoti(client, db):  # noqa: F811
    for i in range(30):
        svc.crea_pratica(db, f"Pratica di prova {i:02d}", stato_verifica=StatoVerifica.CONFERMATO)
    db.commit()
    _login(client)
    prima = client.get("/pratiche?q=prova&cliente_id=")
    assert prima.status_code == 200
    successiva = client.get("/pratiche?q=prova&cliente_id=&pagina=2")
    assert successiva.status_code == 200  # prima di questa correzione i link di pagina con un filtro vuoto davano 422
