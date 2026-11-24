"""Domain tests for composition, questions, rubric and follow_ups (public interfaces only)."""

import pytest

from app.modules.interview.composition import Composition, TurnRules
from app.modules.interview.follow_ups import (
    GapType,
    allowed_gaps,
    build_fallback_follow_up,
    detect_rule_gaps,
    fallback_question_text,
    follow_up_candidate,
    select_follow_ups,
    we_only,
)
from app.modules.interview.questions import (
    CommonCategory,
    FinalUtterance,
    ItemRecord,
    Material,
    PlannedQuestion,
    RubricItem,
    dedupe_questions,
    find_banned_topic,
    is_double_question,
    validate_material,
    validate_question,
)
from app.modules.interview.rubric import (
    GRADE_DEFINITIONS,
    RUBRIC,
    assess_evaluability,
    overall,
    score,
)


def make_question(
    text="질문입니다.",
    *,
    qid="q1",
    kind="common",
    subtype="motivation",
    rubric_items=tuple(RubricItem),
    source_quote=None,
    round=1,
) -> PlannedQuestion:
    return PlannedQuestion(
        id=qid,
        kind=kind,
        subtype=subtype,
        text=text,
        intent="",
        source_quote=source_quote,
        rubric_items=list(rubric_items),
        parent_id=None,
        bank_id=None,
        round=round,
    )


def make_item(question, text, *, voiced_ms, reason="silence") -> ItemRecord:
    utterances = (
        [FinalUtterance("u1", 1000, 1000 + voiced_ms, text, voiced_ms)] if voiced_ms or text else []
    )
    return ItemRecord(
        question=question,
        shown_ms=0,
        answer_started_ms=1000 if utterances else None,
        ended_ms=60000,
        advance_reason=reason,
        replay_used=False,
        utterances=utterances,
        transcript=text,
    )


# ---------------------------------------------------------------- composition


def test_default_composition_matches_plan():
    c = Composition()
    assert (c.common_basic, c.personality_behavioral, c.personality_situational) == (2, 1, 1)
    assert (c.job, c.experience, c.max_follow_ups) == (2, 2, 2)
    assert c.personality == 2


def test_composition_orders_questions_by_interview_flow():
    subtypes = [
        "closing",
        "personality_behavioral",
        "future_plan",
        "experience",
        "motivation",
        "job",
        "self_introduction",
    ]
    questions = [make_question(qid=s, subtype=s) for s in subtypes]
    ordered = [q.subtype for q in Composition().order_questions(questions)]
    assert ordered[0] == "self_introduction"
    assert ordered[1] == "motivation"
    assert set(ordered[2:4]) == {"job", "experience"}
    assert ordered[4:] == ["personality_behavioral", "future_plan", "closing"]


def test_reading_time_is_three_seconds_plus_chars_over_seven_capped():
    rules = TurnRules()
    assert rules.reading_ms("") == 3000
    assert rules.reading_ms("가" * 7) == 4000
    assert rules.reading_ms("가" * 700) == 15000


def test_turn_rule_defaults_and_answer_limit_for_self_introduction():
    rules = TurnRules()
    assert rules.silence_ms == 4000
    assert rules.min_answer_ms == 10000
    assert rules.no_response_ms == 15000
    assert rules.endpoint_ms == 500
    assert rules.final_wait_cap_ms == 3000
    intro = make_question(subtype=CommonCategory.SELF_INTRODUCTION.value)
    assert rules.answer_limit_for(intro) == 90000
    assert rules.answer_limit_for(make_question()) == 120000


# ------------------------------------------------------------------ questions


def test_material_quote_must_appear_in_document_ignoring_whitespace():
    doc = "저는 캡스톤  프로젝트에서\n백엔드 API를 설계했습니다."
    ok = Material(
        kind="project", quote="캡스톤 프로젝트에서 백엔드 API를 설계했습니다.", summary="x"
    )
    bad = Material(kind="project", quote="프론트엔드를 설계했습니다.", summary="x")
    assert validate_material(ok, doc) is None
    assert validate_material(bad, doc) == "quote_not_in_document"


def test_material_with_banned_topic_is_rejected():
    doc = "저희 가족은 부산에 살고 있으며 저는 동아리 회장을 했습니다."
    material = Material(kind="activity", quote="저희 가족은 부산에 살고 있으며", summary="가족")
    assert validate_material(material, doc) == "banned_topic"


@pytest.mark.parametrize(
    "text",
    [
        "어린 시절 가족 분위기는 어땠나요?",
        "올해 나이가 어떻게 되시나요?",
        "결혼 계획이 있으신가요?",
        "고향이 어디인가요?",
        "종교가 있으신가요?",
        "외모에 대해 어떻게 생각하세요?",
        "재산 규모는 어느 정도인가요?",
        "아버지께서는 어떤 일을 하시나요?",
        "어머니 직업이 무엇인가요?",
        "부모님 직업은 무엇인가요?",
        "자녀 계획이 있으신가요?",
        "지금 어디에 사시나요?",
        "키는 몇 센티미터인가요?",
        "올해 몇 년생인가요?",
        "연세가 어떻게 되시나요?",
        "가정환경은 어땠나요?",
        "남자친구 있으세요?",
        "여자친구와는 잘 지내시나요?",
        "애인은 있으신가요?",
        "부모의 직업은 무엇인가요?",
    ],
)
def test_banned_topics_are_detected(text):
    assert find_banned_topic(text) is not None
    assert validate_question(make_question(text)) == "banned_topic"


@pytest.mark.parametrize(
    "text",
    [
        "대학 시절에 동아리에서 앱을 만들었습니다",
        "제안 거절에 대응한 방법은 무엇인가요?",
        "연세대학교 캡스톤디자인 프로젝트에서 백엔드를 맡았습니다",
        "매출 20% 신장에 기여했습니다",
        "API 키가 노출되는 문제를 해결했습니다",
        "부동산 시세 예측 모델을 개발했습니다",
        "개발자로서의 성장 과정에서 가장 어려웠던 점은 무엇인가요?",
        "트리에서 부모 노드를 찾는 알고리즘을 구현했습니다",
        "가족 같은 팀 분위기를 만들었습니다",
        "그 기술을 어디에 사용했나요?",
        "이 라이브러리를 어디 사용하셨나요?",
        "트리에서 형제 노드를 비교하는 방법을 설명해 주세요",
    ],
)
def test_job_relevant_text_is_not_flagged_as_banned(text):
    assert find_banned_topic(text) is None


def test_naive_bayes_is_not_mistaken_for_age_topic():
    assert find_banned_topic("나이브 베이즈를 선택한 이유는 무엇인가요?") is None


def test_question_length_limits_differ_for_situational():
    long_text = "가" * 150 + "어떻게 하시겠습니까?"
    assert validate_question(make_question("가" * 101)) == "too_long"
    assert validate_question(make_question("가" * 100)) is None
    assert validate_question(make_question(long_text, subtype="personality_situational")) is None
    too_long = make_question("가" * 201, subtype="personality_situational")
    assert validate_question(too_long) == "too_long"


def test_double_questions_are_rejected():
    assert is_double_question("이 프로젝트의 역할은 무엇인가요? 그리고 배운 점은 무엇인가요?")
    assert not is_double_question("이 프로젝트에서 맡은 역할은 무엇인가요?")
    q = make_question("역할은 무엇이었나요? 결과는 어땠나요?")
    assert validate_question(q) == "double_question"


def test_empty_question_is_rejected():
    assert validate_question(make_question("  ")) == "empty"


def test_dedupe_drops_same_material_and_subtype():
    a = make_question(
        "A 프로젝트에서 맡은 역할은 무엇인가요?",
        qid="a",
        kind="document",
        subtype="experience",
        source_quote="A 프로젝트를 했다",
    )
    b = make_question(
        "서버 구성에서 가장 어려웠던 점은 무엇인가요?",
        qid="b",
        kind="document",
        subtype="experience",
        source_quote="A  프로젝트를 했다",
    )
    c = make_question(
        "서버 구성에서 가장 어려웠던 점은 무엇인가요?",
        qid="c",
        kind="document",
        subtype="job",
        source_quote="A 프로젝트를 했다",
    )
    assert [q.id for q in dedupe_questions([a, b, c])] == ["a", "c"]


def test_dedupe_drops_near_duplicate_text_but_keeps_distinct():
    a = make_question("X 프로젝트에서 본인이 맡은 역할은 무엇인가요?", qid="a")
    b = make_question("X 프로젝트에서 본인이 맡은 역할은 무엇이었나요?", qid="b")
    c = make_question("서버 비용을 줄이기 위해 어떤 대안을 비교했나요?", qid="c")
    assert [q.id for q in dedupe_questions([a, b, c])] == ["a", "c"]


# --------------------------------------------------------------------- rubric


def test_rubric_has_five_items_with_three_levels_and_five_grades():
    assert set(RUBRIC) == set(RubricItem) and len(RUBRIC) == 5
    for criteria in RUBRIC.values():
        assert criteria.low and criteria.mid and criteria.high
    assert sorted(GRADE_DEFINITIONS) == [0, 1, 2, 3, 4]


def test_score_normalises_by_applicable_item_count():
    grades = {RubricItem.UNDERSTANDING: 4, RubricItem.REASONING: 2}
    result = score(grades, [RubricItem.UNDERSTANDING, RubricItem.REASONING])
    assert result.score == 15.0 and not result.partial
    five = {item: 4 for item in RubricItem}
    assert score(five, list(RubricItem)).score == 20.0
    assert score({item: 0 for item in RubricItem}, list(RubricItem)).score == 0.0


def test_score_excludes_invalid_items_missing_from_grades():
    grades = {RubricItem.UNDERSTANDING: 4}  # REASONING was invalidated (no evidence)
    result = score(grades, [RubricItem.UNDERSTANDING, RubricItem.REASONING])
    assert result.score == 20.0
    assert result.excluded_items == (RubricItem.REASONING,)
    assert result.partial


def test_score_rejects_out_of_range_grade_and_empty_applicable():
    with pytest.raises(ValueError):
        score({RubricItem.UNDERSTANDING: 5}, [RubricItem.UNDERSTANDING])
    with pytest.raises(ValueError):
        score({}, [RubricItem.UNDERSTANDING])


def test_overall_averages_scored_items_only():
    assert overall([15.0, None, 5.0]) == 10.0
    assert overall([None]) is None
    assert overall([]) is None


def test_no_answer_is_not_evaluable_as_no_response():
    q = make_question()
    assert assess_evaluability(make_item(q, "", voiced_ms=0, reason="no_response")) == "no_response"
    assert assess_evaluability(make_item(q, "", voiced_ms=0)) == "no_response"


def test_short_answer_is_too_short_below_twenty_hangul_syllables():
    q = make_question()
    assert assess_evaluability(make_item(q, "가" * 19, voiced_ms=8000)) == "too_short"
    assert assess_evaluability(make_item(q, "hello world 123 " * 5, voiced_ms=4000)) == "too_short"
    assert assess_evaluability(make_item(q, "가" * 20, voiced_ms=8000)) is None


def test_few_syllables_over_long_voice_is_recognition_failed():
    q = make_question()
    assert assess_evaluability(make_item(q, "가" * 5, voiced_ms=10000)) == "recognition_failed"
    assert assess_evaluability(make_item(q, "가" * 25, voiced_ms=30000)) == "recognition_failed"
    # Under 5 s of voice the answer is merely too short, not a recognition problem.
    assert assess_evaluability(make_item(q, "가" * 5, voiced_ms=4000)) == "too_short"


# ------------------------------------------------------------------ follow_ups


def test_we_only_requires_we_without_first_person_singular():
    assert we_only("우리 팀은 서버를 만들었고 저희는 배포했습니다.")
    assert not we_only("우리 팀에서 제가 서버를 만들었습니다.")
    assert not we_only("저는 서버를 만들었습니다.")
    assert not we_only("서버를 만들었습니다.")


def test_situational_gaps_exclude_result_and_learning_and_add_ncs_gaps():
    situational = make_question(subtype="personality_situational")
    gaps = allowed_gaps(situational)
    assert GapType.RESULT_CHECK not in gaps and GapType.LEARNING not in gaps
    assert {GapType.CORE_TASK, GapType.STAKEHOLDERS, GapType.EXPECTED_RESULT} <= set(gaps)
    experience = allowed_gaps(make_question(subtype="experience"))
    assert GapType.RESULT_CHECK in experience and GapType.LEARNING in experience
    assert GapType.CORE_TASK not in experience


def test_experience_gaps_follow_priority_order():
    q = make_question(subtype="experience", kind="document")
    assert allowed_gaps(q) == [
        GapType.OWN_ROLE,
        GapType.LEARNING,
        GapType.REASONING,
        GapType.CONCRETE_EXAMPLE,
        GapType.COLLABORATION,
        GapType.RESULT_CHECK,
    ]


def test_detect_rule_gaps_flags_own_role_when_only_we():
    q = make_question(subtype="experience", kind="document")
    we = make_item(
        q,
        "우리 팀은 함께 서비스를 만들었고 결과가 좋았습니다 정말로 그렇게 했습니다",
        voiced_ms=9000,
    )
    me = make_item(
        q, "제가 서비스를 만들었고 결과가 좋았습니다 정말로 그렇게 했습니다 하하", voiced_ms=9000
    )
    assert detect_rule_gaps(we) == [GapType.OWN_ROLE]
    assert detect_rule_gaps(me) == []


def test_candidate_orders_gaps_by_priority_and_filters_disallowed():
    q = make_question(subtype="experience", kind="document")
    item = make_item(q, "가" * 40, voiced_ms=9000)
    candidate = follow_up_candidate(item, [GapType.RESULT_CHECK, GapType.OWN_ROLE])
    assert candidate is not None
    assert candidate.parent_id == "q1"
    assert candidate.gaps == [GapType.OWN_ROLE, GapType.RESULT_CHECK]
    sit = make_question(subtype="personality_situational")
    sit_item = make_item(sit, "가" * 40, voiced_ms=9000)
    candidate = follow_up_candidate(
        sit_item, [GapType.LEARNING, GapType.RESULT_CHECK, GapType.CORE_TASK]
    )
    assert candidate is not None and candidate.gaps == [GapType.CORE_TASK]


def test_no_candidate_for_unevaluable_unscored_or_follow_up_questions():
    q = make_question(subtype="experience", kind="document")
    gaps = [GapType.OWN_ROLE]
    assert follow_up_candidate(make_item(q, "", voiced_ms=0), gaps) is None
    assert follow_up_candidate(make_item(q, "가" * 10, voiced_ms=5000), gaps) is None
    closing = make_question(subtype="closing", rubric_items=())
    assert follow_up_candidate(make_item(closing, "가" * 40, voiced_ms=9000), gaps) is None
    child = make_question(kind="follow_up", subtype="own_role")
    assert follow_up_candidate(make_item(child, "가" * 40, voiced_ms=9000), gaps) is None
    assert follow_up_candidate(make_item(q, "가" * 40, voiced_ms=9000), []) is None


def test_select_follow_ups_picks_most_gaps_first_with_stable_ties():
    q = make_question(subtype="experience", kind="document")

    def cand(qid, gaps):
        item = make_item(
            make_question(qid=qid, subtype="experience", kind="document"), "가" * 40, voiced_ms=9000
        )
        candidate = follow_up_candidate(item, gaps)
        assert candidate is not None
        return candidate

    del q
    a = cand("a", [GapType.OWN_ROLE])
    b = cand("b", [GapType.OWN_ROLE, GapType.LEARNING, GapType.REASONING])
    c = cand("c", [GapType.OWN_ROLE])
    d = cand("d", [GapType.LEARNING, GapType.REASONING])
    assert [x.parent_id for x in select_follow_ups([a, b, c, d], 2)] == ["b", "d"]
    assert [x.parent_id for x in select_follow_ups([a, c], 5)] == ["a", "c"]
    assert select_follow_ups([a, b], 0) == []


def test_fallback_text_exists_for_every_gap_and_builds_round_two_question():
    for gap in GapType:
        assert fallback_question_text(gap)
    assert fallback_question_text(GapType.OWN_ROLE) == "그중 본인이 직접 맡은 부분은 무엇이었나요?"
    parent = make_question(
        subtype="experience",
        kind="document",
        rubric_items=(RubricItem.SPECIFICITY, RubricItem.LEARNING),
    )
    child = build_fallback_follow_up(parent, GapType.OWN_ROLE)
    assert child.kind == "follow_up" and child.round == 2
    assert child.parent_id == parent.id and child.subtype == "own_role"
    assert child.text == fallback_question_text(GapType.OWN_ROLE)
    assert child.rubric_items == parent.rubric_items


def test_dedupe_keeps_same_template_questions_about_different_materials():
    a = make_question(
        "A 쇼핑몰 프로젝트에서 본인이 맡은 역할은 무엇인가요?",
        qid="a",
        kind="document",
        subtype="experience",
        source_quote="A 쇼핑몰을 만들었다",
    )
    b = make_question(
        "B 챗봇 프로젝트에서 본인이 맡은 역할은 무엇인가요?",
        qid="b",
        kind="document",
        subtype="experience",
        source_quote="B 챗봇을 만들었다",
    )
    assert [q.id for q in dedupe_questions([a, b])] == ["a", "b"]
    # Without a source quote on one side the text similarity rule still applies.
    c = make_question("B 챗봇 프로젝트에서 본인이 맡은 역할은 무엇인가요?", qid="c")
    assert [q.id for q in dedupe_questions([b, c])] == ["b"]


def test_gaps_are_limited_to_the_questions_rubric_items():
    motivation = make_question(subtype="motivation", rubric_items=(RubricItem.UNDERSTANDING,))
    assert allowed_gaps(motivation) == []
    experience = make_question(
        subtype="experience",
        kind="document",
        rubric_items=(RubricItem.SPECIFICITY, RubricItem.REASONING, RubricItem.LEARNING),
    )
    assert allowed_gaps(experience) == [
        GapType.OWN_ROLE,
        GapType.LEARNING,
        GapType.REASONING,
        GapType.CONCRETE_EXAMPLE,
        GapType.RESULT_CHECK,
    ]


def test_we_only_motivation_answer_does_not_produce_own_role():
    q = make_question(subtype="motivation", rubric_items=(RubricItem.UNDERSTANDING,))
    item = make_item(
        q, "우리 회사의 비전에 공감하고 그 방향에서 일하고 싶어서 지원했습니다", voiced_ms=9000
    )
    assert detect_rule_gaps(item) == []
    assert follow_up_candidate(item, [GapType.OWN_ROLE]) is None


def test_we_only_ignores_first_person_words_inside_other_words():
    assert we_only("우리 팀은 문제가 생겼을 때 함께 해결했습니다")
    assert we_only("저희는 과제가 많아서 역할을 나눴습니다")
    assert we_only("우리는 안내가 부족했습니다")
    assert not we_only("우리 팀에서 제가 문제를 해결했습니다")
    assert not we_only("그때 내가 안내를 맡았습니다 우리 팀은 만족했습니다")


def test_learning_fallback_is_not_a_yes_no_question():
    assert fallback_question_text(GapType.LEARNING) == "그 경험 이후 어떤 점이 달라졌나요?"


def test_segmenter_related_rule_defaults():
    rules = TurnRules()
    assert rules.max_utterance_ms == 8000
    assert rules.pre_roll_ms == 200
