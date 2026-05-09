from __future__ import annotations

import base64
import json
import os
from typing import Any

from .decryptor import Decryptor
from .input import CryptoInput
from .output import CryptoOutput

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


DOCUMENT_MAGIC = b"ITZ-DOC-V1"


def _check_crypto() -> None:
    if not HAS_CRYPTO:
        raise ImportError(
            "The 'cryptography' library is required for crypto utilities. "
            "Install it with: pip install utilitz[crypto]"
        )


def _build_document_payload(input: CryptoInput) -> bytes:
    metadata: dict[str, Any] = {}

    if input.kind == "file":
        filename = input.metadata.get("filename")
        if filename:
            metadata["filename"] = filename
    elif input.kind in {"text", "text-stream"}:
        metadata["encoding"] = input.metadata.get("encoding", "utf-8")
    elif input.kind == "value":
        metadata.update(input.metadata)

    header = {
        "kind": input.kind,
        "metadata": metadata,
    }
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
    return (
        DOCUMENT_MAGIC
        + len(header_bytes).to_bytes(4, "big")
        + header_bytes
        + input.to_bytes()
    )


class Encryptor:
    """
    State holder for encryption workflows.

    The class receives a ``CryptoInput`` and produces a ``CryptoOutput``.
    """

    def __init__(self, input: CryptoInput | None = None) -> None:
        self.input = input
        self.output: CryptoOutput | None = None

    @property
    def has_input(self) -> bool:
        return self.input is not None

    @property
    def has_output(self) -> bool:
        return self.output is not None

    def set_input(self, input: CryptoInput) -> "Encryptor":
        if not isinstance(input, CryptoInput):
            raise TypeError("input must be an instance of CryptoInput.")
        self.input = input
        return self

    def clear_input(self) -> "Encryptor":
        self.input = None
        return self

    @classmethod
    def from_string(
        cls,
        text: str,
        *,
        encoding: str = "utf-8",
    ) -> "Encryptor":
        return cls(
            CryptoInput.from_string(
                text,
                encoding=encoding,
            )
        )

    @classmethod
    def from_file(
        cls,
        file_path: str,
    ) -> "Encryptor":
        return cls(CryptoInput.from_file(file_path))

    @classmethod
    def from_directory(
        cls,
        directory_path: str,
        *,
        include_patterns: str | list[str] | tuple[str, ...] | None = None,
        exclude_patterns: str | list[str] | tuple[str, ...] | None = None,
    ) -> "Encryptor":
        return cls(
            CryptoInput.from_directory(
                directory_path,
                include_patterns=include_patterns,
                exclude_patterns=exclude_patterns,
            )
        )

    @classmethod
    def from_value(
        cls,
        value: Any,
    ) -> "Encryptor":
        return cls(CryptoInput.from_value(value))

    def encrypt(
        self,
        password: str,
        *,
        salt_size: int = 16,
        iterations: int = 100_000,
        key_length: int = 32,
        hash_name: str = "sha256",
    ) -> "Encryptor":
        if self.input is None:
            raise ValueError("No crypto input has been set.")
        if not isinstance(password, str) or not password:
            raise ValueError("password must be a non-empty string.")
        _check_crypto()
        if not isinstance(salt_size, int) or salt_size <= 0:
            raise ValueError("salt_size must be a positive integer.")
        if not isinstance(iterations, int) or iterations <= 0:
            raise ValueError("iterations must be a positive integer.")
        if not isinstance(key_length, int) or key_length <= 0:
            raise ValueError("key_length must be a positive integer.")
        if not isinstance(hash_name, str) or hash_name.strip().lower() != "sha256":
            raise ValueError("Only 'sha256' is supported for hash_name.")

        password_bytes = password.encode("utf-8")
        salt = None
        kdf = None
        key = None
        document_payload = None
        ciphertext = None
        config = None
        encrypted_content = None

        try:
            salt = os.urandom(salt_size)
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=key_length,
                salt=salt,
                iterations=iterations,
            )
            key = base64.urlsafe_b64encode(kdf.derive(password_bytes))
            document_payload = _build_document_payload(self.input)
            ciphertext = Fernet(key).encrypt(document_payload)

            config = json.dumps(
                {
                    "salt_size": salt_size,
                    "iterations": iterations,
                    "key_length": key_length,
                    "hash_name": "sha256",
                },
                separators=(",", ":"),
            ).encode("utf-8")

            encrypted_content = (
                b"ITZ-CRYPT-V1"
                + b":"
                + base64.urlsafe_b64encode(config)
                + b":"
                + base64.urlsafe_b64encode(salt)
                + b":"
                + base64.urlsafe_b64encode(ciphertext)
            )
            self.output = CryptoOutput.create(encrypted_content)
            return self
        finally:
            del password, password_bytes, salt, kdf, key, document_payload, ciphertext, config, encrypted_content

    def to_bytes(self) -> bytes:
        if self.output is None:
            raise ValueError("No encrypted output has been generated.")
        return self.output.to_bytes()

    def to_string(self, encoding: str = "utf-8") -> str:
        if self.output is None:
            raise ValueError("No encrypted output has been generated.")
        return self.output.to_string(encoding=encoding)

    def to_file(
        self,
        file_path: str,
        *,
        encoding: str = "utf-8",
        overwrite: bool = False,
        binary: bool = False,
    ) -> str:
        if self.output is None:
            raise ValueError("No encrypted output has been generated.")
        return self.output.to_file(
            file_path,
            encoding=encoding,
            overwrite=overwrite,
            binary=binary,
        )

    def to_decryptor(self) -> Decryptor:
        if self.output is None:
            raise ValueError("No encrypted output has been generated.")
        return Decryptor.from_bytes(self.output.to_bytes())

    def __repr__(self) -> str:
        return f"Encryptor(has_input={self.has_input}, has_output={self.has_output})"

    def __str__(self) -> str:
        state = "idle"
        if self.input is not None:
            state = "ready"
        if self.output is not None:
            state = f"{state}, encrypted"
        return f"Encryptor<{state}>"
