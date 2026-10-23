# PMO La Traccia

Tracciabilità delle pratiche dalla **stima** all'**offerta**, all'**ordine**, alle **specifiche**, allo **sviluppo**, alla **consegna** e alla **fatturazione**, costruita a partire da ciò che già esiste: la posta Gmail e il Google Drive delle persone che seguono i progetti. Ogni pratica ha un identificativo univoco (`PMO-AAAA-NNNN`), una cronologia di eventi con il collegamento alla fonte (mail o documento) e un insieme di **solleciti automatici** (ordine senza specifiche, scadenze vicine o superate, consegnato ma non fatturato, fatturato diverso dall'ordinato, pratica ferma).

Il sistema nasce dalla proposta "tracciabilità ordini e solleciti automatici" e ne realizza la prima fase: una o più caselle personali (la propria e, ad esempio, quella del coordinatore tecnico), nessuna dipendenza da SIA, VTE o dalla casella di reparto. L'architettura è pensata per aggiungerli dopo (vedi [docs/architettura.md](docs/architettura.md)).

## Come funziona

1. **Caselle collegate.** Ogni persona collega la propria casella Google con OAuth (Gmail e Drive in sola lettura). I token sono salvati cifrati. Si possono collegare più caselle.
2. **Importazione.** Il sistema legge i messaggi nuovi (prima volta: una finestra di 120 giorni, poi in modo incrementale) e i file delle cartelle Drive scelte. Filtri deterministici scartano subito il rumore (notifiche, acquisti, newsletter). Il testo dei PDF allegati (ordini, offerte) viene estratto.
3. **Collegamento certo.** Un messaggio con il tag `[PMO-2026-0012]` nell'oggetto, o un messaggio di un thread già collegato, viene assegnato alla pratica senza bisogno dell'intelligenza artificiale.
4. **Classificazione con Claude.** Per tutto il resto il modello riceve il catalogo (clienti, prodotti, team, pratiche aperte) e il thread, e restituisce un JSON validato: pertinenza, pratica (esistente o nuova), eventi estratti con date, importi, scadenze e riferimenti (numero ordine, CIG, protocollo). Niente viene applicato alla cieca: le pratiche nuove e i collegamenti incerti finiscono nella **coda di revisione**; gli eventi con confidenza bassa restano "proposti" finché una persona non li conferma.
5. **Stato e cronologia.** Gli eventi confermati avanzano automaticamente lo stato della pratica (mai all'indietro) e aggiornano importi, scadenze e riferimenti.
6. **Solleciti.** Dopo ogni sincronizzazione le regole producono i solleciti, che si risolvono da soli quando la condizione cessa. Un **digest** giornaliero riepiloga solleciti e cose da verificare.

## Requisiti

- Python 3.12 o superiore (oppure Docker).
- Un database: SQLite per provare, PostgreSQL per l'uso reale (va bene anche un progetto Supabase).
- Un client OAuth Google del Workspace `latraccia.it` ([docs/setup-google.md](docs/setup-google.md)).
- Una chiave API Anthropic.

## Installazione rapida

```bash
git clone <questo repository> pmo && cd pmo
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
pmo gen-keys            # incolla PMO_SECRET_KEY e PMO_ENCRYPTION_KEY nel file .env
```

Compila in `.env` almeno `PMO_GOOGLE_CLIENT_ID`, `PMO_GOOGLE_CLIENT_SECRET`, `ANTHROPIC_API_KEY`, `PMO_BASE_URL` e, in produzione, `PMO_DATABASE_URL`. Poi:

```bash
pmo init-db             # crea lo schema e le regole predefinite
pmo seed                # carica clienti, prodotti e team da config/seed.yaml (modificabile)
pmo serve               # interfaccia su http://localhost:8000
```

Con Docker: `docker compose up -d` (PostgreSQL incluso, scheduler attivo), dopo aver preparato `.env`.

## Primi passi nell'interfaccia

1. **Accedi con Google** con un indirizzo del dominio ammesso. Il primo utente che entra diventa amministratore (oltre a quelli in `PMO_ADMIN_EMAILS`).
2. **Caselle → Collega con Google.** Autorizza la tua casella. Poi aggiungi le cartelle Drive da monitorare incollandone l'URL (ad esempio le cartelle Offerte, Ordini e le cartelle per cliente).
3. **Sincronizza ora.** La prima importazione legge la finestra configurata (`PMO_SYNC_WINDOW_DAYS`); se ci sono molti messaggi, i successivi vengono elaborati ai giri seguenti (al massimo `PMO_MAX_MESSAGES_PER_RUN` per volta). Da riga di comando: `pmo sync`.
4. **Revisione.** Conferma o scarta le pratiche proposte, collega a mano le mail che l'IA non ha saputo assegnare, verifica gli eventi proposti nel dettaglio di ogni pratica.
5. **Da oggi in poi** metti il tag della pratica nell'oggetto delle mail (nel dettaglio c'è il pulsante *Copia oggetto mail*): quelle mail vengono collegate senza ambiguità, anche se arrivano in copia ad altre caselle collegate.
6. **Solleciti e digest.** La pagina Solleciti mostra cosa sta scivolando; ogni sollecito si può prendere in carico, risolvere o silenziare per N giorni. Il digest parte ogni mattina se lo scheduler è attivo (`PMO_SCHEDULER_ENABLED=true`) oppure con `pmo digest`.

## Convenzione per l'oggetto delle mail

```
[PMO-2026-0012] Banca degli Occhi – offerta economica rimodulata
```

Il tag può stare ovunque nell'oggetto e sopravvive ai "Re:" e agli inoltri. Lo stesso codice può essere usato nel nome della cartella Drive della pratica: i file che lo contengono nel nome o nel percorso vengono collegati automaticamente.

## Riga di comando

| Comando | Cosa fa |
|---|---|
| `pmo init-db` | crea/aggiorna lo schema (Alembic) e le regole predefinite |
| `pmo seed [--file]` | carica anagrafiche da `config/seed.yaml` |
| `pmo serve` | avvia l'interfaccia web |
| `pmo sync [--account EMAIL] [--completa] [--giorni N] [--no-classifica]` | importa, classifica, esegue le regole |
| `pmo classifica` | classifica solo ciò che è in attesa (senza scaricare) |
| `pmo regole` | ricalcola i solleciti |
| `pmo digest [--anteprima] [--a EMAIL]` | invia o mostra il digest |
| `pmo stato` | riepilogo numerico |
| `pmo scheduler` | esegue lo scheduler in primo piano (alternativa a `PMO_SCHEDULER_ENABLED`) |
| `pmo caselle collega` | collega una casella dal terminale (apre il browser) |
| `pmo caselle cartella EMAIL URL` | aggiunge una cartella Drive da monitorare |
| `pmo utenti aggiungi EMAIL --admin` | abilita un utente |
| `pmo gen-keys` | genera le chiavi per `.env` |
| `pmo mcp [--scrittura]` | avvia il server MCP (stdio) per collegare l'applicazione a Claude |

## Collegare Claude (MCP)

`pmo mcp` espone pratiche, solleciti e coda di revisione a Claude Desktop e Claude Code tramite il Model Context Protocol: si può chiedere "quali ordini sono senza specifiche?" o "riassumi la pratica PMO-2026-0042". Parte in sola lettura, gira sul proprio PC e non apre porte di rete. Configurazione, strumenti disponibili e note sulla sicurezza in [docs/mcp.md](docs/mcp.md).

## Regole di sollecito

Soglie e gravità sono modificabili da *Impostazioni → Regole*. Dettagli in [docs/regole.md](docs/regole.md).

| Regola | Condizione predefinita |
|---|---|
| Ordine senza specifiche | stato "ordine" da più di 15 giorni senza specifiche ricevute/inviate |
| Stima non inviata | stato "stima" da più di 7 giorni senza stima inviata |
| Offerta senza risposta | stato "offerta" da più di 30 giorni |
| Scadenza vicina / superata | scadenza entro 7 giorni / già passata |
| Consegnato ma non fatturato | stato "consegna" da più di 30 giorni |
| Fatturato diverso dall'ordinato | differenza oltre 1% (o 1 €) |
| Pratica ferma | nessun evento da più di 30 giorni |
| Elementi da verificare | pratica o eventi proposti dall'IA in attesa da più di 3 giorni |

## Costi e scelta del modello

La classificazione usa Claude con structured outputs e prompt caching (il catalogo è condiviso tra le chiamate dello stesso giro). Con il modello predefinito `claude-opus-5-5` un thread costa indicativamente pochi centesimi; il primo giro su 120 giorni di posta è il più costoso, poi si lavora solo sui messaggi nuovi. Per ridurre i costi: `PMO_CLAUDE_MODEL=claude-sonnet-5-5` o `claude-haiku-5-5`, una finestra iniziale più corta, filtri più stretti (Impostazioni → Filtri) o un filtro Gmail per casella (ad esempio per escludere etichette personali). L'uso di token è registrato in ogni esecuzione (Caselle → Storico esecuzioni).

## Sicurezza

- Login solo con Google e domini ammessi; CSRF su tutte le azioni; sessioni firmate.
- Token OAuth cifrati con Fernet (`PMO_ENCRYPTION_KEY`), scope in sola lettura salvo `PMO_GMAIL_SEND_SCOPE`.
- Ogni utente vede e sincronizza le proprie caselle; gli amministratori tutte. Le pratiche sono condivise dal team.
- Il corpo delle mail viene salvato troncato (`PMO_BODY_MAX_CHARS`) per la revisione e il contesto dell'IA; gli allegati non vengono conservati, solo un estratto testuale.

## Sviluppo

```bash
pip install -e ".[dev]"
ruff check src tests
pytest
```

I test usano SQLite e un classificatore finto: non chiamano Google né Anthropic. Con `PMO_DEV_LOGIN=true` si entra con la sola email, utile in locale.

## Struttura del progetto

```
src/pmo/
  config.py            impostazioni (variabili PMO_*)
  db/                  modelli SQLAlchemy, sessioni
  connectors/          OAuth Google, Gmail, Drive
  ingest/              filtri, catalogo, classificatore Claude, collegamento, sincronizzazioni
  rules/               regole di sollecito e motore
  services/            pratiche ed eventi, codici, digest, seed, orchestrazione
  web/                 FastAPI, template Jinja, CSS
  cli.py, scheduler.py, mcp_server.py
alembic/               migrazioni
config/seed.yaml       anagrafiche iniziali
docs/                  architettura, setup Google, regole
tests/
```

Documentazione: [docs/architettura.md](docs/architettura.md) · [docs/setup-google.md](docs/setup-google.md) · [docs/regole.md](docs/regole.md) · [docs/mcp.md](docs/mcp.md).
