import json
import os
import shutil

from .kernel import (
    build_compatible_extension,
    build_hashed_output_name,
    check_crypto,
    DEFAULT_ENCRYPTED_EXTENSION,
    FILE_MAGIC,
    decrypt_payload,
    encrypt_payload,
    format_compatible_token,
    pack_directory_to_zip_bytes,
    parse_compatible_token,
    require_security_profile,
    safe_extract_zip,
    unpack_file_payload,
)
from .security import SECURITY_STANDARD, SecurityProfile


def encrypt(
    plaintext: str,
    password: str,
    security: SecurityProfile = SECURITY_STANDARD,
) -> str:
    check_crypto()
    security = require_security_profile(security)
    token = encrypt_payload(plaintext.encode(), password, security=security)
    return token.decode("ascii")


def encrypt_file(
    file_path: str,
    password: str,
    output_path: str = None,
    security: SecurityProfile = SECURITY_STANDARD,
    compatible: bool = False,
) -> str:
    """
    Encrypt a file using a password.

    The encrypted payload stores the original filename (including extension)
    so it can be restored automatically when decrypting.
    """
    check_crypto()

    source_path = os.path.abspath(os.path.expanduser(file_path))
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"Input file not found: {source_path}")

    with open(source_path, "rb") as f:
        file_bytes = f.read()

    if output_path is None:
        source_dir = os.path.dirname(source_path)
        ext = build_compatible_extension() if compatible else DEFAULT_ENCRYPTED_EXTENSION
        base_name = build_hashed_output_name(file_bytes=file_bytes, ext=ext)
        output_path = os.path.join(source_dir, base_name)

    output_path = os.path.abspath(os.path.expanduser(output_path))

    metadata = {"filename": os.path.basename(source_path)}
    metadata_bytes = json.dumps(
        metadata, separators=(",", ":")).encode("utf-8")
    metadata_len = len(metadata_bytes).to_bytes(4, "big")

    payload = FILE_MAGIC + metadata_len + metadata_bytes + file_bytes
    security = require_security_profile(security)
    token = encrypt_payload(payload, password, security=security)

    if compatible:
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(format_compatible_token(token))
    else:
        with open(output_path, "wb") as f:
            f.write(token)

    return output_path


def encrypt_directory(
    directory_path: str,
    password: str,
    output_path: str = None,
    security: SecurityProfile = SECURITY_STANDARD,
    compatible: bool = False,
) -> str:
    """
    Encrypt a complete directory into a single encrypted file.

    The encrypted payload stores directory metadata and a zip archive of the
    directory contents, so it can be restored with ``decrypt_directory``.
    """
    check_crypto()

    source_dir = os.path.abspath(os.path.expanduser(directory_path))
    if not os.path.isdir(source_dir):
        raise FileNotFoundError(f"Input directory not found: {source_dir}")

    archive_bytes = pack_directory_to_zip_bytes(source_dir)

    if output_path is None:
        parent_dir = os.path.dirname(source_dir)
        ext = build_compatible_extension() if compatible else DEFAULT_ENCRYPTED_EXTENSION
        base_name = build_hashed_output_name(file_bytes=archive_bytes, ext=ext)
        output_path = os.path.join(parent_dir, base_name)

    output_path = os.path.abspath(os.path.expanduser(output_path))

    metadata = {"type": "directory",
                "dirname": os.path.basename(source_dir.rstrip("\\/"))}
    metadata_bytes = json.dumps(
        metadata, separators=(",", ":")).encode("utf-8")
    metadata_len = len(metadata_bytes).to_bytes(4, "big")
    payload = FILE_MAGIC + metadata_len + metadata_bytes + archive_bytes
    security = require_security_profile(security)
    token = encrypt_payload(payload, password, security=security)

    if compatible:
        with open(output_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(format_compatible_token(token))
    else:
        with open(output_path, "wb") as f:
            f.write(token)

    return output_path


def decrypt(encrypted_text: str, password: str) -> str:
    check_crypto()
    payload = decrypt_payload(encrypted_text.encode("ascii"), password)
    return payload.decode()


def decrypt_file(
    encrypted_file: str,
    password: str,
    output_path: str = None,
    overwrite: bool = False,
) -> str:
    """
    Decrypt a file previously encrypted with ``encrypt_file``.

    By default, it restores the original filename (including extension)
    in the encrypted file directory. If ``output_path`` is provided, it is
    treated as the full destination file path.
    """
    check_crypto()

    source_path = os.path.abspath(os.path.expanduser(encrypted_file))
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"Encrypted file not found: {source_path}")

    with open(source_path, "rb") as f:
        raw_token = f.read()
    token = parse_compatible_token(raw_token) or raw_token
    payload = decrypt_payload(token, password)

    metadata, file_bytes = unpack_file_payload(payload)
    if metadata.get("type") == "directory":
        raise ValueError(
            "Encrypted payload is a directory archive. "
            "Use decrypt_directory(...) instead."
        )
    original_filename = metadata.get("filename", "decrypted_file.bin")

    if output_path is None:
        destination_dir = os.path.dirname(source_path)
        output_path = os.path.join(destination_dir, original_filename)

    output_path = os.path.abspath(os.path.expanduser(output_path))
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if os.path.exists(output_path) and not overwrite:
        raise FileExistsError(
            f"Output file already exists: {output_path}. "
            "Set overwrite=True to overwrite it."
        )

    with open(output_path, "wb") as f:
        f.write(file_bytes)

    return output_path


def decrypt_directory(
    encrypted_file: str,
    password: str,
    output_path: str = None,
    overwrite: bool = False,
) -> str:
    """
    Decrypt a directory previously encrypted with ``encrypt_directory``.
    """
    check_crypto()

    source_path = os.path.abspath(os.path.expanduser(encrypted_file))
    if not os.path.isfile(source_path):
        raise FileNotFoundError(f"Encrypted file not found: {source_path}")

    with open(source_path, "rb") as f:
        raw_token = f.read()
    token = parse_compatible_token(raw_token) or raw_token
    payload = decrypt_payload(token, password)

    metadata, archive_bytes = unpack_file_payload(payload)

    if metadata.get("type") != "directory":
        raise ValueError("Encrypted payload is not a directory archive.")

    original_dirname = metadata.get("dirname", "decrypted_directory")
    if output_path is None:
        output_path = os.path.join(
            os.path.dirname(source_path), original_dirname)

    final_dir_path = os.path.abspath(os.path.expanduser(output_path))
    output_dir = os.path.dirname(final_dir_path)
    os.makedirs(output_dir, exist_ok=True)

    if os.path.exists(final_dir_path):
        if not overwrite:
            raise FileExistsError(
                f"Output directory already exists: {final_dir_path}. "
                "Set overwrite=True to overwrite it."
            )
        shutil.rmtree(final_dir_path)

    temp_extract_dir = os.path.join(
        output_dir, f".tmp_extract_{os.urandom(6).hex()}")
    os.makedirs(temp_extract_dir, exist_ok=True)

    try:
        safe_extract_zip(archive_bytes, temp_extract_dir)
        extracted_root = os.path.join(temp_extract_dir, original_dirname)
        if not os.path.isdir(extracted_root):
            raise ValueError("Invalid directory archive structure.")
        os.replace(extracted_root, final_dir_path)
    finally:
        if os.path.isdir(temp_extract_dir):
            shutil.rmtree(temp_extract_dir, ignore_errors=True)

    return final_dir_path
