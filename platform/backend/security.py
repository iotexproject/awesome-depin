from __future__ import annotations

import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash


SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "14"))
UNSAFE_DEVELOPMENT_SECRET = "unsafe-development-secret-change-me"


def secret_pepper() -> str:
    return os.environ.get("APP_SECRET", UNSAFE_DEVELOPMENT_SECRET)


def validate_security_configuration() -> None:
    """Fail closed when production starts with development credentials."""
    if os.environ.get("APP_ENV", "development").lower() != "production":
        return
    app_secret = os.environ.get("APP_SECRET", "")
    admin_token = os.environ.get("ADMIN_TOKEN", "")
    problems = []
    if app_secret == UNSAFE_DEVELOPMENT_SECRET or len(app_secret) < 32:
        problems.append("APP_SECRET must be a unique value with at least 32 characters")
    if len(admin_token) < 32:
        problems.append("ADMIN_TOKEN must contain at least 32 characters")
    if os.environ.get("SESSION_COOKIE_SECURE") != "1":
        problems.append("SESSION_COOKIE_SECURE must be 1")
    if problems:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


def hash_token(token: str) -> str:
    return hashlib.sha256(f"{secret_pepper()}:{token}".encode("utf-8")).hexdigest()


def password_hash(password: str) -> str:
    return generate_password_hash(password, method="scrypt")


def password_matches(encoded: str, password: str) -> bool:
    return check_password_hash(encoded, password)


def new_session_token() -> tuple[str, str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(days=SESSION_DAYS)
    return token, hash_token(token), expires_at


def new_api_key() -> tuple[str, str, str]:
    secret = secrets.token_urlsafe(32)
    raw = f"qtail_live_{secret}"
    prefix = raw[:20]
    return raw, prefix, hash_token(raw)
