"""Classificazione con Claude di mail e documenti: pertinenza, pratica collegata, eventi estratti.

Il modello riceve il catalogo (clienti, prodotti, team, pratiche aperte) come blocco di sistema
cacheable e il thread (o un gruppo di documenti) come messaggio utente; risponde con un JSON
validato contro uno schema Pydantic (structured outputs).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Protocol

import anthropic
from pydantic import BaseModel, Field

from pmo.config import Settings, get_settings

log = logging.getLogger(__name__)

TipoEventoAI = Literal[
    "stima_richiesta",
    "stima_inviata",
    "offerta_inviata",
    "offerta_accettata",
    "offerta_rifiutata",
    "ordine_ricevuto",
    "specifiche_richieste",
    "specifiche_ricevute",
    "specifiche_inviate",
    "sviluppo_avviato",
    "sal",
    "consegna_effettuata",
    "collaudo",
    "sal_firmato",
    "fattura_emessa",
    "pagamento_ricevuto",
    "scadenza",
    "riunione",
    "richiesta_informazioni",
    "sollecito_ricevuto",
    "sollecito_inviato",
    "promemoria",
    "documento",
    "nota",
    "annullamento",
    "altro",
]

StatoIniziale = Literal["bozza", "stima", "offerta", "ordine", "specifiche", "sviluppo", "consegna", "fatturazione"]
ChiaveRiferimento = Literal[
    "numero_ordine",
    "numero_offerta",
    "numero_stima",
    "protocollo",
    "cig",
    "cup",
    "numero_contratto",
    "numero_fattura",
    "numero_procedura",
    "id_sia",
    "id_vte",
    "altro",
]
TipoDocumentoAI = Literal["stima", "offerta", "ordine", "specifica", "contratto", "sal", "verbale", "fattura", "altro"]


class RiferimentoEstratto(BaseModel):
    chiave: ChiaveRiferimento
    valore: str


class EventoEstratto(BaseModel):
    tipo: TipoEventoAI
    data: str | None = Field(description="Data dell'evento in formato AAAA-MM-GG; null se coincide con la data del messaggio")
    titolo: str = Field(description="Titolo breve in italiano, massimo 120 caratteri")
    descrizione: str = Field(description="Dettaglio dei fatti documentati nel messaggio, 1-3 frasi")
    importo_eur: float | None = Field(description="Importo in euro se esplicito, altrimenti null")
    scadenza: str | None = Field(description="Data limite AAAA-MM-GG implicata dall'evento, altrimenti null")
    confidenza: float = Field(description="Tra 0 e 1")


class PraticaProposta(BaseModel):
    titolo: str = Field(description="Titolo della pratica, es. 'Banca degli Occhi - canone e giornate'")
    cliente: str | None = Field(description="Ente o azienda committente (nome dall'elenco se presente)")
    prodotto: str | None = Field(description="Prodotto/soluzione dall'elenco se identificabile")
    descrizione: str
    stato_iniziale: StatoIniziale


class RisultatoMessaggio(BaseModel):
    id: str = Field(description="Identificativo del messaggio così come fornito")
    rilevante: bool
    motivo: str = Field(description="Una frase: perché è o non è rilevante")
    collegamento: Literal["esistente", "nuova", "nessuno"]
    pratica_codice: str | None = Field(description="Codice PMO-AAAA-NNNN della pratica esistente, altrimenti null")
    pratica_nuova: PraticaProposta | None
    confidenza_collegamento: float = Field(description="Tra 0 e 1")
    eventi: list[EventoEstratto]
    riferimenti: list[RiferimentoEstratto]


class RisultatoThread(BaseModel):
    messaggi: list[RisultatoMessaggio]


class RisultatoDocumento(BaseModel):
    id: str
    rilevante: bool
    motivo: str
    tipo_documento: TipoDocumentoAI
    collegamento: Literal["esistente", "nuova", "nessuno"]
    pratica_codice: str | None
    pratica_nuova: PraticaProposta | None
    confidenza_collegamento: float
    evento: EventoEstratto | None = Field(description="Evento implicato dal documento (es. offerta_inviata per un'offerta), se pertinente")
    riferimenti: list[RiferimentoEstratto]


class RisultatoDocumenti(BaseModel):
    documenti: list[RisultatoDocumento]


SYSTEM_PROMPT = """Sei l'assistente del PMO (Project Management Office) della Cooperativa EDP La Traccia di Matera, software house che lavora con aziende sanitarie, ospedali, regioni e pubbliche amministrazioni (informatica medica, telemedicina, portali regionali), spesso dentro raggruppamenti temporanei d'impresa (RTI) con partner come Engineering, TIM, Maps, Dedalus, Accenture/ARIA.

Il tuo compito: leggere mail e documenti e ricondurli alle "pratiche", cioè le commesse seguite dalla richiesta di stima fino alla fattura. Fasi di una pratica, in ordine: bozza → stima → offerta → ordine → specifiche → sviluppo → consegna → fatturazione → chiusa.

Per ogni messaggio (o documento) devi stabilire:

1. RILEVANTE: true solo se riguarda una pratica commerciale o progettuale della cooperativa: richieste e invii di stime, preventivi e offerte, ordini e contratti, specifiche tecniche e di integrazione, analisi e riunioni di progetto, sviluppo, consegne, rilasci, collaudi, SAL, fatturazione, pagamenti, scadenze, proroghe, solleciti. NON rilevanti: acquisti e spedizioni personali o di ufficio, notifiche automatiche, newsletter, selezione del personale, gestione interna generica, eventi e congressi, questioni IT interne non legate a una commessa, gare a cui si decide di non partecipare.

2. COLLEGAMENTO: "esistente" se il messaggio riguarda una pratica dell'elenco (indica il codice PMO), "nuova" se riguarda una pratica non ancora in elenco (proponi titolo, cliente, prodotto, stato iniziale coerente con i fatti), "nessuno" se non è rilevante o non è riconducibile. Se il thread è già collegato a una pratica, mantieni quel collegamento salvo evidenza contraria. Il cliente è l'ente o l'azienda committente (ASL, azienda ospedaliera, regione, partner capofila), non la persona. Distingui pratiche diverse dello stesso cliente (prodotti o oggetti diversi).

3. EVENTI: estrai solo fatti documentati nel messaggio, non ipotesi. Tipi disponibili:
- stima_richiesta / stima_inviata: richiesta o invio di una stima o preventivo
- offerta_inviata / offerta_accettata / offerta_rifiutata: offerta economica formale
- ordine_ricevuto: ordine, PO, contratto, affidamento, piano operativo ricevuto dal cliente o dal capofila
- specifiche_richieste / specifiche_ricevute / specifiche_inviate: specifiche tecniche, di integrazione, requisiti, analisi di fattibilità, documenti di analisi
- sviluppo_avviato, sal: avvio lavori e stati di avanzamento
- consegna_effettuata: rilascio, messa in produzione, consegna di modifiche o documenti finali
- collaudo: test, verifica, collaudo
- sal_firmato: SAL o reso servizio firmato/accettato, via libera alla fatturazione
- fattura_emessa, pagamento_ricevuto
- scadenza: termine o data limite (consegne, risposte, proroghe); indica la data nel campo scadenza
- riunione: incontro o call di progetto fissata o svolta
- richiesta_informazioni, sollecito_ricevuto, sollecito_inviato
- promemoria: nota che l'utente invia a sé stesso o al team come cosa da fare
- documento: documento rilevante condiviso (usa questo tipo per i file Drive non riconducibili ad altro)
- nota, annullamento, altro
Per ogni evento indica la data (null se è quella del messaggio), un titolo breve, una descrizione fattuale, l'importo in euro solo se esplicito, l'eventuale scadenza e la confidenza. Un messaggio può produrre zero, uno o più eventi; evita duplicati tra messaggi dello stesso thread già riportati nella storia.

4. RIFERIMENTI: numeri d'ordine, protocollo, CIG, CUP, numero di procedura, numero offerta o fattura, identificativi SIA/VTE, quando presenti.

5. CONFIDENZA: tra 0 e 1, quanto sei sicuro del collegamento.

I messaggi inviati dal team interno possono essere offerte inviate, specifiche inviate, consegne o solleciti inviati. Gli ordini arrivano spesso dalla casella info@ o dalla segreteria commerciale con oggetto "CLIENTE: Ordine per ..." e allegato il PDF dell'ordine: usa il testo dell'allegato per importi e riferimenti. Rispondi in italiano."""

SYSTEM_PROMPT_DOCUMENTI = SYSTEM_PROMPT + """

Stai classificando FILE presenti nelle cartelle Google Drive monitorate. Per ciascun file: stabilisci se è rilevante, il tipo di documento (stima, offerta, ordine, specifica, contratto, sal, verbale, fattura, altro), la pratica collegata (esistente o nuova) e, se il documento implica un fatto (un'offerta inviata, un ordine ricevuto, una specifica consegnata), l'evento corrispondente con la data di modifica del file come data. Il percorso della cartella spesso contiene il nome del cliente o del progetto."""

BETA_FALLBACK = "server-side-fallback-2026-07-01"


class ErroreClassificazione(Exception):
    """Errore temporaneo o definitivo del classificatore."""

    def __init__(self, messaggio: str, temporaneo: bool = True):
        super().__init__(messaggio)
        self.temporaneo = temporaneo


class Classificatore(Protocol):
    def classifica_thread(self, catalogo_testo: str, prompt: str) -> RisultatoThread: ...

    def classifica_documenti(self, catalogo_testo: str, prompt: str) -> RisultatoDocumenti: ...


@dataclass
class UsoToken:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    chiamate: int = 0

    def aggiungi(self, usage) -> None:  # noqa: ANN001
        self.chiamate += 1
        self.input += getattr(usage, "input_tokens", 0) or 0
        self.output += getattr(usage, "output_tokens", 0) or 0
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0

    def to_dict(self) -> dict[str, int]:
        return {
            "chiamate": self.chiamate,
            "input": self.input,
            "output": self.output,
            "cache_read": self.cache_read,
            "cache_write": self.cache_write,
        }


class ClassificatoreClaude:
    def __init__(self, settings: Settings | None = None, client: anthropic.Anthropic | None = None):
        self.settings = settings or get_settings()
        if client is not None:
            self.client = client
        elif self.settings.anthropic_api_key:
            self.client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key)
        else:
            self.client = anthropic.Anthropic()  # ANTHROPIC_API_KEY o profilo `ant auth login`
        self.uso = UsoToken()

    def _system(self, testo_base: str, catalogo_testo: str) -> list[dict]:
        return [
            {"type": "text", "text": testo_base, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": catalogo_testo, "cache_control": {"type": "ephemeral"}},
        ]

    def _chiama(self, system: list[dict], prompt: str, schema: type[BaseModel]) -> BaseModel:
        kwargs: dict = {
            "model": self.settings.claude_model,
            "max_tokens": self.settings.claude_max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "output_format": schema,
            "output_config": {"effort": self.settings.claude_effort},
        }
        if self.settings.claude_fallbacks:
            kwargs["betas"] = [BETA_FALLBACK]
            kwargs["fallbacks"] = "default"
        try:
            response = self.client.beta.messages.parse(**kwargs)
        except anthropic.RateLimitError as exc:
            raise ErroreClassificazione(f"Limite di richieste raggiunto: {exc.message}", temporaneo=True) from exc
        except anthropic.AuthenticationError as exc:
            raise ErroreClassificazione("Chiave API Anthropic non valida", temporaneo=False) from exc
        except anthropic.BadRequestError as exc:
            raise ErroreClassificazione(f"Richiesta non valida: {exc.message}", temporaneo=False) from exc
        except anthropic.APIStatusError as exc:
            raise ErroreClassificazione(f"Errore API ({exc.status_code}): {exc.message}", temporaneo=exc.status_code >= 500) from exc
        except anthropic.APIConnectionError as exc:
            raise ErroreClassificazione(f"Errore di rete verso Anthropic: {exc}", temporaneo=True) from exc
        self.uso.aggiungi(response.usage)
        if response.stop_reason == "refusal":
            dettaglio = getattr(response.stop_details, "explanation", None) if response.stop_details else None
            raise ErroreClassificazione(f"Il modello ha rifiutato la richiesta: {dettaglio or 'nessun dettaglio'}", temporaneo=False)
        if response.stop_reason == "max_tokens":
            raise ErroreClassificazione("Risposta troncata (max_tokens): ridurre la dimensione del thread", temporaneo=False)
        parsed = response.parsed_output
        if parsed is None:
            raise ErroreClassificazione("Risposta senza JSON valido", temporaneo=True)
        return parsed

    def classifica_thread(self, catalogo_testo: str, prompt: str) -> RisultatoThread:
        risultato = self._chiama(self._system(SYSTEM_PROMPT, catalogo_testo), prompt, RisultatoThread)
        return risultato  # type: ignore[return-value]

    def classifica_documenti(self, catalogo_testo: str, prompt: str) -> RisultatoDocumenti:
        risultato = self._chiama(self._system(SYSTEM_PROMPT_DOCUMENTI, catalogo_testo), prompt, RisultatoDocumenti)
        return risultato  # type: ignore[return-value]


class ClassificatoreNullo:
    """Non chiama l'IA: tutto resta da rivedere. Utile quando PMO_AI_ENABLED=false."""

    def classifica_thread(self, catalogo_testo: str, prompt: str) -> RisultatoThread:
        raise ErroreClassificazione("IA disabilitata (PMO_AI_ENABLED=false)", temporaneo=False)

    def classifica_documenti(self, catalogo_testo: str, prompt: str) -> RisultatoDocumenti:
        raise ErroreClassificazione("IA disabilitata (PMO_AI_ENABLED=false)", temporaneo=False)


def crea_classificatore(settings: Settings | None = None) -> Classificatore:
    settings = settings or get_settings()
    if not settings.ai_enabled:
        return ClassificatoreNullo()
    return ClassificatoreClaude(settings)
