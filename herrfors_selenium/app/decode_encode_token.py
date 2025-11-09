import base64
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import secrets

# Static salt (must match decode helper)
PBKDF2_SALT = b"HerrforsAddOnStaticSalt_v1"

def derive_key(username: str, password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
    )
    return kdf.derive(f"{username}:{password}".encode("utf-8"))

def decrypt_wrapped_token(wrapped: str, username: str, password: str):
    """
    wrapped: "<ISO-timestamp>:<urlsafe-base64>"
    returns: (timestamp_str, plaintext_token) or raises
    """
    if ":" not in wrapped:
        raise ValueError("Invalid wrapped token")
    ts, b64 = wrapped.split(":", 1)
    payload = base64.urlsafe_b64decode(b64.encode("utf-8"))
    if len(payload) < 12:
        raise ValueError("Invalid payload")
    nonce = payload[:12]
    ct = payload[12:]
    key = derive_key(username, password, PBKDF2_SALT)
    aesgcm = AESGCM(key)
    pt = aesgcm.decrypt(nonce, ct, None)
    return ts, pt.decode("utf-8")

def encrypt_token(plain_token: str, username: str, password: str) -> str:
    key = derive_key(username, password, PBKDF2_SALT)
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)
    ct = aesgcm.encrypt(nonce, plain_token.encode("utf-8"), None)
    payload = nonce + ct
    b64 = base64.urlsafe_b64encode(payload).decode("utf-8")
    return b64