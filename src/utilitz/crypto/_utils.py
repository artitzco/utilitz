from __future__ import annotations

import os

try:
    import pyperclip

    HAS_CLIPBOARD = True
except ImportError:
    pyperclip = None
    HAS_CLIPBOARD = False


KEY_VARNAME = "UTILITZ_CRYPTO_KEY"
CRYPT_MAGIC = b"ITZ-CRYPT-V1"
DOCUMENT_MAGIC = b"ITZ-DOC-V1"


def validate_key_env_varname(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("key_env_varname must be a non-empty string.")
    return name.strip()


def resolve_password(password: str | None, key_env_varname: str) -> str:
    if password is None:
        password = os.environ.get(key_env_varname)

    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string.")

    return password


def copy_text_to_clipboard(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a string.")

    if not HAS_CLIPBOARD:
        raise RuntimeError(
            "Clipboard support requires pyperclip. "
            "Install it with: pip install utilitz[crypto]"
        )

    try:
        pyperclip.copy(text)
    except pyperclip.PyperclipException as exc:
        raise RuntimeError(
            "Clipboard support is not available in this environment."
        ) from exc

    return text
