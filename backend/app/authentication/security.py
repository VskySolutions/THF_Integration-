import secrets

from pwdlib import PasswordHash
from starlette.requests import Request

password_hash = PasswordHash.recommended()

# Used when a submitted username does not exist, keeping the expensive password
# verification step present for both successful and unsuccessful lookups.
DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$93RK8t0Kux+czaPI6jwmgA"
    "$7OhKBiSuSB+m5xYgUwD0MowLEo5Q5eg/qodeFkryQb8"
)


def verify_password(plain_password: str, stored_hash: str) -> bool:
    try:
        return password_hash.verify(plain_password, stored_hash)
    except (TypeError, ValueError):
        return False


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def valid_csrf_token(request: Request, submitted_token: str) -> bool:
    expected_token = request.session.get("csrf_token")
    return isinstance(expected_token, str) and secrets.compare_digest(
        expected_token, submitted_token
    )
