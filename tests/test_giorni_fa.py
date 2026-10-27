"""I "giorni fa" mostrati accanto a una data contano giorni di calendario, non periodi di 24 ore."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from pmo.web.deps import f_giorni_fa

ROMA = ZoneInfo("Europe/Rome")


def _ieri_sera() -> datetime:
    """Ieri alle 23:30, ora di Roma: sono passate poche ore ma il giorno di calendario è un altro."""
    adesso = datetime.now(ROMA)
    ieri = (adesso - timedelta(days=1)).replace(hour=23, minute=30, second=0, microsecond=0)
    return ieri.astimezone(UTC)


def test_una_mail_di_ieri_sera_e_di_ieri_anche_se_sono_passate_poche_ore():
    ieri_sera = _ieri_sera()
    if datetime.now(ROMA).hour == 23 and datetime.now(ROMA).minute >= 30:
        return  # a ridosso della mezzanotte l'ora di "ieri sera" sarebbe nel futuro
    assert f_giorni_fa(ieri_sera) == "ieri"


def test_oggi_ieri_e_giorni_fa():
    adesso = datetime.now(UTC)
    assert f_giorni_fa(adesso) == "oggi"
    assert f_giorni_fa(adesso - timedelta(days=3)) in {"3 giorni fa", "2 giorni fa"}  # dipende dall'ora, mai "oggi"
    assert f_giorni_fa(date.today()) == "oggi"
    assert f_giorni_fa(date.today() - timedelta(days=1)) == "ieri"
    assert f_giorni_fa(date.today() - timedelta(days=10)) == "10 giorni fa"
    assert f_giorni_fa(None) == "-"
