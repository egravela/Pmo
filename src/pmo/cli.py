"""Interfaccia a riga di comando: `pmo --help`."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import typer
from sqlalchemy import func, select

from pmo.config import get_settings

app = typer.Typer(help="PMO La Traccia: tracciabilità pratiche da Gmail e Google Drive", no_args_is_help=True)
utenti_app = typer.Typer(help="Gestione utenti")
caselle_app = typer.Typer(help="Gestione caselle collegate")
app.add_typer(utenti_app, name="utenti")
app.add_typer(caselle_app, name="caselle")


def _logging() -> None:
    logging.basicConfig(level=get_settings().log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _stampa(obj: object) -> None:
    typer.echo(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def _radice_progetto() -> Path:
    """Cartella con alembic.ini e config/: il sorgente (installazione editable) oppure la cartella corrente."""
    candidati = [Path(__file__).resolve().parents[2], Path.cwd()]
    for cand in candidati:
        if (cand / "alembic.ini").exists():
            return cand
    raise typer.BadParameter("alembic.ini non trovato: eseguire il comando dalla cartella del progetto")


@app.command("init-db")
def init_db() -> None:
    """Crea o aggiorna lo schema del database (alembic upgrade head) e le regole predefinite."""
    _logging()
    from alembic import command
    from alembic.config import Config

    radice = _radice_progetto()
    cfg = Config(str(radice / "alembic.ini"))
    cfg.set_main_option("script_location", str(radice / "alembic"))
    command.upgrade(cfg, "head")
    from pmo.db.session import session_scope
    from pmo.rules.definitions import assicura_regole

    with session_scope() as session:
        assicura_regole(session)
    typer.echo("Database pronto.")


@app.command()
def seed(file: Path | None = typer.Option(None, help="File YAML alternativo a config/seed.yaml")) -> None:
    """Carica clienti, prodotti, utenti e regole iniziali."""
    _logging()
    from pmo.db.session import session_scope
    from pmo.services.seed import carica_seed

    with session_scope() as session:
        _stampa(carica_seed(session, file))


@app.command("gen-keys")
def gen_keys() -> None:
    """Genera PMO_SECRET_KEY e PMO_ENCRYPTION_KEY da incollare nel file .env."""
    import secrets

    from pmo.security import genera_chiave

    typer.echo(f"PMO_SECRET_KEY={secrets.token_urlsafe(48)}")
    typer.echo(f"PMO_ENCRYPTION_KEY={genera_chiave()}")


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000, reload: bool = False) -> None:  # noqa: S104
    """Avvia l'interfaccia web."""
    import uvicorn

    uvicorn.run("pmo.web.app:create_app", host=host, port=port, reload=reload, factory=True)


@app.command("mcp")
def mcp_server(
    scrittura: bool = typer.Option(
        False, "--scrittura", help="Abilita anche le azioni che modificano i dati (conferma o scarta pratiche, note, stati, solleciti)"
    ),
    utente: str | None = typer.Option(None, help="Email a cui attribuire le modifiche (default: primo amministratore)"),
) -> None:
    """Avvia il server MCP (stdio) per collegare l'applicazione a Claude Desktop o Claude Code."""
    import os

    try:
        # avviato da Claude, il processo non parte dalla cartella del progetto: .env e il database SQLite sono relativi ad essa
        os.chdir(_radice_progetto())
    except typer.BadParameter:
        pass
    _logging()  # i log vanno su stderr: stdout è riservato al protocollo MCP
    from pmo.mcp_server import avvia

    avvia(scrittura=scrittura, utente_email=utente)


@app.command()
def sync(
    account: str | None = typer.Option(None, help="Email della casella (default: tutte)"),
    completa: bool = typer.Option(False, help="Ignora i segnalibri e rilegge l'intera finestra"),
    giorni: int | None = typer.Option(None, help="Finestra in giorni per l'importazione"),
    classifica: bool = typer.Option(True, help="Classifica con l'IA i messaggi nuovi"),
    regole: bool = typer.Option(True, help="Esegue le regole di sollecito al termine"),
) -> None:
    """Sincronizza Gmail e Drive, classifica e aggiorna i solleciti."""
    _logging()
    from pmo.db.models import Account
    from pmo.db.session import session_scope
    from pmo.services.sync import esegui_regole_tutto, sincronizza_account, sincronizza_tutto

    settings = get_settings()
    inizio = time.time()
    if account:
        with session_scope() as session:
            acc = session.scalar(select(Account).where(Account.email == account.lower()))
            if acc is None:
                raise typer.BadParameter(f"Casella {account} non trovata")
            account_id = acc.id
        esito = sincronizza_account(account_id, settings, completa=completa, giorni=giorni, classifica=classifica)
        if regole:
            esito["regole"] = esegui_regole_tutto()
    else:
        esito = sincronizza_tutto(settings, classifica=classifica, regole=regole, completa=completa, giorni=giorni)
    esito["durata_s"] = round(time.time() - inizio, 1)
    _stampa(esito)


@app.command()
def classifica(account: str | None = None, limite: int = 200) -> None:
    """Classifica con l'IA i messaggi e i documenti in attesa, senza scaricare nulla di nuovo."""
    _logging()
    from pmo.db.models import Account
    from pmo.db.session import session_scope
    from pmo.ingest.catalogo import carica_catalogo
    from pmo.ingest.classifier import crea_classificatore
    from pmo.ingest.drive_sync import classifica_documenti
    from pmo.ingest.gmail_sync import classifica_messaggi

    settings = get_settings()
    with session_scope() as session:
        q = select(Account).where(Account.attivo.is_(True))
        if account:
            q = q.where(Account.email == account.lower())
        classificatore = crea_classificatore(settings)
        catalogo = carica_catalogo(session, settings)
        esiti = {}
        for acc in session.scalars(q).all():
            run = classifica_messaggi(session, acc, settings, classificatore=classificatore, catalogo=catalogo, limite=limite)
            run2 = classifica_documenti(session, acc, settings, classificatore=classificatore, catalogo=catalogo, limite=limite)
            esiti[acc.email] = {"mail": run.contatori, "drive": run2.contatori, "errori": run.errori + run2.errori}
    _stampa(esiti)


@app.command()
def regole() -> None:
    """Valuta le regole di sollecito su tutte le pratiche."""
    _logging()
    from pmo.services.sync import esegui_regole_tutto

    _stampa(esegui_regole_tutto())


@app.command()
def digest(
    anteprima: bool = typer.Option(False, help="Mostra il digest senza inviarlo"),
    a: list[str] = typer.Option(None, "--a", help="Destinatario (ripetibile)"),
) -> None:
    """Invia (o mostra) il digest dei solleciti."""
    _logging()
    from pmo.db.session import session_scope
    from pmo.services.digest import invia_digest

    with session_scope() as session:
        esito = invia_digest(session, get_settings(), destinatari=list(a) if a else None, solo_anteprima=anteprima)
    if anteprima:
        typer.echo(esito.pop("testo", ""))
    _stampa(esito)


@app.command()
def stato() -> None:
    """Riepilogo rapido: pratiche per stato, solleciti aperti, elementi da verificare, caselle."""
    from pmo.db.models import Account, Documento, Messaggio, Pratica, Sollecito
    from pmo.db.session import session_scope

    with session_scope() as session:
        per_stato = dict(session.execute(select(Pratica.stato, func.count()).group_by(Pratica.stato)).all())
        solleciti = dict(session.execute(select(Sollecito.stato, func.count()).group_by(Sollecito.stato)).all())
        messaggi = dict(session.execute(select(Messaggio.stato, func.count()).group_by(Messaggio.stato)).all())
        documenti = dict(session.execute(select(Documento.stato, func.count()).group_by(Documento.stato)).all())
        caselle = [
            {"email": a.email, "collegata": a.collegato, "ultima_sync": a.gmail_last_sync_at, "stato": a.last_sync_status}
            for a in session.scalars(select(Account)).all()
        ]
    _stampa({"pratiche": per_stato, "solleciti": solleciti, "messaggi": messaggi, "documenti": documenti, "caselle": caselle})


@app.command()
def scheduler() -> None:
    """Esegue lo scheduler in primo piano (sincronizzazione periodica e digest)."""
    _logging()
    from pmo.scheduler import crea_scheduler

    sched = crea_scheduler(get_settings())
    sched.start()
    typer.echo("Scheduler avviato (Ctrl+C per uscire)")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        sched.shutdown()


@utenti_app.command("aggiungi")
def utenti_aggiungi(email: str, nome: str = "", admin: bool = False) -> None:
    """Crea o aggiorna un utente abilitato all'accesso."""
    from pmo.db.models import User
    from pmo.db.session import session_scope

    with session_scope() as session:
        utente = session.scalar(select(User).where(User.email == email.lower()))
        if utente is None:
            utente = User(email=email.lower())
            session.add(utente)
        utente.nome = nome or utente.nome or email
        if admin:
            utente.ruolo = "admin"
        utente.attivo = True
    typer.echo(f"Utente {email} pronto ({'admin' if admin else 'membro'}).")


@caselle_app.command("elenco")
def caselle_elenco() -> None:
    from pmo.db.models import Account
    from pmo.db.session import session_scope

    with session_scope() as session:
        righe = [
            {
                "id": a.id,
                "email": a.email,
                "collegata": a.collegato,
                "scopes": a.scopes,
                "cartelle": [f.nome or f.drive_folder_id for f in a.watched_folders],
                "ultima_sync": a.gmail_last_sync_at,
                "stato": a.last_sync_status,
                "errore": a.last_error,
            }
            for a in session.scalars(select(Account)).all()
        ]
    _stampa(righe)


@caselle_app.command("collega")
def caselle_collega(porta: int = 8765) -> None:
    """Collega una casella dal terminale (apre il browser su questa macchina)."""
    _logging()
    from google_auth_oauthlib.flow import InstalledAppFlow

    from pmo.config import OPENID_SCOPES
    from pmo.connectors.gmail import GmailClient
    from pmo.connectors.google_oauth import credentials_to_dict, salva_token
    from pmo.db.models import Account
    from pmo.db.session import session_scope

    settings = get_settings()
    if not settings.google_configured:
        raise typer.BadParameter("Impostare PMO_GOOGLE_CLIENT_ID e PMO_GOOGLE_CLIENT_SECRET")
    config = {
        "installed": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }
    flow = InstalledAppFlow.from_client_config(config, scopes=OPENID_SCOPES + settings.gmail_scopes)
    creds = flow.run_local_server(port=porta, access_type="offline", prompt="consent")
    profilo = GmailClient(creds).profile()
    email = profilo["emailAddress"].lower()
    with session_scope() as session:
        account = session.scalar(select(Account).where(Account.email == email))
        if account is None:
            account = Account(email=email, display_name=email)
            session.add(account)
        salva_token(account, credentials_to_dict(creds))
        account.attivo = True
    typer.echo(f"Casella {email} collegata.")


@caselle_app.command("cartella")
def caselle_cartella(email: str, cartella: str, ricorsivo: bool = True) -> None:
    """Aggiunge una cartella Drive (ID o URL) da monitorare per la casella indicata."""
    from pmo.connectors.drive import DriveClient, estrai_folder_id
    from pmo.connectors.google_oauth import credentials_per_account
    from pmo.db.models import Account, WatchedFolder
    from pmo.db.session import session_scope

    with session_scope() as session:
        account = session.scalar(select(Account).where(Account.email == email.lower()))
        if account is None:
            raise typer.BadParameter(f"Casella {email} non trovata")
        folder_id = estrai_folder_id(cartella)
        meta = DriveClient(credentials_per_account(account)).get_file(folder_id)
        wf = WatchedFolder(account_id=account.id, drive_folder_id=folder_id, nome=meta.get("name", ""), ricorsivo=ricorsivo)
        session.add(wf)
    typer.echo(f"Cartella '{meta.get('name')}' monitorata per {email}.")


if __name__ == "__main__":
    app()
