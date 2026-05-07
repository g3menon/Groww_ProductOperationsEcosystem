"""GOOGLE_OAUTH_SCOPES normalization for Google's authorize URL."""

from app.core.config import normalize_google_oauth_scopes_value


def test_commas_become_spaces() -> None:
    raw = (
        "openid,email,profile,https://www.googleapis.com/auth/gmail.send,"
        "https://www.googleapis.com/auth/calendar.events,"
        "https://www.googleapis.com/auth/spreadsheets"
    )
    out = normalize_google_oauth_scopes_value(raw)
    assert out == (
        "openid email profile https://www.googleapis.com/auth/gmail.send "
        "https://www.googleapis.com/auth/calendar.events "
        "https://www.googleapis.com/auth/spreadsheets"
    )


def test_encoded_commas_and_semicolons() -> None:
    raw = "openid%2Cemail%3Bprofile https://x.test/a"
    out = normalize_google_oauth_scopes_value(raw)
    assert out == "openid email profile https://x.test/a"


def test_strips_wrapping_quotes() -> None:
    raw = (
        '"openid email https://www.googleapis.com/auth/gmail.send"'
    )
    assert (
        normalize_google_oauth_scopes_value(raw)
        == "openid email https://www.googleapis.com/auth/gmail.send"
    )
