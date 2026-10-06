import base64
import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict
from fastapi import Header, HTTPException
from src.config import settings
from src.logger import logger

PBKDF2_ITERATIONS = 200_000
TOKEN_TTL_SECONDS = 8 * 3600
MAX_FAILURES = 5
LOCKOUT_SECONDS = 300

_secret: bytes | None = None
_failures: dict[str, list[float]] = defaultdict(list)


def _signing_key() -> bytes:
    global _secret
    if settings.auth_secret:
        return settings.auth_secret.encode()
    if _secret is None:
        logger.warning("AUTH_SECRET não definido: tokens serão invalidados a cada reinício.")
        _secret = secrets.token_bytes(32)
    return _secret


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, iterations, salt, digest = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest)
    except ValueError:
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def create_token(subject: str, role: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
    body = _b64(json.dumps({"sub": subject, "role": role, "exp": int(time.time()) + ttl}).encode())
    signature = _b64(hmac.new(_signing_key(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def decode_token(token: str) -> dict | None:
    try:
        body, signature = token.split(".")
        expected = _b64(hmac.new(_signing_key(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        return payload if payload.get("exp", 0) > time.time() else None
    except (ValueError, json.JSONDecodeError):
        return None


def check_admin_credentials(user: str, password: str) -> bool:
    if not settings.admin_user or not (settings.admin_password_hash or settings.admin_password):
        raise HTTPException(503, "Acesso administrativo não configurado")
    user_ok = hmac.compare_digest(user.encode(), settings.admin_user.encode())
    if settings.admin_password_hash:
        password_ok = verify_password(password, settings.admin_password_hash)
    else:
        password_ok = hmac.compare_digest(password.encode(), settings.admin_password.encode())
    return user_ok and password_ok


def ensure_not_locked(key: str) -> None:
    now = time.time()
    _failures[key] = [stamp for stamp in _failures[key] if now - stamp < LOCKOUT_SECONDS]
    if len(_failures[key]) >= MAX_FAILURES:
        raise HTTPException(429, "Muitas tentativas. Tente novamente em alguns minutos.")


def register_failure(key: str) -> None:
    _failures[key].append(time.time())


def clear_failures(key: str) -> None:
    _failures.pop(key, None)


def _actor(authorization: str | None, role: str) -> dict:
    scheme, _, token = (authorization or "").partition(" ")
    payload = decode_token(token) if scheme.lower() == "bearer" else None
    if not payload or payload.get("role") != role:
        raise HTTPException(401, "Sessão inválida ou expirada")
    return payload


def require_company(authorization: str | None = Header(None)) -> dict:
    return _actor(authorization, "empresa")


def require_admin(authorization: str | None = Header(None)) -> dict:
    return _actor(authorization, "admin")
