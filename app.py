"""AI Gmail Cleaner: local Desktop OAuth and secure Streamlit Cloud OAuth."""
import hashlib
import json
import os
from pathlib import Path

import streamlit as st
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from classifier import classify_email
from cloud_oauth import (
    GMAIL_MODIFY_SCOPE,
    CloudOAuthConfig,
    OAuthSecurityError,
    ReauthorizationRequired,
    bind_session_identity,
    build_authorization_url,
    clear_user_gmail_state,
    exchange_authorization_code,
    load_session_credentials,
    store_session_credentials,
    validate_signed_state,
)
from drag_select_table import drag_select_table
from gmail_client import fetch_inbox
from selection import eligible_trash_ids, normalize_selected_ids


ROOT = Path(__file__).resolve().parent
TOKEN = ROOT / "token.json"
CLIENT = ROOT / "credentials.json"
SETTINGS = ROOT / "settings.json"
DESKTOP_SCOPES = [GMAIL_MODIFY_SCOPE]

st.set_page_config(page_title="AI Gmail Cleaner", page_icon="📬", layout="wide")
st.title("📬 AI Gmail Cleaner")
st.caption("Review-before-trash inbox organizer • Never permanently deletes email")


def secret_section(name):
    """Read one Streamlit Secrets section without exposing its contents."""
    try:
        section = st.secrets.get(name, {})
        return dict(section) if section else {}
    except (FileNotFoundError, TypeError, ValueError):
        return {}


APP_CONFIG = secret_section("app")
CLOUD_MODE = str(APP_CONFIG.get("deployment_mode", "local")).strip().casefold() == "cloud"


def get_desktop_service():
    """Preserve the installed-app loopback flow for local development."""
    credentials = None
    if TOKEN.exists():
        credentials = Credentials.from_authorized_user_file(str(TOKEN), DESKTOP_SCOPES)
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
            except RefreshError:
                credentials = None
        if not credentials or not credentials.valid:
            if not CLIENT.exists():
                raise FileNotFoundError("credentials.json missing. See README.md.")
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), DESKTOP_SCOPES)
            credentials = flow.run_local_server(port=0, open_browser=True)
        TOKEN.write_text(credentials.to_json(), encoding="utf-8")
        try:
            os.chmod(TOKEN, 0o600)
        except OSError:
            pass
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def get_cloud_service(config, identity):
    """Create Gmail service only from this authenticated user's session grant."""
    credentials = load_session_credentials(
        st.session_state, identity["sub"], identity["email"]
    )
    if credentials is None:
        raise ReauthorizationRequired("Authorize Gmail access before continuing.")
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def get_service():
    if CLOUD_MODE:
        return get_cloud_service(CLOUD_OAUTH_CONFIG, CLOUD_IDENTITY)
    return get_desktop_service()


def load_whitelist():
    if CLOUD_MODE:
        return []
    if SETTINGS.exists():
        try:
            data = json.loads(SETTINGS.read_text(encoding="utf-8"))
            return data.get("whitelist", [])
        except (ValueError, OSError):
            pass
    return ["aiub.edu"]


def normalized_verified_identity():
    """Require verified Google OIDC claims and an explicit allowlist match."""
    if not getattr(st.user, "is_logged_in", False):
        st.info("Sign in to verify your identity. Gmail access is authorized separately.")
        st.button("Sign in with Google", type="primary", on_click=st.login)
        st.stop()

    subject = str(st.user.get("sub", "")).strip()
    email = str(st.user.get("email", "")).strip().casefold()
    verified_claim = st.user.get("email_verified", False)
    email_verified = verified_claim is True or str(verified_claim).lower() == "true"
    allowed_value = APP_CONFIG.get("allowed_users", [])
    if not isinstance(allowed_value, (list, tuple)):
        allowed_value = []
    allowed_users = {
        str(value).strip().casefold() for value in allowed_value if str(value).strip()
    }
    if not subject or not email or not email_verified or not allowed_users or email not in allowed_users:
        st.error("Access denied. This deployment is limited to approved, verified test users.")
        if st.button("Sign out"):
            clear_user_gmail_state(st.session_state)
            st.logout()
        st.stop()
    return {"sub": subject, "email": email}


def query_value(name):
    value = st.query_params.get(name)
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value) if value is not None else ""


def handle_cloud_oauth_callback(config, identity):
    """Consume the Gmail callback once and remove its sensitive query data."""
    code = query_value("code")
    state = query_value("state")
    oauth_error = query_value("error")
    if not (code or state or oauth_error):
        return

    st.query_params.clear()
    try:
        if oauth_error:
            validate_signed_state(state, config, identity["sub"], identity["email"])
            st.session_state.oauth_notice = (
                "warning",
                "Gmail authorization was not completed. No mailbox action was taken.",
            )
        elif code and state:
            credentials, authorized_email = exchange_authorization_code(
                config,
                identity["sub"],
                identity["email"],
                code,
                state,
            )
            store_session_credentials(
                st.session_state,
                credentials,
                identity["sub"],
                identity["email"],
                authorized_email,
            )
            st.session_state.oauth_notice = (
                "success",
                "Gmail authorization completed for this session.",
            )
        else:
            raise OAuthSecurityError("Incomplete OAuth callback.")
    except (OAuthSecurityError, GoogleAuthError, ValueError, OSError):
        clear_user_gmail_state(st.session_state)
        st.session_state.oauth_notice = (
            "error",
            "Gmail authorization failed security validation. Start the connection again.",
        )
    st.rerun()


CLOUD_IDENTITY = None
CLOUD_OAUTH_CONFIG = None
if CLOUD_MODE:
    CLOUD_IDENTITY = normalized_verified_identity()
    bind_session_identity(
        st.session_state, CLOUD_IDENTITY["sub"], CLOUD_IDENTITY["email"]
    )
    try:
        CLOUD_OAUTH_CONFIG = CloudOAuthConfig.from_mapping(secret_section("google_oauth"))
    except OAuthSecurityError:
        st.error("Cloud Gmail OAuth is not securely configured. Check Streamlit Secrets.")
        st.stop()
    handle_cloud_oauth_callback(CLOUD_OAUTH_CONFIG, CLOUD_IDENTITY)

notice = st.session_state.pop("oauth_notice", None)
if notice:
    getattr(st, notice[0])(notice[1])

cloud_credentials = None
if CLOUD_MODE:
    try:
        cloud_credentials = load_session_credentials(
            st.session_state, CLOUD_IDENTITY["sub"], CLOUD_IDENTITY["email"]
        )
    except (OAuthSecurityError, ReauthorizationRequired):
        cloud_credentials = None

if "whitelist" not in st.session_state:
    st.session_state.whitelist = load_whitelist()
if "messages" not in st.session_state:
    st.session_state.messages = []
if "selected_message_ids" not in st.session_state:
    st.session_state.selected_message_ids = []
if "scan_revision" not in st.session_state:
    st.session_state.scan_revision = 0


with st.sidebar:
    st.header("Settings")
    if CLOUD_MODE:
        st.caption(f"Signed in as {CLOUD_IDENTITY['email']}")
        if cloud_credentials is not None and st.button("Disconnect Gmail"):
            clear_user_gmail_state(st.session_state)
            st.session_state.oauth_notice = (
                "success",
                "Gmail credentials and mailbox data were removed from this session.",
            )
            st.rerun()
        if st.button("Sign out"):
            clear_user_gmail_state(st.session_state)
            st.logout()
    limit = st.slider("Inbox messages to scan", 10, 500, 200, step=10)
    whitelist_text = st.text_area(
        "Never trash senders/domains (one per line)",
        "\n".join(st.session_state.whitelist),
        height=130,
    )
    if st.button("Save whitelist"):
        st.session_state.whitelist = [
            value.strip().lower()
            for value in whitelist_text.splitlines()
            if value.strip()
        ]
        if not CLOUD_MODE:
            SETTINGS.write_text(
                json.dumps({"whitelist": st.session_state.whitelist}, indent=2),
                encoding="utf-8",
            )
        st.success("Whitelist saved for this session." if CLOUD_MODE else "Whitelist saved.")
    st.caption("A whitelist entry may be a full email address or a domain, e.g. example.edu.")
    if CLOUD_MODE:
        st.caption("Cloud Gmail tokens and whitelist data are isolated to this browser session.")
    else:
        st.warning("Keep token.json and credentials.json private; local OAuth files never belong in Git.")


if CLOUD_MODE:
    if cloud_credentials is None:
        try:
            gmail_authorization_url = build_authorization_url(
                CLOUD_OAUTH_CONFIG,
                CLOUD_IDENTITY["sub"],
                CLOUD_IDENTITY["email"],
            )
            st.info("Identity is verified. Grant Gmail access separately to scan your inbox.")
            st.link_button("Authorize Gmail access", gmail_authorization_url, type="primary")
            st.caption("Authorization uses signed state, a short expiry, PKCE, and account binding.")
        except OAuthSecurityError:
            st.error("Could not start Gmail authorization safely. Check the deployment configuration.")
        st.stop()
elif not CLIENT.exists():
    st.error("Google OAuth credentials.json not found. Follow the local setup in README.md.")
    st.stop()


if st.button("Connect Gmail & Scan Inbox", type="primary"):
    scan_progress = st.progress(0)
    scan_status = st.empty()

    def report_scan_progress(phase, current, total):
        if phase == "listing":
            percentage = min(20, round(20 * current / max(total, 1)))
            scan_progress.progress(percentage)
            scan_status.caption(f"Found {current} inbox message(s), up to the {total}-message limit.")
        else:
            percentage = 20 + round(80 * current / max(total, 1)) if total else 100
            scan_progress.progress(min(percentage, 100))
            scan_status.caption(f"Retrieving message metadata: {current} of {total}.")

    def report_scan_retry(attempt, maximum, delay):
        scan_status.caption(
            f"Gmail is temporarily busy or rate-limited. Retrying in {delay:g}s "
            f"(attempt {attempt} of {maximum})."
        )

    try:
        with st.spinner("Connecting and scanning…"):
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
        scan_status.caption(f"Scan complete: {len(st.session_state.messages)} message(s) retrieved.")
        st.success(f"Scanned {len(st.session_state.messages)} messages. Nothing has been deleted.")
    except ReauthorizationRequired:
        scan_status.caption("Scan stopped safely. No Gmail messages were changed.")
        st.error("Gmail authorization expired or was revoked. Authorize Gmail again.")
    except (HttpError, GoogleAuthError, ValueError, OSError, FileNotFoundError):
        scan_status.caption("Scan stopped safely. No Gmail messages were changed.")
        st.error("Unable to scan Gmail safely. Check authorization, connectivity, and API quota.")


messages = st.session_state.get("messages", [])
if messages:
    classified = []
    for mail in messages:
        result = classify_email(mail, st.session_state.whitelist)
        classified.append({**mail, **result})
    column_1, column_2, column_3, column_4 = st.columns(4)
    column_1.metric("Scanned", len(classified))
    column_2.metric("Suggested for review", sum(message["suggested"] for message in classified))
    column_3.metric("Protected", sum(message["category"] == "Protected" for message in classified))
    column_4.metric("Other / uncertain", sum(message["category"] == "Uncertain" for message in classified))
    st.subheader("Review suggestions")
    st.write(
        "Drag vertically across checkboxes to select a range. Ctrl+Click toggles "
        "one email; Shift+Click selects a continuous visible range. Selections "
        "reset after each new scan."
    )
    category_order = {"Promotion": 0, "Uncertain": 1, "Protected": 2}
    classified.sort(key=lambda message: category_order.get(message["category"], 3))
    valid_ids = [message["id"] for message in classified]
    previous_ids = normalize_selected_ids(st.session_state.selected_message_ids, valid_ids)
    component_ids = drag_select_table(
        rows=[{
            "id": message["id"],
            "sender": message["from"],
            "subject": message["subject"],
            "category": message["category"],
            "reason": message["reason"],
            "date": message["date"],
            "protected": message["category"] == "Protected",
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
    st.info(f"{len(selected_ids)} messages selected. Protected messages cannot be trashed by this app.")
    safe_ids = eligible_trash_ids(selected_ids, classified)
    if len(safe_ids) != len(selected_ids):
        st.warning("Protected messages are excluded even if selected.")
    selection_fingerprint = hashlib.sha256(
        "\0".join(sorted(safe_ids)).encode("utf-8")
    ).hexdigest()[:12]
    confirm = st.checkbox(
        "I reviewed the selected emails and authorize moving them to Gmail Trash.",
        value=False,
        key=f"confirm_trash_{st.session_state.scan_revision}_{selection_fingerprint}",
    )
    if st.button(
        f"Move {len(safe_ids)} selected message(s) to Trash",
        disabled=not (confirm and safe_ids),
    ):
        try:
            service = get_service()
            succeeded = []
            failure_count = 0
            for message_id in safe_ids:
                try:
                    service.users().messages().trash(userId="me", id=message_id).execute()
                    succeeded.append(message_id)
                except HttpError:
                    failure_count += 1
            st.session_state.messages = [
                message for message in messages if message["id"] not in succeeded
            ]
            st.session_state.selected_message_ids = [
                message_id for message_id in selected_ids if message_id not in succeeded
            ]
            st.success(f"Moved {len(succeeded)} messages to Trash. You can restore them from Gmail Trash.")
            if failure_count:
                st.error(f"{failure_count} message(s) could not be moved to Trash.")
            st.rerun()
        except ReauthorizationRequired:
            st.error("Gmail authorization expired or was revoked. Authorize Gmail again.")
        except (HttpError, GoogleAuthError, ValueError, OSError):
            st.error("The Trash action failed safely. No permanent deletion was attempted.")
else:
    st.info("Click Connect Gmail & Scan Inbox to start. Scanning only reads and suggests.")
