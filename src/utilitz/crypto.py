import base64
import os
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet


def _derive_key(password: str, salt: bytes) -> bytes:
    """
    Derive a symmetric encryption key from a password and salt using PBKDF2-HMAC-SHA256.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def encrypt(plaintext: str, password: str) -> str:
    """
    Encrypt a plaintext string using a password.

    A random salt is generated and prepended to the encrypted payload.
    The final result is base64-url encoded for safe storage or transport.
    """
    salt = os.urandom(16)  # must be stored along with the ciphertext
    key = _derive_key(password, salt)
    fernet = Fernet(key)

    ciphertext = fernet.encrypt(plaintext.encode())
    return base64.urlsafe_b64encode(salt + ciphertext).decode()


def decrypt(encrypted_text: str, password: str) -> str:
    """
    Decrypt a previously encrypted string using the same password.

    The salt is extracted from the encrypted payload to re-derive the key.
    """
    data = base64.urlsafe_b64decode(encrypted_text.encode())
    salt = data[:16]
    ciphertext = data[16:]

    key = _derive_key(password, salt)
    fernet = Fernet(key)

    return fernet.decrypt(ciphertext).decode()
