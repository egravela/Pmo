# Prompt per Claude Code: avvio del progetto PMO sul mio PC

Copia tutto il testo sotto la riga e incollalo come primo messaggio in una sessione Claude Code aperta sul tuo computer, in una cartella vuota.

---

Sei Claude Code in una sessione locale sul mio computer. Il tuo compito è far partire sul mio PC il progetto **PMO La Traccia**, verificarne il funzionamento con i miei dati reali e correggere ciò che eventualmente non funziona. Rispondi in italiano.

## Contesto

Il repository è `https://github.com/egravela/Pmo`, branch `ccr-f1c3ae55-xraq7l` (è il branch predefinito; non ne esistono altri). Il progetto è un'applicazione Python che ricostruisce le "pratiche" della Cooperativa EDP La Traccia (stima → offerta → ordine → specifiche → sviluppo → consegna → fatturazione) leggendo la posta Gmail e le cartelle Google Drive delle persone del team. Ogni pratica ha un codice `PMO-AAAA-NNNN`, una cronologia di eventi collegati alla fonte e dei solleciti automatici (ordine senza specifiche, scadenze, consegnato ma non fatturato, ecc.). La classificazione delle mail usa l'API Anthropic (Claude) con output strutturato; i collegamenti certi (tag nell'oggetto, thread già collegati) non passano dall'IA.

Stack: Python 3.12+, FastAPI + Jinja (interfaccia web in italiano), SQLAlchemy + Alembic, Google API (OAuth, Gmail, Drive), SDK Anthropic, APScheduler, Typer per la CLI (`pmo`). Documentazione nel repo: `README.md`, `docs/setup-google.md`, `docs/architettura.md`, `docs/regole.md`, `.env.example`, `config/seed.yaml`.

Stato attuale, importante: il codice è stato scritto in una sessione cloud senza credenziali Google né Anthropic. I 35 test passano, ma usano SQLite e un classificatore finto. **Le chiamate reali a Gmail, Drive e Anthropic non sono mai state eseguite**: la prima sincronizzazione va seguita con attenzione e, se emergono errori nei connettori o nel classificatore, vanno corretti.

## Regole di lavoro

- Procedi un passo alla volta e verifica l'esito di ciascuno prima di passare al successivo.
- Chiedimi solo ciò che posso fornire solo io: credenziali OAuth Google, chiave API Anthropic, cartelle Drive da monitorare, eventuale stringa di connessione a un database esterno.
- Non stampare mai in chat il contenuto del file `.env` e non incollare mai chiavi o segreti nelle risposte. Il file `.env` è ignorato da git: non deve essere committato.
- Se devi correggere il codice: modifiche minime, `ruff check src tests` e `pytest` verdi, commit sul branch `ccr-f1c3ae55-xraq7l` con messaggio chiaro, `git push`. Non cambiare l'architettura e non aggiungere funzionalità non richieste.
- Se un comando fallisce, leggi l'errore, spiegamelo in una riga e proponi la correzione prima di cambiare configurazioni di sistema.

## Passo 1. Prerequisiti

Verifica che siano disponibili `git` e Python 3.12 o superiore (`python3 --version` su macOS/Linux, `py -3 --version` o `python --version` su Windows). Se Python manca o è più vecchio: su Windows installalo da python.org o con `winget install Python.Python.3.12` spuntando "Add to PATH"; su macOS con `brew install python@3.12`. Dimmi quale sistema operativo rilevi e adatta i comandi seguenti.

## Passo 2. Clone e ambiente virtuale

macOS/Linux:

```bash
git clone https://github.com/egravela/Pmo.git pmo && cd pmo
python3 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip && pip install -e ".[dev]"
pytest -q
```

Windows (PowerShell):

```powershell
git clone https://github.com/egravela/Pmo.git pmo; cd pmo
py -3 -m venv .venv; .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip; pip install -e ".[dev]"
pytest -q
```

Se PowerShell blocca l'attivazione, esegui prima `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. I test devono passare tutti: se qualcosa fallisce già qui, fermati e indagine.

## Passo 3. File di configurazione

Copia `.env.example` in `.env` (`cp` su macOS/Linux, `Copy-Item` su Windows), poi esegui `pmo gen-keys` e inserisci in `.env` i valori generati per `PMO_SECRET_KEY` e `PMO_ENCRYPTION_KEY`. Imposta inoltre:

- `PMO_BASE_URL=http://localhost:8000`
- `PMO_DATABASE_URL=sqlite:///data/pmo.sqlite` per la prova (il database esterno viene dopo)
- `PMO_ALLOWED_DOMAINS=latraccia.it`
- `PMO_ADMIN_EMAILS=egravela@latraccia.it`
- `PMO_SYNC_WINDOW_DAYS=30` per il primo giro (poi lo porteremo a 120)
- `PMO_DEV_LOGIN=true` solo se voglio vedere l'interfaccia prima di configurare Google; va rimesso a `false` dopo

Lascia il modello predefinito `claude-opus-5-5`; se voglio contenere i costi della prova, propongo `claude-sonnet-5-5`.

## Passo 4. Client OAuth Google (devo farlo io, guidami)

Serve un client OAuth del Workspace `latraccia.it`. Guidami nella Google Cloud Console con questi passi, uno alla volta, e aspetta la mia conferma:

1. Creare un progetto (ad esempio `pmo-latraccia`) nell'organizzazione del Workspace.
2. In "API e servizi → Libreria" abilitare **Gmail API** e **Google Drive API**.
3. In "Schermata consenso OAuth" scegliere tipo utente **Interno**. È essenziale: con un'app "Esterna" in stato di test i refresh token scadono dopo 7 giorni e gli scope Gmail/Drive richiederebbero la verifica di Google. Aggiungere gli scope `openid`, `userinfo.email`, `userinfo.profile`, `https://www.googleapis.com/auth/gmail.readonly`, `https://www.googleapis.com/auth/drive.readonly`.
4. In "Credenziali" creare un **ID client OAuth** di tipo **Applicazione web** con questi URI di reindirizzamento autorizzati: `http://localhost:8000/auth/callback` e `http://localhost:8000/caselle/callback`. Se vorrò collegare caselle dal terminale, aggiungere anche `http://localhost:8765/`.
5. Mi dirai dove incollare ID client e secret in `.env` (`PMO_GOOGLE_CLIENT_ID`, `PMO_GOOGLE_CLIENT_SECRET`). Non chiedermi di scriverli in chat: li inserisco io nel file.

## Passo 5. Chiave Anthropic

Chiedimi di inserire la chiave in `.env` come `ANTHROPIC_API_KEY`. Verifica che sia letta senza stamparla, ad esempio con un piccolo script che controlla solo che la variabile non sia vuota.

## Passo 6. Database e anagrafiche

```bash
pmo init-db
pmo seed
pmo stato
```

`pmo seed` carica clienti, prodotti e team da `config/seed.yaml`: mostrami l'elenco dei clienti e dei prodotti caricati e chiedimi se c'è qualcosa da correggere o aggiungere (alias e domini email migliorano i collegamenti automatici).

## Passo 7. Avvio e collegamento della casella

Avvia `pmo serve` in un terminale dedicato (o in background) e dimmi di aprire `http://localhost:8000`. Poi, nell'ordine:

1. "Accedi con Google" con `egravela@latraccia.it`.
2. Pagina **Caselle → Collega con Google**: autorizzo la mia casella.
3. Nella stessa pagina aggiungo le cartelle Drive da monitorare incollandone l'URL. Chiedimi quali: candidate le cartelle "Ordini", "OFFERTE", "Clienti" e le cartelle per cliente come "Umberto I".
4. Prima sincronizzazione di prova con una finestra corta, dal terminale, così vediamo i log:

```bash
pmo sync --giorni 14
```

Se preferisco dall'interfaccia: pulsante "Sincronizza ora" indicando 14 giorni.

## Passo 8. Verifica e correzione

Controlla l'esito in **Caselle → Storico esecuzioni** (o con `pmo caselle elenco` e `pmo stato`): per ogni esecuzione ci sono contatori, errori e token consumati. Problemi possibili e dove guardare:

- `redirect_uri_mismatch`: l'URI in `PMO_BASE_URL` non coincide con quelli autorizzati su Google (http/https, porta).
- `invalid_grant` o "nessun refresh token": scollegare e ricollegare la casella dall'interfaccia.
- Errori 403 "insufficient scopes": gli scope sulla schermata di consenso non includono Gmail o Drive.
- Errori 429 da Gmail: il client legge a lotti; in caso di limiti ridurre `PMO_MAX_MESSAGES_PER_RUN`.
- Errori dall'API Anthropic (401 chiave, 400 modello o parametri, 429 limiti): il codice è in `src/pmo/ingest/classifier.py`; i messaggi restano in stato "nuovo" e vengono ritentati al giro successivo, dopo tre errori passano in "errore" e si rilanciano dalla pagina Revisione.
- Messaggi importati ma mai classificati: controlla `PMO_AI_ENABLED` e la chiave.

Per avere più dettagli: `PMO_LOG_LEVEL=DEBUG` in `.env`. I file da conoscere per eventuali correzioni: `src/pmo/connectors/google_oauth.py`, `src/pmo/connectors/gmail.py`, `src/pmo/connectors/drive.py`, `src/pmo/ingest/gmail_sync.py`, `src/pmo/ingest/drive_sync.py`, `src/pmo/ingest/classifier.py`, `src/pmo/ingest/linker.py`. Ogni correzione va coperta, dove ha senso, da un test in `tests/`, poi commit e push come da regole.

Poi fammi usare l'interfaccia: pagina **Revisione** per confermare o scartare le pratiche proposte dall'IA e collegare le mail incerte, pagina **Pratiche** per vedere la cronologia, pagina **Solleciti**. Controlla anche `pmo digest --anteprima`.

## Passo 9. Messa a regime

Quando la prova è soddisfacente:

1. Porta `PMO_SYNC_WINDOW_DAYS` a 120 e lancia `pmo sync` più volte finché il backlog è smaltito (al massimo `PMO_MAX_MESSAGES_PER_RUN` messaggi per giro; riportami i token consumati per giro, così stimiamo il costo).
2. Attiva lo scheduler: `PMO_SCHEDULER_ENABLED=true` nel processo web oppure `pmo scheduler` in un secondo terminale. Il digest parte alle 8:00, orario in `PMO_DIGEST_HOUR`. Per inviarlo dalla mia casella serve `PMO_GMAIL_SEND_SCOPE=true`, lo scope `gmail.send` sulla schermata di consenso e un ricollegamento della casella; in alternativa configura SMTP.
3. Spiegami come usare il tag `[PMO-AAAA-NNNN]` negli oggetti delle mail da oggi in poi (nel dettaglio di ogni pratica c'è "Copia oggetto mail").

## Passo 10. Opzionali, solo se te lo chiedo

- Casella del coordinatore tecnico Pasquale Loizzo: lui accede all'interfaccia con il suo account e collega la propria casella dalla pagina Caselle. Il consenso deve darlo lui.
- Database PostgreSQL o Supabase: basta impostare `PMO_DATABASE_URL=postgresql+psycopg://...` ed eseguire `pmo init-db`.
- Esecuzione in Docker su un server: `docker compose up -d` con lo stesso `.env` e gli URI di reindirizzamento aggiornati all'URL pubblico.

## Cosa voglio alla fine

Un riepilogo con: esito di ogni passo, problemi trovati e correzioni committate (con hash dei commit), numero di messaggi importati, classificati, da rivedere e ignorati, token consumati dalla prima sincronizzazione, e i prossimi passi consigliati.
