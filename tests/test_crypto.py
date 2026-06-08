"""Tests for crypto.py — AES-256-GCM encryption with scrypt key derivation."""

import os

import pytest
from cryptography.exceptions import InvalidTag

import crypto


class TestDeriveKey:
    def test_deterministic(self):
        salt = b"\x00" * 16
        key1 = crypto.derive_key(b"password", salt)
        key2 = crypto.derive_key(b"password", salt)
        assert key1 == key2

    def test_different_salts(self):
        key1 = crypto.derive_key(b"password", b"\x00" * 16)
        key2 = crypto.derive_key(b"password", b"\x01" * 16)
        assert key1 != key2

    def test_different_passwords(self):
        salt = b"\x00" * 16
        key1 = crypto.derive_key(b"alpha", salt)
        key2 = crypto.derive_key(b"bravo", salt)
        assert key1 != key2

    def test_length(self):
        key = crypto.derive_key(b"password", os.urandom(16))
        assert len(key) == crypto.KEY_SIZE == 32

    def test_accepts_bytearray(self):
        key = crypto.derive_key(bytearray(b"password"), b"\x00" * 16)
        assert len(key) == 32

    def test_production_scrypt_n(self):
        """Verify the production default is 2**20 (patched to 2**14 in tests)."""
        import importlib
        import types
        # Read the source file directly to check the default value
        src = open(crypto.__file__).read()
        assert "SCRYPT_N = 2**20" in src


class TestWipe:
    def test_zeros_buffer(self):
        buf = bytearray(b"secret-data-123")
        crypto.wipe(buf)
        assert buf == bytearray(len(b"secret-data-123"))

    def test_empty_buffer(self):
        buf = bytearray(b"")
        crypto.wipe(buf)  # should not raise
        assert buf == bytearray(b"")


class TestEncrypt:
    def test_returns_triple(self):
        salt, nonce, ct = crypto.encrypt(b"data", b"password")
        assert isinstance(salt, bytes)
        assert isinstance(nonce, bytes)
        assert isinstance(ct, bytes)

    def test_salt_size(self):
        salt, _, _ = crypto.encrypt(b"data", b"password")
        assert len(salt) == crypto.SALT_SIZE == 16

    def test_nonce_size(self):
        _, nonce, _ = crypto.encrypt(b"data", b"password")
        assert len(nonce) == crypto.NONCE_SIZE == 12

    def test_ciphertext_includes_tag(self):
        data = b"hello world"
        _, _, ct = crypto.encrypt(data, b"password")
        assert len(ct) == len(data) + 16  # 16-byte GCM auth tag

    def test_nondeterministic(self):
        s1, n1, c1 = crypto.encrypt(b"data", b"password")
        s2, n2, c2 = crypto.encrypt(b"data", b"password")
        # Salt and nonce should differ (random)
        assert s1 != s2 or n1 != n2

    def test_empty_data(self):
        salt, nonce, ct = crypto.encrypt(b"", b"password")
        assert len(ct) == 16  # just the GCM tag

    def test_large_data(self):
        data = os.urandom(1024 * 1024)  # 1 MB
        salt, nonce, ct = crypto.encrypt(data, b"password")
        assert len(ct) == len(data) + 16


class TestDecrypt:
    def test_round_trip(self):
        data = b"hello, fvault!"
        pw = b"password"
        salt, nonce, ct = crypto.encrypt(data, pw)
        result = crypto.decrypt(salt, nonce, ct, pw)
        assert result == data

    def test_round_trip_with_aad(self):
        data = b"secret payload"
        pw = b"password"
        aad = b"metadata-json"
        salt, nonce, ct = crypto.encrypt(data, pw, aad=aad)
        result = crypto.decrypt(salt, nonce, ct, pw, aad=aad)
        assert result == data

    def test_wrong_password(self):
        salt, nonce, ct = crypto.encrypt(b"data", b"correct")
        with pytest.raises(InvalidTag):
            crypto.decrypt(salt, nonce, ct, b"wrong")

    def test_tampered_ciphertext(self):
        salt, nonce, ct = crypto.encrypt(b"data", b"password")
        tampered = bytearray(ct)
        tampered[0] ^= 0xFF
        with pytest.raises(InvalidTag):
            crypto.decrypt(salt, nonce, bytes(tampered), b"password")

    def test_wrong_aad(self):
        salt, nonce, ct = crypto.encrypt(b"data", b"pw", aad=b"original")
        with pytest.raises(InvalidTag):
            crypto.decrypt(salt, nonce, ct, b"pw", aad=b"tampered")

    def test_missing_aad(self):
        salt, nonce, ct = crypto.encrypt(b"data", b"pw", aad=b"metadata")
        with pytest.raises(InvalidTag):
            crypto.decrypt(salt, nonce, ct, b"pw", aad=None)

    def test_empty_data_round_trip(self):
        salt, nonce, ct = crypto.encrypt(b"", b"password")
        assert crypto.decrypt(salt, nonce, ct, b"password") == b""

    def test_large_data_round_trip(self):
        data = os.urandom(1024 * 1024)
        pw = b"password"
        salt, nonce, ct = crypto.encrypt(data, pw)
        assert crypto.decrypt(salt, nonce, ct, pw) == data

    def test_bytearray_password(self):
        data = b"payload"
        pw = bytearray(b"password")
        salt, nonce, ct = crypto.encrypt(data, pw)
        result = crypto.decrypt(salt, nonce, ct, bytearray(b"password"))
        assert result == data
