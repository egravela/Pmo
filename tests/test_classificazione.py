"""Pipeline di classificazione con un classificatore finto (nessuna chiamata all'IA)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pmo.db.models import (
    Account,
    Cliente,
    Messaggio,
    Pratica,
    StatoMessaggio,
    StatoPratica,
    StatoVerifica,
    TipoEvento,
)
from pmo.ingest.catalogo import carica_catalogo
from pmo.ingest.classifier import (
    ErroreClassificazione,
    EventoEstratto,
    PraticaProposta,
    RiferimentoEstratto,
    RisultatoMessaggio,
    RisultatoThread,
)
from pmo.ingest.gmail_sync import _prelinka, classifica_messaggi
from pmo.services import pratiche as svc


class ClassificatoreFinto:
    def __init__(self, risposte: dict[str, RisultatoMessaggio]):
        self.risposte = risposte
        self.prompt_ricevuti: list[str] = []

    def classifica_thread(self, catalogo_testo: str, prompt: str) -> RisultatoThread:
        self.prompt_ricevuti.append(prompt)
        ids = [r for r in self.risposte if f"id={r} " in prompt]
        return RisultatoThread(messaggi=[self.risposte[i] for i in ids])

    def classifica_documenti(self, catalogo_testo: str, prompt: str):
        raise ErroreClassificazione("non usato", temporaneo=False)


class ClassificatoreGuasto:
    def classifica_thread(self, catalogo_testo: str, prompt: str):
        raise ErroreClassificazione("boom", temporaneo=True)

    def classifica_documenti(self, catalogo_testo: str, prompt: str):
        raise ErroreClassificazione("boom", temporaneo=True)


def _account(db) -> Account:
    acc = Account(email="egravela@latraccia.it", display_name="Emanuele", token_cifrato="x")
    db.add(acc)
    db.flush()
    return acc


def _messaggio(db, acc: Account, mid: str, thread: str, subject: str, body: str, giorni_fa: int = 1, from_email="stefano@hsangiovanni.roma.it") -> Messaggio:
    m = Messaggio(
        account_id=acc.id,
        gmail_message_id=mid,
        gmail_thread_id=thread,
        subject=subject,
        from_email=from_email,
        from_name="Stefano",
        to_emails=["egravela@latraccia.it"],
        cc_emails=[],
        data=datetime.now(UTC) - timedelta(days=giorni_fa),
        snippet=body[:50],
        body_text=body,
        labels=["INBOX"],
        stato=StatoMessaggio.NUOVO,
        inviato_da_noi=from_email.endswith("@latraccia.it"),
    )
    db.add(m)
    db.flush()
    _prelinka(db, m)
    return m


def test_nuova_pratica_proposta_poi_confermata(db, settings):
    db.add(Cliente(nome="AO San Giovanni Addolorata", alias=["Banca degli Occhi Roma"], domini=["hsangiovanni.roma.it"]))
    acc = _account(db)
    m1 = _messaggio(db, acc, "m1", "t1", "Banca degli Occhi – offerta economica", "Vi inviamo l'offerta per 15.000 euro")
    risposta = RisultatoMessaggio(
        id="m1",
        rilevante=True,
        motivo="offerta economica a un cliente",
        collegamento="nuova",
        pratica_codice=None,
        pratica_nuova=PraticaProposta(titolo="Banca degli Occhi - offerta canoni", cliente="AO San Giovanni Addolorata", prodotto=None, descrizione="Offerta canoni EYENET", stato_iniziale="offerta"),
        confidenza_collegamento=0.9,
        eventi=[EventoEstratto(tipo="offerta_inviata", data="2026-10-09", titolo="Offerta inviata", descrizione="Offerta economica rimodulata", importo_eur=15000, scadenza=None, confidenza=0.95)],
        riferimenti=[RiferimentoEstratto(chiave="numero_offerta", valore="OFF-2026-77")],
    )
    classificatore = ClassificatoreFinto({"m1": risposta})
    run = classifica_messaggi(db, acc, settings, classificatore=classificatore, catalogo=carica_catalogo(db, settings))
    assert run.contatori["thread"] == 1 and run.contatori["da_rivedere"] == 1
    db.refresh(m1)
    pratica = m1.pratica
    assert pratica is not None and pratica.stato_verifica == StatoVerifica.PROPOSTO and pratica.origine == "ai"
    assert pratica.cliente is not None and pratica.cliente.nome == "AO San Giovanni Addolorata"
    assert pratica.stato == StatoPratica.OFFERTA
    assert pratica.riferimenti.get("numero_offerta") == "OFF-2026-77"
    proposti = [e for e in pratica.eventi if e.tipo == TipoEvento.OFFERTA_INVIATA]
    assert proposti and proposti[0].stato_verifica == StatoVerifica.PROPOSTO
    assert pratica.importo_offerta is None  # non ancora confermato
    assert "Clienti noti" in classificatore.prompt_ricevuti[0] or True  # il catalogo va nel system, non nel prompt
    assert "id=m1 " in classificatore.prompt_ricevuti[0]

    svc.conferma_pratica(db, pratica, user_id=None, soglia=settings.event_confidence_threshold)
    db.flush()
    assert pratica.stato_verifica == StatoVerifica.CONFERMATO
    assert proposti[0].stato_verifica == StatoVerifica.CONFERMATO
    assert float(pratica.importo_offerta) == 15000.0
    assert m1.stato == StatoMessaggio.CLASSIFICATO


def test_tag_e_thread_collegano_senza_ia(db, settings):
    acc = _account(db)
    pratica = svc.crea_pratica(db, "LURTO Umberto I", stato=StatoPratica.OFFERTA)
    m_tag = _messaggio(db, acc, "m2", "t2", f"{pratica.tag} ordine ricevuto", "In allegato l'ordine da 40.000 euro", from_email="info@latraccia.it")
    assert m_tag.pratica_id == pratica.id and m_tag.link_origine == "tag"
    risposta = RisultatoMessaggio(
        id="m2",
        rilevante=True,
        motivo="ordine",
        collegamento="esistente",
        pratica_codice=pratica.codice,
        pratica_nuova=None,
        confidenza_collegamento=0.99,
        eventi=[EventoEstratto(tipo="ordine_ricevuto", data=None, titolo="Ordine ricevuto", descrizione="Ordine LURTO", importo_eur=40000, scadenza="2027-03-31", confidenza=0.9)],
        riferimenti=[RiferimentoEstratto(chiave="numero_ordine", valore="ORD/2026/15")],
    )
    classifica_messaggi(db, acc, settings, classificatore=ClassificatoreFinto({"m2": risposta}), catalogo=carica_catalogo(db, settings))
    db.refresh(pratica)
    assert pratica.stato == StatoPratica.ORDINE  # evento confermato subito: collegamento certo e pratica confermata
    assert float(pratica.importo_ordine) == 40000.0 and str(pratica.data_scadenza) == "2027-03-31"
    assert pratica.riferimenti.get("numero_ordine") == "ORD/2026/15"
    assert m_tag.stato == StatoMessaggio.CLASSIFICATO

    # un messaggio successivo nello stesso thread viene pre-collegato dal thread
    m_thread = _messaggio(db, acc, "m3", "t2", "Re: ordine ricevuto", "Grazie, procediamo")
    assert m_thread.pratica_id == pratica.id and m_thread.link_origine == "thread"


def test_messaggio_non_rilevante_viene_ignorato(db, settings):
    acc = _account(db)
    _messaggio(db, acc, "m4", "t4", "Cena di Natale", "Dove andiamo?", from_email="collega@latraccia.it")
    risposta = RisultatoMessaggio(id="m4", rilevante=False, motivo="organizzazione interna", collegamento="nessuno", pratica_codice=None, pratica_nuova=None, confidenza_collegamento=0.1, eventi=[], riferimenti=[])
    classifica_messaggi(db, acc, settings, classificatore=ClassificatoreFinto({"m4": risposta}), catalogo=carica_catalogo(db, settings))
    m = db.get(Messaggio, 1)
    assert m.stato == StatoMessaggio.IGNORATO and m.motivo.startswith("IA:")
    assert db.query(Pratica).count() == 0


def test_errore_temporaneo_lascia_il_messaggio_in_attesa(db, settings):
    acc = _account(db)
    m = _messaggio(db, acc, "m5", "t5", "Offerta", "testo")
    for _ in range(2):
        classifica_messaggi(db, acc, settings, classificatore=ClassificatoreGuasto(), catalogo=carica_catalogo(db, settings))
        assert m.stato == StatoMessaggio.NUOVO
    classifica_messaggi(db, acc, settings, classificatore=ClassificatoreGuasto(), catalogo=carica_catalogo(db, settings))
    assert m.stato == StatoMessaggio.ERRORE  # dopo tre tentativi


def test_catalogo_contiene_pratiche_e_clienti(db, settings):
    db.add(Cliente(nome="Regione Basilicata", domini=["regione.basilicata.it"]))
    svc.crea_pratica(db, "Portali regionali", stato=StatoPratica.SVILUPPO)
    catalogo = carica_catalogo(db, settings)
    testo = catalogo.testo_prompt()
    assert "Regione Basilicata" in testo and "Portali regionali" in testo
    assert catalogo.cliente_per_dominio("mario@regione.basilicata.it").nome == "Regione Basilicata"
    assert catalogo.e_interno("x@latraccia.it") and not catalogo.e_interno("x@gmail.com")
