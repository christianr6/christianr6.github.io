import json

from bull_bear import debate, pipeline
from bull_bear.debate import Claim, Opening, Rebuttal, Rebuttals, Verdict
from bull_bear.llm import ClaudeLlm
from bull_bear.sections import Section

SECTIONS = [
    Section("mdna", "MD&A", "Net sales increased 15% during 2026 because customers bought more units at higher prices."),
    Section("risk_factors", "Risk", "The Company depends on a single supplier for a component that has no substitute today."),
]
GOOD_BULL = "Net sales increased 15% during 2026 because customers bought more units"
GOOD_BEAR = "The Company depends on a single supplier for a component that has no substitute"
VERDICT = Verdict(winner="bull", bull_score=7, bear_score=5, reasoning="r", strongest_bull_point="b",
                  strongest_bear_point="s", missing_evidence="price")


class Script:
    """Stands in for the model: returns canned answers and records each prompt."""

    def __init__(self, bull_claims, bear_claims, bull_rebuttals=(), bear_rebuttals=()):
        self.prompts: list[str] = []
        self.answers = {
            "bull case: why": Opening(thesis="Growing.", claims=list(bull_claims)),
            "bear case: what": Opening(thesis="Fragile.", claims=list(bear_claims)),
            "argue the bull case. Below": Rebuttals(rebuttals=list(bull_rebuttals)),
            "argue the bear case. Below": Rebuttals(rebuttals=list(bear_rebuttals)),
            "You are the judge": VERDICT,
        }

    def ask(self, prompt, schema):
        self.prompts.append(prompt)
        for marker, answer in self.answers.items():
            if marker in prompt:
                assert isinstance(answer, schema)
                return answer
        raise AssertionError(f"unexpected prompt: {prompt[:60]}")

    def prompt_with(self, marker):
        return next(p for p in self.prompts if marker in p)


def claim(point, quote, source="mdna"):
    return Claim(point=point, quote=quote, source=source)


def test_claims_with_real_quotes_stand_and_fabricated_ones_are_dropped():
    llm = Script(
        bull_claims=[claim("Sales grew.", GOOD_BULL), claim("Margins doubled.", "Gross margin doubled to a record level this year")],
        bear_claims=[claim("One supplier.", GOOD_BEAR, "risk_factors")],
    )
    result = debate.run(llm, SECTIONS)
    assert [c.point for c in result.bull.standing] == ["Sales grew."]
    assert [(c.point, c.reason) for c in result.bull.dropped] == [("Margins doubled.", "not_found")]
    assert len(result.bear.standing) == 1


def test_the_judge_never_sees_a_dropped_claim():
    llm = Script(
        bull_claims=[claim("Sales grew.", GOOD_BULL), claim("Margins doubled.", "Gross margin doubled to a record level this year")],
        bear_claims=[claim("One supplier.", GOOD_BEAR, "risk_factors")],
    )
    debate.run(llm, SECTIONS)
    judge_prompt = llm.prompt_with("You are the judge")
    assert "Sales grew." in judge_prompt and "One supplier." in judge_prompt
    assert "Margins doubled." not in judge_prompt


def test_the_opponent_only_rebuts_claims_that_survived():
    llm = Script(
        bull_claims=[claim("Sales grew.", GOOD_BULL), claim("Margins doubled.", "Gross margin doubled to a record level this year")],
        bear_claims=[claim("One supplier.", GOOD_BEAR, "risk_factors")],
    )
    debate.run(llm, SECTIONS)
    bear_rebuttal_prompt = llm.prompt_with("argue the bear case. Below")
    assert "Sales grew." in bear_rebuttal_prompt and "Margins doubled." not in bear_rebuttal_prompt


def test_rebuttal_quotes_are_checked_too():
    llm = Script(
        bull_claims=[claim("Sales grew.", GOOD_BULL)],
        bear_claims=[claim("One supplier.", GOOD_BEAR, "risk_factors")],
        bear_rebuttals=[
            Rebuttal(target=1, response="Growth leaned on price.", quote=GOOD_BULL, source="mdna"),
            Rebuttal(target=1, response="Invented.", quote="Unit volumes actually fell sharply in every region", source="mdna"),
        ],
    )
    result = debate.run(llm, SECTIONS)
    assert [r.verified for r in result.bear.rebuttals] == [True, False]
    judge_prompt = llm.prompt_with("You are the judge")
    assert "Growth leaned on price." in judge_prompt and "Invented." not in judge_prompt


def test_a_rebuttal_aimed_at_a_claim_that_does_not_exist_is_ignored():
    llm = Script(
        bull_claims=[claim("Sales grew.", GOOD_BULL)],
        bear_claims=[claim("One supplier.", GOOD_BEAR, "risk_factors")],
        bear_rebuttals=[Rebuttal(target=9, response="Nothing there.", quote=GOOD_BULL, source="mdna")],
    )
    assert debate.run(llm, SECTIONS).bear.rebuttals == []


def test_a_side_with_nothing_standing_is_not_rebutted_and_the_debate_still_ends():
    llm = Script(bull_claims=[claim("Made up.", "Everything is wonderful and will stay so for all time")],
                 bear_claims=[claim("One supplier.", GOOD_BEAR, "risk_factors")])
    result = debate.run(llm, SECTIONS)
    assert result.bull.standing == [] and result.verdict.winner == "bull"
    assert not any("argue the bear case. Below" in p for p in llm.prompts)


def test_the_real_section_is_recorded_even_if_the_model_named_the_wrong_one():
    llm = Script(bull_claims=[claim("Sales grew.", GOOD_BULL, source="risk_factors")], bear_claims=[])
    assert debate.run(llm, SECTIONS).bull.claims[0].found_in == "mdna"


def test_transcripts_are_saved_and_reloaded(tmp_path):
    sources = pipeline.Sources(
        company="Testco", ticker="TEST", accession="0000000000-26-000001", filed="2026-11-01",
        period="2026-09-30", url="https://example.test/10k.htm", notes=[],
        sections=[{"key": s.key, "title": s.title, "text": s.text} for s in SECTIONS],
    )
    llm = Script(bull_claims=[claim("Sales grew.", GOOD_BULL)], bear_claims=[claim("One supplier.", GOOD_BEAR, "risk_factors")])
    saved = pipeline.hold(sources, llm, directory=tmp_path)
    again = pipeline.load_saved(sources, directory=tmp_path)
    assert again == saved
    assert json.loads(pipeline.transcript_path(sources, tmp_path).read_text())["debate"]["verdict"]["winner"] == "bull"


# ---------- the request sent to Claude ----------

class _Usage:
    input_tokens, cache_creation_input_tokens, cache_read_input_tokens, output_tokens = 10, 2000, 0, 300


class _Response:
    stop_reason = "end_turn"
    usage = _Usage()

    def __init__(self, parsed):
        self.parsed_output = parsed


class _Client:
    def __init__(self):
        self.calls = []
        self.beta = self
        self.messages = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(VERDICT)


def test_every_call_shares_one_cached_prefix_and_only_the_question_changes():
    client = _Client()
    llm = ClaudeLlm(SECTIONS, client=client)
    llm.ask("first question", Verdict)
    llm.ask("second question", Verdict)
    first, second = client.calls
    assert first["system"] == second["system"]
    assert first["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert "depends on a single supplier" in first["system"][-1]["text"]
    assert [c["messages"][0]["content"] for c in client.calls] == ["first question", "second question"]


def test_request_uses_the_default_model_structured_output_and_refusal_fallback():
    client = _Client()
    ClaudeLlm(SECTIONS, client=client).ask("q", Verdict)
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_format"] is Verdict
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in call and "temperature" not in call


def test_token_usage_adds_up_across_calls():
    llm = ClaudeLlm(SECTIONS, client=_Client())
    llm.ask("a", Verdict)
    llm.ask("b", Verdict)
    assert llm.usage.calls == 2 and llm.usage.cache_write_tokens == 4000 and llm.usage.output_tokens == 600
