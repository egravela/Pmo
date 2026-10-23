# Collegare PMO a Claude (MCP)

`pmo mcp` avvia un server [MCP](https://modelcontextprotocol.io) che permette a Claude di consultare le pratiche, i solleciti e la coda di revisione. Si usa da Claude Desktop e da Claude Code; chiede a Claude cose come:

- "Quali ordini sono senza specifiche da più di 15 giorni?"
- "Riassumi la pratica PMO-2026-0042: cosa è successo e cosa manca?"
- "Fammi vedere le pratiche proposte dall'IA per Azienda Zero, da confermare."
- "Cerca nei documenti l'ID dell'accordo quadro SAC 3."

## Come funziona

Il server gira **sul tuo PC**, avviato da Claude, sul trasporto *stdio*: legge lo stesso database dell'applicazione (`PMO_DATABASE_URL` dal tuo `.env`) e non apre porte di rete. Non serve che l'interfaccia web o la sincronizzazione siano in esecuzione, e può restare attivo mentre `pmo sync` lavora.

Non è utilizzabile come connettore remoto di claude.ai (web o telefono): quello richiederebbe un indirizzo pubblico, l'autenticazione OAuth e l'esposizione dei dati della Cooperativa su internet. Per ora il collegamento è solo locale.

## Installazione

Il pacchetto `mcp` è tra le dipendenze del progetto. In un ambiente già installato:

```bash
pip install -e .
pmo mcp --help
```

## Configurazione

### Claude Desktop

Apri **Impostazioni → Sviluppatore → Modifica configurazione**: si apre il file `claude_desktop_config.json` giusto per la tua installazione. Aggiungi:

```json
{
  "mcpServers": {
    "pmo": {
      "command": "C:\\percorso\\del\\progetto\\.venv\\Scripts\\pmo.exe",
      "args": ["mcp"]
    }
  }
}
```

Su macOS/Linux il comando è `/percorso/del/progetto/.venv/bin/pmo`. Riavvia Claude Desktop: compare lo strumento "pmo".

### Claude Code

```bash
claude mcp add pmo -- "C:\percorso\del\progetto\.venv\Scripts\pmo.exe" mcp
```

Con `--scope user` è disponibile in tutti i progetti, con `--scope project` viene salvato in `.mcp.json` (attenzione: contiene un percorso del tuo PC).

Non serve impostare la cartella di lavoro né variabili d'ambiente: all'avvio `pmo mcp` si sposta nella cartella del progetto, dove trova `.env` e il database SQLite.

## Strumenti disponibili

Di sola lettura (sempre attivi):

| Strumento | Cosa restituisce |
|---|---|
| `stato_sistema` | pratiche per stato, solleciti aperti, elementi da verificare, caselle e ultime sincronizzazioni |
| `catalogo` | clienti (con alias), prodotti, stati ed eventi ammessi |
| `elenca_pratiche` | pratiche filtrabili per testo, stato, cliente, prodotto, verifica, scadenza |
| `dettaglio_pratica` | dati, cronologia con link alle fonti, solleciti, messaggi e documenti collegati |
| `elenca_solleciti` | solleciti automatici, dal più grave |
| `coda_revisione` | pratiche proposte dall'IA, messaggi e documenti da rivedere, errori |
| `cerca_messaggi` | ricerca nella posta importata (oggetto, mittente, anteprima, link a Gmail) |
| `cerca_documenti` | ricerca nei documenti di Drive importati (nome, percorso, estratto) |

Un elenco restituisce al massimo 100 elementi e dice sempre il totale; i testi lunghi sono troncati.

### Azioni di scrittura (opzionali)

Si abilitano solo avviando il server con `--scrittura` (`"args": ["mcp", "--scrittura"]`). Ogni modifica è attribuita all'utente indicato con `--utente EMAIL` (predefinito: il primo di `PMO_ADMIN_EMAILS`) e appare nella cronologia della pratica con la nota "via MCP".

| Strumento | Cosa fa |
|---|---|
| `aggiungi_nota` | aggiunge una nota, un promemoria o una riunione alla cronologia (non cambia lo stato) |
| `cambia_stato_pratica` | cambia lo stato di una pratica |
| `conferma_pratica` | conferma una pratica proposta dall'IA (come "Conferma" in Revisione) |
| `scarta_pratica` | scarta una pratica proposta; rifiuta le pratiche già confermate |
| `aggiorna_sollecito` | prende in carico, risolve, silenzia o riapre un sollecito |

Claude è istruito a usarle solo su richiesta esplicita e a chiedere conferma prima di confermare, scartare o cambiare stato. Non esistono strumenti per eliminare dati, unire pratiche, inviare mail o toccare le impostazioni.

## Sicurezza

- **I dati passano da Claude.** Quando Claude legge una pratica, il testo restituito entra nella conversazione e viene elaborato da Anthropic, come per qualsiasi altro contenuto condiviso con Claude. Valuta se è adatto ai dati della Cooperativa e dei suoi clienti. I corpi completi delle mail non vengono mai restituiti: solo oggetto, mittente, anteprima di circa 250 caratteri e link a Gmail.
- **Le mail sono dati non attendibili.** Un'email o un documento può contenere testo pensato per ingannare l'assistente ("ignora le istruzioni precedenti e..."). Il server avverte Claude di trattare quei contenuti come dati. Per questo la sola lettura è la modalità predefinita: abilita `--scrittura` solo se ti serve e rileggi ciò che Claude propone di fare.
- **Chi può usarlo.** Il server non ha un proprio login: chi può avviare `pmo mcp` sul tuo PC con il tuo `.env` accede ai dati, esattamente come con `pmo stato`. Non esporre il processo in rete.
- **Token e segreti.** Il server non restituisce mai token OAuth, chiavi o contenuto del `.env`, e non esegue sincronizzazioni né chiamate a Google o ad Anthropic.

## Risoluzione dei problemi

- **Lo strumento non compare:** controlla il percorso di `pmo.exe` nella configurazione e riavvia Claude. Prova `pmo mcp` da terminale: deve restare in attesa senza errori (Ctrl+C per uscire).
- **"database is locked":** SQLite è occupato da una sincronizzazione; riprova dopo qualche secondo.
- **Dati vecchi o mancanti:** il server legge ciò che la sincronizzazione ha già importato; lancia `pmo sync` o guarda `stato_sistema`.
- **Log:** il server scrive i log su stderr (`PMO_LOG_LEVEL=DEBUG` nel `.env` per più dettagli); stdout è riservato al protocollo.
