from pmo.ingest.filters import FiltriRumore, html_to_text, parse_addresses, strip_quoted
from pmo.services.codici import estrai_codice, estrai_codici, formatta_codice


def test_estrai_codice_normalizza():
    assert estrai_codice("Re: [pmo-2026-12] Offerta Banca degli Occhi") == "PMO-2026-0012"
    assert estrai_codice("nessun codice qui") is None
    assert estrai_codici("PMO-2026-0001 e PMO-2026-0002 e ancora PMO-2026-0001") == ["PMO-2026-0001", "PMO-2026-0002"]
    assert formatta_codice(2026, 7) == "PMO-2026-0007"


def test_filtri_rumore_default():
    f = FiltriRumore()
    assert f.motivo_esclusione(from_email="noreply@newgarden.es", subject="Ordine #IT12424 confermato", labels=[], has_list_unsubscribe=False, tag_presente=False)
    assert f.motivo_esclusione(from_email="x@y.it", subject="Newsletter di ottobre", labels=["CATEGORY_PROMOTIONS"], has_list_unsubscribe=True, tag_presente=False)
    assert f.motivo_esclusione(from_email="info@latraccia.it", subject="ASL VERCELLI: Ordine per assistenza", labels=["INBOX"], has_list_unsubscribe=False, tag_presente=False) is None
    # un codice pratica nell'oggetto vince sempre
    assert f.motivo_esclusione(from_email="noreply@newgarden.es", subject="[PMO-2026-0001] ordine", labels=["CATEGORY_PROMOTIONS"], has_list_unsubscribe=True, tag_presente=True) is None
    # mailing list interna non viene ignorata
    assert f.motivo_esclusione(from_email="dipendenti@latraccia.it", subject="Comunicazione", labels=[], has_list_unsubscribe=True, tag_presente=False) is None


def test_filtri_personalizzati():
    f = FiltriRumore(ignore_senders=["spam@example.com"], ignore_domains=["pubblicita.it"], keep_senders=["noreply@cliente.it"])
    assert f.motivo_esclusione(from_email="spam@example.com", subject="x", labels=[], has_list_unsubscribe=False, tag_presente=False) == "mittente in lista di esclusione"
    assert f.motivo_esclusione(from_email="a@mail.pubblicita.it", subject="x", labels=[], has_list_unsubscribe=False, tag_presente=False) == "dominio in lista di esclusione"
    assert f.motivo_esclusione(from_email="noreply@cliente.it", subject="x", labels=[], has_list_unsubscribe=False, tag_presente=False) is None


def test_strip_quoted_risposta():
    testo = "Ok per me, procediamo.\n\nIl giorno lun 19 ott 2026 alle ore 16:01 Mario Rossi <mario@x.it> ha scritto:\n> testo citato\n> altro"
    assert strip_quoted(testo) == "Ok per me, procediamo."


def test_strip_quoted_mantiene_inoltro():
    testo = "Ciao, ti giro l'ordine.\n\n---------- Forwarded message ---------\nDa: Servizio Info <info@latraccia.it>\nSubject: Ordine\n\nIn allegato l'ordine n. 123"
    assert "ordine n. 123" in strip_quoted(testo)


def test_html_to_text_e_indirizzi():
    testo = html_to_text("<html><body><p>Buongiorno,</p><p>in allegato l'<b>offerta</b>.</p><style>p{}</style></body></html>")
    assert "Buongiorno," in testo and "offerta" in testo and "style" not in testo
    assert parse_addresses('"Rossi, Mario" <Mario@X.it>, anna@y.it') == [("Rossi, Mario", "mario@x.it"), ("", "anna@y.it")]
