#!/usr/bin/env python3
"""Encryption key rotation utility for MCPbox.

Re-encrypts all stored secrets from an old key to a new key.
Run this script, then update MCPBOX_ENCRYPTION_KEY in your environment.

Usage:
    python scripts/rotate_encryption_key.py --old-key <old_hex> --new-key <new_hex>
    python scripts/rotate_encryption_key.py --old-key <old_hex> --generate-new

Tables with encrypted data:
    - credentials: encrypted_value, encrypted_username, encrypted_password,
                   oauth_client_secret, encrypted_access_token, encrypted_refresh_token
    - cloudflare_configs: encrypted_api_token, encrypted_tunnel_token, encrypted_service_token
    - tunnel_configurations: tunnel_token
    - settings: value (where encrypted=true)
"""

import argparse
import secrets
import sys
from base64 import b64decode, b64encode

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _validate_key(key_hex: str, name: str) -> bytes:
    """Validate and convert a hex key string to bytes."""
    if len(key_hex) != 64:
        print(
            f"ERROR: {name} must be 64 hex characters (32 bytes). Got {len(key_hex)}."
        )
        sys.exit(1)
    try:
        return bytes.fromhex(key_hex)
    except ValueError:
        print(f"ERROR: {name} is not valid hexadecimal.")
        sys.exit(1)


def _decrypt(encrypted: bytes, key: bytes) -> str:
    """Decrypt AES-256-GCM: IV (12) || ciphertext || tag (16)."""
    aesgcm = AESGCM(key)
    iv = encrypted[:12]
    ciphertext = encrypted[12:]
    return aesgcm.decrypt(iv, ciphertext, None).decode("utf-8")


def _encrypt(plaintext: str, key: bytes) -> bytes:
    """Encrypt with AES-256-GCM, returns IV || ciphertext || tag."""
    aesgcm = AESGCM(key)
    iv = secrets.token_bytes(12)
    ciphertext = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)
    return iv + ciphertext


def _rotate_bytes(value: bytes, old_key: bytes, new_key: bytes) -> bytes:
    """Decrypt with old key, re-encrypt with new key (raw bytes)."""
    plaintext = _decrypt(value, old_key)
    return _encrypt(plaintext, new_key)


def _rotate_b64(value: str, old_key: bytes, new_key: bytes) -> str:
    """Decrypt with old key, re-encrypt with new key (base64-encoded)."""
    encrypted = b64decode(value)
    plaintext = _decrypt(encrypted, old_key)
    re_encrypted = _encrypt(plaintext, new_key)
    return b64encode(re_encrypted).decode("ascii")


def main():
    parser = argparse.ArgumentParser(description="Rotate MCPbox encryption key")
    parser.add_argument("--old-key", required=True, help="Current 64-char hex key")
    parser.add_argument("--new-key", help="New 64-char hex key")
    parser.add_argument(
        "--generate-new",
        action="store_true",
        help="Generate a new key instead of providing one",
    )
    parser.add_argument(
        "--database-url",
        help="PostgreSQL URL (default: from DATABASE_URL env var)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change without writing"
    )
    args = parser.parse_args()

    old_key = _validate_key(args.old_key, "--old-key")

    if args.generate_new:
        new_key_hex = secrets.token_hex(32)
        new_key = bytes.fromhex(new_key_hex)
        print(f"Generated new key: {new_key_hex}")
    elif args.new_key:
        new_key_hex = args.new_key
        new_key = _validate_key(args.new_key, "--new-key")
    else:
        print("ERROR: Provide --new-key or --generate-new")
        sys.exit(1)

    if old_key == new_key:
        print("ERROR: Old and new keys are identical.")
        sys.exit(1)

    # Import database dependencies
    import os

    db_url = args.database_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: Provide --database-url or set DATABASE_URL env var")
        sys.exit(1)

    # Convert async URL to sync for this script
    sync_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

    from sqlalchemy import create_engine, text

    engine = create_engine(sync_url)
    rotated = 0
    errors = 0

    with engine.begin() as conn:
        # --- credentials table (BYTEA columns) ---
        bytea_columns = [
            "encrypted_value",
            "encrypted_username",
            "encrypted_password",
            "oauth_client_secret",
            "encrypted_access_token",
            "encrypted_refresh_token",
        ]
        rows = conn.execute(text("SELECT id FROM credentials")).fetchall()
        for (row_id,) in rows:
            for col in bytea_columns:
                result = conn.execute(
                    text(f"SELECT {col} FROM credentials WHERE id = :id"),
                    {"id": row_id},
                ).fetchone()
                value = result[0] if result else None
                if value is None:
                    continue
                try:
                    new_value = _rotate_bytes(bytes(value), old_key, new_key)
                    if not args.dry_run:
                        conn.execute(
                            text(f"UPDATE credentials SET {col} = :val WHERE id = :id"),
                            {"val": new_value, "id": row_id},
                        )
                    rotated += 1
                    print(f"  credentials.{col} (id={row_id}): rotated")
                except Exception as e:
                    errors += 1
                    print(f"  credentials.{col} (id={row_id}): FAILED - {e}")

        # --- cloudflare_configs table (base64-encoded text columns) ---
        b64_cf_columns = [
            "encrypted_api_token",
            "encrypted_tunnel_token",
            "encrypted_service_token",
        ]
        rows = conn.execute(text("SELECT id FROM cloudflare_configs")).fetchall()
        for (row_id,) in rows:
            for col in b64_cf_columns:
                result = conn.execute(
                    text(f"SELECT {col} FROM cloudflare_configs WHERE id = :id"),
                    {"id": row_id},
                ).fetchone()
                value = result[0] if result else None
                if value is None:
                    continue
                try:
                    new_value = _rotate_b64(value, old_key, new_key)
                    if not args.dry_run:
                        conn.execute(
                            text(
                                f"UPDATE cloudflare_configs SET {col} = :val WHERE id = :id"
                            ),
                            {"val": new_value, "id": row_id},
                        )
                    rotated += 1
                    print(f"  cloudflare_configs.{col} (id={row_id}): rotated")
                except Exception as e:
                    errors += 1
                    print(f"  cloudflare_configs.{col} (id={row_id}): FAILED - {e}")

        # --- tunnel_configurations table (base64-encoded text) ---
        rows = conn.execute(
            text(
                "SELECT id, tunnel_token FROM tunnel_configurations WHERE tunnel_token IS NOT NULL"
            )
        ).fetchall()
        for row_id, value in rows:
            try:
                new_value = _rotate_b64(value, old_key, new_key)
                if not args.dry_run:
                    conn.execute(
                        text(
                            "UPDATE tunnel_configurations SET tunnel_token = :val WHERE id = :id"
                        ),
                        {"val": new_value, "id": row_id},
                    )
                rotated += 1
                print(f"  tunnel_configurations.tunnel_token (id={row_id}): rotated")
            except Exception as e:
                errors += 1
                print(
                    f"  tunnel_configurations.tunnel_token (id={row_id}): FAILED - {e}"
                )

        # --- settings table (base64-encoded text, where encrypted=true) ---
        rows = conn.execute(
            text(
                "SELECT id, key, value FROM settings WHERE encrypted = true AND value IS NOT NULL"
            )
        ).fetchall()
        for row_id, key, value in rows:
            try:
                new_value = _rotate_b64(value, old_key, new_key)
                if not args.dry_run:
                    conn.execute(
                        text("UPDATE settings SET value = :val WHERE id = :id"),
                        {"val": new_value, "id": row_id},
                    )
                rotated += 1
                print(f"  settings.value (key={key}): rotated")
            except Exception as e:
                errors += 1
                print(f"  settings.value (key={key}): FAILED - {e}")

    if args.dry_run:
        print(f"\nDry run complete: {rotated} values would be rotated, {errors} errors")
    else:
        print(f"\nRotation complete: {rotated} values rotated, {errors} errors")

    if errors > 0:
        print(
            "\nWARNING: Some values failed to rotate. Do NOT update the encryption key."
        )
        print("Investigate the errors above and re-run.")
        sys.exit(1)
    elif rotated > 0:
        print(f"\nUpdate your environment: MCPBOX_ENCRYPTION_KEY={new_key_hex}")
        print("Then restart all MCPbox services.")
    else:
        print("\nNo encrypted values found. Key rotation not needed.")


if __name__ == "__main__":
    main()
