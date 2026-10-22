"""Identificativo univoco delle pratiche: PMO-AAAA-NNNN.

Il codice va usato tra parentesi quadre nell'oggetto delle mail e nel nome delle cartelle,
ad esempio "[PMO-2026-0012] Banca degli Occhi - offerta". Tutto ciò che lo contiene viene
collegato alla pratica senza bisogno dell'intelligenza artificiale.
"""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy.orm import Session

from pmo.db.models import SequenzaCodici

TAG_RE = re.compile(r"\bPMO-(\d{4})-(\d{1,5})\b", re.IGNORECASE)


def prossimo_codice(session: Session, anno: int | None = None) -> str:
    anno = anno or date.today().year
    seq = session.get(SequenzaCodici, anno, with_for_update=True)
    if seq is None:
        seq = SequenzaCodici(anno=anno, ultimo=0)
        session.add(seq)
        session.flush()
    seq.ultimo += 1
    session.flush()
    return formatta_codice(anno, seq.ultimo)


def formatta_codice(anno: int, numero: int) -> str:
    return f"PMO-{anno}-{numero:04d}"


def estrai_codice(testo: str | None) -> str | None:
    """Restituisce il primo codice pratica presente nel testo, normalizzato."""
    if not testo:
        return None
    match = TAG_RE.search(testo)
    if not match:
        return None
    return formatta_codice(int(match.group(1)), int(match.group(2)))


def estrai_codici(testo: str | None) -> list[str]:
    if not testo:
        return []
    visti: list[str] = []
    for match in TAG_RE.finditer(testo):
        codice = formatta_codice(int(match.group(1)), int(match.group(2)))
        if codice not in visti:
            visti.append(codice)
    return visti
