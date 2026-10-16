# AI Gmail Cleaner

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.35%2B-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A privacy-focused, local Gmail inbox review tool built with Python, the Gmail API, Google OAuth 2.0, and Streamlit. It identifies likely promotional messages, protects important-looking messages, supports sender and domain whitelisting, and requires a human review before anything is moved to Gmail Trash.

> [!IMPORTANT]
> The current classifier is a transparent, rule-based heuristic system—not a trained machine-learning model. It cannot guarantee perfect detection of important or promotional messages. Always review every selection before confirming a trash action.

## Key features

- Reads a configurable number of recent inbox messages through the official Gmail API.
- Uses sender, subject, snippet, Gmail labels, and explicit rules to classify messages.
- Protects starred, important, transactional, security, study, booking, and whitelisted messages.
- Supports exact sender and whole-domain whitelist entries.
- Leaves uncertain messages in the inbox by default.
- Requires individual selection and explicit confirmation before moving mail to Trash.
- Never permanently deletes messages and performs no unattended or scheduled cleaning.
- Processes message metadata and snippets locally; it sends nothing to an external AI service.

## Technology stack

- Python 3.10+
- Streamlit
- Gmail API (`google-api-python-client`)
- Google OAuth 2.0 (`google-auth` and `google-auth-oauthlib`)
- pandas

## How it works

1. The user connects a Gmail account through Google's OAuth consent flow.
2. The app requests up to the chosen number of inbox messages, excluding Spam and Trash.
3. It fetches only metadata needed for review: sender, subject, date, snippet, labels, and Gmail message ID.
4. The rule-based classifier checks whitelist entries and important-message safeguards first.
5. Strong promotional signals are marked `Promotion`; insufficient evidence becomes `Uncertain`.
6. The user reviews the table and selects specific non-protected messages.
7. Only after the confirmation checkbox is selected can the app move those messages to Gmail Trash.

Messages placed in Trash can normally be restored in Gmail until Gmail permanently deletes them under its own retention policy. This application does not call Gmail's permanent-delete endpoint.

## OAuth authentication flow

The app uses the OAuth 2.0 installed desktop application flow:

1. On first connection, `credentials.json` starts a browser-based Google consent flow.
2. Google redirects to a temporary localhost callback opened by the application.
3. The resulting authorization credentials are stored locally in `token.json`.
4. Later sessions refresh the token when possible; otherwise, the consent flow runs again.

Both JSON files are local secrets and are excluded by `.gitignore`. Never commit, upload, paste, or share them. The token is written with restrictive file permissions where the operating system supports them.

## Gmail API permission

The app requests this scope:

```text
https://www.googleapis.com/auth/gmail.modify
```

`gmail.modify` allows the app to read messages and labels and to move selected messages to Trash. This is a sensitive/restricted Gmail scope; distributing a hosted application may require Google verification and, in some cases, a security assessment.

## Project structure

```text
AI-Gmail-Cleaner/
├── app.py                 # Streamlit UI and Gmail/OAuth integration
├── classifier.py          # Conservative rule-based classifier
├── test_classifier.py     # Classifier unit tests
├── requirements.txt       # Runtime dependencies
├── README.md              # Project documentation
├── LICENSE                # MIT license
├── .gitignore             # Secret, local-data, and tooling exclusions
├── credentials.json       # Local OAuth client secret (ignored; user supplied)
├── token.json             # Local OAuth token (ignored; generated)
└── settings.json          # Local whitelist preferences (ignored; generated)
```

## Installation

### Prerequisites

- Python 3.10 or newer
- A Google account with Gmail
- A Google Cloud project
- Git (only needed to clone the repository)

### Set up the application

```powershell
git clone https://github.com/Tashin90/AI-Gmail-Cleaner.git
cd AI-Gmail-Cleaner
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On macOS or Linux, activate the environment with:

```bash
source .venv/bin/activate
```

## Google Cloud configuration

1. Open the [Google Cloud Console](https://console.cloud.google.com/) and create or select a project.
2. Go to **APIs & Services → Library**, find **Gmail API**, and enable it.
3. Open **Google Auth Platform** and configure the app name, support email, and developer contact information.
4. Configure the audience. For a personal account, choose **External**. While the app is in testing, add your own Google account as a test user.
5. Add the `https://www.googleapis.com/auth/gmail.modify` scope if the console requests explicit scope configuration.
6. Go to **Clients** (or **Credentials**), choose **Create OAuth client ID**, and select **Desktop app**.
7. Download the client configuration JSON.

### Create `credentials.json`

Rename the downloaded OAuth client file to `credentials.json` and place it beside `app.py`:

```text
AI-Gmail-Cleaner/credentials.json
```

Do not copy credential values into Python source, environment examples, issues, screenshots, or commits. The repository's `.gitignore` excludes this file and common alternative client-secret filenames.

## Run with Streamlit

From the project directory, with the virtual environment active:

```powershell
python -m streamlit run app.py
```

Open the local URL shown by Streamlit, normally `http://localhost:8501`. On first use, click **Connect Gmail & Scan Inbox**, complete Google's consent screen, and return to the app.

Do not expose this local dashboard directly to the public internet. The current OAuth and token-storage design is intended for a single trusted user on a local computer.

## Email classification workflow

Classification is deterministic and explainable:

- **Protected:** Whitelisted senders/domains, Gmail-starred or important messages, and messages containing strong account, transaction, study, job, booking, security, or delivery cues.
- **Promotion:** Messages with both convincing promotional context and either Gmail's Promotions label or a known promotional sender pattern.
- **Uncertain:** Messages without enough evidence. These are not suggested for removal.

Protection rules take priority over promotion rules. The classifier still makes mistakes: wording, spoofed senders, missing labels, localization, and unusual messages can all affect results.

## Review-before-trash safety

- Scanning is read-only and does not change Gmail data.
- Every row starts unselected after a scan.
- The user must select messages one by one.
- Protected messages are excluded even if selected in the table.
- A separate confirmation checkbox must be enabled before the Trash button works.
- The app calls Gmail's Trash operation only for the reviewed, eligible message IDs.
- No permanent-delete API call exists in the project.

Use a non-critical test account when evaluating changes. Never use real Gmail data for destructive automated testing.

## Security and privacy

- Keep `credentials.json`, `token.json`, `.env` files, `settings.json`, logs, databases, and Streamlit secrets out of Git.
- Treat `token.json` like a password because it can authorize mailbox access within the granted scope.
- Restrict local file access and revoke the app from your [Google Account connections](https://myaccount.google.com/connections) if a token might be exposed.
- Rotate the OAuth client secret in Google Cloud if `credentials.json` might be exposed.
- Review `git status` and staged diffs before every push.
- Do not publish email exports, message bodies, metadata, logs, screenshots, or personal whitelist data.
- No message data is intentionally persisted by this app; scanned messages remain in Streamlit session state for the active session.

## Current limitations

- The classifier is rule-based, not trained AI or machine learning.
- Detection is conservative but not guaranteed to be accurate or complete.
- Only 10–200 inbox messages can be scanned per run through the current UI.
- The app is intended for one local user, not multi-user hosting.
- OAuth testing-mode refresh tokens may expire, requiring reauthentication.
- Network errors, Gmail API quotas, and Google policy changes may affect operation.
- Whitelist preferences are stored in a local plain-text JSON file.

## Future improvements

- Optional user-trained classification based on confirmed labels.
- Gmail batch requests and more efficient pagination.
- Encrypted OS keychain storage for OAuth tokens.
- Dry-run export containing only anonymized aggregate statistics.
- Expanded tests for Gmail API failures and UI safety controls.
- Internationalized rules and user-editable classification policies.

## Testing

Run the classifier tests without connecting to Gmail or installing extra test tools:

```powershell
python test_classifier.py
```

The same tests are also compatible with pytest if you install it separately:

```powershell
python -m pip install pytest
python -m pytest -q
```

## Troubleshooting

### `credentials.json missing`

Download a Desktop app OAuth client from Google Cloud, rename it to `credentials.json`, and put it beside `app.py`.

### `Access blocked` or the app is not verified

Confirm that your Google account is listed as a test user and that the Gmail API and requested scope are configured. Wider public distribution can require Google's verification process.

### `redirect_uri_mismatch`

Create a **Desktop app** OAuth client. A Web application client uses a different redirect configuration and is not suitable for this local flow.

### Token or scope errors

Revoke the app from your Google Account, remove your local `token.json` manually, and reconnect. Never share the old or new token. This is the only troubleshooting step that removes a local credential, so back it up first if needed.

### PowerShell blocks virtual-environment activation

Run the environment's executables directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

### Gmail scanning or trash actions fail

Check your internet connection, confirm the Gmail API is enabled, and inspect the error displayed by the app. API quota, expired authorization, and organization policies can also block access.

## License

Distributed under the [MIT License](LICENSE).
