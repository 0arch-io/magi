"""Tests for Pydantic validators that enforce the council's decisiveness rules."""

import pytest
from pydantic import ValidationError

from magi.core import (
    ChoiceResponse,
    PersonaResponse,
    Rebuttal,
    RecommendResponse,
    Verdict,
    _condition_is_vague,
    _normalize_option,
    _recommendation_is_vague,
    _strip_persona_prefixes,
)


class TestConditionVagueness:
    def test_empty_is_vague(self):
        assert _condition_is_vague("")

    def test_whitespace_is_vague(self):
        assert _condition_is_vague("   ")

    def test_banned_phrase_detected(self):
        assert _condition_is_vague("They need a clear plan before proceeding")

    def test_concrete_condition_passes(self):
        assert not _condition_is_vague("Need to see the Q3 revenue report showing >$50k MRR")

    def test_all_banned_phrases(self):
        from magi.core import _BANNED_CONDITION_PHRASES
        for phrase in _BANNED_CONDITION_PHRASES:
            assert _condition_is_vague(f"The user needs {phrase} first"), f"missed: {phrase}"


class TestRecommendationVagueness:
    def test_short_is_vague(self):
        assert _recommendation_is_vague("thing")

    def test_banned_phrase_detected(self):
        assert _recommendation_is_vague("something you're passionate about")

    def test_consider_building_detected(self):
        assert _recommendation_is_vague("Consider building a project that helps people")

    def test_consider_exploring_detected(self):
        assert _recommendation_is_vague("Consider exploring new frameworks for web development")

    def test_concrete_recommendation_passes(self):
        assert not _recommendation_is_vague("A personal finance tracker with bank API integration")


class TestPersonaResponseCoercion:
    def test_vague_conditional_coerced_to_accept(self):
        r = PersonaResponse(
            verdict=Verdict.CONDITIONAL,
            reasoning="This is a reasonable approach with some caveats.",
            condition="They need a clear plan",
        )
        assert r.verdict == Verdict.ACCEPT
        assert r.condition == ""

    def test_empty_conditional_coerced_to_accept(self):
        r = PersonaResponse(
            verdict=Verdict.CONDITIONAL,
            reasoning="This is a reasonable approach with some caveats.",
            condition="",
        )
        assert r.verdict == Verdict.ACCEPT

    def test_concrete_conditional_kept(self):
        r = PersonaResponse(
            verdict=Verdict.CONDITIONAL,
            reasoning="The numbers are tight but workable under one scenario.",
            condition="Only if their landlord agrees to extend the lease past June 2026",
        )
        assert r.verdict == Verdict.CONDITIONAL
        assert "landlord" in r.condition

    def test_accept_passes_through(self):
        r = PersonaResponse(
            verdict=Verdict.ACCEPT,
            reasoning="This is clearly the right move given the data.",
        )
        assert r.verdict == Verdict.ACCEPT

    def test_reject_passes_through(self):
        r = PersonaResponse(
            verdict=Verdict.REJECT,
            reasoning="The risk profile is unacceptable at this stage.",
        )
        assert r.verdict == Verdict.REJECT

    def test_short_reasoning_rejected(self):
        with pytest.raises(ValidationError):
            PersonaResponse(verdict=Verdict.ACCEPT, reasoning="No.")


class TestRebuttalCoercion:
    def test_vague_conditional_coerced(self):
        r = Rebuttal(
            response="MELCHIOR is right about the timeline but wrong about scope.",
            final_verdict=Verdict.CONDITIONAL,
            condition="manageable scope",
        )
        assert r.final_verdict == Verdict.ACCEPT
        assert r.condition == ""


class TestRecommendResponse:
    def test_vague_recommendation_rejected(self):
        with pytest.raises(ValidationError):
            RecommendResponse(
                recommendation="something you're passionate about",
                reasoning="Follow your heart on this one, the answer is within.",
            )

    def test_concrete_recommendation_passes(self):
        r = RecommendResponse(
            recommendation="Build a CLI habit tracker with SQLite persistence",
            reasoning="Small scope, ship in a weekend, and it scratches a real itch.",
        )
        assert "habit tracker" in r.recommendation


class TestChoiceResponse:
    def test_valid_choice(self):
        r = ChoiceResponse(
            chosen_option="Swift",
            reasoning="Native performance matters more than cross-platform speed for this app.",
        )
        assert r.chosen_option == "Swift"

    def test_empty_choice_rejected(self):
        with pytest.raises(ValidationError):
            ChoiceResponse(
                chosen_option="",
                reasoning="Can't decide between these two equally valid options.",
            )


class TestNormalizeOption:
    def test_exact_match(self):
        assert _normalize_option("Swift", ["Swift", "React Native"]) == "Swift"

    def test_case_insensitive(self):
        assert _normalize_option("swift", ["Swift", "React Native"]) == "Swift"

    def test_substring_match(self):
        assert _normalize_option("React", ["Swift", "React Native"]) == "React Native"

    def test_no_match_returns_raw(self):
        assert _normalize_option("Flutter", ["Swift", "React Native"]) == "Flutter"

    def test_empty_returns_empty(self):
        assert _normalize_option("", ["Swift", "React Native"]) == ""


class TestStripPersonaPrefixes:
    def test_strips_name_prefix(self):
        assert _strip_persona_prefixes("CASPER: Build a habit tracker") == "Build a habit tracker"

    def test_strips_recommendation_prefix(self):
        assert _strip_persona_prefixes("MELCHIOR's recommendation: A data tool") == "A data tool"

    def test_strips_verdict_prefix(self):
        assert _strip_persona_prefixes("ACCEPT - This is the right call") == "This is the right call"

    def test_strips_nested(self):
        assert _strip_persona_prefixes("CASPER: ACCEPT - Do it") == "Do it"

    def test_leaves_clean_text(self):
        assert _strip_persona_prefixes("Build a habit tracker app") == "Build a habit tracker app"
