# Avvia il server di PMO La Traccia (interfaccia web e scheduler della sincronizzazione) in background.
# Lo lancia all'accesso a Windows l'attività pianificata "PMO La Traccia - server" (vedi docs/avvio-automatico.md).
# Se il server risponde già sulla porta, non fa nulla. Il log è in data\logs\server.log.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$porta = 8001
if (Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue) { exit 0 }

$cartellaLog = Join-Path $repo "data\logs"
New-Item -ItemType Directory -Force $cartellaLog | Out-Null
$log = Join-Path $cartellaLog "server.log"
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 5MB)) { Move-Item $log "$log.old" -Force }

$programma = Join-Path $repo ".venv\Scripts\pmo.exe"
# cmd gestisce la redirezione di stdout e stderr: PowerShell 5.1 la sporcherebbe con record di errore
& cmd.exe /c "`"$programma`" serve --host 127.0.0.1 --port $porta >> `"$log`" 2>&1"
