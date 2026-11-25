"""question_bank tests: seeded sampling through sample_common."""
# ruff: noqa: E501  (the seed text snapshot is unwrapped)

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


MIN_PER_GROUP = 10
# Closing has fewer: two of its ten were removed (2026-11-25); their ids stay unused.
MIN_CLOSING = 8
REMOVED_IDS = {"basic-closing-4", "basic-closing-10"}
PERSONALITY = (CommonCategory.PERSONALITY_BEHAVIORAL, CommonCategory.PERSONALITY_SITUATIONAL)
# IDs of the seed questions; they are stored in users' browser history and must never change.
_SEED_BASIC_PREFIXES = ("intro", "motive", "strength", "plan", "closing")
SEED_IDS = (
    [f"basic-{p}-{n}" for p in _SEED_BASIC_PREFIXES for n in (1, 2, 3)]
    + [f"beh-{t}-{n}" for t in PersonalityTopic for n in (1, 2, 3)]
    + [f"sit-{t}-{n}" for t in PersonalityTopic for n in (1, 2, 3)]
)
# Texts of the seed questions as first shipped (snapshot of 9845a0c~1).
SEED_TEXTS = {
    "basic-intro-1": "1분 동안 {직무} 직무에 지원한 본인을 소개해 주세요.",
    "basic-intro-2": "본인을 가장 잘 나타내는 키워드 하나를 골라 자기소개를 해 주세요.",
    "basic-intro-3": "1분 동안 자기소개를 해 주세요.",
    "basic-motive-1": "{직무} 직무에 지원한 이유는 무엇인가요?",
    "basic-motive-2": "많은 직무 중에서 {직무} 직무를 선택하게 된 계기를 말씀해 주세요.",
    "basic-motive-3": "이 직무에 지원하게 된 가장 큰 이유는 무엇인가요?",
    "basic-strength-1": "{직무} 직무에서 본인의 강점이 가장 잘 드러났던 경험 하나를 말씀해 주세요.",
    "basic-strength-2": "본인의 약점을 보완하려고 노력했던 경험 하나를 말씀해 주세요.",
    "basic-strength-3": "동료나 팀원에게 가장 자주 들었던 본인의 강점 하나를 사례와 함께 말씀해 주세요.",
    "basic-plan-1": "입사 후 첫 1년 동안 이루고 싶은 목표는 무엇인가요?",
    "basic-plan-2": "{직무} 직무에서 3년 뒤 어떤 모습으로 성장하고 싶은지 말씀해 주세요.",
    "basic-plan-3": "입사 후 가장 먼저 배우고 싶은 것은 무엇인가요?",
    "basic-closing-1": "마지막으로 저희에게 궁금한 점이 있으면 질문해 주세요.",
    "basic-closing-2": "면접을 마치기 전에 직무나 조직에 대해 궁금한 점이 있으면 질문해 주세요.",
    "basic-closing-3": "{직무} 직무와 관련해 궁금한 점이 있으면 편하게 질문해 주세요.",
    "beh-collaboration-1": "팀으로 일하면서 본인의 행동이 팀에 가장 긍정적인 영향을 줬던 경험 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 인턴 등).",
    "beh-collaboration-2": "여러 사람과 함께 목표를 이뤄 냈던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 인턴 등).",
    "beh-collaboration-3": "다양한 배경의 팀원과 협력해 과제를 해결했던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 아르바이트 등).",
    "beh-conflict-1": "팀 프로젝트에서 의견이 가장 크게 엇갈렸던 순간 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 인턴 등).",
    "beh-conflict-2": "함께 일하는 사람과 갈등이 있었지만 조율해서 풀었던 경험 중 가장 어려웠던 하나를 말씀해 주세요 (동아리, 인턴 등).",
    "beh-conflict-3": "팀원 사이의 갈등을 중재했던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 인턴 등).",
    "beh-failure-1": "계획대로 되지 않아 가장 크게 실패했다고 느낀 경험 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 인턴, 아르바이트 등).",
    "beh-failure-2": "일을 하면서 가장 많은 시행착오를 겪었던 경험 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 인턴 등).",
    "beh-failure-3": "도전했다가 기대한 결과를 얻지 못했던 경험 중 가장 아쉬웠던 하나를 말씀해 주세요 (수업 프로젝트, 공모전, 인턴 등).",
    "beh-responsibility-1": "맡은 일을 끝까지 책임지고 해냈던 경험 중 가장 힘들었던 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 인턴, 아르바이트 등).",
    "beh-responsibility-2": "지키기 어려운 약속이나 마감을 끝내 지켜 낸 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 인턴 등).",
    "beh-responsibility-3": "아무도 맡지 않으려던 일을 먼저 맡아 끝까지 해낸 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 인턴 등).",
    "beh-problem_solving-1": "문제를 주도적으로 해결했던 경험 중 가장 어려웠던 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 인턴, 캡스톤디자인 등).",
    "beh-problem_solving-2": "일의 방법이나 프로세스를 개선했던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 인턴, 아르바이트 등).",
    "beh-problem_solving-3": "{직무} 직무와 관련된 문제를 스스로 해결했던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 프로젝트, 인턴 등).",
    "beh-ethics-1": "편법의 유혹이 있었지만 정직한 방법을 택했던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 인턴, 아르바이트 등).",
    "beh-ethics-2": "원칙을 지키느라 손해를 감수했던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 인턴 등).",
    "beh-ethics-3": "규칙이나 약속을 지키기 어려운 상황에서 끝까지 지켰던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 프로젝트, 동아리, 아르바이트 등).",
    "sit-collaboration-1": "당신은 팀 프로젝트의 팀원입니다. 발표 이틀 전, 팀원 한 명이 맡은 부분을 아직 시작하지도 못했다고 털어놓았습니다. 다른 팀원들도 각자 일이 많습니다. 어떻게 하시겠습니까?",
    "sit-collaboration-2": "인턴으로 {직무} 직무의 업무를 돕고 있습니다. 옆 팀과 함께 하는 일인데 상대 팀이 요청한 자료를 계속 보내 주지 않습니다. 어떻게 하시겠습니까?",
    "sit-collaboration-3": "팀 프로젝트에서 당신이 생각한 방식과 다른 방식으로 하자고 팀원 대부분이 의견을 모았습니다. 당신은 그 방식에 아직 확신이 없습니다. 어떻게 하시겠습니까?",
    "sit-conflict-1": "동아리 행사를 준비하는 중 역할을 나눴는데, 한 팀원은 자기 몫이 너무 많다고 불만을 말하고 다른 팀원은 지금 분담이 가장 효율적이라고 합니다. 어떻게 하시겠습니까?",
    "sit-conflict-2": "마찰이 있었던 동료와 같은 팀으로 프로젝트를 계속하라는 지도교수님의 요청을 받았습니다. 두 사람 사이는 아직 어색합니다. 어떻게 하시겠습니까?",
    "sit-conflict-3": "팀 프로젝트 회의에서 두 팀원이 서로 다른 방향을 고집하며 언성을 높이고 있고, 결정할 시간은 얼마 남지 않았습니다. 어떻게 하시겠습니까?",
    "sit-failure-1": "당신이 맡아 진행한 팀 프로젝트 결과물에 중요한 오류가 있다는 것을 발표 직전에 발견했습니다. 고칠 시간은 충분하지 않습니다. 어떻게 하시겠습니까?",
    "sit-failure-2": "인턴으로 처음 맡은 업무에서 실수로 잘못된 자료를 팀에 공유한 사실을 뒤늦게 알게 됐습니다. 아직 아무도 눈치채지 못했습니다. 어떻게 하시겠습니까?",
    "sit-failure-3": "공모전을 준비하며 몇 주간 만든 방향이 중간 점검에서 심사 기준과 맞지 않는다는 말을 들었습니다. 남은 기간은 일주일입니다. 어떻게 하시겠습니까?",
    "sit-responsibility-1": "마감 이틀 전, 팀원 한 명이 맡은 기능이 아직 동작하지 않는다는 사실을 알게 됐습니다. 어떻게 하시겠습니까?",
    "sit-responsibility-2": "당신은 동아리 회계를 맡고 있습니다. 행사 직후 정산을 하다 영수증 한 장이 없어졌고 금액이 맞지 않는다는 것을 발견했습니다. 어떻게 하시겠습니까?",
    "sit-responsibility-3": "인턴 마지막 주에 담당 업무를 인수인계하라는 요청을 받았는데, 같은 시간에 새로 급한 일도 맡게 됐습니다. 어떻게 하시겠습니까?",
    "sit-problem_solving-1": "팀 프로젝트의 마감이 일주일 남았는데 자원이 부족해 계획한 기능을 모두 만들 수 없습니다. 작업의 우선순위를 정해야 합니다. 어떻게 하시겠습니까?",
    "sit-problem_solving-2": "{직무} 직무와 관련된 프로젝트를 하던 중, 비슷한 결과물을 만든 다른 팀이 먼저 공개했다는 소식을 들었습니다. 어떻게 하시겠습니까?",
    "sit-problem_solving-3": "팀 프로젝트에서 사용자 조사 결과가 팀이 세운 가설과 정반대로 나왔습니다. 남은 기간은 열흘입니다. 어떻게 하시겠습니까?",
    "sit-ethics-1": "{직무} 직무 인턴으로 일하는데 선배가 규정에 맞지 않는 방법으로 일을 빨리 끝내라고 지시했습니다. 어떻게 하시겠습니까?",
    "sit-ethics-2": "팀 프로젝트 과제에서 팀원 한 명이 다른 팀의 결과물을 그대로 가져다 쓰자고 제안했습니다. 다른 팀원들은 고민하고 있습니다. 어떻게 하시겠습니까?",
    "sit-ethics-3": "동아리에서 후원금을 받았는데, 선배가 일부를 정해진 용도 외에 쓰자고 제안했습니다. 모두가 동의하는 분위기입니다. 어떻게 하시겠습니까?",
}
# Plan section 4.0: no family/age/marital/region/religion/appearance/wealth questions.
FORBIDDEN_KEYWORDS = (
    "가족", "부모", "아버지", "어머니", "형제", "성장 과정", "성장과정", "나이", "몇 살",
    "결혼", "연애", "고향", "출신", "종교", "외모", "키가", "재산", "집안", "연봉",
)  # fmt: skip


OPEN_WORDS = ("어떤", "무엇", "어떻게", "언제", "왜", "어디")


def groups():
    """(label, questions) for every category, split by topic for the personality ones."""
    for category in CommonCategory:
        if category in PERSONALITY:
            for topic in PersonalityTopic:
                yield (
                    (category, topic),
                    [q for q in COMMON_QUESTIONS if q.category == category and q.topic == topic],
                )
        else:
            yield (category, None), [q for q in COMMON_QUESTIONS if q.category == category]


def test_bank_has_at_least_ten_questions_per_category_and_topic():
    for label, questions in groups():
        minimum = MIN_CLOSING if label == (CommonCategory.CLOSING, None) else MIN_PER_GROUP
        assert len(questions) >= minimum, (label, len(questions))


def test_seed_question_ids_are_preserved():
    assert set(SEED_IDS) <= set(BANK_BY_ID)
    assert len(SEED_IDS) == len(SEED_TEXTS) == 51


def test_seed_question_texts_are_preserved():
    # A stored id must keep meaning the same question in users' browser history.
    assert {i: BANK_BY_ID[i].text for i in SEED_IDS} == SEED_TEXTS


def test_question_ids_are_numbered_without_gaps_except_the_removed_ones():
    for label, questions in groups():
        numbers = [int(q.id.rsplit("-", 1)[1]) for q in questions]
        removed = {10, 4} if label == (CommonCategory.CLOSING, None) else set()
        expected = [n for n in range(1, len(questions) + len(removed) + 1) if n not in removed]
        assert numbers == expected, label  # only the removed ids are missing


def test_removed_questions_are_gone_and_closing_keeps_the_other_eight():
    assert not REMOVED_IDS & set(BANK_BY_ID)
    closing = sorted(
        int(q.id.rsplit("-", 1)[1])
        for q in COMMON_QUESTIONS
        if q.category == CommonCategory.CLOSING
    )
    assert closing == [1, 2, 3, 5, 6, 7, 8, 9]


def test_questions_within_length_limits_and_one_sentence_unless_situational():
    for q in COMMON_QUESTIONS:
        if q.category == CommonCategory.PERSONALITY_SITUATIONAL:
            assert len(q.text) <= 200, q.id
            assert q.text.count("어떻게 하시겠습니까?") == 1, q.id
        else:
            assert len(q.text) <= 100, q.id


def test_questions_are_not_yes_no_leading_or_forbidden():
    for q in COMMON_QUESTIONS:
        assert not any(k in q.text for k in FORBIDDEN_KEYWORDS), q.id
        asks_yes_no = q.text.rstrip("?").endswith(("있나요", "하셨죠", "맞죠", "아닌가요"))
        assert not asks_yes_no or any(w in q.text for w in OPEN_WORDS), q.id


def test_texts_are_unique_in_the_bank():
    assert len({q.text for q in COMMON_QUESTIONS}) == len(COMMON_QUESTIONS)


def test_every_question_has_a_source_marker_and_intent():
    for q in COMMON_QUESTIONS:
        assert q.source in {"NCS 문형", "OPM 문형", "자체 작성"}, q.id
        assert q.intent, q.id


def test_closing_questions_are_not_scored():
    closing = [q for q in COMMON_QUESTIONS if q.category == CommonCategory.CLOSING]
    assert closing and all(q.rubric_items == () for q in closing)


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
