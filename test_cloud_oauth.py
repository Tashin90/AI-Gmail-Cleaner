import json
from urllib.parse import parse_qs, urlparse

from google.auth.exceptions import RefreshError
from oauthlib.oauth2 import InvalidGrantError, MissingTokenError

from cloud_oauth import (
    CLOUD_GMAIL_SCOPES,
    CONSUMED_CALLBACKS_SESSION_KEY,
    PRODUCTION_GMAIL_REDIRECT_URI,
    SESSION_CREDENTIAL_KEY,
    CloudOAuthConfig,
    OAuthSecurityError,
    ReauthorizationRequired,
    bind_session_identity,
    build_authorization_url,
    claim_oauth_callback_state,
    create_signed_state,
    exchange_authorization_code,
    load_session_credentials,
    oauth_failure_diagnostic,
    pkce_challenge,
    sanitize_oauth_error_code,
    store_session_credentials,
    validate_signed_state,
)


NOW = 1_800_000_000
IDENTITY_SUB = "oidc-user-123"
IDENTITY_EMAIL = "approved@example.com"


def config():
    return CloudOAuthConfig(
        client_id="web-client.apps.googleusercontent.com",
        client_secret="placeholder-client-secret",
        redirect_uri="https://ai-gmail-cleaner.streamlit.app/",
        state_secret="s" * 48,
    )


class FakeCredentials:
    def __init__(self, *, expired=False, valid=True, refresh_token="refresh-placeholder"):
        self.expired = expired
        self.valid = valid
        self.refresh_token = refresh_token
        self.id_token = "mock-id-token"
        self.refreshed = False

    def refresh(self, _request):
        self.refreshed = True
        self.expired = False
        self.valid = True

    def to_json(self):
        return json.dumps({
            "token": "access-placeholder",
            "refresh_token": self.refresh_token,
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "web-client.apps.googleusercontent.com",
            "client_secret": "placeholder-client-secret",
            "scopes": list(CLOUD_GMAIL_SCOPES),
        })


def test_signed_state_is_user_bound_tamper_evident_and_short_lived():
    state = create_signed_state(
        config(), IDENTITY_SUB, IDENTITY_EMAIL, now=NOW, nonce_factory=lambda: "n" * 32
    )
    payload = validate_signed_state(
        state, config(), IDENTITY_SUB, IDENTITY_EMAIL, now=NOW + 30
    )
    assert payload["nonce"] == "n" * 32

    for invalid_state, subject, email, timestamp in (
        (state[:-1] + ("A" if state[-1] != "A" else "B"), IDENTITY_SUB, IDENTITY_EMAIL, NOW),
        (state, "another-user", IDENTITY_EMAIL, NOW),
        (state, IDENTITY_SUB, "other@example.com", NOW),
        (state, IDENTITY_SUB, IDENTITY_EMAIL, NOW + 601),
    ):
        try:
            validate_signed_state(
                invalid_state, config(), subject, email, now=timestamp
            )
        except OAuthSecurityError:
            pass
        else:
            raise AssertionError("Invalid OAuth state must fail closed")


def test_authorization_url_uses_exact_redirect_state_nonce_and_pkce():
    url = build_authorization_url(
        config(),
        IDENTITY_SUB,
        IDENTITY_EMAIL,
        now=NOW,
        nonce_factory=lambda: "p" * 32,
    )
    query = parse_qs(urlparse(url).query)
    assert query["redirect_uri"] == [PRODUCTION_GMAIL_REDIRECT_URI]
    assert query["code_challenge_method"] == ["S256"]
    assert query["nonce"] == ["p" * 32]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert "include_granted_scopes" not in query
    assert set(query["scope"][0].split()) == set(CLOUD_GMAIL_SCOPES)
    state_payload = validate_signed_state(
        query["state"][0], config(), IDENTITY_SUB, IDENTITY_EMAIL, now=NOW
    )
    assert len(query["code_challenge"][0]) == 43
    assert state_payload["redirect_uri"] == config().redirect_uri


def test_cloud_config_requires_exact_production_redirect_uri():
    for invalid_redirect in (
        "https://ai-gmail-cleaner.streamlit.app",
        "https://ai-gmail-cleaner.streamlit.app/oauth2callback",
        "https://other-app.streamlit.app/",
    ):
        try:
            CloudOAuthConfig(
                client_id="web-client.apps.googleusercontent.com",
                client_secret="placeholder-client-secret",
                redirect_uri=invalid_redirect,
                state_secret="s" * 48,
            ).validate()
        except OAuthSecurityError:
            pass
        else:
            raise AssertionError("Cloud Gmail redirect URI must match production exactly")


def test_code_exchange_validates_pkce_nonce_and_authorized_email():
    state = create_signed_state(
        config(), IDENTITY_SUB, IDENTITY_EMAIL, now=NOW, nonce_factory=lambda: "x" * 32
    )
    observed = {}

    class FakeFlow:
        def __init__(self):
            self.redirect_uri = None
            self.code_verifier = None
            self.credentials = FakeCredentials()

        def fetch_token(self, *, code):
            observed["code"] = code
            observed["redirect_uri"] = self.redirect_uri
            observed["verifier"] = self.code_verifier

    def flow_factory(client_config, *, scopes, state, autogenerate_code_verifier):
        observed["client_config"] = client_config
        observed["scopes"] = scopes
        observed["state"] = state
        observed["autogenerate"] = autogenerate_code_verifier
        return FakeFlow()

    def verify_id_token(raw_token, _request, *, audience):
        assert raw_token == "mock-id-token"
        assert audience == config().client_id
        return {
            "email": IDENTITY_EMAIL,
            "email_verified": True,
            "nonce": "x" * 32,
        }

    credentials, authorized_email = exchange_authorization_code(
        config(),
        IDENTITY_SUB,
        IDENTITY_EMAIL,
        "one-time-code",
        state,
        now=NOW,
        flow_factory=flow_factory,
        id_token_verifier=verify_id_token,
        request_factory=lambda: object(),
    )
    assert isinstance(credentials, FakeCredentials)
    assert authorized_email == IDENTITY_EMAIL
    assert observed["code"] == "one-time-code"
    assert observed["redirect_uri"] == config().redirect_uri
    assert observed["state"] == state
    assert 43 <= len(observed["verifier"]) <= 128
    assert observed["autogenerate"] is False
    assert pkce_challenge(observed["verifier"])


def test_code_exchange_rejects_a_different_gmail_identity():
    state = create_signed_state(
        config(), IDENTITY_SUB, IDENTITY_EMAIL, now=NOW, nonce_factory=lambda: "z" * 32
    )

    class FakeFlow:
        redirect_uri = None
        code_verifier = None
        credentials = FakeCredentials()

        def fetch_token(self, *, code):
            assert code

    try:
        exchange_authorization_code(
            config(),
            IDENTITY_SUB,
            IDENTITY_EMAIL,
            "one-time-code",
            state,
            now=NOW,
            flow_factory=lambda *args, **kwargs: FakeFlow(),
            id_token_verifier=lambda *args, **kwargs: {
                "email": "attacker@example.com",
                "email_verified": True,
                "nonce": "z" * 32,
            },
            request_factory=lambda: object(),
        )
    except OAuthSecurityError:
        pass
    else:
        raise AssertionError("A Gmail grant for another identity must be rejected")


def test_callback_state_is_claimed_before_one_token_exchange_and_cannot_replay():
    state = create_signed_state(
        config(), IDENTITY_SUB, IDENTITY_EMAIL, now=NOW, nonce_factory=lambda: "r" * 32
    )
    session = {}
    claim_oauth_callback_state(
        session, state, config(), IDENTITY_SUB, IDENTITY_EMAIL, now=NOW
    )
    assert len(session[CONSUMED_CALLBACKS_SESSION_KEY]) == 1
    assert state not in session[CONSUMED_CALLBACKS_SESSION_KEY]

    fetch_count = 0

    class FakeFlow:
        redirect_uri = None
        code_verifier = None
        credentials = FakeCredentials()

        def fetch_token(self, *, code):
            nonlocal fetch_count
            assert code == "one-time-code"
            fetch_count += 1

    exchange_authorization_code(
        config(),
        IDENTITY_SUB,
        IDENTITY_EMAIL,
        "one-time-code",
        state,
        now=NOW,
        flow_factory=lambda *args, **kwargs: FakeFlow(),
        id_token_verifier=lambda *args, **kwargs: {
            "email": IDENTITY_EMAIL,
            "email_verified": True,
            "nonce": "r" * 32,
        },
        request_factory=lambda: object(),
    )
    assert fetch_count == 1

    try:
        claim_oauth_callback_state(
            session, state, config(), IDENTITY_SUB, IDENTITY_EMAIL, now=NOW
        )
    except OAuthSecurityError:
        pass
    else:
        raise AssertionError("A consumed OAuth callback must not be replayable")
    assert fetch_count == 1


def test_token_exchange_failures_have_only_sanitized_diagnostics():
    scope_warning = Warning(
        "scope detail containing an authorization code and token must never be rendered"
    )
    scope_warning.token = {"access_token": "sensitive-access-token"}
    scope_warning.old_scope = list(CLOUD_GMAIL_SCOPES)
    scope_warning.new_scope = [*CLOUD_GMAIL_SCOPES, "unexpected.extra.scope"]

    assert oauth_failure_diagnostic(scope_warning) == ("Warning", "scope_mismatch")
    assert oauth_failure_diagnostic(MissingTokenError(description="sensitive")) == (
        "MissingTokenError",
        "missing_token",
    )
    assert oauth_failure_diagnostic(InvalidGrantError(description="sensitive")) == (
        "InvalidGrantError",
        "invalid_grant",
    )
    assert sanitize_oauth_error_code("access_denied") == "access_denied"
    assert sanitize_oauth_error_code("secret-bearing-unknown-value") == "unexpected_error"


def test_scope_mismatch_from_fetch_token_is_classified_without_sensitive_details():
    state = create_signed_state(
        config(), IDENTITY_SUB, IDENTITY_EMAIL, now=NOW, nonce_factory=lambda: "w" * 32
    )

    class ScopeMismatchFlow:
        redirect_uri = None
        code_verifier = None

        def fetch_token(self, *, code):
            assert code == "one-time-code"
            warning = Warning("sensitive scope and token response details")
            warning.token = {"access_token": "sensitive-access-token"}
            warning.old_scope = list(CLOUD_GMAIL_SCOPES)
            warning.new_scope = [*CLOUD_GMAIL_SCOPES, "unexpected.extra.scope"]
            raise warning

    try:
        exchange_authorization_code(
            config(),
            IDENTITY_SUB,
            IDENTITY_EMAIL,
            "one-time-code",
            state,
            now=NOW,
            flow_factory=lambda *args, **kwargs: ScopeMismatchFlow(),
        )
    except Warning as exc:
        assert oauth_failure_diagnostic(exc) == ("Warning", "scope_mismatch")
    else:
        raise AssertionError("A token scope mismatch must fail closed")


def test_session_credentials_are_isolated_by_authenticated_user():
    session = {"messages": [{"id": "private-message"}], "whitelist": ["private.example"]}
    store_session_credentials(
        session,
        FakeCredentials(),
        IDENTITY_SUB,
        IDENTITY_EMAIL,
        IDENTITY_EMAIL,
    )
    try:
        load_session_credentials(
            session,
            "different-sub",
            IDENTITY_EMAIL,
            credentials_factory=lambda *args, **kwargs: FakeCredentials(),
        )
    except OAuthSecurityError:
        pass
    else:
        raise AssertionError("Cross-user session credentials must be rejected")
    assert SESSION_CREDENTIAL_KEY not in session
    assert "messages" not in session
    assert "whitelist" not in session


def test_expired_credentials_refresh_and_revocation_fails_closed():
    session = {}
    store_session_credentials(
        session,
        FakeCredentials(),
        IDENTITY_SUB,
        IDENTITY_EMAIL,
        IDENTITY_EMAIL,
    )
    expired = FakeCredentials(expired=True, valid=False)
    loaded = load_session_credentials(
        session,
        IDENTITY_SUB,
        IDENTITY_EMAIL,
        credentials_factory=lambda *args, **kwargs: expired,
        request_factory=lambda: object(),
    )
    assert loaded.valid and loaded.refreshed

    class RevokedCredentials(FakeCredentials):
        def refresh(self, _request):
            raise RefreshError("revoked")

    try:
        load_session_credentials(
            session,
            IDENTITY_SUB,
            IDENTITY_EMAIL,
            credentials_factory=lambda *args, **kwargs: RevokedCredentials(
                expired=True, valid=False
            ),
            request_factory=lambda: object(),
        )
    except ReauthorizationRequired:
        pass
    else:
        raise AssertionError("Revoked credentials must require reauthorization")
    assert SESSION_CREDENTIAL_KEY not in session


def test_identity_change_clears_user_mailbox_state():
    session = {
        "authenticated_identity": (IDENTITY_SUB, IDENTITY_EMAIL),
        "messages": [{"id": "private-message"}],
        "selected_message_ids": ["private-message"],
        SESSION_CREDENTIAL_KEY: {"private": True},
    }
    bind_session_identity(session, "new-sub", "new@example.com")
    assert session["authenticated_identity"] == ("new-sub", "new@example.com")
    assert "messages" not in session
    assert "selected_message_ids" not in session
    assert SESSION_CREDENTIAL_KEY not in session


if __name__ == "__main__":
    tests = [
        test_signed_state_is_user_bound_tamper_evident_and_short_lived,
        test_authorization_url_uses_exact_redirect_state_nonce_and_pkce,
        test_cloud_config_requires_exact_production_redirect_uri,
        test_code_exchange_validates_pkce_nonce_and_authorized_email,
        test_code_exchange_rejects_a_different_gmail_identity,
        test_callback_state_is_claimed_before_one_token_exchange_and_cannot_replay,
        test_token_exchange_failures_have_only_sanitized_diagnostics,
        test_scope_mismatch_from_fetch_token_is_classified_without_sensitive_details,
        test_session_credentials_are_isolated_by_authenticated_user,
        test_expired_credentials_refresh_and_revocation_fails_closed,
        test_identity_change_clears_user_mailbox_state,
    ]
    for test in tests:
        test()
    print(f"{len(tests)} cloud OAuth security tests passed")
