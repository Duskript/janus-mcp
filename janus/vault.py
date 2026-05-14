"""Janus Vault — encrypted local token storage.

Uses Fernet (AES-128-CBC + HMAC-SHA256) symmetric encryption.
Key is derived from JANUS_MASTER_KEY env var or auto-generated file key.
"""

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet

CONFIG_DIR = Path.home() / ".config" / "janus"
VAULT_PATH = CONFIG_DIR / "vault"
KEY_FILE = CONFIG_DIR / "vault.key"

_MASTER_KEY_ENV = "JANUS_MASTER_KEY"


def _ensure_dirs():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _get_fernet() -> Fernet:
    """Get a Fernet instance from the master key."""
    key = os.environ.get(_MASTER_KEY_ENV)
    if key:
        # Env var can be either raw Fernet key (32-byte base64) or any string
        # If it's a valid Fernet key, use it directly
        try:
            return Fernet(key.encode("utf-8"))
        except Exception:
            pass
        # Otherwise derive by taking sha256 and base64-encoding it
        import hashlib, base64
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        fernet_key = base64.urlsafe_b64encode(digest)
        return Fernet(fernet_key)

    # Fall back to key file
    if KEY_FILE.exists():
        stored_key = KEY_FILE.read_text().strip()
        return Fernet(stored_key.encode("utf-8"))

    raise RuntimeError(
        f"No vault key found. Set {_MASTER_KEY_ENV} env var or run `janus vault init`."
    )


def vault_init():
    """Initialize the vault, generating a key if needed."""
    _ensure_dirs()
    key = os.environ.get(_MASTER_KEY_ENV)
    if not key:
        # Generate a fresh Fernet key
        key = Fernet.generate_key().decode("utf-8")
        KEY_FILE.write_text(key + "\n")
        KEY_FILE.chmod(0o600)
    # Write empty vault
    fernet = _get_fernet()
    encrypted = fernet.encrypt(json.dumps({}).encode("utf-8"))
    VAULT_PATH.write_bytes(encrypted)
    VAULT_PATH.chmod(0o600)


def _load_vault() -> dict:
    if not VAULT_PATH.exists():
        return {}
    try:
        fernet = _get_fernet()
        data = fernet.decrypt(VAULT_PATH.read_bytes())
        return json.loads(data.decode("utf-8"))
    except Exception:
        return {}


def _save_vault(vault: dict):
    fernet = _get_fernet()
    encrypted = fernet.encrypt(json.dumps(vault).encode("utf-8"))
    VAULT_PATH.write_bytes(encrypted)
    VAULT_PATH.chmod(0o600)


def vault_store(key: str, value: dict):
    """Store a value in the vault."""
    vault = _load_vault()
    vault[key] = value
    _save_vault(vault)


def vault_get(key: str) -> dict | None:
    """Get a value from the vault."""
    vault = _load_vault()
    return vault.get(key)


def vault_has(key: str) -> bool:
    """Check if a key exists in the vault."""
    vault = _load_vault()
    return key in vault


def vault_remove(key: str):
    """Remove a key from the vault."""
    vault = _load_vault()
    vault.pop(key, None)
    _save_vault(vault)


def vault_list() -> list[str]:
    """List all keys in the vault."""
    vault = _load_vault()
    return list(vault.keys())
