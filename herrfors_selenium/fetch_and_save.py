#!/usr/bin/env python3
import os
import json
from datetime import datetime, timezone
from pathlib import Path
from herrfors_session import get_herrfors_session_token
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64
import secrets

# Config via environment (set by run.sh)
EMAIL = os.environ.get("HF_EMAIL")
PASSWORD = os.environ.get("HF_PASSWORD")
TOKEN_FILE = os.environ.get("HF_TOKEN_FILE", "/share/herrfors_token.json")

if not EMAIL or not PASSWORD:
    print("Missing HF_EMAIL or HF_PASSWORD", flush=True)
    raise SystemExit(1)

def derive_key(username: str, password: str, salt: bytes) -> bytes:
    # PBKDF2-SHA256 to derive 32-byte key
    passwd = f"{username}:{password}".encode("utf-8")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
    )
    return kdf.derive(passwd)

# STATIC SALT for PBKDF2 — must be identical in decode helper
# Note: This salt is intentionally static in code so the integration can derive the same key;
# if you want per-deploy random salt, you'd need to store it and share for decoding.
PBKDF2_SALT = b"HerrforsAddOnStaticSalt_v1"  # 24 bytes

def encrypt_token(plain_token: str, username: str, password: str) -> str:
    key = derive_key(username, password, PBKDF2_SALT)
    aesgcm = AESGCM(key)
    nonce = secrets.token_bytes(12)  # 96-bit nonce for AESGCM
    ct = aesgcm.encrypt(nonce, plain_token.encode("utf-8"), None)
    # store nonce + ct in URL-safe base64
    payload = nonce + ct
    b64 = base64.urlsafe_b64encode(payload).decode("utf-8")
    return b64

def main():
    print("Attempting to obtain session token via Selenium...")
    token = get_herrfors_session_token(email=EMAIL, password=PASSWORD, headless=True, verbose=False)
    if not token:
        print("Failed to fetch session token.")
        return

    # add timestamp prefix (ISO8601 UTC)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # encrypt token based on username:password
    encrypted = encrypt_token(token, EMAIL, PASSWORD)
    wrapped = f"{timestamp}:{encrypted}"

    # persist to TOKEN_FILE
    payload = {"token": wrapped, "fetched_at": timestamp}
    Path(TOKEN_FILE).write_text(json.dumps(payload))
    print("Saved encrypted token to:", TOKEN_FILE)
    print("Token preview (first 80 chars):", wrapped[:80])

if __name__ == "__main__":
    main()
