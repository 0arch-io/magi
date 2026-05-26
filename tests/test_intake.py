"""Tests for the intake classifier's models and parsing (not the LLM call)."""

from magi.intake import Classification, QuestionClass


class TestClassificationModel:
    def test_decision_parses(self):
        c = Classification(question_class=QuestionClass.DECISION, options=[])
        assert c.question_class == QuestionClass.DECISION
        assert c.options == []

    def test_choice_with_options(self):
        c = Classification(
            question_class=QuestionClass.CHOICE,
            options=["Swift", "React Native"],
        )
        assert c.question_class == QuestionClass.CHOICE
        assert len(c.options) == 2

    def test_noise(self):
        c = Classification(question_class=QuestionClass.NOISE, options=[])
        assert c.question_class == QuestionClass.NOISE

    def test_from_json(self):
        raw = '{"question_class": "open", "options": []}'
        c = Classification.model_validate_json(raw)
        assert c.question_class == QuestionClass.OPEN

    def test_choice_from_json(self):
        raw = '{"question_class": "choice", "options": ["Miami", "Austin", "Denver"]}'
        c = Classification.model_validate_json(raw)
        assert c.question_class == QuestionClass.CHOICE
        assert c.options == ["Miami", "Austin", "Denver"]

    def test_prediction_class(self):
        c = Classification(question_class=QuestionClass.PREDICTION, options=[])
        assert c.question_class == QuestionClass.PREDICTION
