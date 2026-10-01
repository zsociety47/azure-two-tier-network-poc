"""Local Secure Shell (SSH) key used by the virtual machines.

The private key stays in keys/ and is gitignored. Azure receives the public
key only.
"""

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from src.lib.config import ADMIN_USER
from src.lib.log import info

KEY_DIR = Path("keys")
PRIVATE_KEY = KEY_DIR / "id_ed25519"
PUBLIC_KEY = KEY_DIR / "id_ed25519.pub"


def load_or_create_public_key() -> str:
    """Return the OpenSSH public key, creating the key pair on first use."""
    if PRIVATE_KEY.exists() and PUBLIC_KEY.exists():
        info(f"Using existing public key {PUBLIC_KEY}")
        return PUBLIC_KEY.read_text(encoding="utf-8").strip()
    if PRIVATE_KEY.exists() or PUBLIC_KEY.exists():
        raise SystemExit(
            f"Found only one of {PRIVATE_KEY} and {PUBLIC_KEY}. "
            "Move that file aside and run again so a complete pair can be created."
        )

    key = ed25519.Ed25519PrivateKey.generate()
    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )
    public_line = public_bytes.decode("ascii").strip() + f" {ADMIN_USER}"

    KEY_DIR.mkdir(mode=0o700, exist_ok=True)
    PRIVATE_KEY.write_bytes(private_bytes)
    PRIVATE_KEY.chmod(0o600)
    PUBLIC_KEY.write_text(public_line + "\n", encoding="utf-8")
    PUBLIC_KEY.chmod(0o644)
    info(f"Created {PRIVATE_KEY}. It stays on this machine and is not committed.")
    return public_line
