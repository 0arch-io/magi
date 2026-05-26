"""Tests for journal security: symlink detection, permissions, atomic writes."""

import os
from unittest.mock import patch

import pytest

from magi.journal import _safe_path, _verify_file_permissions, save_entry


class TestSymlinkDetection:
    def test_rejects_symlink(self, tmp_path):
        target = tmp_path / "real_file"
        target.write_text("data")
        link = tmp_path / "link_file"
        link.symlink_to(target)
        with patch("magi.journal.JOURNAL_DIR", tmp_path):
            with pytest.raises(OSError, match="symlink"):
                _safe_path(link)

    def test_rejects_path_traversal(self, tmp_path):
        evil_path = tmp_path / ".." / ".." / "etc" / "passwd"
        with patch("magi.journal.JOURNAL_DIR", tmp_path):
            with pytest.raises(OSError, match="escapes"):
                _safe_path(evil_path)

    def test_accepts_normal_path(self, tmp_path):
        normal = tmp_path / "journal.jsonl"
        normal.write_text("")
        with patch("magi.journal.JOURNAL_DIR", tmp_path):
            result = _safe_path(normal)
            assert result == normal.resolve()


class TestFilePermissions:
    def test_fixes_world_readable(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text("data")
        os.chmod(f, 0o644)
        _verify_file_permissions(f)
        actual = f.stat().st_mode & 0o777
        assert actual == 0o600

    def test_already_secure_unchanged(self, tmp_path):
        f = tmp_path / "test.jsonl"
        f.write_text("data")
        os.chmod(f, 0o600)
        _verify_file_permissions(f)
        actual = f.stat().st_mode & 0o777
        assert actual == 0o600

    def test_nonexistent_no_error(self, tmp_path):
        f = tmp_path / "nonexistent.jsonl"
        _verify_file_permissions(f)


class TestAtomicJournalWrite:
    def test_save_creates_with_secure_permissions(self, tmp_path):
        journal_path = tmp_path / "journal.jsonl"
        with patch("magi.journal.JOURNAL_DIR", tmp_path), patch("magi.journal.JOURNAL_PATH", journal_path):
            save_entry("test?", ["M"], 1, "consensus", "YES", {"M": "ACCEPT"})
            assert journal_path.exists()
            actual = journal_path.stat().st_mode & 0o777
            assert actual == 0o600

    def test_dir_created_with_secure_permissions(self, tmp_path):
        new_dir = tmp_path / "subdir" / "magi"
        journal_path = new_dir / "journal.jsonl"
        with patch("magi.journal.JOURNAL_DIR", new_dir), patch("magi.journal.JOURNAL_PATH", journal_path):
            save_entry("test?", ["M"], 1, "consensus", "YES", {"M": "ACCEPT"})
            actual = new_dir.stat().st_mode & 0o777
            assert actual == 0o700
