"""Local Gmail inbox review dashboard. No unattended deletion."""
import json
import os
import re
from pathlib import Path

import pandas as pd
import streamlit as st
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from classifier import classify_email

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


def fetch_inbox(service, limit):
    ids = []
    token = None
    while len(ids) < limit:
        res = service.users().messages().list(
            userId='me', q='in:inbox -in:trash -in:spam',
            maxResults=min(100, limit-len(ids)), pageToken=token
        ).execute()
        ids.extend(item['id'] for item in res.get('messages', []))
        token = res.get('nextPageToken')
        if not token:
            break
    out = []
    for message_id in ids:
        msg = service.users().messages().get(
            userId='me', id=message_id, format='metadata',
            metadataHeaders=['From', 'Subject', 'Date']
        ).execute()
        headers = {h['name'].lower(): h['value'] for h in msg.get('payload', {}).get('headers', [])}
        out.append({
            'id': message_id,
            'from': headers.get('from', ''),
            'subject': headers.get('subject', '(no subject)'),
            'date': headers.get('date', ''),
            'snippet': msg.get('snippet', ''),
            'labels': msg.get('labelIds', []),
        })
    return out


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

with st.sidebar:
    st.header('Settings')
    limit = st.slider('Inbox messages to scan', 10, 200, 50, step=10)
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
    try:
        with st.spinner('Connecting and scanning…'):
            service = get_service()
            st.session_state.messages = fetch_inbox(service, limit)
        st.success(f"Scanned {len(st.session_state.messages)} messages. Nothing has been deleted.")
    except (HttpError, ValueError, OSError, FileNotFoundError) as error:
        st.error(f'Unable to scan: {error}')

messages = st.session_state.messages
if messages:
    classified = []
    for mail in messages:
        result = classify_email(mail, st.session_state.whitelist)
        classified.append({**mail, **result})
    counts = pd.Series([m['category'] for m in classified]).value_counts()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Scanned', len(classified))
    c2.metric('Suggested for review', sum(m['suggested'] for m in classified))
    c3.metric('Protected', sum(m['category'] == 'Protected' for m in classified))
    c4.metric('Other / uncertain', sum(m['category'] == 'Uncertain' for m in classified))
    st.subheader('Review suggestions')
    st.write('Only individually selected messages can be moved to Trash. Your selections reset after each scan.')
    df = pd.DataFrame([{
        'Trash?': False,
        'From': m['from'],
        'Subject': m['subject'],
        'Category': m['category'],
        'Reason': m['reason'],
        'Date': m['date'],
        'Message ID': m['id'],
    } for m in classified])
    df = df.sort_values(by='Category', key=lambda col: col.map({'Promotion':0, 'Uncertain':1, 'Protected':2})).reset_index(drop=True)
    edited = st.data_editor(df, hide_index=True, use_container_width=True, key='review_editor',
        disabled=['From', 'Subject', 'Category', 'Reason', 'Date', 'Message ID'],
        column_config={'Trash?': st.column_config.CheckboxColumn('Trash?', help='Check only messages you have reviewed'),
                       'Message ID': None})
    selected_ids = edited.loc[edited['Trash?'] == True, 'Message ID'].tolist()
    st.info(f'{len(selected_ids)} messages selected. Protected messages cannot be trashed by this app.')
    by_id = {m['id']: m for m in classified}
    safe_ids = [i for i in selected_ids if by_id[i]['category'] != 'Protected']
    if len(safe_ids) != len(selected_ids):
        st.warning('Protected messages are excluded even if selected.')
    confirm = st.checkbox('I reviewed the selected emails and authorize moving them to Gmail Trash.', value=False)
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
            st.success(f'Moved {len(succeeded)} messages to Trash. You can restore them from Gmail Trash.')
            if errors:
                st.error('Some messages failed: ' + '; '.join(errors[:5]))
            st.rerun()
        except (HttpError, ValueError, OSError) as exc:
            st.error(f'Action failed: {exc}')
else:
    st.info('Click Connect Gmail & Scan Inbox to start. Default mode only reads and suggests.')
