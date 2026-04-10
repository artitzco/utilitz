import base64
import binascii
import hashlib
import io
import json
import os
import zipfile

from .security import SecurityProfile

DEFAULT_OUTPUT_PREFIX = "-confidential-"
DEFAULT_ENCRYPTED_EXTENSION = ".asc"
DEFAULT_COMPATIBLE_EXTENSION = ".txt"

TOKEN_MAGIC = b"ITZ-TOKEN-V1"
FILE_MAGIC = b"ITZ-FILE-V1"
COMPAT_TOKEN_BEGIN = "-----BEGIN ITZ ENCRYPTED TOKEN-----"
COMPAT_TOKEN_END = "-----END ITZ ENCRYPTED TOKEN-----"
COMPAT_LINE_WIDTH = 76

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


def check_crypto() -> None:
    if not HAS_CRYPTO:
        raise ImportError(
            "The 'cryptography' library is required for crypto utilities. "
            "Install it with: pip install utilitz[crypto]"
        )


def require_security_profile(security) -> SecurityProfile:
    if not isinstance(security, SecurityProfile):
        raise TypeError("security must be an instance of SecurityProfile.")
    return security


def _get_hash_algorithm(hash_name: str):
    hash_key = hash_name.strip().lower()
    if hash_key == "sha256":
        return hashes.SHA256()
    raise ValueError(f"Unsupported kdf_hash '{hash_name}'.")


def _derive_key(password: str, salt: bytes, security: SecurityProfile) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=_get_hash_algorithm(security.kdf_hash),
        length=security.key_length,
        salt=salt,
        iterations=security.kdf_iterations,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def _serialize_security(security: SecurityProfile) -> bytes:
    return json.dumps(
        {
            "kdf_iterations": security.kdf_iterations,
            "salt_size": security.salt_size,
            "key_length": security.key_length,
            "kdf_hash": security.kdf_hash,
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _deserialize_security(data: bytes) -> SecurityProfile:
    metadata = json.loads(data.decode("utf-8"))
    return SecurityProfile(
        kdf_iterations=metadata["kdf_iterations"],
        salt_size=metadata["salt_size"],
        key_length=metadata["key_length"],
        kdf_hash=metadata["kdf_hash"],
    )


def encrypt_payload(payload: bytes, password: str, security: SecurityProfile) -> bytes:
    salt = os.urandom(security.salt_size)
    key = _derive_key(password, salt, security=security)
    fernet = Fernet(key)
    ciphertext = fernet.encrypt(payload)
    security_bytes = _serialize_security(security)
    return (
        TOKEN_MAGIC
        + b":"
        + base64.urlsafe_b64encode(security_bytes)
        + b":"
        + base64.urlsafe_b64encode(salt)
        + b":"
        + base64.urlsafe_b64encode(ciphertext)
    )


def decrypt_payload(token: bytes, password: str) -> bytes:
    if not token.startswith(TOKEN_MAGIC + b":"):
        raise ValueError("Invalid encrypted token format.")

    parts = token.split(b":", 3)
    if len(parts) != 4:
        raise ValueError("Invalid encrypted token format.")

    try:
        security = _deserialize_security(base64.urlsafe_b64decode(parts[1]))
    except (ValueError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid security metadata in encrypted token.") from exc

    salt = base64.urlsafe_b64decode(parts[2])
    ciphertext = base64.urlsafe_b64decode(parts[3])
    key = _derive_key(password, salt, security=security)
    fernet = Fernet(key)
    return fernet.decrypt(ciphertext)


def unpack_file_payload(payload: bytes) -> tuple[dict, bytes]:
    if not payload.startswith(FILE_MAGIC):
        raise ValueError("Invalid encrypted file format.")

    metadata_len_start = len(FILE_MAGIC)
    metadata_len_end = metadata_len_start + 4
    metadata_len = int.from_bytes(payload[metadata_len_start:metadata_len_end], "big")

    metadata_start = metadata_len_end
    metadata_end = metadata_start + metadata_len

    metadata_bytes = payload[metadata_start:metadata_end]
    content_bytes = payload[metadata_end:]

    return json.loads(metadata_bytes.decode("utf-8")), content_bytes


def build_hashed_output_name(
    file_bytes: bytes,
    prefix: str = DEFAULT_OUTPUT_PREFIX,
    ext: str = DEFAULT_ENCRYPTED_EXTENSION,
) -> str:
    digest = hashlib.sha256(file_bytes).hexdigest()[:24]
    return f"{prefix}{digest}{ext}"


def build_compatible_extension() -> str:
    return DEFAULT_ENCRYPTED_EXTENSION + DEFAULT_COMPATIBLE_EXTENSION


def format_compatible_token(token: bytes) -> str:
    token_b64 = base64.b64encode(token).decode("ascii")
    lines = [
        token_b64[i:i + COMPAT_LINE_WIDTH]
        for i in range(0, len(token_b64), COMPAT_LINE_WIDTH)
    ]
    return "\n".join([COMPAT_TOKEN_BEGIN, *lines, COMPAT_TOKEN_END, ""])


def parse_compatible_token(raw_bytes: bytes) -> bytes | None:
    if raw_bytes.startswith(TOKEN_MAGIC + b":"):
        return raw_bytes

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None

    stripped = text.strip()
    if not stripped:
        return None

    if stripped.startswith(COMPAT_TOKEN_BEGIN):
        if COMPAT_TOKEN_END not in stripped:
            return None
        body = stripped[len(COMPAT_TOKEN_BEGIN):]
        body = body.split(COMPAT_TOKEN_END, 1)[0]
        encoded = "".join(body.split())
    else:
        encoded = "".join(stripped.split())

    if not encoded:
        return None

    try:
        token = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None

    if not token.startswith(TOKEN_MAGIC + b":"):
        return None
    return token


def pack_directory_to_zip_bytes(directory_path: str) -> bytes:
    buffer = io.BytesIO()
    root_dir_name = os.path.basename(directory_path.rstrip("\\/"))

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for current_root, dirs, files in os.walk(directory_path):
            rel_root = os.path.relpath(current_root, directory_path)
            rel_root = "" if rel_root == "." else rel_root

            if not files and not dirs:
                zip_dir = f"{root_dir_name}/{rel_root}/" if rel_root else f"{root_dir_name}/"
                zf.writestr(zip_dir, b"")

            for filename in files:
                abs_file = os.path.join(current_root, filename)
                rel_file = os.path.join(rel_root, filename) if rel_root else filename
                arcname = os.path.join(root_dir_name, rel_file).replace("\\", "/")
                zf.write(abs_file, arcname)

    return buffer.getvalue()


def safe_extract_zip(zip_bytes: bytes, destination_dir: str) -> None:
    destination_dir = os.path.abspath(destination_dir)
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        for member in zf.infolist():
            member_path = os.path.abspath(os.path.join(destination_dir, member.filename))
            if not member_path.startswith(destination_dir + os.sep) and member_path != destination_dir:
                raise ValueError("Unsafe zip entry detected during extraction.")
        zf.extractall(destination_dir)
