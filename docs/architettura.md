# Architettura

## Obiettivo

Dare una visione unica di ogni pratica (stima → offerta → ordine → specifiche → sviluppo → consegna → fatturazione) ricostruendola da mail e documenti, con un identificativo condiviso, una cronologia verificabile e solleciti automatici. Prima fase: caselle personali e Drive delle persone del team. Fasi successive: casella di reparto, SIA, VTE.

## Componenti

```
Gmail / Drive (per casella)        Claude (structured outputs)
        │                                   ▲
        ▼                                   │
 connectors/ ──► ingest/gmail_sync ──► ingest/classifier ──► ingest/linker ──► pratiche / eventi
                 ingest/drive_sync        (catalogo cacheato)                       │
                                                                                    ▼
                                                             rules/engine ──► solleciti ──► digest
                                                                                    │
                                                                   web/ (FastAPI + Jinja)  cli.py  scheduler.py
```

- **connectors/google_oauth.py** – due flussi OAuth con lo stesso client: login (OpenID) e collegamento casella (`gmail.readonly`, `drive.readonly`, opzionale `gmail.send`, `access_type=offline`). Il refresh token è cifrato con Fernet.
- **connectors/gmail.py** – ricerca per finestra (`after:` + esclusioni), lettura incrementale con `history.list` (ripiego sulla finestra se il history id è scaduto), lettura in batch, parsing MIME (testo, HTML→testo, allegati), invio.
- **connectors/drive.py** – visita in ampiezza delle cartelle monitorate, estratto testuale (export dei formati Google, PDF/DOCX scaricati e letti con pypdf/python-docx).
- **ingest/filters.py** – pulizia (citazioni rimosse, inoltri mantenuti) e filtri anti-rumore configurabili: categorie Gmail, mittenti automatici, newsletter (`List-Unsubscribe` da domini esterni), oggetti da e-commerce e corrieri. Un tag pratica nell'oggetto vince sempre.
- **ingest/catalogo.py** – il contesto dato al modello: clienti (con alias e domini), prodotti, team, pratiche aperte (fino a 200, le più attive).
- **ingest/classifier.py** – `client.beta.messages.parse` con schema Pydantic (`RisultatoThread`, `RisultatoDocumenti`), `output_config.effort`, prompt caching sui due blocchi di sistema (istruzioni e catalogo), fallback server-side in caso di rifiuto, gestione di `stop_reason` e degli errori API. `ClassificatoreNullo` quando `PMO_AI_ENABLED=false`.
- **ingest/linker.py** – applica i risultati: collegamento (esistente/nuova/nessuno), creazione di pratiche proposte (con deduplica per titolo), eventi idempotenti per chiave `email:<account>:<id>:<tipo>`, soglie di confidenza.
- **services/pratiche.py** – dominio: codici progressivi per anno, creazione, eventi, avanzamento di stato (solo in avanti, mai per eventi proposti), aggiornamento importi e scadenze, conferma/rifiuto, unione di doppioni.
- **rules/engine.py** – valuta le regole su ogni pratica confermata; i solleciti hanno chiave `<pratica>:<regola>`: aggiornati se persistono, risolti dal sistema se cessano, riaperti se ricompaiono, silenziabili con snooze.
- **services/digest.py** – riepilogo giornaliero via Gmail API (se una casella ha lo scope di invio) o SMTP.
- **services/sync.py** – orchestrazione con lock per casella; usata da CLI, scheduler e pulsante "Sincronizza ora".
- **web/** – interfaccia server-side in italiano: cruscotto, pratiche (elenco, dettaglio con cronologia e fonti, scheda), solleciti, coda di revisione, caselle e cartelle, impostazioni (regole, filtri, digest, clienti, prodotti, utenti).

## Modello dati

| Tabella | Contenuto |
|---|---|
| `users` | persone del team abilitate (ruolo admin/membro, digest) |
| `accounts` | caselle collegate: token cifrato, scope, filtro Gmail, segnalibri (`gmail_history_id`, date di sync) |
| `watched_folders` | cartelle Drive monitorate per casella |
| `clienti`, `prodotti` | anagrafiche con alias e domini email (migliorano la classificazione) |
| `pratiche` | codice, titolo, cliente, prodotto, stato e `stato_dal`, importi (stima/offerta/ordine/fatturato), scadenza, riferimenti JSON (numero ordine, CIG, protocollo, id SIA/VTE…), `stato_verifica` (confermata/proposta), origine |
| `eventi` | cronologia: tipo, data, titolo, descrizione, fonte (email/drive/manuale/sistema) con id e URL, importo, scadenza, confidenza, `stato_verifica` |
| `messaggi` | mail importate: intestazioni, corpo troncato, allegati (metadati + testo estratto), stato (nuovo/classificato/da_rivedere/ignorato/errore), pratica e origine del collegamento (tag/thread/ai/manuale), esito della classificazione |
| `documenti` | file Drive: percorso, tipo, estratto, stato, pratica |
| `regole`, `solleciti` | configurazione delle regole e solleciti generati |
| `sync_runs` | storico delle esecuzioni con contatori (anche token usati) ed errori |
| `sequenze_codici`, `impostazioni` | progressivi per anno; impostazioni modificabili dall'interfaccia |

## Stati e transizioni

Fasi ordinate: `bozza → stima → offerta → ordine → specifiche → sviluppo → consegna → fatturazione → chiusa`; stati fuori sequenza: `sospesa`, `annullata`.

Un evento confermato porta la pratica alla fase che implica (tabella `FASE_PER_EVENTO` in `db/models.py`) solo se è successiva a quella attuale. I cambi di stato manuali sono sempre possibili e tracciati come eventi di sistema.

## Flusso di una sincronizzazione

1. `sincronizza_gmail`: elenco id (history o finestra) → esclusione di quelli già noti → lettura in batch → parsing → filtri → salvataggio (`nuovo` o `ignorato`) → pre-collegamento per tag o thread → aggiornamento segnalibri.
2. `sincronizza_drive`: per ogni cartella monitorata, file nuovi o modificati → estratto → salvataggio → pre-collegamento per tag nel nome/percorso.
3. `classifica_messaggi`: messaggi `nuovo` raggruppati per thread → prompt con storia del thread e pratica pre-collegata → chiamata al modello → `collega_messaggio`. Errori temporanei: nuovo tentativo al giro successivo (massimo 3). Commit per thread.
4. `classifica_documenti`: a gruppi di 8 → `collega_documento`.
5. `esegui_regole`: aggiorna i solleciti.

## Decisioni e limiti

- **Determinismo prima dell'IA**: tag, thread, filtri e regole sono codice; l'IA propone, le persone confermano quando la confidenza è bassa. Ogni evento conserva la fonte.
- **Sola lettura su Google**: nessuna etichetta o modifica viene scritta nelle caselle.
- **Una istanza**: lo scheduler in-process e il lock di sincronizzazione presuppongono un solo processo applicativo (più worker uvicorn avvierebbero più scheduler). Per scalare: `pmo scheduler` in un processo separato e `PMO_SCHEDULER_ENABLED=false` nel web.
- **Finestra iniziale**: la prima importazione è limitata a `PMO_SYNC_WINDOW_DAYS`; il backlog di classificazione viene smaltito `PMO_MAX_MESSAGES_PER_RUN` messaggi per giro.

## Evoluzione verso la proposta completa

| Richiesta | Come si innesta |
|---|---|
| Casella di reparto `coordinamentosanita@` sempre in copia | si collega come una casella qualsiasi; essendo in copia su tutto, diventa la fonte principale e le caselle personali servono per ciò che non la include |
| Identificativo unico in mail, cartelle, SIA, VTE | il codice `PMO-AAAA-NNNN` è già il perno; i campi `riferimenti.id_sia` e `riferimenti.id_vte` legano i sistemi esterni |
| Cronologia eventi gestita nel SIA | gli eventi hanno chiave e fonte: esportabili verso il SIA o importabili da esso con un connettore dedicato (stesso schema di `Evento`) |
| Eliminare la ricopiatura SIA → VTE | il contenuto strutturato dell'ordine (importo, riferimenti, cliente, prodotto) è già estratto: un connettore VTE può usarlo per precompilare |
| Oggetti mail strutturati | il tag è la parte obbligatoria; si può aggiungere una convenzione `[PMO-…][CLIENTE][FASE]` senza cambiare il codice |
