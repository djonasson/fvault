"""Tests for config.py — recent vaults list persistence."""

import json
import os
import stat

import pytest

import config


# All tests use monkeypatch_config_dir to avoid touching ~/.config/fvault/
pytestmark = pytest.mark.usefixtures("monkeypatch_config_dir")


class TestGetRecentVaults:
    def test_empty_when_no_file(self):
        assert config.get_recent_vaults() == []

    def test_empty_after_fresh_init(self):
        # Force a save/load cycle
        config.add_recent_vault("/tmp/test.vault")
        config.remove_recent_vault("/tmp/test.vault")
        assert config.get_recent_vaults() == []


class TestAddRecentVault:
    def test_add_one(self, tmp_path):
        path = str(tmp_path / "one.vault")
        config.add_recent_vault(path)
        assert config.get_recent_vaults() == [path]

    def test_deduplication(self, tmp_path):
        path = str(tmp_path / "dup.vault")
        config.add_recent_vault(path)
        config.add_recent_vault(path)
        recents = config.get_recent_vaults()
        assert recents.count(path) == 1

    def test_ordering(self, tmp_path):
        p1 = str(tmp_path / "first.vault")
        p2 = str(tmp_path / "second.vault")
        config.add_recent_vault(p1)
        config.add_recent_vault(p2)
        recents = config.get_recent_vaults()
        assert recents[0] == p2  # most recent first
        assert recents[1] == p1

    def test_re_add_moves_to_front(self, tmp_path):
        p1 = str(tmp_path / "first.vault")
        p2 = str(tmp_path / "second.vault")
        config.add_recent_vault(p1)
        config.add_recent_vault(p2)
        config.add_recent_vault(p1)  # re-add first
        recents = config.get_recent_vaults()
        assert recents[0] == p1
        assert len(recents) == 2

    def test_max_limit(self, tmp_path):
        for i in range(25):
            config.add_recent_vault(str(tmp_path / f"vault_{i:02d}.vault"))
        recents = config.get_recent_vaults()
        assert len(recents) == config.MAX_RECENT == 20

    def test_stores_absolute_path(self, monkeypatch, tmp_path):
        # Even if we pass something, os.path.abspath will resolve it
        config.add_recent_vault("relative/path.vault")
        recents = config.get_recent_vaults()
        assert len(recents) == 1
        assert os.path.isabs(recents[0])


class TestRemoveRecentVault:
    def test_remove(self, tmp_path):
        path = str(tmp_path / "remove.vault")
        config.add_recent_vault(path)
        config.remove_recent_vault(path)
        assert path not in config.get_recent_vaults()

    def test_remove_not_present(self):
        # Should not raise
        config.remove_recent_vault("/nonexistent/vault.vault")


class TestRenameRecentVault:
    def test_rename(self, tmp_path):
        old = str(tmp_path / "old.vault")
        new = str(tmp_path / "new.vault")
        config.add_recent_vault(old)
        config.rename_recent_vault(old, new)
        recents = config.get_recent_vaults()
        assert new in recents
        assert old not in recents

    def test_rename_preserves_position(self, tmp_path):
        p1 = str(tmp_path / "first.vault")
        p2 = str(tmp_path / "second.vault")
        p3 = str(tmp_path / "third.vault")
        config.add_recent_vault(p1)
        config.add_recent_vault(p2)
        config.add_recent_vault(p3)
        # Order: p3, p2, p1

        new_p2 = str(tmp_path / "renamed.vault")
        config.rename_recent_vault(p2, new_p2)
        recents = config.get_recent_vaults()
        assert recents == [p3, new_p2, p1]

    def test_rename_not_present(self, tmp_path):
        # Should not raise or change anything
        config.add_recent_vault(str(tmp_path / "existing.vault"))
        config.rename_recent_vault("/nonexistent.vault", "/new.vault")
        recents = config.get_recent_vaults()
        assert len(recents) == 1


class TestConfigFileIntegrity:
    def test_file_permissions(self, monkeypatch_config_dir):
        _, cfg_file = monkeypatch_config_dir
        config.add_recent_vault("/tmp/perm.vault")
        mode = os.stat(cfg_file).st_mode & 0o777
        assert mode == 0o600

    def test_dir_permissions(self, monkeypatch_config_dir):
        cfg_dir, _ = monkeypatch_config_dir
        config.add_recent_vault("/tmp/perm.vault")
        mode = os.stat(cfg_dir).st_mode & 0o777
        assert mode == 0o700

    def test_survives_corrupt_json(self, monkeypatch_config_dir):
        _, cfg_file = monkeypatch_config_dir
        # Write valid first so the dir/file exist
        config.add_recent_vault("/tmp/test.vault")
        # Corrupt the file
        with open(cfg_file, "w") as f:
            f.write("{{{not json!!!")
        # Should gracefully return empty
        assert config.get_recent_vaults() == []

    def test_persistence(self, monkeypatch_config_dir):
        _, cfg_file = monkeypatch_config_dir
        config.add_recent_vault("/tmp/persist.vault")
        # Read the file directly to verify it was written
        with open(cfg_file) as f:
            data = json.load(f)
        assert os.path.abspath("/tmp/persist.vault") in data["recent_vaults"]
