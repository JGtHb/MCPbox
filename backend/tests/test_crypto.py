"""Tests for cryptographic operations."""

import pytest

from app.services.crypto import (
    DecryptionError,
    InvalidKeyError,
    decrypt,
    decrypt_from_base64,
    encrypt,
    encrypt_to_base64,
    get_encryption_key,
)


class TestEncryption:
    """Test suite for encryption functionality."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        """Set up a valid encryption key for tests."""
        # 64 hex chars = 32 bytes = 256 bits
        valid_key = "a" * 64
        monkeypatch.setenv("MCPBOX_ENCRYPTION_KEY", valid_key)

    def test_get_encryption_key_valid(self):
        """Test that a valid key is returned as bytes."""
        key = get_encryption_key()
        assert isinstance(key, bytes)
        assert len(key) == 32  # 256 bits

    def test_encrypt_decrypt_roundtrip(self):
        """Test that encrypt/decrypt preserves data."""
        plaintext = "This is a secret message!"
        encrypted = encrypt(plaintext)
        decrypted = decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_produces_different_output(self):
        """Test that encryption produces different ciphertext each time (IV)."""
        plaintext = "Same message"
        encrypted1 = encrypt(plaintext)
        encrypted2 = encrypt(plaintext)
        # Due to random IV, outputs should differ
        assert encrypted1 != encrypted2

    def test_decrypt_invalid_data(self):
        """Test that decryption fails gracefully on invalid data."""
        with pytest.raises(DecryptionError):
            decrypt(b"not valid encrypted data")

    def test_decrypt_too_short(self):
        """Test that decryption fails on too-short data."""
        with pytest.raises(DecryptionError):
            decrypt(b"short")

    def test_base64_roundtrip(self):
        """Test base64 encode/decode roundtrip."""
        plaintext = "Secret data with special chars: äöü 🎉"
        encrypted = encrypt_to_base64(plaintext)

        # Should be a valid base64 string
        assert isinstance(encrypted, str)

        decrypted = decrypt_from_base64(encrypted)
        assert decrypted == plaintext


class TestKeyValidation:
    """Test encryption key validation."""

    def test_short_key_raises(self, monkeypatch):
        """Test that short keys always raise an error."""
        # Clear the settings cache and patch the settings directly
        from app.services import crypto

        monkeypatch.setattr(crypto.settings, "mcpbox_encryption_key", "tooshort")

        with pytest.raises(InvalidKeyError):
            get_encryption_key()

    def test_invalid_hex_raises(self, monkeypatch):
        """Test that invalid hex raises an error."""
        # Patch the settings directly since the global settings is cached
        from app.services import crypto

        monkeypatch.setattr(crypto.settings, "mcpbox_encryption_key", "g" * 64)  # 'g' is not hex

        with pytest.raises(InvalidKeyError):
            get_encryption_key()


class TestEncryptionEdgeCases:
    """Test edge cases for encryption."""

    @pytest.fixture(autouse=True)
    def setup_env(self, monkeypatch):
        """Set up a valid encryption key for tests."""
        valid_key = "b" * 64
        monkeypatch.setenv("MCPBOX_ENCRYPTION_KEY", valid_key)

    def test_encrypt_empty_string(self):
        """Test encrypting an empty string."""
        encrypted = encrypt("")
        decrypted = decrypt(encrypted)
        assert decrypted == ""

    def test_encrypt_unicode(self):
        """Test encrypting unicode characters."""
        plaintext = "Hello 世界 🌍 مرحبا"
        encrypted = encrypt(plaintext)
        decrypted = decrypt(encrypted)
        assert decrypted == plaintext

    def test_encrypt_large_data(self):
        """Test encrypting large amounts of data."""
        plaintext = "x" * 100000  # 100KB
        encrypted = encrypt(plaintext)
        decrypted = decrypt(encrypted)
        assert decrypted == plaintext
