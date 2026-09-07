"""Password hashing and purpose-bound random token proofs."""

import hashlib
import hmac
import re
import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

from reconcile.auth.config import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH, TOKEN_BYTES

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def valid_token(token: str | None) -> bool:
    return isinstance(token, str) and _TOKEN_PATTERN.fullmatch(token) is not None


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def password_valid(password: str) -> bool:
    try:
        password.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH


class Passwords:
    def __init__(self) -> None:
        self.hasher = PasswordHasher(memory_cost=65536, time_cost=3, parallelism=4, type=Type.ID)
        self.dummy_hash = self.hasher.hash(new_token())

    def hash(self, password: str) -> str:
        if not password_valid(password):
            raise ValueError("Password must contain 15–128 characters")
        return self.hasher.hash(password)

    def verify(self, encoded: str | None, password: str) -> bool:
        if len(password) > PASSWORD_MAX_LENGTH:
            return False
        try:
            matched = self.hasher.verify(encoded or self.dummy_hash, password)
            return bool(encoded and matched)
        except (VerificationError, InvalidHashError, UnicodeEncodeError):
            return False

    def needs_rehash(self, encoded: str) -> bool:
        return self.hasher.check_needs_rehash(encoded)


def _signature(secret: bytes, context: str, session: str, nonce: str) -> str:
    message = f"csrf:{len(context)}:{context}:{len(session)}:{session}:{nonce}".encode("ascii")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def csrf_token(secret: bytes, context: str, session: str = "") -> str:
    nonce = new_token()
    return f"{nonce}.{_signature(secret, context, session, nonce)}"


def csrf_valid(secret: bytes, context: str | None, session: str, proof: str | None) -> bool:
    if not valid_token(context) or not proof or len(proof) != 108:
        return False
    nonce, separator, signature = proof.partition(".")
    if not separator or not valid_token(nonce) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        return False
    return hmac.compare_digest(signature, _signature(secret, context, session, nonce))
