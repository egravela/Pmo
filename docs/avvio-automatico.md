# Avvio automatico su Windows

Il server di PMO (interfaccia web e scheduler della sincronizzazione) parte da solo quando accedi a Windows, grazie a
un'attività pianificata. Funziona finché il PC è acceso e tu hai effettuato l'accesso.

## Cosa fa

- **Attività:** `PMO La Traccia - server` (Utilità di pianificazione di Windows), con il tuo utente e senza privilegi
  di amministratore. Parte 30 secondi dopo l'accesso, se si ferma si riavvia (fino a 5 volte, a distanza di un minuto)
  e non ha limiti di durata.
- **Script:** `scripts/avvia_pmo.ps1`. Se il server risponde già sulla porta 8001 non fa nulla, quindi non si creano
  doppioni. Scrive il log in `data/logs/server.log` (ruotato a 5 MB in `server.log.old`).
- **Indirizzo:** `http://localhost:8001` (deve coincidere con `PMO_BASE_URL` e con gli URI di reindirizzamento di Google).

## Scheduler

Con `PMO_SCHEDULER_ENABLED=true` in `.env` il server esegue ogni `PMO_SYNC_INTERVAL_MINUTES` (30) la sincronizzazione
completa: lettura di Gmail e Drive, classificazione con l'IA e calcolo dei solleciti. Se il PC è spento o in
sospensione i giri saltati non si recuperano uno per uno: al risveglio ne parte uno solo.

- **Costo:** la lettura di Gmail e Drive è gratuita. La classificazione consuma token Anthropic solo per la posta nuova
  (poche decine di messaggi al giorno).
- **Credito esaurito:** la classificazione si ferma dopo 5 richieste rifiutate e i messaggi restano in coda "nuovi".
  Si recuperano da soli al giro successivo, dopo la ricarica. Ogni giro fallito compare nello storico delle esecuzioni.
- **Digest delle 8:00:** `PMO_DIGEST_ENABLED=false` finché non c'è un canale di invio (scope `gmail.send` con
  `PMO_GMAIL_SEND_SCOPE=true` e ricollegamento della casella, oppure SMTP). Con il digest attivo e nessun canale, ogni
  mattina verrebbe registrato un errore.

## Comandi utili (PowerShell)

```powershell
# Stato dell'attività e dell'ultimo avvio
Get-ScheduledTask -TaskName "PMO La Traccia - server" | Get-ScheduledTaskInfo

# Avviarla o fermarla ora
Start-ScheduledTask -TaskName "PMO La Traccia - server"
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*pmo*serve*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# Non farla più partire all'accesso (e riabilitarla)
Disable-ScheduledTask -TaskName "PMO La Traccia - server"
Enable-ScheduledTask -TaskName "PMO La Traccia - server"

# Rimuoverla del tutto
Unregister-ScheduledTask -TaskName "PMO La Traccia - server" -Confirm:$false

# Ultime righe del log
Get-Content data\logs\server.log -Tail 50
```

Dopo aver cambiato `.env` il server va riavviato: ferma i processi come sopra e lancia `Start-ScheduledTask`.

## Se cambi cartella o computer

L'attività punta al percorso assoluto di `scripts/avvia_pmo.ps1`. Su un altro PC, o se sposti la cartella, va
ricreata (da PowerShell, correggendo `$repo`); in alternativa usa il Docker Compose: `docker compose up -d`.

```powershell
$repo = "C:\percorso\della\cartella\pmo"
$utente = "$env:USERDOMAIN\$env:USERNAME"
$azione = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $repo `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$repo\scripts\avvia_pmo.ps1`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $utente
$trigger.Delay = "PT30S"
$impostazioni = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $utente -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "PMO La Traccia - server" -Action $azione -Trigger $trigger `
  -Settings $impostazioni -Principal $principal
```
