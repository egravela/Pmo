# Configurazione Google (OAuth, Gmail, Drive)

Serve un client OAuth del Workspace `latraccia.it`. Operazione da fare una volta sola, da un amministratore del Workspace o da chi ha accesso alla Google Cloud Console.

## 1. Progetto e API

1. Apri <https://console.cloud.google.com/> e crea un progetto (ad esempio `pmo-latraccia`).
2. In **API e servizi → Libreria** abilita **Gmail API** e **Google Drive API**.

## 2. Schermata di consenso

1. **API e servizi → Schermata consenso OAuth**.
2. Tipo utente **Interno** (solo account del Workspace): evita la verifica di Google e limita l'accesso al dominio.
3. Nome applicazione "PMO La Traccia", email di supporto, dominio autorizzato `latraccia.it`.
4. Scope da aggiungere:
   - `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile`
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/drive.readonly`
   - `https://www.googleapis.com/auth/gmail.send` solo se si vuole inviare il digest dalla casella (`PMO_GMAIL_SEND_SCOPE=true`)

## 3. Credenziali

1. **API e servizi → Credenziali → Crea credenziali → ID client OAuth**, tipo **Applicazione web**.
2. URI di reindirizzamento autorizzati (sostituire con il proprio `PMO_BASE_URL`):
   - `http://localhost:8000/auth/callback`
   - `http://localhost:8000/caselle/callback`
   - in produzione, ad esempio `https://pmo.latraccia.it/auth/callback` e `https://pmo.latraccia.it/caselle/callback`
3. Copia **ID client** e **Secret** in `.env` come `PMO_GOOGLE_CLIENT_ID` e `PMO_GOOGLE_CLIENT_SECRET`.

Per collegare una casella dal terminale (`pmo caselle collega`) serve in più un client di tipo **App desktop** oppure l'aggiunta di `http://localhost:8765/` tra i redirect; in alternativa si usa sempre il pulsante nell'interfaccia.

## 4. Accesso da parte di altre persone

Ogni persona collega la propria casella dall'interfaccia (Caselle → Collega con Google): il consenso lo dà il titolare della casella, non serve delega amministrativa. Se si preferisce evitare il consenso individuale (ad esempio per la casella di reparto), si può usare in futuro un service account con delega a livello di dominio: il connettore accetta credenziali Google generiche, quindi l'estensione è contenuta.

## 5. Verifiche

- Se Google risponde `redirect_uri_mismatch`, l'URL in `PMO_BASE_URL` non coincide con quelli autorizzati (attenzione a `http`/`https` e alla porta).
- Se il refresh token non arriva (la casella risulta collegata ma la sincronizzazione fallisce dopo un'ora), scollegare e ricollegare: il flusso usa `prompt=consent` proprio per ottenerlo ogni volta.
- In locale senza HTTPS il sistema imposta da solo `OAUTHLIB_INSECURE_TRANSPORT=1` quando `PMO_BASE_URL` inizia con `http://`.
