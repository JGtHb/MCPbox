"""Cryptographic utilities for credential encryption."""

import logging
import secrets
from base64 import b64decode, b64encode

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core import settings

logger = logging.getLogger(__name__)

# Minimum length for encrypted data: 12 bytes IV + 16 bytes auth tag
MIN_ENCRYPTED_LENGTH = 28


class CryptoError(Exception):
    """Base exception for cryptographic operations.

    All crypto-related exceptions inherit from this class.
    """


class InvalidKeyError(CryptoError):
    """Raised when encryption key is invalid.

    This includes missing keys, wrong length, or invalid hex characters.
    """


class DecryptionError(CryptoError):
    """Raised when decryption fails.

    This can occur due to corrupted data, wrong key, or malformed ciphertext.
    """


def get_encryption_key() -> bytes:
    """Get the encryption key from settings.

    The key must be exactly a 64-character hex string (32 bytes / 256 bits).

    Raises:
        InvalidKeyError: If key is missing, wrong length, or invalid hex.
    """
    key_hex = settings.mcpbox_encryption_key

    if len(key_hex) != 64:
        raise InvalidKeyError(
            f"MCPBOX_ENCRYPTION_KEY must be exactly 64 hex characters (32 bytes). "
            f"Got {len(key_hex)} characters. "
            f'Generate a secure key with: python -c "import secrets; print(secrets.token_hex(32))"'
        )

    try:
        return bytes.fromhex(key_hex)
    except ValueError as e:
        raise InvalidKeyError(f"MCPBOX_ENCRYPTION_KEY must be valid hexadecimal: {e}") from e


def encrypt(plaintext: str, aad: str | None = None) -> bytes:
    """Encrypt a plaintext string using AES-256-GCM.

    Args:
        plaintext: The string to encrypt.
        aad: Optional Associated Authenticated Data. When provided, binds the
             ciphertext to a specific context (e.g., "service_token" or
             "server_secret:<id>"), preventing ciphertext swapping attacks
             between different database columns.

    Returns: IV (12 bytes) || ciphertext || tag (16 bytes)
    """
    if aad is None:
        logger.warning(
            "encrypt() called without AAD — context binding disabled. "
            "Pass aad= to prevent ciphertext swapping between database columns (SEC-005)."
        )

    key = get_encryption_key()
    aesgcm = AESGCM(key)

    # Generate random 96-bit IV
    iv = secrets.token_bytes(12)

    # Encrypt with optional AAD for context binding
    aad_bytes = aad.encode("utf-8") if aad else None
    ciphertext = aesgcm.encrypt(iv, plaintext.encode("utf-8"), aad_bytes)

    # Return IV + ciphertext (tag is appended by AESGCM)
    return iv + ciphertext


def decrypt(encrypted: bytes, aad: str | None = None) -> str:
    """Decrypt an AES-256-GCM encrypted value.

    Expects: IV (12 bytes) || ciphertext || tag (16 bytes)

    Args:
        encrypted: The encrypted bytes (IV + ciphertext + tag).
        aad: Optional AAD that was used during encryption. Must match exactly
             or decryption will fail (authentication tag mismatch).

    Supports dual-key decryption for key rotation: tries the current key first,
    then falls back to MCPBOX_ENCRYPTION_KEY_OLD if set.

    For backwards compatibility, if decryption with AAD fails, retries without
    AAD (for data encrypted before AAD was introduced).

    Raises:
        DecryptionError: If decryption fails or data is malformed.
    """
    if len(encrypted) < MIN_ENCRYPTED_LENGTH:
        raise DecryptionError(
            f"Encrypted data too short: {len(encrypted)} bytes, "
            f"minimum {MIN_ENCRYPTED_LENGTH} bytes required"
        )

    iv = encrypted[:12]
    ciphertext = encrypted[12:]
    aad_bytes = aad.encode("utf-8") if aad else None

    # Try current key first
    try:
        key = get_encryption_key()
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(iv, ciphertext, aad_bytes)
        return plaintext.decode("utf-8")
    except InvalidKeyError:
        raise
    except Exception as primary_error:
        # Backwards compatibility: try without AAD for pre-AAD encrypted data
        if aad_bytes is not None:
            try:
                key = get_encryption_key()
                aesgcm = AESGCM(key)
                plaintext = aesgcm.decrypt(iv, ciphertext, None)
                logger.info("Decrypted without AAD (legacy data) — re-encrypt to add AAD binding")
                return plaintext.decode("utf-8")
            except Exception:
                pass  # Fall through to old key attempt

        # Try old key if configured (for key rotation transition)
        old_key_hex = settings.mcpbox_encryption_key_old
        if old_key_hex:
            try:
                old_key = bytes.fromhex(old_key_hex)
                aesgcm_old = AESGCM(old_key)
                plaintext = aesgcm_old.decrypt(iv, ciphertext, aad_bytes)
                logger.info("Decrypted with old key — run key rotation script to re-encrypt")
                return plaintext.decode("utf-8")
            except Exception:
                # Also try old key without AAD for legacy data
                if aad_bytes is not None:
                    try:
                        plaintext = aesgcm_old.decrypt(iv, ciphertext, None)
                        logger.info(
                            "Decrypted with old key without AAD — re-encrypt with new key + AAD"
                        )
                        return plaintext.decode("utf-8")
                    except Exception:
                        pass
        raise DecryptionError(f"Decryption failed: {primary_error}") from primary_error


def encrypt_to_base64(plaintext: str, aad: str | None = None) -> str:
    """Encrypt and return as base64 string (for JSON serialization)."""
    encrypted = encrypt(plaintext, aad=aad)
    return b64encode(encrypted).decode("ascii")


def decrypt_from_base64(encrypted_b64: str, aad: str | None = None) -> str:
    """Decrypt from base64 string."""
    encrypted = b64decode(encrypted_b64)
    return decrypt(encrypted, aad=aad)
