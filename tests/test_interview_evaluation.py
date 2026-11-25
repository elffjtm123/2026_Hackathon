"""Seam: InterviewLlm.evaluate with a fake LlmSession returning canned JSON."""

from app.modules.interview.questions import PlannedQuestion, RubricItem
from tests.test_interview_follow_ups import answered
from tests.test_interview_llm import FakeSession, make

R = RubricItem
ANSWER = "저는 검출 모델을 직접 학습시키고 평가 지표를 비교해서 가장 나은 설정을 골랐습니다."
FOLLOW_ANSWER = "정확도가 비슷한 후보 중에서 추론 속도가 빠른 쪽을 골랐고 팀원과 상의했습니다."


def main_q(qid="q1", items=(R.REASONING, R.SPECIFICITY)) -> PlannedQuestion:
    return PlannedQuestion(
        id=qid,
        kind="document",
        subtype="experience",
        text="맡은 역할은 무엇인가요?",
        intent="실제 기여를 확인한다.",
        source_quote="검출 모델을 학습",
        rubric_items=list(items),
    )


def follow_q(parent="q1", qid="fu-1") -> PlannedQuestion:
    return PlannedQuestion(
        id=qid,
        kind="follow_up",
        subtype="reasoning",
        text="그 설정을 고른 이유는 무엇인가요?",
        parent_id=parent,
        round=2,
    )


def grade(g=3, quote="검출 모델을 직접 학습시키고", source="main") -> dict:
    return {
        "grade": g,
        "evidence_quote": quote,
        "evidence_source": source,
        "reason": "근거가 있다.",
        "improvement": "수치를 더하세요.",
    }


def good_eval(items=(R.REASONING, R.SPECIFICITY), **overrides) -> dict:
    return {i.value: overrides.get(i.value, grade()) for i in items}


SUMMARY = {
    "strengths": ["역할이 분명합니다."],
    "improvements": ["수치를 더하세요."],
    "next_goals": ["결과 확인 방법을 말해 보세요."],
}


def session(**replies) -> FakeSession:
    replies.setdefault("evaluation", good_eval())
    replies.setdefault("summary", SUMMARY)
    return FakeSession(replies)


async def test_not_evaluable_answers_make_no_model_call() -> None:
    interview, _ = make()
    fake = session()
    result = await interview.evaluate([answered(main_q(), "")], fake)
    (item,) = result.items
    assert (item.status, item.not_evaluable_reason, item.score) == (
        "not_evaluable",
        "no_response",
        None,
    )
    assert fake.calls == []  # no item call and no summary call
    assert result.overall_score is None
    assert result.summary.strengths == []


class SchemaSession(FakeSession):
    """Also records the JSON schema of every call."""

    def __init__(self, replies) -> None:
        super().__init__(replies)
        self.schemas: list[dict] = []

    async def complete_json(self, prompt, schema, **kwargs):
        self.schemas.append(schema)
        return await super().complete_json(prompt, schema, **kwargs)


async def test_an_evaluable_answer_is_graded_in_one_call_and_scored() -> None:
    interview, _ = make()
    fake = SchemaSession({"evaluation": good_eval(), "summary": SUMMARY})
    result = await interview.evaluate([answered(main_q(), ANSWER)], fake)
    (item,) = result.items
    assert item.status == "evaluated" and not item.partial and item.excluded_items == []
    assert item.score == 15.0  # 20 * (3 + 3) / (4 * 2)
    assert set(item.grades) == {R.REASONING, R.SPECIFICITY}
    assert item.grades[R.REASONING].evidence_quote == "검출 모델을 직접 학습시키고"
    assert result.overall_score == 15.0
    assert result.summary.strengths == SUMMARY["strengths"]
    assert fake.count("evaluation") == 1 and fake.count("summary") == 1
    assert [name for name, _ in fake.calls] == ["evaluation", "summary"]  # summary last
    prompt = fake.calls[0][1]
    assert "맡은 역할은 무엇인가요?" in prompt and "실제 기여를 확인한다." in prompt
    assert "검출 모델을 학습" in prompt and ANSWER in prompt
    assert "문제 해결과 판단 근거" in prompt and "경험·행동의 구체성" in prompt
    assert "협업과 의사소통" not in prompt and "결과와 학습" not in prompt  # only applicable
    schema = fake.schemas[0]
    assert set(schema["properties"]) == {"reasoning", "specificity"}
    assert set(schema["required"]) == {"reasoning", "specificity"}
    entry = schema["properties"]["reasoning"]["properties"]
    assert (entry["grade"]["minimum"], entry["grade"]["maximum"]) == (0, 4)
    assert entry["evidence_source"]["enum"] == ["main"]


async def test_follow_up_answers_are_bundled_into_the_parents_single_call() -> None:
    interview, _ = make()
    fake = SchemaSession(
        {
            "evaluation": good_eval(
                reasoning=grade(4, "추론 속도가 빠른 쪽을 골랐고", "follow_up")
            ),
            "summary": SUMMARY,
        }
    )
    items = [answered(main_q(), ANSWER), answered(follow_q(), FOLLOW_ANSWER)]
    result = await interview.evaluate(items, fake)
    (item,) = result.items  # the follow-up has no entry of its own
    assert item.question_id == "q1" and item.follow_up_ids == ["fu-1"]
    assert item.status == "evaluated" and not item.partial
    assert item.grades[R.REASONING].evidence_source == "follow_up"
    assert fake.count("evaluation") == 1
    prompt = fake.calls[0][1]
    assert FOLLOW_ANSWER in prompt and "그 설정을 고른 이유는 무엇인가요?" in prompt
    entry = fake.schemas[0]["properties"]["reasoning"]["properties"]
    assert entry["evidence_source"]["enum"] == ["main", "follow_up"]


async def test_an_unevaluable_follow_up_is_left_out_and_the_main_answer_is_still_graded() -> None:
    interview, _ = make()
    fake = SchemaSession({"evaluation": good_eval(), "summary": SUMMARY})
    items = [answered(main_q(), ANSWER), answered(follow_q(), "")]
    result = await interview.evaluate(items, fake)
    (item,) = result.items
    assert item.status == "evaluated" and item.follow_up_ids == []
    assert "그 설정을 고른 이유는 무엇인가요?" not in fake.calls[0][1]
    entry = fake.schemas[0]["properties"]["reasoning"]["properties"]
    assert entry["evidence_source"]["enum"] == ["main"]


async def test_an_unevaluable_main_answer_makes_no_call_even_with_a_follow_up() -> None:
    interview, _ = make()
    fake = session()
    items = [answered(main_q(), ""), answered(follow_q(), FOLLOW_ANSWER)]
    result = await interview.evaluate(items, fake)
    assert [i.status for i in result.items] == ["not_evaluable"]
    assert fake.calls == []


async def test_a_question_without_rubric_items_is_not_scored_and_makes_no_call() -> None:
    interview, _ = make()
    fake = session()
    closing = main_q("closing", items=())
    result = await interview.evaluate([answered(closing, ANSWER)], fake)
    (item,) = result.items
    assert (item.status, item.score, item.grades) == ("not_scored", None, {})
    assert fake.calls == []


async def test_a_quote_missing_from_the_answer_excludes_only_that_item() -> None:
    interview, _ = make()
    fake = session(
        evaluation=good_eval(
            specificity=grade(1, "답변에 없는 문장입니다", "main"), reasoning=grade(4)
        )
    )
    result = await interview.evaluate([answered(main_q(), ANSWER)], fake)
    (item,) = result.items
    assert item.status == "evaluated" and item.partial
    assert item.excluded_items == [R.SPECIFICITY]
    assert set(item.grades) == {R.REASONING}
    assert item.score == 20.0  # remaining item only
    assert fake.count("evaluation") == 1  # partial invalidation is not retried
    assert result.overall_score == 20.0


async def test_quotes_match_ignoring_spacing_and_punctuation() -> None:
    interview, _ = make()
    fake = session(evaluation=good_eval(reasoning=grade(3, "검출  모델을, 직접 학습시키고!")))
    result = await interview.evaluate([answered(main_q(), ANSWER)], fake)
    assert R.REASONING in result.items[0].grades and not result.items[0].partial


async def test_a_quote_must_come_from_the_answer_named_as_its_source() -> None:
    interview, _ = make()
    wrong = grade(3, FOLLOW_ANSWER[:15], "main")  # quoted from the follow-up but labelled main
    fake = session(evaluation=good_eval(reasoning=wrong))
    items = [answered(main_q(), ANSWER), answered(follow_q(), FOLLOW_ANSWER)]
    result = await interview.evaluate(items, fake)
    assert result.items[0].excluded_items == [R.REASONING]


async def test_grades_zero_and_one_may_come_without_a_quote_but_higher_grades_may_not() -> None:
    interview, _ = make()
    fake = session(evaluation=good_eval(reasoning=grade(0, ""), specificity=grade(2, "", "main")))
    result = await interview.evaluate([answered(main_q(), ANSWER)], fake)
    (item,) = result.items
    assert item.grades[R.REASONING].grade == 0
    assert item.excluded_items == [R.SPECIFICITY]
    assert item.score == 0.0


async def test_all_items_invalid_after_the_retry_fails_the_question() -> None:
    interview, _ = make()
    nothing = grade(3, "답변에 없는 문장입니다")
    fake = session(evaluation=good_eval(reasoning=nothing, specificity=nothing))
    result = await interview.evaluate([answered(main_q(), ANSWER)], fake)
    (item,) = result.items
    assert (item.status, item.score, item.grades) == ("failed", None, {})
    assert "item_evaluation_failed" in result.warnings
    assert result.overall_score is None
    assert fake.count("evaluation") == 2 and fake.seeds[0] != fake.seeds[1]
    assert fake.count("summary") == 0  # nothing evaluated, so no summary call
    assert result.summary.strengths == []


async def test_a_structural_failure_is_retried_once_with_another_seed_and_a_hint() -> None:
    interview, _ = make()
    broken = good_eval(reasoning={**grade(), "grade": 7})  # out of range
    fake = session(evaluation=[broken, good_eval()])
    result = await interview.evaluate([answered(main_q(), ANSWER)], fake)
    assert result.items[0].status == "evaluated"
    assert fake.count("evaluation") == 2
    assert fake.seeds[0] != fake.seeds[1]
    first, second = fake.calls[0][1], fake.calls[1][1]
    assert second.startswith(first) and len(second) > len(first)  # hint appended


async def test_a_missing_key_or_bad_json_twice_fails_the_question() -> None:
    interview, _ = make()
    for bad in ({"reasoning": grade()}, "not an object", {**good_eval(), "specificity": 5}):
        fake = session(evaluation=bad)
        result = await interview.evaluate([answered(main_q(), ANSWER)], fake)
        assert result.items[0].status == "failed"
        assert fake.count("evaluation") == 2
        assert result.warnings == ["item_evaluation_failed"]


async def test_one_failed_question_does_not_stop_the_others() -> None:
    interview, _ = make()
    fake = session(evaluation=[{}, {}, good_eval()])
    items = [answered(main_q("q1"), ANSWER), answered(main_q("q2"), ANSWER)]
    result = await interview.evaluate(items, fake)
    assert [i.status for i in result.items] == ["failed", "evaluated"]
    assert result.overall_score == result.items[1].score == 15.0


async def test_overall_averages_only_evaluated_questions() -> None:
    interview, _ = make()
    low = good_eval(reasoning=grade(1), specificity=grade(1))  # 5.0
    fake = session(evaluation=[good_eval(), low])
    items = [
        answered(main_q("q1"), ANSWER),
        answered(main_q("q2"), ANSWER),
        answered(main_q("q3"), ""),
        answered(main_q("q4", items=()), ANSWER),
    ]
    result = await interview.evaluate(items, fake)
    assert [i.status for i in result.items] == [
        "evaluated",
        "evaluated",
        "not_evaluable",
        "not_scored",
    ]
    assert result.overall_score == 10.0  # (15 + 5) / 2


async def test_the_summary_is_one_final_call_with_grades_and_no_transcripts() -> None:
    interview, _ = make()
    fake = session()
    items = [answered(main_q("q1"), ANSWER), answered(main_q("q2"), ANSWER)]
    await interview.evaluate(items, fake)
    assert [n for n, _ in fake.calls] == ["evaluation", "evaluation", "summary"]
    prompt = fake.calls[-1][1]
    assert "근거가 있다." in prompt and "수치를 더하세요." in prompt
    assert ANSWER not in prompt


async def test_a_failing_summary_is_retried_then_left_empty_with_a_warning() -> None:
    interview, _ = make()
    fake = session(summary=[{"strengths": "x"}, {"strengths": ["a"]}])
    result = await interview.evaluate([answered(main_q(), ANSWER)], fake)
    assert fake.count("summary") == 2
    assert result.summary.strengths == [] and result.summary.improvements == []
    assert result.warnings == ["summary_failed"]
    assert result.items[0].status == "evaluated"  # item results survive


async def test_summary_lists_are_capped_at_three() -> None:
    interview, _ = make()
    many = {k: [f"{k}{n}" for n in range(5)] for k in SUMMARY}
    result = await interview.evaluate([answered(main_q(), ANSWER)], session(summary=many))
    assert result.summary.strengths == ["strengths0", "strengths1", "strengths2"]


async def test_a_long_summary_prompt_is_shortened_to_fit_the_context() -> None:
    interview, _ = make()
    long_grade = {**grade(), "reason": "가" * 200, "improvement": "나" * 200}
    evaluation = {i.value: long_grade for i in (R.REASONING, R.SPECIFICITY)}
    fake = session(evaluation=evaluation)
    items = [answered(main_q(f"q{n}"), ANSWER) for n in range(9)]
    await interview.evaluate(items, fake)
    from app.ai.interview_llm import PROMPT_TOKEN_BUDGET

    assert await fake.count_tokens(fake.calls[-1][1]) <= PROMPT_TOKEN_BUDGET
    assert fake.calls[-1][0] == "summary"


async def test_progress_reports_each_question_then_summarizing() -> None:
    interview, _ = make()
    events: list[dict] = []
    items = [answered(main_q("q1"), ANSWER), answered(main_q("q2"), ""), answered(follow_q(), "")]
    await interview.evaluate(items, session(), events.append)
    assert events == [
        {"stage": "evaluating", "index": 1, "total": 2},
        {"stage": "evaluating", "index": 2, "total": 2},
        {"stage": "summarizing"},
    ]


async def test_a_broken_progress_observer_does_not_interrupt_evaluation() -> None:
    interview, _ = make()

    def boom(event):
        raise RuntimeError("observer")

    result = await interview.evaluate([answered(main_q(), ANSWER)], session(), boom)
    assert result.items[0].status == "evaluated"


async def test_time_running_out_fails_the_remaining_questions_but_still_returns() -> None:
    now = [0.0]
    interview, _ = make(clock=lambda: now[0], evaluation_timeout_seconds=600)
    fake = session()
    fake.on_call = lambda: now.__setitem__(0, now[0] + 400)
    items = [answered(main_q(f"q{n}"), ANSWER) for n in range(3)]
    result = await interview.evaluate(items, fake)
    assert [i.status for i in result.items] == ["evaluated", "evaluated", "failed"]
    assert "evaluation_timeout" in result.warnings
    assert "item_evaluation_failed" not in result.warnings
    assert fake.count("evaluation") == 2
    assert result.overall_score == 15.0
    assert result.elapsed_seconds == 800.0


async def test_the_model_name_comes_from_the_settings_when_there_are_some() -> None:
    from types import SimpleNamespace

    interview, llm = make()
    llm.settings = SimpleNamespace(summary_model_path=".models/Qwen3.5-9B-Q4_K_M.gguf")
    result = await interview.evaluate([answered(main_q(), ANSWER)], session())
    assert result.model == "Qwen3.5-9B-Q4_K_M.gguf"


async def test_a_short_quote_is_not_valid_evidence_for_a_non_zero_grade() -> None:
    interview, _ = make()
    # "모델을" is in the answer but is too short (3 characters) to show anything.
    fake = session(evaluation=good_eval(reasoning=grade(3, "모델을"), specificity=grade(3)))
    result = await interview.evaluate([answered(main_q(), ANSWER)], fake)
    (item,) = result.items
    assert item.excluded_items == [R.REASONING] and item.partial
    assert set(item.grades) == {R.SPECIFICITY}
    # The shortest quote that still counts (8 characters without spaces).
    fake = session(
        evaluation=good_eval(reasoning=grade(3, "검출 모델을 직접 학습"), specificity=grade(3))
    )
    result = await interview.evaluate([answered(main_q(), ANSWER)], fake)
    assert result.items[0].excluded_items == []


class TokenSession(SchemaSession):
    """One token per character, so long answers force the prompt to shrink."""

    async def count_tokens(self, prompt: str) -> int:
        return len(prompt)


FILLER = "가" * 4000
TAIL = "마지막에 덧붙인 결과 확인 방법과 배운 점을 정리했습니다"


async def test_long_answers_are_cut_until_the_prompt_fits_the_context() -> None:
    from app.ai.interview_llm import PROMPT_TOKEN_BUDGET

    interview, _ = make()
    fake = TokenSession({"evaluation": good_eval(), "summary": SUMMARY})
    await interview.evaluate([answered(main_q(), ANSWER + FILLER)], fake)
    prompt = fake.calls[0][1]
    assert len(prompt) <= PROMPT_TOKEN_BUDGET
    assert ANSWER in prompt  # the start of the answer is kept
    assert prompt.count("가") < 1500  # cut below the default cap


async def test_a_quote_from_the_part_cut_out_of_the_prompt_is_invalid() -> None:
    # The model never saw that text, so a quote from it cannot be real evidence.
    interview, _ = make()
    evaluation = good_eval(reasoning=grade(3, TAIL), specificity=grade(3))
    fake = TokenSession({"evaluation": evaluation, "summary": SUMMARY})
    result = await interview.evaluate([answered(main_q(), ANSWER + FILLER + TAIL)], fake)
    (item,) = result.items
    assert item.excluded_items == [R.REASONING] and item.partial
    assert TAIL not in fake.calls[0][1]


async def test_a_generic_answer_graded_one_without_a_quote_is_valid() -> None:
    interview, _ = make()
    fake = session(evaluation=good_eval(reasoning=grade(1, ""), specificity=grade(1, "")))
    result = await interview.evaluate([answered(main_q(), ANSWER)], fake)
    (item,) = result.items
    assert item.status == "evaluated" and not item.partial
    assert item.score == 5.0 and fake.count("evaluation") == 1


async def test_a_given_quote_is_still_checked_for_grade_one_and_grade_two_needs_one() -> None:
    interview, _ = make()
    evaluation = good_eval(reasoning=grade(1, "모델을"), specificity=grade(2, ""))
    result = await interview.evaluate([answered(main_q(), ANSWER)], session(evaluation=evaluation))
    # Both items are invalid, so the question fails after its retry.
    assert result.items[0].status == "failed"
    evaluation = good_eval(reasoning=grade(1, "답변에 없는 문장입니다"), specificity=grade(3))
    result = await interview.evaluate([answered(main_q(), ANSWER)], session(evaluation=evaluation))
    assert result.items[0].excluded_items == [R.REASONING]
