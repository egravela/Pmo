"""Modello dati del PMO.

Entità principali:
- Account: casella Gmail/Drive collegata (token cifrati, segnalibri di sincronizzazione).
- Pratica: la "commessa" seguita dalla stima alla fattura, con codice univoco PMO-AAAA-NNNN.
- Evento: cronologia della pratica (ogni evento punta alla fonte: mail, documento, utente, sistema).
- Messaggio / Documento: elementi importati da Gmail e Drive, classificati e collegati alle pratiche.
- Sollecito: segnalazione generata dalle regole (ordine senza specifiche, scadenze, ecc.).
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from pmo.db.base import Base, JSONType, TZDateTime, utcnow


class StatoPratica(enum.StrEnum):
    BOZZA = "bozza"
    STIMA = "stima"
    OFFERTA = "offerta"
    ORDINE = "ordine"
    SPECIFICHE = "specifiche"
    SVILUPPO = "sviluppo"
    CONSEGNA = "consegna"
    FATTURAZIONE = "fatturazione"
    CHIUSA = "chiusa"
    SOSPESA = "sospesa"
    ANNULLATA = "annullata"


# Ordine delle fasi "attive": una pratica avanza solo in avanti in automatico.
FASI_ORDINATE: list[StatoPratica] = [
    StatoPratica.BOZZA,
    StatoPratica.STIMA,
    StatoPratica.OFFERTA,
    StatoPratica.ORDINE,
    StatoPratica.SPECIFICHE,
    StatoPratica.SVILUPPO,
    StatoPratica.CONSEGNA,
    StatoPratica.FATTURAZIONE,
    StatoPratica.CHIUSA,
]
STATI_ATTIVI: set[StatoPratica] = set(FASI_ORDINATE) - {StatoPratica.CHIUSA}
STATI_TERMINALI: set[StatoPratica] = {StatoPratica.CHIUSA, StatoPratica.ANNULLATA}

ETICHETTE_STATO: dict[str, str] = {
    "bozza": "Bozza",
    "stima": "Stima",
    "offerta": "Offerta",
    "ordine": "Ordine",
    "specifiche": "Specifiche",
    "sviluppo": "Sviluppo",
    "consegna": "Consegna",
    "fatturazione": "Fatturazione",
    "chiusa": "Chiusa",
    "sospesa": "Sospesa",
    "annullata": "Annullata",
}


class TipoEvento(enum.StrEnum):
    STIMA_RICHIESTA = "stima_richiesta"
    STIMA_INVIATA = "stima_inviata"
    OFFERTA_INVIATA = "offerta_inviata"
    OFFERTA_ACCETTATA = "offerta_accettata"
    OFFERTA_RIFIUTATA = "offerta_rifiutata"
    ORDINE_RICEVUTO = "ordine_ricevuto"
    SPECIFICHE_RICHIESTE = "specifiche_richieste"
    SPECIFICHE_RICEVUTE = "specifiche_ricevute"
    SPECIFICHE_INVIATE = "specifiche_inviate"
    SVILUPPO_AVVIATO = "sviluppo_avviato"
    SAL = "sal"
    CONSEGNA_EFFETTUATA = "consegna_effettuata"
    COLLAUDO = "collaudo"
    SAL_FIRMATO = "sal_firmato"
    FATTURA_EMESSA = "fattura_emessa"
    PAGAMENTO_RICEVUTO = "pagamento_ricevuto"
    SCADENZA = "scadenza"
    RIUNIONE = "riunione"
    RICHIESTA_INFORMAZIONI = "richiesta_informazioni"
    SOLLECITO_RICEVUTO = "sollecito_ricevuto"
    SOLLECITO_INVIATO = "sollecito_inviato"
    PROMEMORIA = "promemoria"
    DOCUMENTO = "documento"
    NOTA = "nota"
    CAMBIO_STATO = "cambio_stato"
    ANNULLAMENTO = "annullamento"
    ALTRO = "altro"


ETICHETTE_EVENTO: dict[str, str] = {
    "stima_richiesta": "Richiesta di stima",
    "stima_inviata": "Stima inviata",
    "offerta_inviata": "Offerta inviata",
    "offerta_accettata": "Offerta accettata",
    "offerta_rifiutata": "Offerta rifiutata",
    "ordine_ricevuto": "Ordine ricevuto",
    "specifiche_richieste": "Specifiche richieste",
    "specifiche_ricevute": "Specifiche ricevute",
    "specifiche_inviate": "Specifiche inviate",
    "sviluppo_avviato": "Sviluppo avviato",
    "sal": "Stato avanzamento lavori",
    "consegna_effettuata": "Consegna / rilascio",
    "collaudo": "Collaudo",
    "sal_firmato": "SAL firmato / accettazione",
    "fattura_emessa": "Fattura emessa",
    "pagamento_ricevuto": "Pagamento ricevuto",
    "scadenza": "Scadenza",
    "riunione": "Riunione",
    "richiesta_informazioni": "Richiesta informazioni",
    "sollecito_ricevuto": "Sollecito ricevuto",
    "sollecito_inviato": "Sollecito inviato",
    "promemoria": "Promemoria",
    "documento": "Documento",
    "nota": "Nota",
    "cambio_stato": "Cambio di stato",
    "annullamento": "Annullamento",
    "altro": "Altro",
}

# Fase implicata da ciascun tipo di evento (None = nessun avanzamento automatico).
FASE_PER_EVENTO: dict[str, StatoPratica | None] = {
    TipoEvento.STIMA_RICHIESTA: StatoPratica.STIMA,
    TipoEvento.STIMA_INVIATA: StatoPratica.STIMA,
    TipoEvento.OFFERTA_INVIATA: StatoPratica.OFFERTA,
    TipoEvento.OFFERTA_ACCETTATA: StatoPratica.OFFERTA,
    TipoEvento.ORDINE_RICEVUTO: StatoPratica.ORDINE,
    TipoEvento.SPECIFICHE_RICHIESTE: StatoPratica.ORDINE,
    TipoEvento.SPECIFICHE_RICEVUTE: StatoPratica.SPECIFICHE,
    TipoEvento.SPECIFICHE_INVIATE: StatoPratica.SPECIFICHE,
    TipoEvento.SVILUPPO_AVVIATO: StatoPratica.SVILUPPO,
    TipoEvento.SAL: StatoPratica.SVILUPPO,
    TipoEvento.CONSEGNA_EFFETTUATA: StatoPratica.CONSEGNA,
    TipoEvento.COLLAUDO: StatoPratica.CONSEGNA,
    TipoEvento.SAL_FIRMATO: StatoPratica.CONSEGNA,
    TipoEvento.FATTURA_EMESSA: StatoPratica.FATTURAZIONE,
    TipoEvento.PAGAMENTO_RICEVUTO: StatoPratica.FATTURAZIONE,
}


class TipoFonte(enum.StrEnum):
    EMAIL = "email"
    DRIVE = "drive"
    MANUALE = "manuale"
    SISTEMA = "sistema"


class StatoVerifica(enum.StrEnum):
    PROPOSTO = "proposto"
    CONFERMATO = "confermato"
    RIFIUTATO = "rifiutato"


class StatoMessaggio(enum.StrEnum):
    NUOVO = "nuovo"
    CLASSIFICATO = "classificato"
    DA_RIVEDERE = "da_rivedere"
    IGNORATO = "ignorato"
    ERRORE = "errore"


class StatoSollecito(enum.StrEnum):
    APERTO = "aperto"
    IN_CARICO = "in_carico"
    RISOLTO = "risolto"
    SILENZIATO = "silenziato"


class Gravita(enum.StrEnum):
    INFO = "info"
    AVVISO = "avviso"
    CRITICO = "critico"


class TipoDocumento(enum.StrEnum):
    STIMA = "stima"
    OFFERTA = "offerta"
    ORDINE = "ordine"
    SPECIFICA = "specifica"
    CONTRATTO = "contratto"
    SAL = "sal"
    VERBALE = "verbale"
    FATTURA = "fattura"
    ALTRO = "altro"


# ---------------------------------------------------------------------------------------------
# Utenti e caselle
# ---------------------------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(255), default="")
    ruolo: Mapped[str] = mapped_column(String(32), default="membro")  # admin | membro
    attivo: Mapped[bool] = mapped_column(Boolean, default=True)
    google_sub: Mapped[str | None] = mapped_column(String(64))
    riceve_digest: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    accounts: Mapped[list[Account]] = relationship(back_populates="owner")

    @property
    def is_admin(self) -> bool:
        return self.ruolo == "admin"


class Account(Base):
    """Casella Gmail (e Drive) collegata al sistema."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    attivo: Mapped[bool] = mapped_column(Boolean, default=True)
    token_cifrato: Mapped[str | None] = mapped_column(Text)  # JSON cifrato con Fernet
    scopes: Mapped[list] = mapped_column(JSONType, default=list)
    query_filter: Mapped[str] = mapped_column(String(500), default="")  # filtro Gmail aggiuntivo
    sync_gmail: Mapped[bool] = mapped_column(Boolean, default=True)
    sync_drive: Mapped[bool] = mapped_column(Boolean, default=True)
    gmail_history_id: Mapped[str | None] = mapped_column(String(32))
    gmail_last_sync_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    gmail_sync_from: Mapped[date | None] = mapped_column(Date)
    drive_last_sync_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    last_sync_status: Mapped[str] = mapped_column(String(32), default="mai")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User | None] = relationship(back_populates="accounts")
    watched_folders: Mapped[list[WatchedFolder]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )

    @property
    def collegato(self) -> bool:
        return bool(self.token_cifrato)


class WatchedFolder(Base):
    """Cartella Drive monitorata per una casella."""

    __tablename__ = "watched_folders"
    __table_args__ = (UniqueConstraint("account_id", "drive_folder_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    drive_folder_id: Mapped[str] = mapped_column(String(128))
    nome: Mapped[str] = mapped_column(String(255), default="")
    ricorsivo: Mapped[bool] = mapped_column(Boolean, default=True)
    attivo: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    account: Mapped[Account] = relationship(back_populates="watched_folders")


# ---------------------------------------------------------------------------------------------
# Anagrafiche
# ---------------------------------------------------------------------------------------------


class Cliente(Base):
    __tablename__ = "clienti"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(255), unique=True)
    alias: Mapped[list] = mapped_column(JSONType, default=list)
    domini: Mapped[list] = mapped_column(JSONType, default=list)
    tipo: Mapped[str] = mapped_column(String(32), default="altro")  # sanita | pa | partner | altro
    note: Mapped[str] = mapped_column(Text, default="")
    attivo: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    pratiche: Mapped[list[Pratica]] = relationship(back_populates="cliente")


class Prodotto(Base):
    """Prodotto o area (LURTO, Gepadial, T-MED, portali regionali, ...)."""

    __tablename__ = "prodotti"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(255), unique=True)
    alias: Mapped[list] = mapped_column(JSONType, default=list)
    descrizione: Mapped[str] = mapped_column(Text, default="")
    attivo: Mapped[bool] = mapped_column(Boolean, default=True)

    pratiche: Mapped[list[Pratica]] = relationship(back_populates="prodotto")


# ---------------------------------------------------------------------------------------------
# Pratiche ed eventi
# ---------------------------------------------------------------------------------------------


class Pratica(Base):
    __tablename__ = "pratiche"

    id: Mapped[int] = mapped_column(primary_key=True)
    codice: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    titolo: Mapped[str] = mapped_column(String(300))
    descrizione: Mapped[str] = mapped_column(Text, default="")
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clienti.id"), index=True)
    prodotto_id: Mapped[int | None] = mapped_column(ForeignKey("prodotti.id"), index=True)
    stato: Mapped[str] = mapped_column(String(32), default=StatoPratica.BOZZA, index=True)
    stato_dal: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    stato_verifica: Mapped[str] = mapped_column(String(16), default=StatoVerifica.CONFERMATO, index=True)
    origine: Mapped[str] = mapped_column(String(16), default="manuale")  # manuale | ai | tag
    priorita: Mapped[str] = mapped_column(String(16), default="media")  # alta | media | bassa
    responsabile_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    importo_stima: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    importo_offerta: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    importo_ordine: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    importo_fatturato: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    data_apertura: Mapped[date] = mapped_column(Date, default=date.today)
    data_scadenza: Mapped[date | None] = mapped_column(Date, index=True)
    data_chiusura: Mapped[date | None] = mapped_column(Date)
    riferimenti: Mapped[dict] = mapped_column(JSONType, default=dict)  # numero ordine, CIG, protocollo, SIA, VTE...
    drive_folder_id: Mapped[str | None] = mapped_column(String(128))
    drive_folder_url: Mapped[str | None] = mapped_column(String(500))
    note: Mapped[str] = mapped_column(Text, default="")
    ultimo_evento_at: Mapped[datetime | None] = mapped_column(TZDateTime, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, onupdate=utcnow)

    cliente: Mapped[Cliente | None] = relationship(back_populates="pratiche")
    prodotto: Mapped[Prodotto | None] = relationship(back_populates="pratiche")
    responsabile: Mapped[User | None] = relationship(foreign_keys=[responsabile_user_id])
    eventi: Mapped[list[Evento]] = relationship(
        back_populates="pratica", cascade="all, delete-orphan", order_by="Evento.data_evento"
    )
    messaggi: Mapped[list[Messaggio]] = relationship(back_populates="pratica")
    documenti: Mapped[list[Documento]] = relationship(back_populates="pratica")
    solleciti: Mapped[list[Sollecito]] = relationship(back_populates="pratica", cascade="all, delete-orphan")

    @property
    def etichetta_stato(self) -> str:
        return ETICHETTE_STATO.get(self.stato, self.stato)

    @property
    def attiva(self) -> bool:
        return self.stato in {s.value for s in STATI_ATTIVI}

    @property
    def tag(self) -> str:
        return f"[{self.codice}]"


class Evento(Base):
    __tablename__ = "eventi"
    __table_args__ = (Index("ix_eventi_pratica_data", "pratica_id", "data_evento"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pratica_id: Mapped[int] = mapped_column(ForeignKey("pratiche.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(40), index=True)
    data_evento: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    titolo: Mapped[str] = mapped_column(String(300))
    descrizione: Mapped[str] = mapped_column(Text, default="")
    fonte_tipo: Mapped[str] = mapped_column(String(16), default=TipoFonte.MANUALE)
    fonte_id: Mapped[str | None] = mapped_column(String(255))
    fonte_url: Mapped[str | None] = mapped_column(String(1000))
    chiave: Mapped[str | None] = mapped_column(String(400), unique=True)  # idempotenza (fonte:tipo)
    messaggio_id: Mapped[int | None] = mapped_column(ForeignKey("messaggi.id", ondelete="SET NULL"))
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documenti.id", ondelete="SET NULL"))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    importo: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    scadenza: Mapped[date | None] = mapped_column(Date)
    confidenza: Mapped[float | None] = mapped_column()
    stato_verifica: Mapped[str] = mapped_column(String(16), default=StatoVerifica.CONFERMATO, index=True)
    dati: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    pratica: Mapped[Pratica] = relationship(back_populates="eventi")
    messaggio: Mapped[Messaggio | None] = relationship(foreign_keys=[messaggio_id])
    documento: Mapped[Documento | None] = relationship(foreign_keys=[documento_id])

    @property
    def etichetta_tipo(self) -> str:
        return ETICHETTE_EVENTO.get(self.tipo, self.tipo)


# ---------------------------------------------------------------------------------------------
# Messaggi e documenti importati
# ---------------------------------------------------------------------------------------------


class Messaggio(Base):
    __tablename__ = "messaggi"
    __table_args__ = (
        UniqueConstraint("account_id", "gmail_message_id"),
        Index("ix_messaggi_thread", "account_id", "gmail_thread_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    gmail_message_id: Mapped[str] = mapped_column(String(32))
    gmail_thread_id: Mapped[str] = mapped_column(String(32))
    message_id_header: Mapped[str | None] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(1000), default="")
    from_email: Mapped[str] = mapped_column(String(255), default="", index=True)
    from_name: Mapped[str] = mapped_column(String(255), default="")
    to_emails: Mapped[list] = mapped_column(JSONType, default=list)
    cc_emails: Mapped[list] = mapped_column(JSONType, default=list)
    data: Mapped[datetime] = mapped_column(TZDateTime, index=True)
    snippet: Mapped[str] = mapped_column(Text, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    labels: Mapped[list] = mapped_column(JSONType, default=list)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    attachments: Mapped[list] = mapped_column(JSONType, default=list)
    attachments_text: Mapped[str] = mapped_column(Text, default="")
    inviato_da_noi: Mapped[bool] = mapped_column(Boolean, default=False)
    tag_codice: Mapped[str | None] = mapped_column(String(20), index=True)
    stato: Mapped[str] = mapped_column(String(16), default=StatoMessaggio.NUOVO, index=True)
    motivo: Mapped[str] = mapped_column(String(500), default="")
    classificazione: Mapped[dict] = mapped_column(JSONType, default=dict)
    pratica_id: Mapped[int | None] = mapped_column(ForeignKey("pratiche.id", ondelete="SET NULL"), index=True)
    link_origine: Mapped[str | None] = mapped_column(String(16))  # tag | thread | ai | manuale
    confidenza: Mapped[float | None] = mapped_column()
    processed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    account: Mapped[Account] = relationship()
    pratica: Mapped[Pratica | None] = relationship(back_populates="messaggi")

    @property
    def gmail_url(self) -> str:
        return f"https://mail.google.com/mail/u/0/#all/{self.gmail_message_id}"


class Documento(Base):
    __tablename__ = "documenti"
    __table_args__ = (UniqueConstraint("account_id", "drive_file_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    watched_folder_id: Mapped[int | None] = mapped_column(ForeignKey("watched_folders.id", ondelete="SET NULL"))
    drive_file_id: Mapped[str] = mapped_column(String(128))
    nome: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str] = mapped_column(String(255), default="")
    percorso: Mapped[str] = mapped_column(String(1000), default="")
    parent_folder_id: Mapped[str | None] = mapped_column(String(128))
    web_view_link: Mapped[str | None] = mapped_column(String(1000))
    dimensione: Mapped[int | None] = mapped_column(Integer)
    modified_time: Mapped[datetime | None] = mapped_column(TZDateTime, index=True)
    created_time: Mapped[datetime | None] = mapped_column(TZDateTime)
    ultimo_autore: Mapped[str] = mapped_column(String(255), default="")
    estratto: Mapped[str] = mapped_column(Text, default="")
    tag_codice: Mapped[str | None] = mapped_column(String(20), index=True)
    tipo_documento: Mapped[str | None] = mapped_column(String(32))
    stato: Mapped[str] = mapped_column(String(16), default=StatoMessaggio.NUOVO, index=True)
    motivo: Mapped[str] = mapped_column(String(500), default="")
    classificazione: Mapped[dict] = mapped_column(JSONType, default=dict)
    pratica_id: Mapped[int | None] = mapped_column(ForeignKey("pratiche.id", ondelete="SET NULL"), index=True)
    link_origine: Mapped[str | None] = mapped_column(String(16))
    confidenza: Mapped[float | None] = mapped_column()
    processed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)

    account: Mapped[Account] = relationship()
    pratica: Mapped[Pratica | None] = relationship(back_populates="documenti")


# ---------------------------------------------------------------------------------------------
# Solleciti e regole
# ---------------------------------------------------------------------------------------------


class Regola(Base):
    __tablename__ = "regole"

    id: Mapped[int] = mapped_column(primary_key=True)
    codice: Mapped[str] = mapped_column(String(64), unique=True)
    nome: Mapped[str] = mapped_column(String(255))
    descrizione: Mapped[str] = mapped_column(Text, default="")
    soglia_giorni: Mapped[int | None] = mapped_column(Integer)
    gravita: Mapped[str] = mapped_column(String(16), default=Gravita.AVVISO)
    attiva: Mapped[bool] = mapped_column(Boolean, default=True)
    parametri: Mapped[dict] = mapped_column(JSONType, default=dict)


class Sollecito(Base):
    __tablename__ = "solleciti"

    id: Mapped[int] = mapped_column(primary_key=True)
    pratica_id: Mapped[int] = mapped_column(ForeignKey("pratiche.id", ondelete="CASCADE"), index=True)
    regola: Mapped[str] = mapped_column(String(64), index=True)
    chiave: Mapped[str] = mapped_column(String(100), unique=True)  # "<pratica_id>:<regola>"
    gravita: Mapped[str] = mapped_column(String(16), default=Gravita.AVVISO)
    titolo: Mapped[str] = mapped_column(String(300))
    messaggio: Mapped[str] = mapped_column(Text, default="")
    dati: Mapped[dict] = mapped_column(JSONType, default=dict)
    stato: Mapped[str] = mapped_column(String(16), default=StatoSollecito.APERTO, index=True)
    assegnato_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    snooze_fino: Mapped[date | None] = mapped_column(Date)
    aperto_il: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    aggiornato_il: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, onupdate=utcnow)
    risolto_il: Mapped[datetime | None] = mapped_column(TZDateTime)
    risolto_da: Mapped[str | None] = mapped_column(String(16))  # sistema | utente
    notificato_il: Mapped[datetime | None] = mapped_column(TZDateTime)
    occorrenze: Mapped[int] = mapped_column(Integer, default=1)

    pratica: Mapped[Pratica] = relationship(back_populates="solleciti")
    assegnato: Mapped[User | None] = relationship(foreign_keys=[assegnato_user_id])


# ---------------------------------------------------------------------------------------------
# Supporto: sequenze codici, esecuzioni, impostazioni
# ---------------------------------------------------------------------------------------------


class SequenzaCodici(Base):
    __tablename__ = "sequenze_codici"

    anno: Mapped[int] = mapped_column(Integer, primary_key=True)
    ultimo: Mapped[int] = mapped_column(Integer, default=0)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(16))  # gmail | drive | classify | regole | digest
    stato: Mapped[str] = mapped_column(String(16), default="in_corso")  # in_corso | ok | errore
    started_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    contatori: Mapped[dict] = mapped_column(JSONType, default=dict)
    errori: Mapped[list] = mapped_column(JSONType, default=list)
    note: Mapped[str] = mapped_column(Text, default="")


class Impostazione(Base):
    """Impostazioni modificabili dall'interfaccia (chiave → valore JSON)."""

    __tablename__ = "impostazioni"

    chiave: Mapped[str] = mapped_column(String(100), primary_key=True)
    valore: Mapped[dict] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, onupdate=utcnow)
