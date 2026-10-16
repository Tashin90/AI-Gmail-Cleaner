"""Security boundary for Streamlit Cloud Gmail OAuth.

This module intentionally contains no Streamlit imports.  The UI owns the
authenticated Streamlit session; these helpers bind a separate Gmail grant to
that identity and keep credentials in that session only.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, MutableMapping
from urllib.parse import urlparse

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2 import id_token as google_id_token
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow


GMAIL_MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
PRODUCTION_GMAIL_REDIRECT_URI = "https://ai-gmail-cleaner.streamlit.app/"
CLOUD_GMAIL_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    GMAIL_MODIFY_SCOPE,
)
STATE_MAX_AGE_SECONDS = 10 * 60
SESSION_CREDENTIAL_KEY = "cloud_gmail_credentials"
CONSUMED_CALLBACKS_SESSION_KEY = "consumed_gmail_oauth_callbacks"
MAX_CONSUMED_CALLBACKS = 32
SAFE_OAUTH_ERROR_CODES = frozenset(
    {
        "access_denied",
        "consent_required",
        "google_auth_error",
        "interaction_required",
        "invalid_client",
        "invalid_grant",
        "invalid_request",
        "invalid_scope",
        "login_required",
        "missing_token",
        "scope_mismatch",
        "security_validation_failed",
        "server_error",
        "temporarily_unavailable",
        "transport_error",
        "unauthorized_client",
        "unexpected_error",
        "unsupported_grant_type",
        "unsupported_response_type",
    }
)
USER_DATA_SESSION_KEYS = (
    SESSION_CREDENTIAL_KEY,
    "messages",
    "selected_message_ids",
    "whitelist",
    "scan_revision",
)


class OAuthSecurityError(ValueError):
    """Raised when an OAuth response fails a security check."""


class ReauthorizationRequired(RuntimeError):
    """Raised when the user must grant Gmail access again."""


def sanitize_oauth_error_code(value: object) -> str:
    """Return only an allowlisted OAuth error identifier."""
    candidate = str(value or "").strip().casefold()
    return candidate if candidate in SAFE_OAUTH_ERROR_CODES else "unexpected_error"


def oauth_failure_diagnostic(exc: BaseException) -> tuple[str, str]:
    """Describe an OAuth failure without rendering its message or attached data."""
    exception_type = type(exc).__name__
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", exception_type):
        exception_type = "Exception"

    if isinstance(exc, Warning) and all(
        hasattr(exc, attribute) for attribute in ("token", "old_scope", "new_scope")
    ):
        error_code = "scope_mismatch"
    else:
        error_code = sanitize_oauth_error_code(getattr(exc, "error", ""))
        if error_code == "unexpected_error":
            if isinstance(exc, OAuthSecurityError):
                error_code = "security_validation_failed"
            elif isinstance(exc, GoogleAuthError):
                error_code = "google_auth_error"
            elif isinstance(exc, OSError):
                error_code = "transport_error"
    return exception_type, error_code


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, UnicodeEncodeError) as exc:
        raise OAuthSecurityError("Invalid OAuth state encoding.") from exc


def _normalized_email(value: object) -> str:
    return str(value or "").strip().casefold()


@dataclass(frozen=True)
class CloudOAuthConfig:
    """Validated confidential Web OAuth client configuration."""

    client_id: str
    client_secret: str
    redirect_uri: str
    state_secret: str

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> "CloudOAuthConfig":
        config = cls(
            client_id=str(values.get("client_id", "")).strip(),
            client_secret=str(values.get("client_secret", "")).strip(),
            redirect_uri=str(values.get("redirect_uri", "")).strip(),
            state_secret=str(values.get("state_secret", "")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.client_id or not self.client_secret:
            raise OAuthSecurityError("The Gmail Web OAuth client is not configured.")
        parsed = urlparse(self.redirect_uri)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise OAuthSecurityError("The Gmail OAuth redirect URI must be an HTTPS URL without query or fragment data.")
        if not hmac.compare_digest(self.redirect_uri, PRODUCTION_GMAIL_REDIRECT_URI):
            raise OAuthSecurityError(
                "The Gmail OAuth redirect URI does not match the production callback."
            )
        if len(self.state_secret.encode("utf-8")) < 32:
            raise OAuthSecurityError("The OAuth state secret must contain at least 32 bytes.")

    def client_config(self) -> dict[str, dict[str, str]]:
        return {
            "web": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [self.redirect_uri],
            }
        }


def create_signed_state(
    config: CloudOAuthConfig,
    identity_sub: str,
    identity_email: str,
    *,
    now: int | None = None,
    nonce_factory: Callable[[], str] | None = None,
) -> str:
    """Create a short-lived state value bound to the authenticated identity."""
    nonce_factory = nonce_factory or (lambda: secrets.token_urlsafe(24))
    payload = {
        "v": 1,
        "purpose": "gmail_authorization",
        "sub": str(identity_sub),
        "email": _normalized_email(identity_email),
        "nonce": nonce_factory(),
        "iat": int(time.time() if now is None else now),
        "redirect_uri": config.redirect_uri,
    }
    encoded = _b64url_encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    signature = _b64url_encode(
        hmac.new(config.state_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    return f"{encoded}.{signature}"


def validate_signed_state(
    state: str,
    config: CloudOAuthConfig,
    identity_sub: str,
    identity_email: str,
    *,
    now: int | None = None,
    max_age: int = STATE_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Validate signature, lifetime, purpose, redirect URI, and user binding."""
    try:
        encoded, supplied_signature = state.split(".", 1)
    except (AttributeError, ValueError) as exc:
        raise OAuthSecurityError("Missing or malformed OAuth state.") from exc
    expected_signature = _b64url_encode(
        hmac.new(config.state_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise OAuthSecurityError("OAuth state validation failed.")
    try:
        payload = json.loads(_b64url_decode(encoded))
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise OAuthSecurityError("Invalid OAuth state payload.") from exc
    if not isinstance(payload, dict):
        raise OAuthSecurityError("Invalid OAuth state payload.")
    current_time = int(time.time() if now is None else now)
    issued_at = payload.get("iat")
    if not isinstance(issued_at, int) or issued_at > current_time + 30:
        raise OAuthSecurityError("Invalid OAuth state timestamp.")
    if current_time - issued_at > max_age:
        raise OAuthSecurityError("The OAuth request expired. Start the Gmail connection again.")
    checks = (
        payload.get("v") == 1,
        payload.get("purpose") == "gmail_authorization",
        hmac.compare_digest(str(payload.get("sub", "")), str(identity_sub)),
        hmac.compare_digest(_normalized_email(payload.get("email")), _normalized_email(identity_email)),
        hmac.compare_digest(str(payload.get("redirect_uri", "")), config.redirect_uri),
        isinstance(payload.get("nonce"), str) and len(payload["nonce"]) >= 20,
    )
    if not all(checks):
        raise OAuthSecurityError("OAuth state does not match this authenticated session.")
    return payload


def claim_oauth_callback_state(
    session: MutableMapping[str, Any],
    state: str,
    config: CloudOAuthConfig,
    identity_sub: str,
    identity_email: str,
    *,
    now: int | None = None,
) -> dict[str, Any]:
    """Validate and atomically claim a callback state once per browser session."""
    payload = validate_signed_state(
        state, config, identity_sub, identity_email, now=now
    )
    fingerprint = hmac.new(
        config.state_secret.encode("utf-8"),
        b"consumed-gmail-oauth-callback\0" + state.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    consumed_value = session.get(CONSUMED_CALLBACKS_SESSION_KEY, [])
    consumed = consumed_value if isinstance(consumed_value, list) else []
    if any(
        isinstance(previous, str) and hmac.compare_digest(previous, fingerprint)
        for previous in consumed
    ):
        raise OAuthSecurityError("The OAuth callback has already been consumed.")
    session[CONSUMED_CALLBACKS_SESSION_KEY] = [
        *[value for value in consumed if isinstance(value, str)],
        fingerprint,
    ][-MAX_CONSUMED_CALLBACKS:]
    return payload


def derive_pkce_verifier(config: CloudOAuthConfig, nonce: str, identity_sub: str) -> str:
    """Derive a callback-recoverable PKCE verifier from signed state claims."""
    material = f"gmail-pkce\0{nonce}\0{identity_sub}".encode("utf-8")
    return _b64url_encode(
        hmac.new(config.state_secret.encode("utf-8"), material, hashlib.sha512).digest()
    )


def pkce_challenge(verifier: str) -> str:
    return _b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())


def _flow_for_state(
    config: CloudOAuthConfig,
    state: str,
    payload: Mapping[str, Any],
    flow_factory: Callable[..., Any],
) -> Any:
    flow = flow_factory(
        config.client_config(),
        scopes=list(CLOUD_GMAIL_SCOPES),
        state=state,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = config.redirect_uri
    flow.code_verifier = derive_pkce_verifier(config, payload["nonce"], payload["sub"])
    return flow


def build_authorization_url(
    config: CloudOAuthConfig,
    identity_sub: str,
    identity_email: str,
    *,
    now: int | None = None,
    nonce_factory: Callable[[], str] | None = None,
    flow_factory: Callable[..., Any] = Flow.from_client_config,
) -> str:
    """Build Google's Web OAuth authorization URL with state, nonce, and PKCE."""
    state = create_signed_state(
        config,
        identity_sub,
        identity_email,
        now=now,
        nonce_factory=nonce_factory,
    )
    payload = validate_signed_state(
        state, config, identity_sub, identity_email, now=now
    )
    flow = _flow_for_state(config, state, payload, flow_factory)
    authorization_url, returned_state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        login_hint=_normalized_email(identity_email),
        nonce=payload["nonce"],
    )
    if not hmac.compare_digest(str(returned_state), state):
        raise OAuthSecurityError("OAuth library returned an unexpected state value.")
    return authorization_url


def exchange_authorization_code(
    config: CloudOAuthConfig,
    identity_sub: str,
    identity_email: str,
    code: str,
    state: str,
    *,
    now: int | None = None,
    flow_factory: Callable[..., Any] = Flow.from_client_config,
    id_token_verifier: Callable[..., Mapping[str, Any]] = google_id_token.verify_oauth2_token,
    request_factory: Callable[[], Any] = Request,
) -> tuple[Credentials, str]:
    """Exchange an authorization code and bind its Google identity to OIDC."""
    if not code or not isinstance(code, str):
        raise OAuthSecurityError("The OAuth callback did not include an authorization code.")
    payload = validate_signed_state(
        state, config, identity_sub, identity_email, now=now
    )
    flow = _flow_for_state(config, state, payload, flow_factory)
    flow.fetch_token(code=code)
    credentials = flow.credentials
    raw_id_token = getattr(credentials, "id_token", None)
    if not raw_id_token:
        raise OAuthSecurityError("Google did not return the identity proof required for Gmail access.")
    claims = id_token_verifier(
        raw_id_token,
        request_factory(),
        audience=config.client_id,
    )
    token_email = _normalized_email(claims.get("email"))
    email_verified = claims.get("email_verified") is True or str(claims.get("email_verified", "")).lower() == "true"
    nonce_matches = hmac.compare_digest(str(claims.get("nonce", "")), payload["nonce"])
    email_matches = hmac.compare_digest(token_email, _normalized_email(identity_email))
    if not token_email or not email_verified or not nonce_matches or not email_matches:
        raise OAuthSecurityError("The Gmail authorization identity could not be verified.")
    return credentials, token_email


def clear_user_gmail_state(session: MutableMapping[str, Any]) -> None:
    """Remove credentials and mailbox-derived state from one Streamlit session."""
    for key in USER_DATA_SESSION_KEYS:
        session.pop(key, None)


def bind_session_identity(
    session: MutableMapping[str, Any], identity_sub: str, identity_email: str
) -> None:
    """Clear all user-derived state if a Streamlit session changes identity."""
    current = (str(identity_sub), _normalized_email(identity_email))
    previous = session.get("authenticated_identity")
    if previous is not None and tuple(previous) != current:
        clear_user_gmail_state(session)
    session["authenticated_identity"] = current


def store_session_credentials(
    session: MutableMapping[str, Any],
    credentials: Credentials,
    identity_sub: str,
    identity_email: str,
    authorized_email: str,
) -> None:
    """Store a Gmail grant only in its authenticated Streamlit session."""
    session[SESSION_CREDENTIAL_KEY] = {
        "owner_sub": str(identity_sub),
        "owner_email": _normalized_email(identity_email),
        "authorized_email": _normalized_email(authorized_email),
        "credentials": json.loads(credentials.to_json()),
    }


def load_session_credentials(
    session: MutableMapping[str, Any],
    identity_sub: str,
    identity_email: str,
    *,
    credentials_factory: Callable[..., Credentials] = Credentials.from_authorized_user_info,
    request_factory: Callable[[], Any] = Request,
) -> Credentials | None:
    """Load/refresh credentials after enforcing exact per-user ownership."""
    record = session.get(SESSION_CREDENTIAL_KEY)
    if record is None:
        return None
    if not isinstance(record, dict):
        clear_user_gmail_state(session)
        raise ReauthorizationRequired("The Gmail session is invalid. Authorize Gmail again.")
    expected_email = _normalized_email(identity_email)
    owner_matches = (
        hmac.compare_digest(str(record.get("owner_sub", "")), str(identity_sub))
        and hmac.compare_digest(_normalized_email(record.get("owner_email")), expected_email)
        and hmac.compare_digest(_normalized_email(record.get("authorized_email")), expected_email)
    )
    if not owner_matches:
        clear_user_gmail_state(session)
        raise OAuthSecurityError("Gmail credentials do not belong to this authenticated session.")
    try:
        credentials = credentials_factory(
            record["credentials"], scopes=list(CLOUD_GMAIL_SCOPES)
        )
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(request_factory())
            record["credentials"] = json.loads(credentials.to_json())
            session[SESSION_CREDENTIAL_KEY] = record
        if not credentials.valid:
            raise ReauthorizationRequired("Gmail authorization expired. Authorize Gmail again.")
        return credentials
    except (KeyError, TypeError, ValueError, GoogleAuthError) as exc:
        clear_user_gmail_state(session)
        raise ReauthorizationRequired("Gmail authorization expired or was revoked. Authorize Gmail again.") from exc
