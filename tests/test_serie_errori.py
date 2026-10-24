"""Una serie di errori temporanei consecutivi (rete caduta) ferma la classificazione senza bruciare i tentativi."""

from __future__ import annotations

from tests.test_classificazione import ClassificatoreGuasto, _account, _messaggio

from pmo.db.models import Documento, StatoMessaggio
from pmo.ingest.catalogo import carica_catalogo
from pmo.ingest.classifier import ErroreClassificazione
from pmo.ingest.drive_sync import DOCUMENTI_PER_CHIAMATA, classifica_documenti
from pmo.ingest.gmail_sync import classifica_messaggi
from pmo.ingest.serie_errori import MOTIVO_INTERRUZIONE, SERIE_ERRORI_MAX


class ClassificatoreNonNeutro(ClassificatoreGuasto):
    """Come il guasto ma conta le chiamate, per verificare che ci si fermi."""

    def __init__(self):
        self.chiamate = 0

    def classifica_thread(self, catalogo_testo: str, prompt: str):
        self.chiamate += 1
        raise ErroreClassificazione("Connection error", temporaneo=True)

    def classifica_documenti(self, catalogo_testo: str, prompt: str):
        self.chiamate += 1
        raise ErroreClassificazione("Connection error", temporaneo=True)


def test_serie_di_errori_di_rete_ferma_i_messaggi_e_annulla_i_tentativi(db, settings):
    acc = _account(db)
    messaggi = [_messaggio(db, acc, f"m{i}", f"t{i}", "Offerta", "testo") for i in range(SERIE_ERRORI_MAX + 4)]
    guasto = ClassificatoreNonNeutro()
    # tre giri consecutivi con la rete assente: senza l'interruzione tutti finirebbero in "errore"
    for _ in range(3):
        run = classifica_messaggi(db, acc, settings, classificatore=guasto, catalogo=carica_catalogo(db, settings))
        assert MOTIVO_INTERRUZIONE in run.errori
    assert guasto.chiamate == 3 * SERIE_ERRORI_MAX  # ogni giro si ferma dopo la serie
    assert all(m.stato == StatoMessaggio.NUOVO for m in messaggi)
    assert all(int((m.classificazione or {}).get("tentativi", 0)) == 0 for m in messaggi)


def test_serie_di_errori_di_rete_ferma_i_documenti_e_annulla_i_tentativi(db, settings):
    acc = _account(db)
    documenti = []
    for i in range(DOCUMENTI_PER_CHIAMATA * (SERIE_ERRORI_MAX + 2)):  # più gruppi di quelli della serie
        d = Documento(account_id=acc.id, drive_file_id=f"f{i}", nome=f"a{i}.pdf", stato=StatoMessaggio.NUOVO)
        db.add(d)
        documenti.append(d)
    db.flush()
    guasto = ClassificatoreNonNeutro()
    for _ in range(3):
        run = classifica_documenti(db, acc, settings, classificatore=guasto, catalogo=carica_catalogo(db, settings))
        assert MOTIVO_INTERRUZIONE in run.errori
    assert all(d.stato == StatoMessaggio.NUOVO for d in documenti)
    assert all(int((d.classificazione or {}).get("tentativi", 0)) == 0 for d in documenti)
