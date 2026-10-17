# AI Gmail Cleaner

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.42%2B-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![GitHub stars](https://img.shields.io/github/stars/Tashin90/AI-Gmail-Cleaner?style=social)](https://github.com/Tashin90/AI-Gmail-Cleaner/stargazers)
[![Live Demo](https://img.shields.io/badge/Live%20Demo-Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://ai-gmail-cleaner.streamlit.app)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A privacy-focused Gmail inbox cleanup assistant built with Python, Gmail API, Google OAuth 2.0, and Streamlit.

It helps you quickly review inbox clutter while keeping you in full control of every Trash action.

## Why people use this project

- **Safer than one-click cleaners:** no automatic delete, no permanent delete endpoint.
- **Built for control:** review-first workflow with protection rules and confirmation gates.
- **Practical for real inboxes:** handles 10–500 emails with progress and retry support.
- **Cloud-ready and local-ready:** secure Streamlit Cloud OAuth flow and local desktop OAuth.

## Quick start (2 minutes)

1. Open the app: [ai-gmail-cleaner.streamlit.app](https://ai-gmail-cleaner.streamlit.app)
2. Sign in with Google.
3. Authorize Gmail access for the same account.
4. Scan your inbox and review suggested promotional messages.
5. Select what to move to Trash and confirm explicitly.

Prefer running locally? Jump to [Installation and local run](#installation-and-local-run).

> [!IMPORTANT]
> The classifier is a transparent, rule-based heuristic—not a trained machine-learning model. It cannot guarantee perfect detection. Review every selection before confirming a Trash action.

## Features

- Scans 10–500 inbox messages with pagination, accurate progress, and bounded retry for transient Gmail API errors.
- Classifies mail as `Promotion`, `Protected`, or `Uncertain` using conservative rules.
- Protects starred, important, transactional, security, study, booking, delivery, and whitelisted mail.
- Supports sender and whole-domain whitelisting.
- Provides drag-to-select checkboxes, edge auto-scroll, Ctrl+Click, Shift+Click, sorting, and filtering.
- Keeps selection attached to stable Gmail Message IDs across Streamlit reruns.
- Requires review plus a separate confirmation checkbox before moving eligible mail to Trash.
- Never calls Gmail's permanent-delete endpoint and never performs an automatic Trash action.
- Supports both local Desktop OAuth and a separate HTTPS Web OAuth flow for Streamlit Cloud.

## Technology

- Python 3.10+
- Streamlit 1.42+ with the official authentication extra (Authlib and HTTPX)
- Gmail API (`google-api-python-client`)
- Google OAuth (`google-auth`, `google-auth-oauthlib`)
- Local HTML/JavaScript Streamlit component for the review table

## How it works

1. The user authenticates and separately authorizes Gmail access.
2. The app lists inbox message IDs, following Gmail pagination up to the selected limit.
3. It retrieves sender, subject, date, snippet, labels, and stable message ID.
4. Protection rules and the whitelist run before promotional rules.
5. The user reviews and selects messages in the drag-select table.
6. Protected IDs are removed again at the server-side safety boundary.
7. Gmail's reversible `trash` operation runs only after explicit confirmation.

Messages normally remain recoverable from Gmail Trash until Gmail applies its own retention policy. This project has no permanent-delete call.

## Two separate cloud authorization flows

Streamlit authentication and Gmail authorization are deliberately separate:

1. **Streamlit OIDC authentication** uses `st.login()` to establish who may use the deployment. It does not grant Gmail API access.
2. **Gmail Web OAuth authorization** asks that verified user for `gmail.modify`, exchanges the code at Google's token endpoint, and creates the Gmail service.

The Gmail flow uses a signed, user-bound state value with a 10-minute lifetime, OAuth nonce validation, PKCE S256, an HTTPS authorization-code exchange, and Google ID-token verification. The Gmail account email must match the verified Streamlit identity email. Missing claims, a non-allowlisted user, tampered/expired state, account mismatch, revoked credentials, or incomplete configuration fails closed.

Cloud tokens, whitelist entries, Gmail metadata, and selections live only in the authenticated user's Streamlit session. There is no shared token file, process-global mailbox cache, or cloud filesystem persistence. A browser refresh, disconnected session, or app restart can require Gmail authorization again; this is an intentional security tradeoff for the current deployment.

## Exact Google Cloud Web client configuration

Enable **Gmail API**, configure the OAuth consent screen, add the required test accounts under **Audience → Test users**, and add `https://www.googleapis.com/auth/gmail.modify` under **Data Access**.

Create two distinct OAuth 2.0 client IDs of type **Web application**:

### 1. Streamlit identity client

This client is used only by `st.login()`.

- Authorized JavaScript origin: `https://ai-gmail-cleaner.streamlit.app`
- Authorized redirect URI: `https://ai-gmail-cleaner.streamlit.app/oauth2callback`

### 2. Gmail authorization client

This client is used only by the app's Gmail authorization-code flow.

- Authorized JavaScript origin: `https://ai-gmail-cleaner.streamlit.app`
- **Authorized redirect URI: `https://ai-gmail-cleaner.streamlit.app/`**

The trailing slash is part of the Gmail redirect URI. Google requires an exact match. Do not use localhost, `/oauth2callback`, a wildcard, or the GitHub repository URL for this second client.

Keep the consent screen in **Testing** and list every permitted account as a Google test user unless/until the application completes Google's applicable verification requirements. `gmail.modify` is a sensitive/restricted scope and broader public distribution may require verification and a security assessment.

## Streamlit Secrets

In Streamlit Community Cloud, open the app's **Settings → Secrets** and add the following TOML with your own values. Never commit this configuration.

```toml
[app]
deployment_mode = "cloud"
allowed_users = ["approved-test-user@example.com"]

# Streamlit OIDC identity client (Web application client #1)
[auth]
redirect_uri = "https://ai-gmail-cleaner.streamlit.app/oauth2callback"
cookie_secret = "GENERATE_A_LONG_RANDOM_VALUE"
client_id = "IDENTITY_WEB_CLIENT_ID.apps.googleusercontent.com"
client_secret = "IDENTITY_WEB_CLIENT_SECRET"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

# Gmail API authorization client (Web application client #2)
[google_oauth]
client_id = "GMAIL_WEB_CLIENT_ID.apps.googleusercontent.com"
client_secret = "GMAIL_WEB_CLIENT_SECRET"
redirect_uri = "https://ai-gmail-cleaner.streamlit.app/"
state_secret = "GENERATE_A_DIFFERENT_RANDOM_VALUE_OF_AT_LEAST_32_BYTES"
```

Generate `cookie_secret` and `state_secret` independently with a cryptographically secure password generator. Do not reuse client secrets as state or cookie secrets. After saving Secrets, reboot the Streamlit app. Add the same email addresses to both `allowed_users` and Google OAuth test users.

## Streamlit Cloud deployment

1. Fork or deploy `Tashin90/AI-Gmail-Cleaner`, branch `main`, entrypoint `app.py`.
2. Configure both Google Web clients with the exact URIs above.
3. Add the placeholder-shaped configuration above to Streamlit Secrets using real secret values.
4. Reboot the app.
5. Select **Sign in with Google**. This establishes identity only.
6. Select **Authorize Gmail access** and choose the same Google account.
7. Scan and review mail. Authorization never triggers a scan or Trash operation by itself.

The deployed URL is [https://ai-gmail-cleaner.streamlit.app](https://ai-gmail-cleaner.streamlit.app).

## Local Desktop OAuth

Local development keeps the existing installed-application flow and does not require Streamlit Secrets.

1. In Google Cloud, create an OAuth client ID of type **Desktop app**.
2. Download it, rename it `credentials.json`, and place it beside `app.py`.
3. Do not set `[app].deployment_mode = "cloud"` locally.
4. Start Streamlit and choose **Connect Gmail & Scan Inbox**.

Google redirects the Desktop flow to a temporary loopback URL created by `run_local_server(port=0)`. The resulting `token.json` remains local and is refreshed when possible. Both files are ignored by Git.

## Installation and local run

```powershell
git clone https://github.com/Tashin90/AI-Gmail-Cleaner.git
cd AI-Gmail-Cleaner
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

On macOS or Linux, activate with `source .venv/bin/activate`. Streamlit normally opens `http://localhost:8501`.

## Gmail permission

The app requests:

```text
https://www.googleapis.com/auth/gmail.modify
```

The cloud Gmail flow also requests `openid` and email identity claims solely to prove that the authorizing Gmail account matches the verified Streamlit user. `gmail.modify` can read mailbox data and move selected messages to Trash, so protect all resulting credentials like passwords.

## Project structure

```text
AI-Gmail-Cleaner/
├── app.py                    # Streamlit UI, local/cloud mode selection, safety gates
├── cloud_oauth.py            # Signed state, PKCE, token exchange, user isolation
├── classifier.py             # Conservative rule-based classifier
├── gmail_client.py           # Paginated retrieval and bounded API retries
├── selection.py              # Stable-ID and protected-message safety boundary
├── drag_select_table.py      # Custom-component wrapper
├── drag_select_component/    # HTML/JavaScript drag-select review table
├── test_cloud_oauth.py       # Mocked OAuth and isolation security tests
├── test_gmail_client.py      # Synthetic Gmail pagination/retry tests
├── test_classifier.py        # Classifier tests
├── test_selection.py         # Protected-ID tests
├── tests/js/                 # Browser interaction and selection model tests
├── requirements.txt
├── .gitignore
├── LICENSE
└── README.md
```

## Selection and review safety

- Drag upward or downward across checkboxes to apply the starting checkbox state.
- Hold near the table edge to auto-scroll.
- Ctrl+Click toggles one row; Shift+Click selects a visible range.
- Sort or filter freely: selection is keyed by Gmail Message ID, not row position.
- Selection never calls Gmail.
- Protected messages remain ineligible even if their UI checkbox is selected.
- The confirmation checkbox must be checked before the Trash button is enabled.
- Automated tests use synthetic IDs and mocked APIs; they never connect to Gmail.

## Security and privacy

- Never commit `credentials.json`, `token.json`, `.env`, `.streamlit/secrets.toml`, client-secret downloads, private keys, mail exports, logs, or local settings.
- Never put OAuth secrets in Python, README examples, issues, screenshots, or build logs.
- Cloud callback errors are intentionally generic and never echo authorization codes or token values.
- Scanned content is shown only in the authenticated review session and is not intentionally persisted.
- Local mode writes only the local OAuth token and whitelist settings; cloud mode writes neither.
- Revoke the app in Google Account connections and rotate the client secret if a credential may have leaked.
- Use a non-critical test mailbox while evaluating the app.

## Tests

All Python tests use synthetic data or mocked OAuth/Gmail behavior:

```powershell
python -m compileall -q .
python test_classifier.py
python test_gmail_client.py
python test_selection.py
python test_cloud_oauth.py
node tests/js/selection_model.test.cjs
node tests/js/component_browser_test.cjs
```

They are also pytest-compatible:

```powershell
python -m pytest -q
```

## Current limitations

- Classification is rule-based and cannot guarantee correct detection.
- Cloud credentials are session-only; reconnect after session loss, refresh, restart, or token revocation.
- Streamlit session state is isolation, not durable encrypted token storage. A multi-instance production service needing persistent grants should use a dedicated backend and encrypted per-user token database.
- Whitelist changes are session-only in cloud mode; local mode uses ignored `settings.json`.
- Google testing-mode refresh tokens can expire, and Gmail quota/policy changes can interrupt scans.
- A hosted app using `gmail.modify` may require Google OAuth verification and an independent security assessment before wider use.
- Metadata requests are currently sequential and may be slow near 500 messages.

## Troubleshooting

### `redirect_uri_mismatch`

Confirm which client failed. Streamlit identity must use exactly `https://ai-gmail-cleaner.streamlit.app/oauth2callback`; Gmail authorization must use exactly `https://ai-gmail-cleaner.streamlit.app/`, including its trailing slash. The client IDs in Secrets must match those Web clients.

### Access denied

The signed-in email must have a verified claim, appear exactly in `[app].allowed_users`, and be listed as a Google OAuth test user while the consent screen is in Testing.

### Gmail authorization fails after sign-in

Streamlit sign-in does not grant Gmail access. Select **Authorize Gmail access**, choose the same Google account, and complete consent within 10 minutes. An account mismatch fails closed.

### Authorization expired or revoked

Authorize Gmail again. In local mode, if manual recovery is necessary, revoke the old grant first and remove `token.json` yourself; never share it.

### `credentials.json missing` locally

Download a **Desktop app** OAuth client, rename it `credentials.json`, and place it beside `app.py`. Web client configuration is for cloud mode, not the local loopback flow.

### Gmail scan or Trash action fails

Check network access, Gmail API enablement, consent-screen status, account allowlisting, API quota, and grant validity. The app stops safely and never falls back to permanent deletion.

## Contributing

Contributions are welcome. If you want to help:

1. Open an issue describing the bug, UX friction, or improvement idea.
2. Fork the repo and create a focused branch.
3. Submit a PR with clear before/after behavior.

Please keep safety and privacy guarantees intact, especially around OAuth handling and message deletion boundaries.

## Support this project

If this project helps you, consider:

- ⭐ Starring the repo
- 🐛 Reporting bugs
- 💡 Suggesting features
- 🔁 Sharing it with others who manage large Gmail inboxes

## License

Distributed under the [MIT License](LICENSE).
