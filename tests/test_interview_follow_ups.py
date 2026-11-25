"""Seam: InterviewLlm.follow_ups with a fake LlmSession returning canned JSON."""

import random

from app.ai.interview_llm import InterviewLlm
from app.modules.interview.follow_ups import GAP_RUBRIC_ITEM, GapType, fallback_question_text
from app.modules.interview.questions import (
    SITUATIONAL,
    FinalUtterance,
    ItemRecord,
    PlannedQuestion,
    RubricItem,
)
from tests.test_interview_llm import FakeLlm, FakeSession

# 33 hangul syllables and 9 s of voice: evaluable. Says 우리 but never 제가.
WE_ANSWER = "우리 팀은 검출 모델을 학습시키고 서버에 올려서 성능을 확인했고 결과가 좋았습니다"
# Same length with a first-person pronoun.
I_ANSWER = "제가 검출 모델을 학습시키고 서버에 올려서 성능을 확인했고 결과가 좋았습니다"


def main_question(qid="q1", subtype="experience", rubric_items=None) -> PlannedQuestion:
    return PlannedQuestion(
        id=qid,
        kind="document",
        subtype=subtype,
        text="프로젝트에서 맡은 역할은 무엇인가요?",
        intent="",
        rubric_items=list(
            [RubricItem.SPECIFICITY, RubricItem.REASONING, RubricItem.LEARNING]
            if rubric_items is None
            else rubric_items
        ),
    )


def answered(question: PlannedQuestion, text: str, voiced_ms: int = 9000) -> ItemRecord:
    utterances = [FinalUtterance("u1", 1000, 1000 + voiced_ms, text, voiced_ms)] if text else []
    return ItemRecord(
        question=question,
        shown_ms=0,
        answer_started_ms=1000 if utterances else None,
        ended_ms=60_000,
        advance_reason="silence" if utterances else "no_response",
        replay_used=False,
        utterances=utterances,
        transcript=text,
    )


def reply(
    gap: str, quote: str = "검출 모델을 학습시키고", question: str = "그 방법을 고른 이유는?"
):
    return {"gap_type": gap, "answer_quote": quote, "question": question}


class RecordingSession(FakeSession):
    def __init__(self, replies):
        super().__init__(replies)
        self.schemas: list[dict] = []

    async def complete_json(self, prompt, schema, **kwargs):
        self.schemas.append(schema)
        return await super().complete_json(prompt, schema, **kwargs)


def interview() -> InterviewLlm:
    return InterviewLlm(FakeLlm(), rng=random.Random(1))


async def run(session, items, **kwargs):
    return await interview().follow_ups(items, session, **kwargs)


async def test_a_valid_reply_becomes_a_round_two_follow_up_of_its_parent() -> None:
    session = FakeSession({"follow_up": reply("reasoning", question="그 서버 구성을 택한 이유는?")})
    parent = main_question()
    (child,) = await run(session, [answered(parent, I_ANSWER)])
    assert child.kind == "follow_up" and child.round == 2
    assert child.parent_id == parent.id and child.subtype == "reasoning"
    assert child.text == "그 서버 구성을 택한 이유는?"
    assert child.source_quote == "검출 모델을 학습시키고"
    assert child.rubric_items == [GAP_RUBRIC_ITEM[GapType.REASONING]]
    assert child.id == "q1-f"
    assert session.seeds == [42]


async def test_only_evaluable_main_questions_reach_the_model() -> None:
    session = FakeSession({"follow_up": reply("reasoning")})
    items = [
        answered(main_question("empty"), ""),
        answered(main_question("short"), "네 맞습니다", voiced_ms=2000),
        answered(main_question("closing", rubric_items=[]), I_ANSWER),
        answered(
            PlannedQuestion(
                "f1", "follow_up", "own_role", "?", rubric_items=[RubricItem.SPECIFICITY], round=2
            ),
            I_ANSWER,
        ),
        answered(main_question("good"), I_ANSWER),
    ]
    result = await run(session, items)
    assert [q.parent_id for q in result] == ["good"]
    assert session.count("follow_up") == 1


async def test_the_reply_may_only_choose_a_gap_allowed_for_the_question() -> None:
    session = RecordingSession({"follow_up": reply("core_task")})
    await run(session, [answered(main_question(), I_ANSWER)])
    experience_enum = session.schemas[0]["properties"]["gap_type"]["enum"]
    assert "none" in experience_enum and "own_role" in experience_enum
    assert "core_task" not in experience_enum and "stakeholders" not in experience_enum

    session = RecordingSession({"follow_up": reply("expected_result")})
    situational = main_question(
        subtype=SITUATIONAL,
        rubric_items=[RubricItem.UNDERSTANDING, RubricItem.REASONING, RubricItem.COLLABORATION],
    )
    await run(session, [answered(situational, I_ANSWER)])
    situational_enum = session.schemas[0]["properties"]["gap_type"]["enum"]
    assert "core_task" in situational_enum
    assert "result_check" not in situational_enum and "learning" not in situational_enum


async def test_a_gap_outside_the_allowed_set_is_retried() -> None:
    session = FakeSession({"follow_up": [reply("core_task"), reply("reasoning")]})
    (child,) = await run(session, [answered(main_question(), I_ANSWER)])
    assert child.subtype == "reasoning"
    assert session.seeds == [42, 43]


async def test_a_quote_missing_from_the_answer_is_retried_with_another_seed_and_a_hint() -> None:
    session = FakeSession(
        {"follow_up": [reply("reasoning", quote="답변에 없는 문장"), reply("reasoning")]}
    )
    (child,) = await run(session, [answered(main_question(), I_ANSWER)])
    assert child.source_quote == "검출 모델을 학습시키고"
    assert session.seeds == [42, 43]
    first, second = (prompt for _, prompt in session.calls)
    assert second.startswith(first) and len(second) > len(first)


async def test_the_quote_is_matched_after_normalising_whitespace() -> None:
    answer = "제가  검출 모델을\n학습시키고 서버에 올려서 성능을 확인했고 결과가 좋았습니다"
    session = FakeSession({"follow_up": reply("reasoning", quote="검출   모델을 학습시키고")})
    (child,) = await run(session, [answered(main_question(), answer)])
    assert child.source_quote == "검출 모델을 학습시키고"
    assert session.seeds == [42]


async def test_invalid_question_text_is_retried() -> None:
    bad = [
        reply("reasoning", question="가족 관계는 어떻게 되나요?"),  # banned topic
        reply("reasoning", question="왜 그랬나요? 결과는요?"),  # two questions
        reply("reasoning", question="가" * 101),  # too long
        reply("reasoning", question="  "),  # empty
    ]
    for first in bad:
        session = FakeSession({"follow_up": [first, reply("reasoning")]})
        (child,) = await run(session, [answered(main_question(), I_ANSWER)])
        assert child.text == "그 방법을 고른 이유는?", first
        assert session.seeds == [42, 43]


async def test_after_a_failed_retry_the_fixed_sentence_for_the_chosen_gap_is_used() -> None:
    bad = reply("reasoning", quote="답변에 없는 문장", question="이 질문은 쓰이지 않습니다")
    session = FakeSession({"follow_up": [bad, bad]})
    (child,) = await run(session, [answered(main_question(), I_ANSWER)])
    assert child.text == fallback_question_text(GapType.REASONING)
    assert child.subtype == "reasoning" and child.source_quote is None
    assert child.round == 2 and child.parent_id == "q1"
    assert session.seeds == [42, 43]


async def test_a_failing_call_uses_the_rule_gap_sentence_or_gives_up() -> None:
    errors = [ValueError("bad json"), ValueError("bad json")]
    session = FakeSession({"follow_up": errors})
    (child,) = await run(session, [answered(main_question(), WE_ANSWER)])  # 우리 only: own_role
    assert child.subtype == "own_role" and child.text == fallback_question_text(GapType.OWN_ROLE)

    session = FakeSession({"follow_up": errors})
    assert await run(session, [answered(main_question(), I_ANSWER)]) == []  # no known gap


async def test_no_gap_means_no_follow_up() -> None:
    session = FakeSession({"follow_up": reply("none", quote="", question="")})
    assert await run(session, [answered(main_question(), I_ANSWER)]) == []


async def test_a_rule_signal_survives_the_model_finding_no_gap() -> None:
    session = FakeSession({"follow_up": reply("none", quote="", question="")})
    (child,) = await run(session, [answered(main_question(), WE_ANSWER)])
    assert child.subtype == "own_role" and child.text == fallback_question_text(GapType.OWN_ROLE)
    assert "own_role" in session.calls[0][1]  # the signal is part of the prompt


async def test_the_answers_with_most_gaps_win_and_ties_keep_interview_order() -> None:
    session = FakeSession(
        {
            "follow_up": [
                reply("reasoning"),  # q-a: one gap
                reply("reasoning"),  # q-b: 우리 only + reasoning = two gaps
                reply("learning"),  # q-c: one gap
            ]
        }
    )
    items = [
        answered(main_question("q-a"), I_ANSWER),
        answered(main_question("q-b"), WE_ANSWER),
        answered(main_question("q-c"), I_ANSWER),
    ]
    assert [q.parent_id for q in await run(session, items)] == ["q-b", "q-a"]


async def test_the_follow_up_count_is_capped_by_the_composition_default_or_the_argument() -> None:
    def three() -> list[ItemRecord]:
        return [answered(main_question(f"q{n}"), I_ANSWER) for n in range(3)]

    assert len(await run(FakeSession({"follow_up": reply("reasoning")}), three())) == 2
    assert len(await run(FakeSession({"follow_up": reply("reasoning")}), three(), max_count=1)) == 1
    assert await run(FakeSession({"follow_up": reply("reasoning")}), three(), max_count=0) == []


async def test_the_fixed_sentence_follows_the_gap_the_model_named_not_the_rule_signal() -> None:
    bad = reply("reasoning", quote="답변에 없는 문장")
    session = FakeSession({"follow_up": [bad, bad]})
    (child,) = await run(session, [answered(main_question(), WE_ANSWER)])  # 우리 only: own_role
    assert child.subtype == "reasoning"
    assert child.text == fallback_question_text(GapType.REASONING)
