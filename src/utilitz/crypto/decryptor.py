from __future__ import annotations

import base64
import io
import json
import os
import pickle
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


def _check_crypto() -> None:
    if not HAS_CRYPTO:
        raise ImportError(
            "The 'cryptography' library is required for crypto utilities. "
            "Install it with: pip install utilitz[crypto]"
        )


DOCUMENT_MAGIC = b"ITZ-DOC-V1"


def _unpack_document_payload(payload: bytes) -> tuple[dict[str, Any], bytes]:
    if not payload.startswith(DOCUMENT_MAGIC):
        raise ValueError("Invalid decrypted document format.")

    header_len_start = len(DOCUMENT_MAGIC)
    header_len_end = header_len_start + 4
    header_len = int.from_bytes(payload[header_len_start:header_len_end], "big")

    header_start = header_len_end
    header_end = header_start + header_len
    header_bytes = payload[header_start:header_end]
    content_bytes = payload[header_end:]

    try:
        header = json.loads(header_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid decrypted document metadata.") from exc

    if not isinstance(header, dict):
        raise ValueError("Invalid decrypted document metadata.")

    return header, content_bytes


def _safe_extract_zip(zip_bytes: bytes, destination_dir: str) -> None:
    destination_dir = os.path.abspath(destination_dir)
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        for member in zf.infolist():
            member_path = os.path.abspath(
                os.path.join(destination_dir, member.filename)
            )
            if (
                not member_path.startswith(destination_dir + os.sep)
                and member_path != destination_dir
            ):
                raise ValueError("Unsafe zip entry detected during extraction.")
        zf.extractall(destination_dir)


class Decryptor:
    """
    Minimal state holder for decryption workflows.

    This class mirrors the content-oriented output constructors and keeps the
    decrypted payload separate from the encrypted input.
    """

    def __init__(self, content: bytes | None = None) -> None:
        self.content = content
        self.decrypted_content: bytes | None = None
        self.kind: str | None = None
        self.metadata: dict[str, Any] = {}

    @property
    def has_content(self) -> bool:
        return self.content is not None

    @property
    def has_decrypted_content(self) -> bool:
        return self.decrypted_content is not None

    @property
    def has_kind(self) -> bool:
        return self.kind is not None

    def set_content(self, content: bytes) -> "Decryptor":
        if not isinstance(content, (bytes, bytearray, memoryview)):
            raise TypeError("content must be bytes-like.")
        self.content = bytes(content)
        self.decrypted_content = None
        self.kind = None
        self.metadata = {}
        return self

    def clear_content(self) -> "Decryptor":
        self.content = None
        self.decrypted_content = None
        self.kind = None
        self.metadata = {}
        return self

    def clear_decrypted_content(self) -> "Decryptor":
        self.decrypted_content = None
        self.kind = None
        self.metadata = {}
        return self

    @classmethod
    def from_bytes(cls, content: bytes) -> "Decryptor":
        if not isinstance(content, (bytes, bytearray, memoryview)):
            raise TypeError("content must be bytes-like.")
        return cls(bytes(content))

    @classmethod
    def from_string(
        cls,
        text: str,
        *,
        encoding: str = "utf-8",
    ) -> "Decryptor":
        if not isinstance(text, str):
            raise TypeError("text must be a string.")
        return cls(text.encode(encoding))

    @classmethod
    def from_file(cls, file_path: str) -> "Decryptor":
        path = os.path.abspath(os.path.expanduser(file_path))
        with open(path, "rb") as file_obj:
            return cls.from_bytes(file_obj.read())

    def decrypt(
        self,
        password: str,
    ) -> "Decryptor":
        if self.content is None:
            raise ValueError("No encrypted content has been set.")
        if not isinstance(password, str) or not password:
            raise ValueError("password must be a non-empty string.")
        _check_crypto()

        password_bytes = password.encode("utf-8")
        parts = None
        config = None
        salt = None
        ciphertext = None
        kdf = None
        key = None
        try:
            parts = self.content.split(b":", 3)
            if len(parts) != 4 or parts[0] != b"ITZ-CRYPT-V1":
                raise ValueError("Invalid encrypted output format.")

            try:
                config = json.loads(
                    base64.urlsafe_b64decode(parts[1]).decode("utf-8")
                )
            except (ValueError, KeyError, json.JSONDecodeError) as exc:
                raise ValueError("Invalid encryption metadata.") from exc

            if config.get("hash_name", "sha256").strip().lower() != "sha256":
                raise ValueError("Unsupported hash_name in encrypted output.")

            salt = base64.urlsafe_b64decode(parts[2])
            ciphertext = base64.urlsafe_b64decode(parts[3])

            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=int(config["key_length"]),
                salt=salt,
                iterations=int(config["iterations"]),
            )
            key = base64.urlsafe_b64encode(kdf.derive(password_bytes))
            decrypted_payload = Fernet(key).decrypt(ciphertext)
            document_header, document_content = _unpack_document_payload(decrypted_payload)
            self.kind = document_header.get("kind")
            metadata = document_header.get("metadata", {})
            self.metadata = metadata if isinstance(metadata, dict) else {}
            self.decrypted_content = document_content
            return self
        finally:
            del password, password_bytes, parts, config, salt, ciphertext, kdf, key

    def to_bytes(self) -> bytes:
        if self.decrypted_content is None:
            raise ValueError("No decrypted content has been generated.")
        return self.decrypted_content

    def to_string(self, encoding: str | None = None) -> str:
        if self.decrypted_content is None:
            raise ValueError("No decrypted content has been generated.")
        if encoding is None:
            encoding = self.metadata.get("encoding", "utf-8")
        return self.decrypted_content.decode(encoding)

    def to_file(
        self,
        file_path: str | None = None,
        *,
        overwrite: bool = False,
    ) -> str:
        if self.decrypted_content is None:
            raise ValueError("No decrypted content has been generated.")

        if file_path is None:
            filename = self.metadata.get("filename", "decrypted_file.bin")
            file_path = filename

        path = os.path.abspath(os.path.expanduser(file_path))
        parent_dir = os.path.dirname(path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        if os.path.exists(path) and not overwrite:
            raise FileExistsError(
                f"Output file already exists: {path}. "
                "Set overwrite=True to overwrite it."
            )

        with open(path, "wb") as file_obj:
            file_obj.write(self.decrypted_content)

        return path

    def to_directory(
        self,
        output_path: str | None = None,
        *,
        overwrite: bool = False,
    ) -> str:
        if self.decrypted_content is None:
            raise ValueError("No decrypted content has been generated.")
        if self.kind != "directory":
            raise ValueError("The decrypted content is not a directory archive.")

        try:
            with zipfile.ZipFile(io.BytesIO(self.decrypted_content), "r") as zf:
                root_names = {
                    Path(member.filename).parts[0]
                    for member in zf.infolist()
                    if member.filename and not member.filename.startswith("__MACOSX/")
                }
                root_name = next(iter(sorted(root_names)), "decrypted_directory")
        except zipfile.BadZipFile as exc:
            raise ValueError("Invalid directory archive.") from exc

        if output_path is None:
            output_path = root_name

        final_dir_path = os.path.abspath(os.path.expanduser(output_path))
        output_dir = os.path.dirname(final_dir_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        if os.path.exists(final_dir_path):
            if not overwrite:
                raise FileExistsError(
                    f"Output directory already exists: {final_dir_path}. "
                    "Set overwrite=True to overwrite it."
                )
            shutil.rmtree(final_dir_path)

        temp_extract_dir = tempfile.mkdtemp(prefix=".tmp_extract_")
        try:
            _safe_extract_zip(self.decrypted_content, temp_extract_dir)

            extracted_root = os.path.join(temp_extract_dir, root_name)
            if not os.path.isdir(extracted_root):
                raise ValueError("Invalid directory archive structure.")
            os.replace(extracted_root, final_dir_path)
        finally:
            if os.path.isdir(temp_extract_dir):
                shutil.rmtree(temp_extract_dir, ignore_errors=True)
        return final_dir_path

    def to_value(self) -> Any:
        if self.decrypted_content is None:
            raise ValueError("No decrypted content has been generated.")
        if self.kind != "value":
            raise ValueError("The decrypted content is not a Python value.")
        if self.metadata.get("serializer") != "pickle":
            raise ValueError("Unsupported value serializer.")
        return pickle.loads(self.decrypted_content)

    def __str__(self) -> str:
        state = "idle" if self.content is None else "ready"
        if self.decrypted_content is not None:
            state = f"{state}, decrypted"
        return f"Decryptor<{state}>"

    def __repr__(self) -> str:
        if self.content is None and self.decrypted_content is None:
            return "Decryptor(content=None, decrypted_content=None)"
        content_part = "None" if self.content is None else f"{len(self.content)} bytes"
        decrypted_part = (
            "None"
            if self.decrypted_content is None
            else f"{len(self.decrypted_content)} bytes"
        )
        return (
            f"Decryptor(content={content_part}, "
            f"decrypted_content={decrypted_part}, "
            f"kind={self.kind!r})"
        )
