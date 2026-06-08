"""Tests for pure helper functions in filebrowser.py.

These tests import filebrowser, which requires GTK 3. Tests are skipped
if GTK is not available (e.g., headless CI without a display server).
"""

import os
import re

import pytest

gi = pytest.importorskip("gi")


from filebrowser import _format_size, _format_time, _copy_item


class TestFormatSize:
    def test_zero(self):
        assert _format_size(0) == "0 B"

    def test_bytes(self):
        assert _format_size(500) == "500 B"

    def test_one_byte(self):
        assert _format_size(1) == "1 B"

    def test_kb(self):
        assert _format_size(1536) == "1.5 KB"

    def test_exact_kb(self):
        assert _format_size(1024) == "1.0 KB"

    def test_mb(self):
        assert _format_size(2 * 1024 * 1024) == "2.0 MB"

    def test_gb(self):
        assert _format_size(3 * 1024 ** 3) == "3.0 GB"

    def test_tb(self):
        assert _format_size(2 * 1024 ** 4) == "2.0 TB"

    def test_fractional_kb(self):
        result = _format_size(2560)  # 2.5 KB
        assert result == "2.5 KB"


class TestFormatTime:
    def test_returns_datetime_format(self):
        result = _format_time(1700000000)
        # Should match YYYY-MM-DD HH:MM
        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", result)

    def test_zero_epoch(self):
        result = _format_time(0)
        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", result)


class TestCopyItem:
    def test_copy_file(self, tmp_path):
        src = tmp_path / "source.txt"
        src.write_text("hello")
        dest = tmp_path / "dest.txt"
        _copy_item(str(src), str(dest))
        assert dest.read_text() == "hello"

    def test_copy_directory(self, tmp_path):
        src_dir = tmp_path / "srcdir"
        src_dir.mkdir()
        (src_dir / "file.txt").write_text("inside")
        sub = src_dir / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_text("deep")

        dest_dir = tmp_path / "destdir"
        _copy_item(str(src_dir), str(dest_dir))
        assert (dest_dir / "file.txt").read_text() == "inside"
        assert (dest_dir / "sub" / "deep.txt").read_text() == "deep"

    def test_copy_binary_file(self, tmp_path):
        data = os.urandom(1024)
        src = tmp_path / "data.bin"
        src.write_bytes(data)
        dest = tmp_path / "copy.bin"
        _copy_item(str(src), str(dest))
        assert dest.read_bytes() == data

    def test_copy_preserves_metadata(self, tmp_path):
        src = tmp_path / "meta.txt"
        src.write_text("test")
        dest = tmp_path / "metacopy.txt"
        _copy_item(str(src), str(dest))
        # copy2 preserves modification time
        assert abs(os.stat(str(src)).st_mtime - os.stat(str(dest)).st_mtime) < 1
