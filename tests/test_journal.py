"""Tests for journal save/load/search."""

from unittest.mock import patch

from magi.journal import find_entry, load_entries, save_entry, set_user_outcome


class TestJournal:
    def test_save_and_load(self, tmp_path):
        journal_path = tmp_path / "journal.jsonl"
        with patch("magi.journal.JOURNAL_DIR", tmp_path), patch("magi.journal.JOURNAL_PATH", journal_path):
            entry_id = save_entry(
                question="should I take the job?",
                members=["MELCHIOR", "BALTHASAR", "CASPER"],
                rounds=2,
                outcome="consensus",
                synthesis="CONSENSUS — YES  (3A · 0C · 0R)",
                final_verdicts={"MELCHIOR": "ACCEPT", "BALTHASAR": "ACCEPT", "CASPER": "ACCEPT"},
            )
            assert len(entry_id) == 8

            entries = load_entries()
            assert len(entries) == 1
            assert entries[0]["question"] == "should I take the job?"
            assert entries[0]["outcome"] == "consensus"

    def test_load_empty(self, tmp_path):
        journal_path = tmp_path / "journal.jsonl"
        with patch("magi.journal.JOURNAL_DIR", tmp_path), patch("magi.journal.JOURNAL_PATH", journal_path):
            assert load_entries() == []

    def test_find_entry(self, tmp_path):
        journal_path = tmp_path / "journal.jsonl"
        with patch("magi.journal.JOURNAL_DIR", tmp_path), patch("magi.journal.JOURNAL_PATH", journal_path):
            entry_id = save_entry(
                question="should I move?",
                members=["MELCHIOR", "BALTHASAR", "CASPER"],
                rounds=1,
                outcome="deadlock",
                synthesis="DEADLOCK — split",
                final_verdicts={"MELCHIOR": "ACCEPT", "BALTHASAR": "REJECT", "CASPER": "ACCEPT"},
            )
            found = find_entry(entry_id[:4])
            assert found is not None
            assert found["question"] == "should I move?"

    def test_set_user_outcome(self, tmp_path):
        journal_path = tmp_path / "journal.jsonl"
        with patch("magi.journal.JOURNAL_DIR", tmp_path), patch("magi.journal.JOURNAL_PATH", journal_path):
            entry_id = save_entry(
                question="should I quit?",
                members=["MELCHIOR", "BALTHASAR", "CASPER"],
                rounds=3,
                outcome="consensus",
                synthesis="CONSENSUS — NO",
                final_verdicts={"MELCHIOR": "REJECT", "BALTHASAR": "REJECT", "CASPER": "REJECT"},
            )
            assert set_user_outcome(entry_id[:4], "quit anyway, no regrets")

            entries = load_entries()
            assert entries[0]["user_outcome"] == "quit anyway, no regrets"

    def test_multiple_entries_order(self, tmp_path):
        journal_path = tmp_path / "journal.jsonl"
        with patch("magi.journal.JOURNAL_DIR", tmp_path), patch("magi.journal.JOURNAL_PATH", journal_path):
            save_entry("first", ["M"], 1, "consensus", "yes", {"M": "ACCEPT"})
            save_entry("second", ["M"], 1, "deadlock", "split", {"M": "REJECT"})
            save_entry("third", ["M"], 1, "consensus", "yes", {"M": "ACCEPT"})

            entries = load_entries()
            assert len(entries) == 3
            assert entries[0]["question"] == "third"

            limited = load_entries(limit=2)
            assert len(limited) == 2
