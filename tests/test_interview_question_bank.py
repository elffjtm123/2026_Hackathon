"""question_bank tests: seeded sampling through sample_common."""

import random

from app.modules.interview.composition import Composition
from app.modules.interview.question_bank import (
    BANK_BY_ID,
    COMMON_QUESTIONS,
    PersonalityTopic,
    sample_common,
    to_planned,
)
from app.modules.interview.questions import CommonCategory, validate_question


def sample(seed=0, *, job=None, exclude=(), composition=None):
    return sample_common(composition or Composition(), job, list(exclude), random.Random(seed))


def test_bank_has_at_least_three_questions_per_category_and_topic():
    for category in CommonCategory:
        if category in (
            CommonCategory.PERSONALITY_BEHAVIORAL,
            CommonCategory.PERSONALITY_SITUATIONAL,
        ):
            for topic in PersonalityTopic:
                n = [q for q in COMMON_QUESTIONS if q.category == category and q.topic == topic]
                assert len(n) >= 3, (category, topic)
        else:
            assert len([q for q in COMMON_QUESTIONS if q.category == category]) >= 3, category


def test_bank_ids_are_unique_and_sources_are_marked():
    assert len(BANK_BY_ID) == len(COMMON_QUESTIONS)
    assert {q.source for q in COMMON_QUESTIONS} <= {"NCS 문형", "OPM 문형", "자체 작성"}


def test_every_bank_question_passes_question_validation():
    for q in COMMON_QUESTIONS:
        planned = sample_planned(q)
        assert validate_question(planned) is None, (q.id, q.text)


def sample_planned(bank_question):
    return to_planned(bank_question, job="백엔드 개발자")


def test_behavioral_and_situational_follow_the_writing_rules():
    for q in COMMON_QUESTIONS:
        if q.category == CommonCategory.PERSONALITY_BEHAVIORAL:
            assert "가장" in q.text and "하나" in q.text and "(" in q.text, q.text
        if q.category == CommonCategory.PERSONALITY_SITUATIONAL:
            assert q.text.endswith("어떻게 하시겠습니까?"), q.text
        if q.category == CommonCategory.CLOSING:
            assert q.rubric_items == ()


def test_default_sample_has_expected_counts_and_order():
    questions = sample(1)
    subtypes = [q.subtype for q in questions]
    assert subtypes[0] == "self_introduction"
    assert subtypes[-1] == "closing"
    assert subtypes.count("personality_behavioral") == 1
    assert subtypes.count("personality_situational") == 1
    basic = [
        s
        for s in subtypes
        if s in {"self_introduction", "motivation", "strength_weakness", "future_plan"}
    ]
    assert len(basic) == 2
    assert all(q.kind == "common" and q.bank_id == q.id and q.round == 1 for q in questions)


def test_behavioral_and_situational_topics_never_overlap():
    for seed in range(60):
        questions = sample(seed)
        topics = {
            q.subtype: BANK_BY_ID[q.bank_id].topic
            for q in questions
            if q.subtype.startswith("personality")
        }
        assert topics["personality_behavioral"] != topics["personality_situational"], seed


def test_same_seed_is_deterministic():
    assert [q.id for q in sample(7)] == [q.id for q in sample(7)]


def test_excluded_ids_are_skipped_while_alternatives_remain():
    intros = [q.id for q in COMMON_QUESTIONS if q.category == CommonCategory.SELF_INTRODUCTION]
    for seed in range(20):
        chosen = [q.id for q in sample(seed, exclude=intros[:-1])]
        assert intros[-1] in chosen
        assert not set(intros[:-1]) & set(chosen)


def test_exhausted_pool_falls_back_to_oldest_excluded_first():
    all_ids = [q.id for q in COMMON_QUESTIONS]  # oldest -> newest in bank order
    intros = [q.id for q in COMMON_QUESTIONS if q.category == CommonCategory.SELF_INTRODUCTION]
    questions = sample(3, exclude=all_ids)
    assert questions[0].id == intros[0]
    reversed_ids = list(reversed(all_ids))
    assert sample(3, exclude=reversed_ids)[0].id == intros[-1]


def test_job_placeholder_is_always_replaced():
    for seed in range(30):
        for job in ("백엔드 개발자", None):
            for q in sample(seed, job=job):
                assert "{직무}" not in q.text
    texts = [q.text for seed in range(30) for q in sample(seed, job="백엔드 개발자")]
    assert any("백엔드 개발자" in t for t in texts)


def test_without_job_templated_questions_are_avoided_when_alternatives_exist():
    texts = [
        q.text
        for seed in range(30)
        for q in sample(seed, job=None)
        if q.subtype == "self_introduction"
    ]
    assert not any("지원 직무" in t for t in texts)


def test_job_given_raises_share_of_templated_questions():
    def share(job):
        total = hits = 0
        for seed in range(80):
            for q in sample(seed, job=job):
                total += 1
                hits += "{직무}" in BANK_BY_ID[q.bank_id].text
        return hits / total

    assert share("백엔드 개발자") > share(None)


def test_closing_can_be_left_out_and_counts_follow_composition():
    comp = Composition(
        common_basic=3, personality_behavioral=2, personality_situational=2, include_closing=False
    )
    questions = sample(5, composition=comp)
    subtypes = [q.subtype for q in questions]
    assert "closing" not in subtypes
    assert subtypes[0] == "self_introduction"
    assert subtypes.count("personality_behavioral") == 2
    assert subtypes.count("personality_situational") == 2
    assert len({q.id for q in questions}) == len(questions)


def test_trailing_job_word_is_not_doubled_and_long_names_are_capped():
    from app.modules.interview.question_bank import MAX_JOB_NAME_CHARS, clean_job_name

    assert clean_job_name("백엔드 개발자 직무") == "백엔드 개발자"
    assert clean_job_name("  ") == "지원"
    assert len(clean_job_name("가" * 200)) == MAX_JOB_NAME_CHARS
    texts = [q.text for q in COMMON_QUESTIONS if "{직무}" in q.text]
    assert texts
    planned = [to_planned(q, "백엔드 개발자 직무") for q in COMMON_QUESTIONS if "{직무}" in q.text]
    assert all("직무 직무" not in p.text for p in planned)


def test_templated_questions_stay_within_length_limits_with_longest_job_name():
    job = "가" * 200
    for q in COMMON_QUESTIONS:
        planned = to_planned(q, job)
        assert validate_question(planned) is None, (q.id, len(planned.text))
