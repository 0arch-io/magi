from magi.core import (
    ChoiceResponse,
    PersonaResponse,
    RecommendResponse,
    Verdict,
    synthesize,
    synthesize_choice,
    synthesize_recommend,
)


class TestSynthesizeDecision:
    def test_consensus_accept(self):
        positions = {
            "MELCHIOR": PersonaResponse(verdict=Verdict.ACCEPT, reasoning="The data supports this move clearly."),
            "BALTHASAR": PersonaResponse(verdict=Verdict.ACCEPT, reasoning="Long-term this is sustainable and healthy."),
            "CASPER": PersonaResponse(verdict=Verdict.ACCEPT, reasoning="This aligns with what they actually want."),
        }
        result = synthesize(positions, outcome="consensus")
        assert "CONSENSUS" in result
        assert "YES" in result
        assert "3A" in result

    def test_consensus_reject(self):
        positions = {
            "MELCHIOR": PersonaResponse(verdict=Verdict.REJECT, reasoning="The numbers do not add up at all."),
            "BALTHASAR": PersonaResponse(verdict=Verdict.REJECT, reasoning="This would damage key relationships irreparably."),
            "CASPER": PersonaResponse(verdict=Verdict.REJECT, reasoning="They do not actually want this outcome."),
        }
        result = synthesize(positions, outcome="consensus")
        assert "CONSENSUS" in result
        assert "NO" in result

    def test_deadlock_leans_yes(self):
        positions = {
            "MELCHIOR": PersonaResponse(verdict=Verdict.ACCEPT, reasoning="Strong data case for proceeding now."),
            "BALTHASAR": PersonaResponse(verdict=Verdict.ACCEPT, reasoning="Sustainable path with good upside."),
            "CASPER": PersonaResponse(verdict=Verdict.CONDITIONAL, reasoning="Close call but one blocker remains.", condition="Only if they negotiate the equity split first"),
        }
        result = synthesize(positions, outcome="deadlock")
        assert "DEADLOCK" in result
        assert "leans YES" in result

    def test_deadlock_split(self):
        positions = {
            "MELCHIOR": PersonaResponse(verdict=Verdict.ACCEPT, reasoning="Data says go for it now."),
            "BALTHASAR": PersonaResponse(verdict=Verdict.REJECT, reasoning="Too risky for their current life stage."),
            "CASPER": PersonaResponse(verdict=Verdict.CONDITIONAL, reasoning="The timing is everything here, and September is the hard cutoff.", condition="Only if they start before September 2026"),
        }
        result = synthesize(positions, outcome="deadlock")
        assert "DEADLOCK" in result
        assert "split" in result
        assert "your call" in result

    def test_incomplete(self):
        positions = {
            "MELCHIOR": PersonaResponse(verdict=Verdict.ACCEPT, reasoning="The evidence is clear on this one."),
        }
        result = synthesize(positions, outcome="incomplete")
        assert "INCOMPLETE" in result

    def test_auto_detection_consensus(self):
        positions = {
            "MELCHIOR": PersonaResponse(verdict=Verdict.REJECT, reasoning="Terrible risk-reward ratio here."),
            "BALTHASAR": PersonaResponse(verdict=Verdict.REJECT, reasoning="Would cause lasting damage to wellbeing."),
        }
        result = synthesize(positions, outcome="auto")
        assert "CONSENSUS" in result
        assert "NO" in result

    def test_auto_detection_deadlock(self):
        positions = {
            "MELCHIOR": PersonaResponse(verdict=Verdict.ACCEPT, reasoning="Numbers check out for this move."),
            "BALTHASAR": PersonaResponse(verdict=Verdict.REJECT, reasoning="Cost to relationships is too high."),
        }
        result = synthesize(positions, outcome="auto")
        assert "DEADLOCK" in result


class TestSynthesizeChoice:
    def test_consensus(self):
        positions = {
            "MELCHIOR": ChoiceResponse(chosen_option="Swift", reasoning="Native performance is non-negotiable for this app."),
            "BALTHASAR": ChoiceResponse(chosen_option="Swift", reasoning="Better long-term investment for iOS career."),
            "CASPER": ChoiceResponse(chosen_option="Swift", reasoning="They genuinely want to learn Swift anyway."),
        }
        result = synthesize_choice(positions, "consensus", ["Swift", "React Native"])
        assert "CONSENSUS" in result
        assert "Swift" in result

    def test_winner(self):
        positions = {
            "MELCHIOR": ChoiceResponse(chosen_option="Swift", reasoning="Performance edge matters here."),
            "BALTHASAR": ChoiceResponse(chosen_option="Swift", reasoning="Deeper ecosystem for what they need."),
            "CASPER": ChoiceResponse(chosen_option="React Native", reasoning="They value shipping fast over polish."),
        }
        result = synthesize_choice(positions, "split", ["Swift", "React Native"])
        assert "WINNER" in result
        assert "Swift" in result

    def test_tie(self):
        positions = {
            "MELCHIOR": ChoiceResponse(chosen_option="Miami", reasoning="Lower taxes, better for the business long-term."),
            "BALTHASAR": ChoiceResponse(chosen_option="Austin", reasoning="Stronger support network in Austin."),
        }
        result = synthesize_choice(positions, "split", ["Miami", "Austin"])
        assert "TIE" in result
        assert "your call" in result


class TestSynthesizeRecommend:
    def test_distinct_picks(self):
        positions = {
            "MELCHIOR": RecommendResponse(recommendation="A personal finance dashboard with Plaid integration", reasoning="Addresses a real need and teaches API work."),
            "BALTHASAR": RecommendResponse(recommendation="A neighborhood mutual aid app", reasoning="Builds community and has low technical risk."),
            "CASPER": RecommendResponse(recommendation="A generative art tool using local Stable Diffusion", reasoning="Matches their creative side that has been dormant."),
        }
        result = synthesize_recommend(positions)
        assert "DISTINCT PICKS" in result

    def test_consensus(self):
        positions = {
            "MELCHIOR": RecommendResponse(recommendation="habit tracker", reasoning="Simple scope, concrete deliverable."),
            "BALTHASAR": RecommendResponse(recommendation="habit tracker", reasoning="Builds a healthy routine simultaneously."),
            "CASPER": RecommendResponse(recommendation="habit tracker", reasoning="Something they will actually use daily."),
        }
        result = synthesize_recommend(positions)
        assert "CONSENSUS" in result

    def test_incomplete(self):
        positions = {
            "MELCHIOR": RecommendResponse(recommendation="A budget CLI tool", reasoning="Practical and shippable in a weekend."),
        }
        result = synthesize_recommend(positions)
        assert "INCOMPLETE" in result
