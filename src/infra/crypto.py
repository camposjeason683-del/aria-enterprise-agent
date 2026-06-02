"""
ARIA-OS: symmetric encryption for tenant secrets (WooCommerce credentials).

Uses Fernet (AES-128-CBC + HMAC-SHA256, from the already-installed `cryptography`
package) with a key in ARIA_ENCRYPTION_KEY. Credentials are encrypted before they
ever touch the database (tenant_integrations) and decrypted only when the sync
needs them — they are never stored or logged in plaintext.

Generate a key once:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# spec: specs/integrations/tenant-woocommerce.spec.md
"""
from __future__ import annotations

import os

from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    key = os.environ.get("ARIA_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("ARIA_ENCRYPTION_KEY is not configured")
    return Fernet(key.encode())


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    return _fernet().decrypt(ciphertext.encode()).decode()
