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


def derive_key(password: bytes | bytearray, salt: bytes) -> bytes:
    """Derive a 256-bit key from a password using scrypt.

    password should be bytes or bytearray (not str) so the caller can
    zero sensitive material after use.
    """
    kdf = Scrypt(salt=salt, length=KEY_SIZE, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return kdf.derive(bytes(password))


def wipe(buf: bytearray):
    """Overwrite a bytearray with zeros. Best-effort secure erase."""
    for i in range(len(buf)):
        buf[i] = 0


def encrypt(data: bytes, password: bytes | bytearray,
            aad: bytes = None) -> tuple[bytes, bytes, bytes]:
    """Encrypt data with password. Returns (salt, nonce, ciphertext_with_tag).

    If aad (associated authenticated data) is provided, it is authenticated
    but not encrypted. The same aad must be passed to decrypt.
    """
    salt = os.urandom(SALT_SIZE)
    nonce = os.urandom(NONCE_SIZE)
    key = derive_key(password, salt)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, aad)
    return salt, nonce, ciphertext


def decrypt(salt: bytes, nonce: bytes, ciphertext: bytes,
            password: bytes | bytearray, aad: bytes = None) -> bytes:
    """Decrypt data with password. Raises InvalidTag on wrong password or tampered aad."""
    key = derive_key(password, salt)
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, aad)
