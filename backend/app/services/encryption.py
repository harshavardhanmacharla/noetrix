"""
Authenticated Encryption Service for Project Test Variables.

Implements AES-256-GCM authenticated encryption for secret variables at rest.
The encryption key must be loaded from server configuration (SECRET_ENCRYPTION_KEY)
and is never stored in databases, logs, client bundles, or source code.
"""
from __future__ import annotations

import base64
import os
import re
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.config import get_settings


def get_encryption_key() -> bytes:
    """
    Retrieve and validate the 256-bit (32-byte) AES-GCM encryption key
    from server environment configuration.

    Supports URL-safe base64, standard base64, 64-character hex, or 32 raw bytes.
    Raises ValueError if the key is missing or invalid. Never silently falls back
    to a hardcoded default key.
    """
    settings = get_settings()
    key_str = (settings.SECRET_ENCRYPTION_KEY or os.environ.get("SECRET_ENCRYPTION_KEY") or "").strip()

    if not key_str:
        raise ValueError(
            "SECRET_ENCRYPTION_KEY is not configured. Server must configure a 32-byte key "
            "encoded in base64 or hex. Never silently use a hardcoded default key."
        )

    # 1. Hex format (64 hex characters)
    if len(key_str) == 64 and re.fullmatch(r"[0-9a-fA-F]{64}", key_str):
        try:
            return bytes.fromhex(key_str)
        except Exception:
            pass

    # 2. Base64 format (typically 43 or 44 characters)
    try:
        # Pad if needed
        padded = key_str + "=" * ((4 - len(key_str) % 4) % 4)
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass

    try:
        padded = key_str + "=" * ((4 - len(key_str) % 4) % 4)
        decoded = base64.b64decode(padded.encode("ascii"))
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass

    # 3. Raw 32 bytes string
    raw_bytes = key_str.encode("utf-8")
    if len(raw_bytes) == 32:
        return raw_bytes

    raise ValueError(
        f"Invalid SECRET_ENCRYPTION_KEY length: expected 32 bytes (256 bits), got {len(raw_bytes)} bytes. "
        "Key must be provided as 32 bytes in base64 or hex."
    )


def encrypt_secret(plaintext: str) -> str:
    """
    Encrypt a plaintext secret using AES-256-GCM.
    Returns a base64-encoded string combining the 12-byte random nonce and ciphertext.
    """
    if plaintext is None:
        raise ValueError("Cannot encrypt None value.")

    key = get_encryption_key()
    aesgcm = AESGCM(key)

    # 96-bit (12-byte) random nonce per NIST SP 800-38D recommendation
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)

    return base64.urlsafe_b64encode(nonce + ciphertext).decode("utf-8")


def decrypt_secret(ciphertext_b64: str) -> str:
    """
    Decrypt an AES-256-GCM ciphertext payload produced by encrypt_secret.
    Extracts the 12-byte nonce, verifies the authentication tag, and returns decrypted plaintext.
    """
    if not ciphertext_b64:
        raise ValueError("Ciphertext cannot be empty.")

    key = get_encryption_key()
    aesgcm = AESGCM(key)

    try:
        raw_data = base64.urlsafe_b64decode(ciphertext_b64.encode("utf-8"))
    except Exception as exc:
        raise ValueError("Malformed ciphertext: invalid base64 encoding.") from exc

    if len(raw_data) < 12 + 16:  # 12 bytes nonce + 16 bytes GCM auth tag minimum
        raise ValueError("Malformed ciphertext: payload too short for AES-GCM.")

    nonce = raw_data[:12]
    ciphertext = raw_data[12:]

    try:
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        raise ValueError("Decryption failed: integrity check failed or corrupted secret.") from exc

