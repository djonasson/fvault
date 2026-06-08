"""Tests for vault.py — .vault file format and lifecycle."""

import json
import os
import struct

import pytest
from cryptography.exceptions import InvalidTag

import crypto
import vault
from tests.conftest import craft_vault_file


# ===========================================================================
# count_files
# ===========================================================================

class TestCountFiles:
    def test_empty_dir(self, tmp_path):
        assert vault.count_files(str(tmp_path)) == 0

    def test_with_files(self, tmp_path):
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "c.bin").write_bytes(b"\x00")
        assert vault.count_files(str(tmp_path)) == 3

    def test_nested(self, tmp_path):
        (tmp_path / "top.txt").write_text("t")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_text("d")
        assert vault.count_files(str(tmp_path)) == 2

    def test_excludes_pid_file(self, tmp_path):
        (tmp_path / "real.txt").write_text("data")
        (tmp_path / ".fvault.pid").write_text("12345")
        assert vault.count_files(str(tmp_path)) == 1

    def test_only_internal_files(self, tmp_path):
        (tmp_path / ".fvault.pid").write_text("12345")
        assert vault.count_files(str(tmp_path)) == 0


# ===========================================================================
# create_vault
# ===========================================================================

class TestCreateVault:
    def test_basic(self, sample_folder, vault_path, sample_password):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        assert vault_path.exists()
        assert vault_path.read_bytes()[:8] == vault.MAGIC

    def test_not_a_directory(self, tmp_path, sample_password):
        f = tmp_path / "file.txt"
        f.write_text("not a dir")
        with pytest.raises(ValueError, match="Not a directory"):
            vault.create_vault(str(f), str(tmp_path / "out.vault"), sample_password)

    def test_permissions(self, sample_folder, vault_path, sample_password):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        mode = os.stat(str(vault_path)).st_mode & 0o777
        assert mode == 0o600

    def test_header_structure(self, sample_folder, vault_path, sample_password):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)

        with open(str(vault_path), "rb") as f:
            magic = f.read(8)
            assert magic == vault.MAGIC

            salt = f.read(16)
            assert len(salt) == 16

            nonce = f.read(12)
            assert len(nonce) == 12

            meta_len = struct.unpack(">I", f.read(4))[0]
            assert meta_len > 0

            meta_bytes = f.read(meta_len)
            meta = json.loads(meta_bytes)
            assert meta["version"] == vault.CURRENT_VERSION
            assert "created" in meta
            assert "files_count" in meta
            assert "folder_name" in meta

    def test_empty_folder(self, tmp_path, sample_password):
        empty = tmp_path / "empty"
        empty.mkdir()
        vp = tmp_path / "empty.vault"
        vault.create_vault(str(empty), str(vp), sample_password)
        info = vault.get_vault_info(str(vp))
        assert info["files_count"] == 0


# ===========================================================================
# get_vault_info
# ===========================================================================

class TestGetVaultInfo:
    def test_basic(self, sample_folder, vault_path, sample_password):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        info = vault.get_vault_info(str(vault_path))
        assert "version" in info
        assert "created" in info
        assert "files_count" in info
        assert "folder_name" in info
        assert "file_size" in info

    def test_version(self, sample_folder, vault_path, sample_password):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        assert vault.get_vault_info(str(vault_path))["version"] == vault.CURRENT_VERSION

    def test_file_count(self, sample_folder, vault_path, sample_password):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        info = vault.get_vault_info(str(vault_path))
        assert info["files_count"] == 3  # hello.txt, data.bin, subdir/nested.txt

    def test_folder_name(self, sample_folder, vault_path, sample_password):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        info = vault.get_vault_info(str(vault_path))
        assert info["folder_name"] == "sample"

    def test_invalid_file(self, tmp_path):
        f = tmp_path / "notavault.bin"
        f.write_text("this is not a vault")
        with pytest.raises(ValueError, match="Not a valid vault file"):
            vault.get_vault_info(str(f))

    def test_truncated_file(self, tmp_path):
        f = tmp_path / "tiny.vault"
        f.write_bytes(b"\x00\x01\x02\x03")
        with pytest.raises(ValueError):
            vault.get_vault_info(str(f))


# ===========================================================================
# open_vault
# ===========================================================================

class TestOpenVault:
    def test_round_trip(self, sample_folder, vault_path, sample_password,
                        monkeypatch_temp_base):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        temp_dir = vault.open_vault(str(vault_path), sample_password)
        try:
            # Check files match
            assert (sample_folder / "hello.txt").read_text() == \
                open(os.path.join(temp_dir, "hello.txt")).read()
            assert (sample_folder / "data.bin").read_bytes() == \
                open(os.path.join(temp_dir, "data.bin"), "rb").read()
            assert (sample_folder / "subdir" / "nested.txt").read_text() == \
                open(os.path.join(temp_dir, "subdir", "nested.txt")).read()
        finally:
            vault.release_temp_dir(temp_dir)

    def test_wrong_password(self, sample_folder, vault_path, sample_password,
                            monkeypatch_temp_base):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        with pytest.raises(InvalidTag):
            vault.open_vault(str(vault_path), "wrong-password")

    def test_creates_temp_dir(self, sample_folder, vault_path, sample_password,
                              monkeypatch_temp_base):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        temp_dir = vault.open_vault(str(vault_path), sample_password)
        try:
            assert os.path.isdir(temp_dir)
        finally:
            vault.release_temp_dir(temp_dir)

    def test_temp_dir_has_pid_file(self, sample_folder, vault_path, sample_password,
                                   monkeypatch_temp_base):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        temp_dir = vault.open_vault(str(vault_path), sample_password)
        try:
            pidfile = os.path.join(temp_dir, ".fvault.pid")
            assert os.path.exists(pidfile)
            assert int(open(pidfile).read().strip()) == os.getpid()
        finally:
            vault.release_temp_dir(temp_dir)

    def test_temp_dir_tracked(self, sample_folder, vault_path, sample_password,
                              monkeypatch_temp_base):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        temp_dir = vault.open_vault(str(vault_path), sample_password)
        try:
            assert temp_dir in vault._active_temp_dirs
        finally:
            vault.release_temp_dir(temp_dir)

    def test_preserves_nested_structure(self, tmp_path, sample_password,
                                       monkeypatch_temp_base):
        folder = tmp_path / "deep"
        folder.mkdir()
        (folder / "a").mkdir()
        (folder / "a" / "b").mkdir()
        (folder / "a" / "b" / "file.txt").write_text("deep")

        vp = tmp_path / "deep.vault"
        vault.create_vault(str(folder), str(vp), sample_password)
        temp_dir = vault.open_vault(str(vp), sample_password)
        try:
            assert open(os.path.join(temp_dir, "a", "b", "file.txt")).read() == "deep"
        finally:
            vault.release_temp_dir(temp_dir)

    def test_preserves_binary_content(self, tmp_path, sample_password,
                                      monkeypatch_temp_base):
        folder = tmp_path / "bintest"
        folder.mkdir()
        data = os.urandom(4096)
        (folder / "random.bin").write_bytes(data)

        vp = tmp_path / "bin.vault"
        vault.create_vault(str(folder), str(vp), sample_password)
        temp_dir = vault.open_vault(str(vp), sample_password)
        try:
            assert open(os.path.join(temp_dir, "random.bin"), "rb").read() == data
        finally:
            vault.release_temp_dir(temp_dir)

    def test_incompatible_old_version(self, tmp_path, sample_password,
                                      monkeypatch_temp_base):
        vp = tmp_path / "old.vault"
        craft_vault_file(vp, password=sample_password,
                         metadata_override={"version": 1})
        with pytest.raises(vault.IncompatibleVaultError, match="format version 1"):
            vault.open_vault(str(vp), sample_password)

    def test_incompatible_future_version(self, tmp_path, sample_password,
                                         monkeypatch_temp_base):
        vp = tmp_path / "future.vault"
        craft_vault_file(vp, password=sample_password,
                         metadata_override={"version": 99})
        with pytest.raises(vault.IncompatibleVaultError, match="newer format"):
            vault.open_vault(str(vp), sample_password)

    def test_corrupted_magic(self, tmp_path, sample_password, monkeypatch_temp_base):
        vp = tmp_path / "badmagic.vault"
        craft_vault_file(vp, password=sample_password, magic=b"BADBAD\x00\x00")
        with pytest.raises(ValueError, match="Not a valid vault file"):
            vault.open_vault(str(vp), sample_password)

    def test_corrupted_metadata_length(self, tmp_path, sample_password,
                                       monkeypatch_temp_base):
        vp = tmp_path / "bigmeta.vault"
        craft_vault_file(vp, password=sample_password,
                         meta_len_override=vault.META_MAX_SIZE + 1)
        with pytest.raises(ValueError, match="Metadata too large"):
            vault.get_vault_info(str(vp))


# ===========================================================================
# save_vault
# ===========================================================================

class TestSaveVault:
    def test_after_modification(self, sample_folder, vault_path, sample_password,
                                monkeypatch_temp_base):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        temp_dir = vault.open_vault(str(vault_path), sample_password)
        try:
            # Add a new file
            with open(os.path.join(temp_dir, "new.txt"), "w") as f:
                f.write("added after open")
            vault.save_vault(temp_dir, str(vault_path), sample_password)
        finally:
            vault.release_temp_dir(temp_dir)

        # Reopen and verify
        temp_dir2 = vault.open_vault(str(vault_path), sample_password)
        try:
            assert open(os.path.join(temp_dir2, "new.txt")).read() == "added after open"
        finally:
            vault.release_temp_dir(temp_dir2)

    def test_preserves_created_date(self, sample_folder, vault_path, sample_password,
                                    monkeypatch_temp_base):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        original_created = vault.get_vault_info(str(vault_path))["created"]

        temp_dir = vault.open_vault(str(vault_path), sample_password)
        try:
            vault.save_vault(temp_dir, str(vault_path), sample_password)
        finally:
            vault.release_temp_dir(temp_dir)

        assert vault.get_vault_info(str(vault_path))["created"] == original_created

    def test_updates_modified_date(self, sample_folder, vault_path, sample_password,
                                   monkeypatch_temp_base):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        # create_vault doesn't set "modified"
        assert "modified" not in vault.get_vault_info(str(vault_path)) or \
            vault.get_vault_info(str(vault_path)).get("modified") is None

        temp_dir = vault.open_vault(str(vault_path), sample_password)
        try:
            vault.save_vault(temp_dir, str(vault_path), sample_password)
        finally:
            vault.release_temp_dir(temp_dir)

        info = vault.get_vault_info(str(vault_path))
        assert "modified" in info
        assert info["modified"] is not None

    def test_updates_file_count(self, sample_folder, vault_path, sample_password,
                                monkeypatch_temp_base):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        assert vault.get_vault_info(str(vault_path))["files_count"] == 3

        temp_dir = vault.open_vault(str(vault_path), sample_password)
        try:
            with open(os.path.join(temp_dir, "extra1.txt"), "w") as f:
                f.write("extra")
            with open(os.path.join(temp_dir, "extra2.txt"), "w") as f:
                f.write("extra")
            vault.save_vault(temp_dir, str(vault_path), sample_password)
        finally:
            vault.release_temp_dir(temp_dir)

        assert vault.get_vault_info(str(vault_path))["files_count"] == 5

    def test_no_tmp_file_remains(self, sample_folder, vault_path, sample_password,
                                 monkeypatch_temp_base):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        temp_dir = vault.open_vault(str(vault_path), sample_password)
        try:
            vault.save_vault(temp_dir, str(vault_path), sample_password)
        finally:
            vault.release_temp_dir(temp_dir)

        tmp_file = str(vault_path) + ".tmp"
        assert not os.path.exists(tmp_file)

    def test_pid_file_not_in_saved_vault(self, sample_folder, vault_path,
                                         sample_password, monkeypatch_temp_base):
        """Verify .fvault.pid is not stored in the encrypted vault payload."""
        import io
        import tarfile

        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        temp_dir = vault.open_vault(str(vault_path), sample_password)
        try:
            assert os.path.exists(os.path.join(temp_dir, ".fvault.pid"))
            vault.save_vault(temp_dir, str(vault_path), sample_password)
        finally:
            vault.release_temp_dir(temp_dir)

        # Decrypt the vault payload and inspect the tar contents directly
        with open(str(vault_path), "rb") as f:
            salt, nonce, meta_bytes = vault._read_header(f)
            ciphertext = f.read()

        pw_buf = bytearray(sample_password.encode("utf-8"))
        tar_data = crypto.decrypt(salt, nonce, ciphertext, pw_buf, aad=meta_bytes)
        crypto.wipe(pw_buf)

        buf = io.BytesIO(tar_data)
        with tarfile.open(fileobj=buf, mode="r:gz") as tar:
            names = tar.getnames()

        assert ".fvault.pid" not in names


# ===========================================================================
# Full round-trip integration
# ===========================================================================

class TestFullRoundTrip:
    def test_create_open_modify_save_reopen(self, sample_folder, vault_path,
                                            sample_password, monkeypatch_temp_base):
        # Create
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)

        # Open and verify original contents
        temp_dir = vault.open_vault(str(vault_path), sample_password)
        try:
            assert os.path.exists(os.path.join(temp_dir, "hello.txt"))
            assert os.path.exists(os.path.join(temp_dir, "data.bin"))
            assert os.path.exists(os.path.join(temp_dir, "subdir", "nested.txt"))

            # Add a file
            with open(os.path.join(temp_dir, "added.txt"), "w") as f:
                f.write("new content")

            # Delete a file
            os.remove(os.path.join(temp_dir, "hello.txt"))

            # Save
            vault.save_vault(temp_dir, str(vault_path), sample_password)
        finally:
            vault.release_temp_dir(temp_dir)

        # Reopen and verify modifications persisted
        temp_dir2 = vault.open_vault(str(vault_path), sample_password)
        try:
            assert not os.path.exists(os.path.join(temp_dir2, "hello.txt"))
            assert open(os.path.join(temp_dir2, "added.txt")).read() == "new content"
            assert os.path.exists(os.path.join(temp_dir2, "data.bin"))
            assert os.path.exists(os.path.join(temp_dir2, "subdir", "nested.txt"))
        finally:
            vault.release_temp_dir(temp_dir2)


# ===========================================================================
# Temp dir management
# ===========================================================================

class TestTempDirManagement:
    def test_release_temp_dir(self, sample_folder, vault_path, sample_password,
                              monkeypatch_temp_base):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        temp_dir = vault.open_vault(str(vault_path), sample_password)
        assert os.path.isdir(temp_dir)
        assert temp_dir in vault._active_temp_dirs

        vault.release_temp_dir(temp_dir)
        assert not os.path.exists(temp_dir)
        assert temp_dir not in vault._active_temp_dirs

    def test_release_temp_dir_none(self):
        """release_temp_dir(None) should not raise."""
        vault.release_temp_dir(None)

    def test_release_temp_dir_already_gone(self, tmp_path, monkeypatch_temp_base):
        """release_temp_dir on a non-existent path should not raise."""
        vault.release_temp_dir(str(tmp_path / "nonexistent"))

    def test_cleanup_active_temp_dirs(self, sample_folder, vault_path,
                                      sample_password, monkeypatch_temp_base):
        vault.create_vault(str(sample_folder), str(vault_path), sample_password)
        td1 = vault.open_vault(str(vault_path), sample_password)
        td2 = vault.open_vault(str(vault_path), sample_password)
        assert os.path.isdir(td1)
        assert os.path.isdir(td2)

        vault.cleanup_active_temp_dirs()
        assert not os.path.exists(td1)
        assert not os.path.exists(td2)
        assert len(vault._active_temp_dirs) == 0

    def test_cleanup_stale_removes_dead_pid(self, monkeypatch_temp_base):
        stale_dir = os.path.join(monkeypatch_temp_base, "fvault-stale")
        os.makedirs(stale_dir)
        with open(os.path.join(stale_dir, ".fvault.pid"), "w") as f:
            f.write("999999999")  # non-existent PID

        vault.cleanup_stale_temp_dirs()
        assert not os.path.exists(stale_dir)

    def test_cleanup_stale_keeps_live_pid(self, monkeypatch_temp_base):
        live_dir = os.path.join(monkeypatch_temp_base, "fvault-live")
        os.makedirs(live_dir)
        with open(os.path.join(live_dir, ".fvault.pid"), "w") as f:
            f.write(str(os.getpid()))  # current process — alive

        vault.cleanup_stale_temp_dirs()
        assert os.path.exists(live_dir)

        # Cleanup after test
        import shutil
        shutil.rmtree(live_dir)

    def test_cleanup_stale_removes_no_pidfile(self, monkeypatch_temp_base):
        orphan_dir = os.path.join(monkeypatch_temp_base, "fvault-orphan")
        os.makedirs(orphan_dir)
        # No .fvault.pid file

        vault.cleanup_stale_temp_dirs()
        assert not os.path.exists(orphan_dir)


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    def test_unicode_filenames(self, tmp_path, sample_password, monkeypatch_temp_base):
        folder = tmp_path / "unicode"
        folder.mkdir()
        (folder / "caf\u00e9.txt").write_text("coffee")
        (folder / "data_\u00e4\u00f6\u00fc.bin").write_bytes(b"\x00")

        vp = tmp_path / "unicode.vault"
        vault.create_vault(str(folder), str(vp), sample_password)
        temp_dir = vault.open_vault(str(vp), sample_password)
        try:
            assert open(os.path.join(temp_dir, "caf\u00e9.txt")).read() == "coffee"
            assert os.path.exists(os.path.join(temp_dir, "data_\u00e4\u00f6\u00fc.bin"))
        finally:
            vault.release_temp_dir(temp_dir)

    def test_long_filename(self, tmp_path, sample_password, monkeypatch_temp_base):
        folder = tmp_path / "longname"
        folder.mkdir()
        long_name = "a" * 200 + ".txt"
        (folder / long_name).write_text("long")

        vp = tmp_path / "long.vault"
        vault.create_vault(str(folder), str(vp), sample_password)
        temp_dir = vault.open_vault(str(vp), sample_password)
        try:
            assert open(os.path.join(temp_dir, long_name)).read() == "long"
        finally:
            vault.release_temp_dir(temp_dir)

    def test_deeply_nested(self, tmp_path, sample_password, monkeypatch_temp_base):
        folder = tmp_path / "deepnest"
        folder.mkdir()
        current = folder
        for i in range(10):
            current = current / f"level{i}"
            current.mkdir()
        (current / "bottom.txt").write_text("found it")

        vp = tmp_path / "deep.vault"
        vault.create_vault(str(folder), str(vp), sample_password)
        temp_dir = vault.open_vault(str(vp), sample_password)
        try:
            deep_path = os.path.join(temp_dir, *[f"level{i}" for i in range(10)], "bottom.txt")
            assert open(deep_path).read() == "found it"
        finally:
            vault.release_temp_dir(temp_dir)

    def test_empty_vault_round_trip(self, tmp_path, sample_password,
                                    monkeypatch_temp_base):
        folder = tmp_path / "empty"
        folder.mkdir()

        vp = tmp_path / "empty.vault"
        vault.create_vault(str(folder), str(vp), sample_password)
        temp_dir = vault.open_vault(str(vp), sample_password)
        try:
            # Only the PID file should be present
            entries = [e for e in os.listdir(temp_dir) if e not in vault._INTERNAL_FILES]
            assert entries == []
        finally:
            vault.release_temp_dir(temp_dir)

    def test_folder_name_removesuffix(self, sample_folder, tmp_path, sample_password,
                                      monkeypatch_temp_base):
        """Verify folder_name in metadata uses removesuffix, not replace."""
        vp = tmp_path / "my.vault.backup.vault"
        vault.create_vault(str(sample_folder), str(vp), sample_password)

        temp_dir = vault.open_vault(str(vp), sample_password)
        try:
            vault.save_vault(temp_dir, str(vp), sample_password)
        finally:
            vault.release_temp_dir(temp_dir)

        info = vault.get_vault_info(str(vp))
        assert info["folder_name"] == "my.vault.backup"
