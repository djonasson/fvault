"""AES-256-GCM encryption/decryption with scrypt key derivation."""

import os
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


SCRYPT_N = 2**20
SCRYPT_R = 8
SCRYPT_P = 1
SALT_SIZE = 16
NONCE_SIZE = 12
KEY_SIZE = 32


def derive_key(password: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=KEY_SIZE, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return kdf.derive(password.encode("utf-8"))


def encrypt(data: bytes, password: str) -> tuple[bytes, bytes, bytes]:
    """Encrypt data with password. Returns (salt, nonce, ciphertext_with_tag)."""
    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    key = derive_key(password, salt)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return salt, nonce, ciphertext


def decrypt(salt: bytes, nonce: bytes, ciphertext: bytes, password: str) -> bytes:
    """Decrypt data with password. Raises InvalidTag on wrong password."""
    key = derive_key(password, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)
