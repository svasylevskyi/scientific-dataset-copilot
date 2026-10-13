import hashlib
import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

# Argon2id defaults: 64 MiB, 3 iterations, parallelism 4.
password_hasher = PasswordHasher()
DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def now() -> datetime:
    return datetime.now(UTC)


def secret() -> str:
    return secrets.token_urlsafe(32)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_matches(value: str, stored: str) -> bool:
    try:
        return password_hasher.verify(stored, value)
    except VerificationError:
        return False
