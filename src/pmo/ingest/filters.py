"""Pulizia del testo delle mail e filtri anti-rumore (prima di coinvolgere l'IA)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from email.utils import getaddresses

from bs4 import BeautifulSoup

# Mittenti automatici che non riguardano mai una pratica.
DEFAULT_IGNORE_SENDER_PATTERNS = [
    r"^(no-?reply|noreply|notifications?|newsletter|news|mailer-daemon|postmaster|bounce)[@.+-]",
    r"^(drive-shares|calendar-notification|gemini-notes|comments-noreply)[@.-]",
    r"@(facebook|facebookmail|linkedin|twitter|x|instagram|tiktok)\.com$",
    r"@(amazon|amazon\.[a-z]+|ebay|paypal|nexi|trenitalia|italo|booking|airbnb)\.",
    r"@(newgarden|kiabi|sklum|zalando|ikea|esselunga|lampade|gruppocomet|th-resorts|shop\.app|vify)\.",
    r"@(brt|dhl|fedex|ups|gls|posteitaliane|poste|sda)\.",
    r"@(google|youtube|apple|microsoft|dropbox|slack|zoom|notion|atlassian|github)\.com$",
]

DEFAULT_IGNORE_SUBJECT_PATTERNS = [
    r"^(out of office|fuori sede|automatic reply|risposta automatica|non in servizio)",
    r"\b(il tuo ordine|tuo ordine|ordine #|spedizione in consegna|è stato spedito|tracking|biglietto)\b",
    r"\b(newsletter|unsubscribe|disiscriviti|webinar gratuito|promo|offerta speciale|sconto)\b",
    r"^(accepted|accettato|declined|rifiutato|invito aggiornato|invitation|invito):",
]

DEFAULT_IGNORE_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "SPAM", "TRASH"}

REPLY_MARKERS = [
    r"^Il giorno .{5,200}? ha scritto:\s*$",
    r"^Il \d{1,2}/\d{1,2}/\d{2,4}.{0,120}? ha scritto:\s*$",
    r"^On .{5,200}? wrote:\s*$",
    r"^Le .{5,200}? a écrit\s*:\s*$",
    r"^-{3,}\s*(Messaggio originale|Original Message)\s*-{3,}\s*$",
    r"^_{10,}\s*$",
    r"^Da:\s.+$",
    r"^From:\s.+$",
    r"^De:\s.+$",
]
_REPLY_RE = re.compile("|".join(f"(?:{m})" for m in REPLY_MARKERS), re.IGNORECASE | re.MULTILINE)
_FORWARD_RE = re.compile(r"-{5,}\s*(Forwarded message|Messaggio inoltrato)\s*-{5,}", re.IGNORECASE)
_SIGNATURE_RE = re.compile(r"^(--\s*$|__+\s*$|Cordiali saluti|Distinti saluti|Best regards|Kind regards)", re.IGNORECASE | re.MULTILINE)
_WS_RE = re.compile(r"[ \t\xa0]+")
_NL_RE = re.compile(r"\n{3,}")


@dataclass
class FiltriRumore:
    ignore_sender_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_SENDER_PATTERNS))
    ignore_subject_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_SUBJECT_PATTERNS))
    ignore_senders: list[str] = field(default_factory=list)  # indirizzi esatti
    ignore_domains: list[str] = field(default_factory=list)
    ignore_labels: set[str] = field(default_factory=lambda: set(DEFAULT_IGNORE_LABELS))
    internal_domains: list[str] = field(default_factory=lambda: ["latraccia.it"])
    keep_senders: list[str] = field(default_factory=list)  # eccezioni: mai ignorati

    def _compiled(self, patterns: list[str]) -> list[re.Pattern[str]]:
        out = []
        for p in patterns:
            try:
                out.append(re.compile(p, re.IGNORECASE))
            except re.error:
                continue
        return out

    def motivo_esclusione(
        self,
        *,
        from_email: str,
        subject: str,
        labels: list[str],
        has_list_unsubscribe: bool,
        tag_presente: bool,
    ) -> str | None:
        """Restituisce il motivo per cui il messaggio va ignorato, oppure None se va analizzato."""
        if tag_presente:
            return None  # un codice pratica nell'oggetto vince su tutto
        from_email = (from_email or "").lower()
        dominio = from_email.split("@")[-1] if "@" in from_email else ""
        if from_email in {s.lower() for s in self.keep_senders}:
            return None
        if any(label in self.ignore_labels for label in labels or []):
            return "categoria Gmail promozioni/social"
        if from_email in {s.lower() for s in self.ignore_senders}:
            return "mittente in lista di esclusione"
        if dominio and any(dominio == d.lower() or dominio.endswith("." + d.lower()) for d in self.ignore_domains):
            return "dominio in lista di esclusione"
        interno = any(dominio == d.lower() or dominio.endswith("." + d.lower()) for d in self.internal_domains)
        if has_list_unsubscribe and not interno:
            return "mailing list / newsletter"
        for pattern in self._compiled(self.ignore_sender_patterns):
            if pattern.search(from_email):
                return "mittente automatico"
        for pattern in self._compiled(self.ignore_subject_patterns):
            if pattern.search(subject or ""):
                return "oggetto non pertinente"
        return None


def parse_addresses(header_value: str | None) -> list[tuple[str, str]]:
    """Restituisce coppie (nome, email) da un header To/Cc/From."""
    if not header_value:
        return []
    out: list[tuple[str, str]] = []
    for nome, email in getaddresses([header_value]):
        email = (email or "").strip().lower()
        if email:
            out.append(((nome or "").strip().strip('"'), email))
    return out


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style", "head", "title", "meta"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table", "blockquote"]):
        block.append("\n")
    testo = soup.get_text()
    return normalizza_spazi(testo)


def normalizza_spazi(testo: str) -> str:
    testo = testo.replace("\r\n", "\n").replace("\r", "\n")
    testo = _WS_RE.sub(" ", testo)
    testo = "\n".join(line.strip() for line in testo.split("\n"))
    testo = _NL_RE.sub("\n\n", testo)
    return testo.strip()


def strip_quoted(testo: str, mantieni_inoltri: bool = True) -> str:
    """Rimuove le citazioni delle risposte precedenti; mantiene il contenuto inoltrato (utile per gli ordini)."""
    if not testo:
        return ""
    if mantieni_inoltri and _FORWARD_RE.search(testo):
        # Un inoltro contiene il messaggio originale: lo teniamo per intero, togliendo solo
        # eventuali citazioni "ha scritto:" che seguono il blocco inoltrato.
        return testo.strip()
    righe = testo.split("\n")
    # righe che iniziano con ">" sono citazioni
    pulite: list[str] = []
    for riga in righe:
        if riga.lstrip().startswith(">"):
            continue
        pulite.append(riga)
    testo = "\n".join(pulite)
    match = _REPLY_RE.search(testo)
    if match and match.start() > 0:
        testo = testo[: match.start()]
    return testo.strip()


def tronca(testo: str, max_chars: int) -> str:
    if len(testo) <= max_chars:
        return testo
    return testo[: max_chars - 20].rstrip() + "\n[... testo troncato]"


def dominio(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    return email.rsplit("@", 1)[1].lower()
