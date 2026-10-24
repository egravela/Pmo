---
name: collega
description: Verifica e ripara il collegamento tra Claude Code e il sistema PMO La Traccia via MCP, e abilita o disabilita le azioni di scrittura. Usala quando gli strumenti pmo non compaiono, il server non parte, l'utente vuole collegare PMO per la prima volta o attivare la modalità di scrittura.
argument-hint: "[scrittura | lettura]"
allowed-tools: mcp__plugin_pmo-la-traccia_pmo__stato_sistema
---

# Collegare Claude Code a PMO La Traccia

Argomento ricevuto: `$ARGUMENTS` (vuoto = solo verifica del collegamento).

Non stampare mai il contenuto del file `.env` né chiavi o token.

## 1. Verifica

Cerca tra gli strumenti disponibili `stato_sistema` del server `pmo`.

- **C'è**: chiamalo. Se risponde, il collegamento funziona: riassumi in due righe lo stato (pratiche, solleciti, ultima sincronizzazione) e dì se la scrittura è abilitata (cerca `conferma_pratica` tra gli strumenti). Poi passa al punto 4 se è stato chiesto `scrittura` o `lettura`; altrimenti fermati.
- **Non c'è**: vai al punto 2.

## 2. Diagnosi

1. Chiedi all'utente di eseguire `/mcp` (o esegui `claude mcp list`) per vedere se il server `pmo` esiste e che stato ha: connesso, in errore, in attesa di approvazione.
2. **Il plugin non è installato**: serve installarlo (vedi `docs/mcp.md` del progetto):
   ```
   claude plugin marketplace add <cartella del progetto o egravela/Pmo>
   claude plugin install pmo-la-traccia@la-traccia
   ```
   Alla richiesta indicare il percorso del comando `pmo` (punto 3).
3. **Il server è in errore**: individua il comando `pmo` configurato e provalo da terminale, nell'ordine:
   - il file esiste? Windows: `<cartella del progetto>\.venv\Scripts\pmo.exe`; macOS e Linux: `<cartella del progetto>/.venv/bin/pmo`;
   - `"<percorso>" mcp --help` mostra le opzioni `--scrittura` e `--utente`; se no, il pacchetto è vecchio: `pip install -e .` nella cartella del progetto;
   - `"<percorso>" stato` stampa i conteggi in JSON; se fallisce c'è un problema di database o di `.env` (variabili `PMO_DATABASE_URL` e simili, nella cartella del progetto), non di MCP;
   - "database is locked": una sincronizzazione sta scrivendo, riprova tra qualche secondo;
   - Windows, "Un criterio di controllo dell'applicazione ha bloccato il file": una libreria con parti native (ad esempio `jiter`) è bloccata dai criteri di sicurezza; non modificare le impostazioni di sistema, installa nel venv una versione precedente di quel pacchetto.
4. Dopo aver corretto, l'utente deve ricaricare i plugin (`/reload-plugins`) o riavviare la sessione.

## 3. Impostare il percorso del comando

Il plugin chiede il percorso di `pmo` quando viene abilitato. Per cambiarlo in seguito, l'utente apre `/config` e modifica le opzioni di `pmo-la-traccia`; poi `/reload-plugins`.

**Senza il plugin** (collegamento manuale), una volta sola e solo se `claude mcp list` non mostra già un server `pmo` (altrimenti gli strumenti risulterebbero doppi):

```
claude mcp add --scope user pmo -- "<percorso di pmo>" mcp
```

Con `--scope user` vale per tutti i progetti. Per rimuoverlo: `claude mcp remove pmo`.

## 4. Scrittura o sola lettura

La scrittura si abilita **solo su richiesta esplicita** dell'utente, non per comodità. Prima spiega cosa permette: confermare o scartare pratiche proposte dall'IA, cambiare stati, aggiungere note e gestire i solleciti, sempre registrate nella cronologia con la nota "via MCP". Ricorda il rischio: mail e documenti sono contenuti esterni che potrebbero contenere istruzioni ingannevoli; per questo la sola lettura è il valore predefinito.

- **Con il plugin**: l'opzione "Abilita le azioni di scrittura" in `/config` → `pmo-la-traccia`, poi `/reload-plugins`.
- **Collegamento manuale**: rimuovi e ricrea il server con `--scrittura` dopo `mcp`: `claude mcp add --scope user pmo -- "<percorso di pmo>" mcp --scrittura`.

Riporta all'utente come tornare alla sola lettura (disattivare l'opzione o ricreare il server senza `--scrittura`).

## 5. Esito

Concludi con una riga: collegato o no, modalità (lettura o scrittura), e il prossimo passo se qualcosa non va.
