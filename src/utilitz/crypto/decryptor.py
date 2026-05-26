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

from . import _utils
from ._utils import (
    CRYPT_MAGIC,
    DOCUMENT_MAGIC,
    KEY_VARNAME,
    resolve_password,
    validate_key_env_varname,
)

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


def _merge_tree(source_dir: str, destination_dir: str) -> None:
    source_dir = os.path.abspath(source_dir)
    destination_dir = os.path.abspath(destination_dir)

    for entry in os.scandir(source_dir):
        source_path = entry.path
        destination_path = os.path.join(destination_dir, entry.name)

        if entry.is_dir(follow_symlinks=False):
            os.makedirs(destination_path, exist_ok=True)
            _merge_tree(source_path, destination_path)
            continue

        parent_dir = os.path.dirname(destination_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        shutil.copy2(source_path, destination_path)


def _contains_single_root(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        root_names = {
            Path(member.filename).parts[0]
            for member in zf.infolist()
            if member.filename and not member.filename.startswith("__MACOSX/")
        }
    return next(iter(sorted(root_names)), "decrypted_directory")


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
        self.key_env_varname = KEY_VARNAME

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

    def set_key_varname(self, name: str) -> "Decryptor":
        self.key_env_varname = validate_key_env_varname(name)
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
        password: str | None = None,
    ) -> "Decryptor":
        if self.content is None:
            raise ValueError("No encrypted content has been set.")
        password = resolve_password(password, self.key_env_varname)
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
            if len(parts) != 4 or parts[0] != CRYPT_MAGIC:
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
            document_header, document_content = _unpack_document_payload(
                decrypted_payload
            )
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

    def to_clipboard(self, encoding: str | None = None) -> str:
        """
        Copy the decrypted content to the system clipboard as text.
        """
        return _utils.copy_text_to_clipboard(self.to_string(encoding=encoding))

    def to_file(
        self,
        file_path: str | None = None,
        *,
        create_parent: bool = False,
        overwrite: bool = False,
    ) -> str:
        """Restore the decrypted payload as a file.

        If ``file_path`` is a directory, the stored filename is appended.
        Set ``create_parent=True`` to create missing parent directories.
        """
        if self.decrypted_content is None:
            raise ValueError("No decrypted content has been generated.")

        if file_path is None:
            filename = self.metadata.get("filename")
            if not filename:
                raise ValueError(
                    "No filename was stored in the decrypted metadata. "
                    "Provide file_path explicitly."
                )
            file_path = filename

        path = os.path.abspath(os.path.expanduser(file_path))
        if os.path.isdir(path):
            filename = self.metadata.get("filename")
            if not filename:
                raise ValueError(
                    "No filename was stored in the decrypted metadata. "
                    "Provide file_path explicitly."
                )
            path = os.path.join(path, filename)
        parent_dir = os.path.dirname(path)
        if parent_dir and not os.path.isdir(parent_dir):
            if not create_parent:
                raise FileNotFoundError(
                    f"Parent directory does not exist: {parent_dir}. "
                    "Set create_parent=True to create it."
                )
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
        exact_path: bool = False,
        create_parent: bool = False,
        overwrite: bool = False,
    ) -> str:
        """Restore the decrypted payload as a directory.

        By default, ``output_path`` acts as the container for the restored
        root folder. Set ``exact_path=True`` to treat it as the final folder
        path, and ``create_parent=True`` to create missing parent directories.
        """
        if self.decrypted_content is None:
            raise ValueError("No decrypted content has been generated.")
        if self.kind != "directory":
            raise ValueError("The decrypted content is not a directory archive.")

        try:
            root_name = _contains_single_root(self.decrypted_content)
        except zipfile.BadZipFile as exc:
            raise ValueError("Invalid directory archive.") from exc

        if output_path is None:
            output_path = root_name

        if exact_path:
            final_dir_path = os.path.abspath(os.path.expanduser(output_path))
        else:
            final_dir_path = os.path.abspath(
                os.path.expanduser(os.path.join(output_path, root_name))
            )

        parent_dir = os.path.dirname(final_dir_path)
        if parent_dir and not os.path.isdir(parent_dir):
            if not create_parent:
                raise FileNotFoundError(
                    f"Parent directory does not exist: {parent_dir}. "
                    "Set create_parent=True to create it."
                )
            os.makedirs(parent_dir, exist_ok=True)

        if os.path.exists(final_dir_path):
            if not overwrite:
                raise FileExistsError(
                    f"Output directory already exists: {final_dir_path}. "
                    "Set overwrite=True to overwrite it."
                )
            if not os.path.isdir(final_dir_path):
                raise NotADirectoryError(
                    f"Output path exists and is not a directory: {final_dir_path}"
                )
        else:
            os.makedirs(final_dir_path, exist_ok=True)

        temp_extract_dir = tempfile.mkdtemp(prefix=".tmp_extract_")
        try:
            _safe_extract_zip(self.decrypted_content, temp_extract_dir)

            extracted_root = os.path.join(temp_extract_dir, root_name)
            if not os.path.isdir(extracted_root):
                raise ValueError("Invalid directory archive structure.")
            _merge_tree(extracted_root, final_dir_path)
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
        content_part = "none" if self.content is None else f"{len(self.content)} bytes"
        decrypted_part = (
            "none"
            if self.decrypted_content is None
            else f"{len(self.decrypted_content)} bytes"
        )
        metadata_keys = ", ".join(sorted(self.metadata)) or "none"
        return (
            "Decryptor\n"
            f"  has_content: {self.has_content}\n"
            f"  content: {content_part}\n"
            f"  has_decrypted_content: {self.has_decrypted_content}\n"
            f"  decrypted_content: {decrypted_part}\n"
            f"  kind: {self.kind}\n"
            f"  metadata keys: {metadata_keys}\n"
            f"  key_env_varname: {self.key_env_varname}"
        )

    def __repr__(self) -> str:
        return (
            f"Decryptor(has_content={self.has_content}, "
            f"has_decrypted_content={self.has_decrypted_content}, kind={self.kind!r})"
        )
