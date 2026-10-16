"""Local Gmail inbox review dashboard. No unattended deletion."""
import hashlib
import json
import os
from pathlib import Path

import streamlit as st
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from classifier import classify_email
from drag_select_table import drag_select_table
from gmail_client import fetch_inbox
from selection import eligible_trash_ids, normalize_selected_ids

ROOT = Path(__file__).resolve().parent
TOKEN = ROOT / 'token.json'
CLIENT = ROOT / 'credentials.json'
SETTINGS = ROOT / 'settings.json'
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

st.set_page_config(page_title='AI Gmail Cleaner', page_icon='📬', layout='wide')
st.title('📬 AI Gmail Cleaner')
st.caption('Local-first, review-before-trash inbox organizer • Never permanently deletes email')


def get_service():
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT.exists():
                raise FileNotFoundError('credentials.json missing. See README.md.')
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)
        TOKEN.write_text(creds.to_json(), encoding='utf-8')
        try:
            os.chmod(TOKEN, 0o600)
        except OSError:
            pass
    return build('gmail', 'v1', credentials=creds, cache_discovery=False)


def load_whitelist():
    if SETTINGS.exists():
        try:
            data = json.loads(SETTINGS.read_text(encoding='utf-8'))
            return data.get('whitelist', [])
        except (ValueError, OSError):
            pass
    return ['aiub.edu']


if 'whitelist' not in st.session_state:
    st.session_state.whitelist = load_whitelist()
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'selected_message_ids' not in st.session_state:
    st.session_state.selected_message_ids = []
if 'scan_revision' not in st.session_state:
    st.session_state.scan_revision = 0

with st.sidebar:
    st.header('Settings')
    limit = st.slider('Inbox messages to scan', 10, 500, 200, step=10)
    wl = st.text_area('Never trash senders/domains (one per line)', '\n'.join(st.session_state.whitelist), height=130)
    if st.button('Save whitelist'):
        st.session_state.whitelist = [s.strip().lower() for s in wl.splitlines() if s.strip()]
        SETTINGS.write_text(json.dumps({'whitelist': st.session_state.whitelist}, indent=2), encoding='utf-8')
        st.success('Whitelist saved.')
    st.caption('A whitelist entry may be a full email address or a domain, e.g. aiub.edu.')
    st.warning('Do not expose this local dashboard on the public internet. Keep token.json and credentials.json private.')

if not CLIENT.exists():
    st.error('Google OAuth credentials.json not found. Follow README setup steps first.')
    st.stop()

if st.button('🔗 Connect Gmail & Scan Inbox', type='primary'):
    scan_progress = st.progress(0)
    scan_status = st.empty()

    def report_scan_progress(phase, current, total):
        if phase == 'listing':
            percentage = min(20, round(20 * current / max(total, 1)))
            scan_progress.progress(percentage)
            scan_status.caption(f'Found {current} inbox message(s), up to the {total}-message limit.')
        else:
            percentage = 20 + round(80 * current / max(total, 1)) if total else 100
            scan_progress.progress(min(percentage, 100))
            scan_status.caption(f'Retrieving message metadata: {current} of {total}.')

    def report_scan_retry(attempt, maximum, delay):
        scan_status.caption(
            f'Gmail is temporarily busy or rate-limited. Retrying in {delay:g}s '
            f'(attempt {attempt} of {maximum}).'
        )

    try:
        with st.spinner('Connecting and scanning…'):
            service = get_service()
            st.session_state.messages = fetch_inbox(
                service,
                limit,
                progress_callback=report_scan_progress,
                retry_callback=report_scan_retry,
            )
            st.session_state.selected_message_ids = []
            st.session_state.scan_revision += 1
        scan_progress.progress(100)
        scan_status.caption(
            f'Scan complete: {len(st.session_state.messages)} message(s) retrieved.'
        )
        st.success(f"Scanned {len(st.session_state.messages)} messages. Nothing has been deleted.")
    except (HttpError, ValueError, OSError, FileNotFoundError) as error:
        scan_status.caption('Scan stopped safely. No Gmail messages were changed.')
        st.error(f'Unable to scan: {error}')

messages = st.session_state.messages
if messages:
    classified = []
    for mail in messages:
        result = classify_email(mail, st.session_state.whitelist)
        classified.append({**mail, **result})
    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Scanned', len(classified))
    c2.metric('Suggested for review', sum(m['suggested'] for m in classified))
    c3.metric('Protected', sum(m['category'] == 'Protected' for m in classified))
    c4.metric('Other / uncertain', sum(m['category'] == 'Uncertain' for m in classified))
    st.subheader('Review suggestions')
    st.write(
        'Drag vertically across checkboxes to select a range. Ctrl+Click toggles '
        'one email; Shift+Click selects a continuous visible range. Selections '
        'reset after each new scan.'
    )
    category_order = {'Promotion': 0, 'Uncertain': 1, 'Protected': 2}
    classified.sort(key=lambda message: category_order.get(message['category'], 3))
    valid_ids = [message['id'] for message in classified]
    previous_ids = normalize_selected_ids(
        st.session_state.selected_message_ids,
        valid_ids,
    )
    component_ids = drag_select_table(
        rows=[{
            'id': message['id'],
            'sender': message['from'],
            'subject': message['subject'],
            'category': message['category'],
            'reason': message['reason'],
            'date': message['date'],
            'protected': message['category'] == 'Protected',
        } for message in classified],
        selected_ids=previous_ids,
        selection_epoch=st.session_state.scan_revision,
        key=f"review_drag_table_{st.session_state.scan_revision}",
    )
    selected_ids = normalize_selected_ids(
        component_ids if component_ids is not None else previous_ids,
        valid_ids,
    )
    st.session_state.selected_message_ids = selected_ids
    st.info(f'{len(selected_ids)} messages selected. Protected messages cannot be trashed by this app.')
    safe_ids = eligible_trash_ids(selected_ids, classified)
    if len(safe_ids) != len(selected_ids):
        st.warning('Protected messages are excluded even if selected.')
    selection_fingerprint = hashlib.sha256(
        '\0'.join(sorted(safe_ids)).encode('utf-8')
    ).hexdigest()[:12]
    confirm = st.checkbox(
        'I reviewed the selected emails and authorize moving them to Gmail Trash.',
        value=False,
        key=f'confirm_trash_{st.session_state.scan_revision}_{selection_fingerprint}',
    )
    if st.button(f'🗑️ Move {len(safe_ids)} selected message(s) to Trash', disabled=not(confirm and safe_ids)):
        try:
            service = get_service()
            succeeded = []
            errors = []
            for message_id in safe_ids:
                try:
                    service.users().messages().trash(userId='me', id=message_id).execute()
                    succeeded.append(message_id)
                except HttpError as exc:
                    errors.append(f'{message_id}: {exc}')
            st.session_state.messages = [m for m in messages if m['id'] not in succeeded]
            st.session_state.selected_message_ids = [
                message_id for message_id in selected_ids
                if message_id not in succeeded
            ]
            st.success(f'Moved {len(succeeded)} messages to Trash. You can restore them from Gmail Trash.')
            if errors:
                st.error('Some messages failed: ' + '; '.join(errors[:5]))
            st.rerun()
        except (HttpError, ValueError, OSError) as exc:
            st.error(f'Action failed: {exc}')
else:
    st.info('Click Connect Gmail & Scan Inbox to start. Default mode only reads and suggests.')
