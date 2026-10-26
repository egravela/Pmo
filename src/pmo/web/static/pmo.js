/* ==========================================================================
   PMO La Traccia — comportamento dell'applicazione

   Tre cose sole, tutte con le regole del design system:
   - i messaggi transitori (.tr-toast): chiusura automatica solo per le conferme,
     con la durata minima di 4 secondi piu' uno ogni cinque parole oltre le dieci;
     il conto si ferma sotto il puntatore e col fuoco dentro; un errore o
     un'allerta non si chiude da solo;
   - l'attivazione della listbox del select (js/tr-select.js);
   - copia negli appunti e conferma prima delle azioni distruttive.
   ========================================================================== */
(function () {
  'use strict';

  /* ---- Messaggi transitori ------------------------------------------------ */

  function durata(toast) {
    var testo = (toast.textContent || '').trim();
    var parole = testo ? testo.split(/\s+/).length : 0;
    return 4000 + Math.floor(Math.max(0, parole - 10) / 5) * 1000;
  }

  function chiudi(toast) {
    if (toast && toast.parentNode) { toast.parentNode.removeChild(toast); }
  }

  function monta(toast) {
    var chiusura = toast.querySelector('[data-toast-close]');
    if (chiusura) { chiusura.addEventListener('click', function () { chiudi(toast); }); }

    // Errori e allerte: solo a mano. Idem se il messaggio porta un comando.
    var manuale = toast.getAttribute('role') === 'alert' || toast.querySelector('.tr-btn:not([data-toast-close])');
    if (manuale) { return; }

    var restante = durata(toast);
    var inizio = null;
    var timer = null;
    function avvia() {
      inizio = Date.now();
      timer = setTimeout(function () { chiudi(toast); }, restante);
    }
    function ferma() {
      if (timer === null) { return; }
      clearTimeout(timer);
      timer = null;
      restante = Math.max(1000, restante - (Date.now() - inizio));
    }
    toast.addEventListener('mouseenter', ferma);
    toast.addEventListener('mouseleave', function () { if (timer === null) { avvia(); } });
    toast.addEventListener('focusin', ferma);
    toast.addEventListener('focusout', function () { if (timer === null) { avvia(); } });
    avvia();
  }

  var TITOLI = { success: 'Fatto', info: 'Informazione', warning: 'Attenzione', danger: 'Errore' };

  function nuovoToast(variante, messaggio, titolo) {
    var zona = document.getElementById('pmo-toasts');
    if (!zona) { return; }
    var t = document.createElement('div');
    t.className = 'tr-toast tr-toast--' + variante;
    if (variante === 'danger' || variante === 'warning') { t.setAttribute('role', 'alert'); }
    t.innerHTML =
      '<span class="tr-toast__icon" aria-hidden="true"></span>' +
      '<div class="tr-toast__content"><p class="tr-toast__title"></p><p class="tr-toast__body"></p></div>' +
      '<button class="tr-btn tr-btn--icon tr-btn--sm" type="button" aria-label="Chiudi il messaggio" data-toast-close>' +
      '<span class="tr-icon tr-icon--close" aria-hidden="true"></span></button>';
    t.querySelector('.tr-toast__title').textContent = titolo || TITOLI[variante] || '';
    t.querySelector('.tr-toast__body').textContent = messaggio;
    zona.appendChild(t);
    monta(t);
  }

  /* ---- Viste di una pagina di dettaglio ------------------------------------
     Pattern ARIA delle tabs: frecce, Home e Fine spostano la scelta; la vista scelta
     resta nell'indirizzo (#messaggi) e, dopo un'azione, si torna su quella. */

  function viste() {
    var cont = document.querySelector('[data-viste]');
    if (!cont) { return; }
    var tabs = Array.prototype.slice.call(document.querySelectorAll('.pmo-viste-barra [role="tab"]'));
    var chiave = 'pmo-vista:' + location.pathname;

    function attiva(tab, conFocus, scorri) {
      tabs.forEach(function (t) {
        var scelta = t === tab;
        t.setAttribute('aria-selected', scelta ? 'true' : 'false');
        t.tabIndex = scelta ? 0 : -1;
        var pannello = document.getElementById(t.getAttribute('aria-controls'));
        if (pannello) { pannello.classList.toggle('is-attiva', scelta); }
      });
      if (conFocus) { tab.focus(); }
      var nome = tab.id.replace('tab-', '');
      try {
        history.replaceState(null, '', '#' + nome);
        sessionStorage.setItem(chiave, nome);
      } catch (e) { /* senza storage resta la vista corrente */ }
      // la barra si vede da tutta la pagina: se le viste sono fuori dallo schermo, ci si porta li'
      var alto = cont.getBoundingClientRect().top;
      if (scorri && (alto < 0 || alto > window.innerHeight * 0.6)) { cont.scrollIntoView({ block: 'start' }); }
    }

    tabs.forEach(function (t, i) {
      t.addEventListener('click', function () { attiva(t, false, true); });
      t.addEventListener('keydown', function (e) {
        var prossima = null;
        if (e.key === 'ArrowRight') { prossima = tabs[(i + 1) % tabs.length]; }
        else if (e.key === 'ArrowLeft') { prossima = tabs[(i - 1 + tabs.length) % tabs.length]; }
        else if (e.key === 'Home') { prossima = tabs[0]; }
        else if (e.key === 'End') { prossima = tabs[tabs.length - 1]; }
        if (prossima) { e.preventDefault(); attiva(prossima, true, true); }
      });
    });

    var iniziale = location.hash.slice(1);
    if (!iniziale) { try { iniziale = sessionStorage.getItem(chiave) || ''; } catch (e) { iniziale = ''; } }
    for (var k = 0; k < tabs.length; k++) {
      if (tabs[k].id === 'tab-' + iniziale) { attiva(tabs[k], false); break; }
    }

    cont.addEventListener('submit', function (e) {
      var ritorno = e.target.querySelector('input[name="ritorno"]');
      var attiva_ = cont.querySelector('.pmo-vista.is-attiva');
      if (ritorno && attiva_ && ritorno.value.indexOf('#') < 0) {
        ritorno.value += '#' + attiva_.id.replace('vista-', '');
      }
    });
  }

  function copiaClassica(testo) {
    var campo = document.createElement('textarea');
    campo.value = testo;
    campo.setAttribute('readonly', '');
    campo.setAttribute('aria-hidden', 'true');
    campo.style.position = 'fixed';
    campo.style.opacity = '0';
    document.body.appendChild(campo);
    campo.select();
    var riuscita = false;
    try { riuscita = document.execCommand('copy'); } catch (e) { riuscita = false; }
    document.body.removeChild(campo);
    return riuscita;
  }

  /* ---- Avvio -------------------------------------------------------------- */

  function avvio() {
    Array.prototype.forEach.call(document.querySelectorAll('.tr-toast'), monta);

    if (window.TrSelect) { window.TrSelect.enhanceAll(); }
    viste();

    Array.prototype.forEach.call(document.querySelectorAll('[data-copia]'), function (el) {
      el.addEventListener('click', function () {
        var testo = el.getAttribute('data-copia');
        var messaggio = el.getAttribute('data-copia-messaggio') || 'Oggetto della mail copiato negli appunti.';
        var fatto = function () { nuovoToast('success', messaggio, 'Copiato'); };
        var errore = function () { nuovoToast('danger', 'Copia non riuscita: seleziona il testo e copialo a mano.'); };
        // L'API moderna puo' mancare o essere negata (indirizzo non sicuro, permessi): si ripiega sul
        // metodo classico, con un campo di testo temporaneo, e solo se fallisce anche quello si avvisa.
        var classico = function () { if (copiaClassica(testo)) { fatto(); } else { errore(); } };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(testo).then(fatto, classico);
        } else { classico(); }
      });
    });

    // Azioni lunghe: il pulsante dichiara l'attesa (aria-busy) e mostra la Sequenza del
    // sistema, tre chevron che si accendono in fila. Cambia il testo, non la scatola.
    Array.prototype.forEach.call(document.querySelectorAll('form[data-attesa]'), function (f) {
      f.addEventListener('submit', function (e) {
        if (e.defaultPrevented) { return; }
        var b = f.querySelector('button[type="submit"]');
        if (!b) { return; }
        var chevron = '<svg class="tr-spinner__mark" width="12" height="15" viewBox="0 0 594 717" aria-hidden="true"><use href="#tr-mark"/></svg>';
        b.setAttribute('aria-busy', 'true');
        b.innerHTML = '<span class="tr-spinner tr-spinner--inherit"><span class="tr-spinner__seq">' + chevron + chevron + chevron + '</span></span><span></span>';
        b.lastChild.textContent = f.getAttribute('data-attesa');
      });
    });

    Array.prototype.forEach.call(document.querySelectorAll('form[data-conferma]'), function (f) {
      f.addEventListener('submit', function (e) {
        if (!window.confirm(f.getAttribute('data-conferma'))) { e.preventDefault(); }
      });
    });
  }

  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', avvio); }
  else { avvio(); }

  window.pmoToast = nuovoToast;
})();
