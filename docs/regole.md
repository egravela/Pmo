# Regole di sollecito

Le regole sono valutate da `rules/engine.py` dopo ogni sincronizzazione, con `pmo regole` e con il pulsante *Ricalcola adesso*. Soglie, gravità e attivazione si modificano da *Impostazioni → Regole*.

Vale solo per le pratiche **confermate** e non annullate/sospese. Per le pratiche **proposte dall'IA** vale solo la regola "Elementi da verificare".

| Codice | Nome | Condizione | Soglia | Gravità |
|---|---|---|---|---|
| `ordine_senza_specifiche` | Ordine senza specifiche | stato `ordine` da N giorni e nessun evento confermato di specifiche ricevute o inviate | 15 | avviso |
| `stima_in_attesa` | Stima non inviata | stato `stima` da N giorni senza stima o offerta inviata | 7 | avviso |
| `offerta_senza_risposta` | Offerta senza risposta | stato `offerta` da N giorni | 30 | avviso |
| `scadenza_vicina` | Scadenza vicina | scadenza entro N giorni | 7 | avviso |
| `scadenza_superata` | Scadenza superata | scadenza passata e pratica non chiusa | 0 | critico |
| `consegnato_non_fatturato` | Consegnato ma non fatturato | stato `consegna` da N giorni (una fattura emessa porta a `fatturazione`) | 30 | critico |
| `fatturato_diverso_da_ordinato` | Fatturato diverso dall'ordinato | pratica in `fatturazione`/`chiusa` con fatturato e ordinato che differiscono oltre la tolleranza (`tolleranza_percento`, `tolleranza_euro`) | - | avviso |
| `pratica_inattiva` | Pratica ferma | nessun evento da N giorni (riferimento: ultimo evento non di sistema, altrimenti data dello stato) | 30 | info |
| `da_verificare` | Elementi da verificare | pratica proposta o eventi proposti dall'IA creati da più di N giorni | 3 | info |

## Ciclo di vita di un sollecito

- **Aperto** quando la condizione compare. Chiave univoca `<pratica>:<regola>`: non si duplica mai.
- **In carico**: una persona lo ha preso; resta visibile.
- **Risolto**: manualmente o dal sistema quando la condizione cessa (`risolto_da = sistema`). Se la condizione ricompare viene **riaperto** e il contatore `occorrenze` aumenta.
- **Silenziato** fino a una data: non compare nel cruscotto né nel digest; alla scadenza dello snooze, se la condizione persiste, torna aperto.

Il digest giornaliero elenca i solleciti aperti e in carico, i nuovi in evidenza, con i contatori degli elementi da verificare.

## Aggiungere una regola

1. Aggiungere la specifica in `rules/definitions.py` (`REGOLE_DEFAULT`): viene creata al prossimo `pmo init-db` o alla prima esecuzione.
2. Aggiungere la valutazione in `valuta_pratica` (`rules/engine.py`) restituendo un `Esito` con titolo e messaggio in italiano.
3. Aggiungere un test in `tests/test_regole.py`.
