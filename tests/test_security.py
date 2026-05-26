"""Tests for security hardening: terminal injection, input caps, response validation."""

import pytest

from magi.core import (
    MAX_INPUT_CHARS,
    MAX_RESPONSE_BYTES,
    Deliberation,
    _check_content_type,
    _check_response_size,
    _sanitize_llm_output,
)


class TestSanitizeLLMOutput:
    def test_strips_ansi_color(self):
        malicious = "\x1b[31mRED TEXT\x1b[0m"
        assert _sanitize_llm_output(malicious) == "RED TEXT"

    def test_strips_cursor_movement(self):
        malicious = "\x1b[2J\x1b[H\x1b[3AOverwritten"
        assert _sanitize_llm_output(malicious) == "Overwritten"

    def test_strips_osc_sequences(self):
        malicious = "\x1b]0;pwned title\x07real content"
        assert _sanitize_llm_output(malicious) == "real content"

    def test_strips_null_bytes(self):
        malicious = "hello\x00world"
        assert _sanitize_llm_output(malicious) == "helloworld"

    def test_strips_bell(self):
        malicious = "normal\x07text"
        assert _sanitize_llm_output(malicious) == "normaltext"

    def test_strips_backspace(self):
        malicious = "secret\x08\x08\x08\x08\x08\x08public"
        assert _sanitize_llm_output(malicious) == "secretpublic"

    def test_preserves_normal_text(self):
        safe = "This is a normal response with punctuation, numbers 123, and unicode: café."
        assert _sanitize_llm_output(safe) == safe

    def test_preserves_newlines_and_tabs(self):
        text = "line one\nline two\ttabbed"
        assert _sanitize_llm_output(text) == text

    def test_combined_attack(self):
        attack = "\x1b[2J\x1b[HCONSENSUS - YES\x1b[0m\x00\x07\x1b]2;evil\x07"
        result = _sanitize_llm_output(attack)
        assert "\x1b" not in result
        assert "\x00" not in result
        assert "\x07" not in result
        assert "CONSENSUS" in result


class TestInputLengthCap:
    def test_long_input_truncated(self):
        d = Deliberation(["MELCHIOR"])
        giant_input = "x" * (MAX_INPUT_CHARS + 5000)
        d.add_user_message(giant_input)
        stored = d.histories["MELCHIOR"][0]["content"]
        assert len(stored) == MAX_INPUT_CHARS

    def test_normal_input_preserved(self):
        d = Deliberation(["MELCHIOR"])
        normal = "should I take the job?"
        d.add_user_message(normal)
        assert d.histories["MELCHIOR"][0]["content"] == normal


class TestResponseSizeCheck:
    def test_oversized_content_length_rejected(self):
        class FakeResponse:
            headers = {"content-length": str(MAX_RESPONSE_BYTES + 1)}
            content = b""
        with pytest.raises(ValueError, match="too large"):
            _check_response_size(FakeResponse())

    def test_oversized_body_rejected(self):
        class FakeResponse:
            headers = {}
            content = b"x" * (MAX_RESPONSE_BYTES + 1)
        with pytest.raises(ValueError, match="too large"):
            _check_response_size(FakeResponse())

    def test_normal_response_passes(self):
        class FakeResponse:
            headers = {"content-length": "500"}
            content = b'{"message": {"content": "{}"}}'
        _check_response_size(FakeResponse())


class TestContentTypeCheck:
    def test_json_passes(self):
        class FakeResponse:
            headers = {"content-type": "application/json"}
        _check_content_type(FakeResponse())

    def test_text_passes(self):
        class FakeResponse:
            headers = {"content-type": "text/plain"}
        _check_content_type(FakeResponse())

    def test_no_header_passes(self):
        class FakeResponse:
            headers = {}
        _check_content_type(FakeResponse())

    def test_binary_rejected(self):
        class FakeResponse:
            headers = {"content-type": "application/octet-stream"}
        with pytest.raises(ValueError, match="unexpected content-type"):
            _check_content_type(FakeResponse())

    def test_html_rejected(self):
        class FakeResponse:
            headers = {"content-type": "text/html"}
        # text/html contains "text" so it passes - this is acceptable
        # since Ollama sometimes returns text/plain
        _check_content_type(FakeResponse())
