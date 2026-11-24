"""Common question bank (seed draft) and sampling.

The seed has three questions per category/topic; the full bank (10+ each) is a later content
task. Texts follow plan section 4.0: behavioral questions pick one "가장 ~한" experience and
list example sources in parentheses; situational questions give role, incident and constraint
in a student scene and end with "어떻게 하시겠습니까?". `{직무}` is replaced by the job name.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from app.modules.interview.composition import Composition
from app.modules.interview.questions import CommonCategory, PlannedQuestion, RubricItem

JOB_PLACEHOLDER = "{직무}"
# Replacement when no job is given; texts use "{직무} 직무" so this reads "지원 직무".
DEFAULT_JOB = "지원"
# Selection weight of a `{직무}` question over a plain one when a job is given.
JOB_QUESTION_WEIGHT = 3
# Longest job name inserted into a question; keeps questions within the length limits.
MAX_JOB_NAME_CHARS = 30

R = RubricItem


class PersonalityTopic(str, Enum):
    COLLABORATION = "collaboration"  # 협업
    CONFLICT = "conflict"  # 갈등 조율
    FAILURE = "failure"  # 실패와 극복
    RESPONSIBILITY = "responsibility"  # 책임감
    PROBLEM_SOLVING = "problem_solving"  # 문제 해결
    ETHICS = "ethics"  # 직업윤리


@dataclass(frozen=True)
class BankQuestion:
    id: str
    category: CommonCategory
    topic: PersonalityTopic | None
    text: str
    rubric_items: tuple[RubricItem, ...]
    source: str  # "NCS 문형" | "OPM 문형" | "자체 작성"
    intent: str = ""


_BASIC_RUBRIC = {
    CommonCategory.SELF_INTRODUCTION: (R.UNDERSTANDING,),
    CommonCategory.MOTIVATION: (R.UNDERSTANDING,),
    CommonCategory.STRENGTH_WEAKNESS: (R.SPECIFICITY, R.LEARNING),
    CommonCategory.FUTURE_PLAN: (R.UNDERSTANDING,),
    CommonCategory.CLOSING: (),
}
_BASIC_INTENT = {
    CommonCategory.SELF_INTRODUCTION: "직무와 연결해 자신을 소개하는지 확인한다.",
    CommonCategory.MOTIVATION: "직무와 조직에 대한 이해가 지원 동기에 드러나는지 확인한다.",
    CommonCategory.STRENGTH_WEAKNESS: "강점·약점을 구체적 경험으로 설명하는지 확인한다.",
    CommonCategory.FUTURE_PLAN: "입사 후 목표가 구체적이고 직무와 맞는지 확인한다.",
    CommonCategory.CLOSING: "지원자가 질문하는 시간이다. 평가하지 않는다.",
}

_BASIC_TEXTS: dict[CommonCategory, tuple[tuple[str, str], ...]] = {
    CommonCategory.SELF_INTRODUCTION: (
        ("1분 동안 {직무} 직무에 지원한 본인을 소개해 주세요.", "자체 작성"),
        ("본인을 가장 잘 나타내는 키워드 하나를 골라 자기소개를 해 주세요.", "자체 작성"),
        ("1분 동안 자기소개를 해 주세요.", "자체 작성"),
    ),
    CommonCategory.MOTIVATION: (
        ("{직무} 직무에 지원한 이유는 무엇인가요?", "자체 작성"),
        ("많은 직무 중에서 {직무} 직무를 선택하게 된 계기를 말씀해 주세요.", "자체 작성"),
        ("이 직무에 지원하게 된 가장 큰 이유는 무엇인가요?", "자체 작성"),
    ),
    CommonCategory.STRENGTH_WEAKNESS: (
        ("{직무} 직무에서 본인의 강점이 가장 잘 드러났던 경험 하나를 말씀해 주세요.", "자체 작성"),
        ("본인의 약점을 보완하려고 노력했던 경험 하나를 말씀해 주세요.", "자체 작성"),
        (
            "동료나 팀원에게 가장 자주 들었던 본인의 강점 하나를 사례와 함께 말씀해 주세요.",
            "자체 작성",
        ),
    ),
    CommonCategory.FUTURE_PLAN: (
        ("입사 후 첫 1년 동안 이루고 싶은 목표는 무엇인가요?", "자체 작성"),
        ("{직무} 직무에서 3년 뒤 어떤 모습으로 성장하고 싶은지 말씀해 주세요.", "자체 작성"),
        ("입사 후 가장 먼저 배우고 싶은 것은 무엇인가요?", "자체 작성"),
    ),
    CommonCategory.CLOSING: (
        ("마지막으로 저희에게 궁금한 점이 있으면 질문해 주세요.", "OPM 문형"),
        ("면접을 마치기 전에 직무나 조직에 대해 궁금한 점이 있으면 질문해 주세요.", "OPM 문형"),
        ("{직무} 직무와 관련해 궁금한 점이 있으면 편하게 질문해 주세요.", "OPM 문형"),
    ),
}

_T = PersonalityTopic
_BEHAVIORAL_TEXTS: dict[PersonalityTopic, tuple[str, ...]] = {
    _T.COLLABORATION: (
        "팀으로 일하면서 본인의 행동이 팀에 가장 긍정적인 영향을 줬던 경험 하나를 말씀해 주세요 "
        "(수업 프로젝트, 동아리, 인턴 등).",
        "여러 사람과 함께 목표를 이뤄 냈던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 "
        "프로젝트, 동아리, 인턴 등).",
        "다양한 배경의 팀원과 협력해 과제를 해결했던 경험 중 가장 기억에 남는 하나를 말씀해 "
        "주세요 (수업 프로젝트, 동아리, 아르바이트 등).",
    ),
    _T.CONFLICT: (
        "팀 프로젝트에서 의견이 가장 크게 엇갈렸던 순간 하나를 말씀해 주세요 (수업 프로젝트, "
        "동아리, 인턴 등).",
        "함께 일하는 사람과 갈등이 있었지만 조율해서 풀었던 경험 중 가장 어려웠던 하나를 말씀해 "
        "주세요 (동아리, 인턴 등).",
        "팀원 사이의 갈등을 중재했던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 "
        "프로젝트, 동아리, 인턴 등).",
    ),
    _T.FAILURE: (
        "계획대로 되지 않아 가장 크게 실패했다고 느낀 경험 하나를 말씀해 주세요 (수업 프로젝트, "
        "동아리, 인턴, 아르바이트 등).",
        "일을 하면서 가장 많은 시행착오를 겪었던 경험 하나를 말씀해 주세요 (수업 프로젝트, "
        "동아리, 인턴 등).",
        "도전했다가 기대한 결과를 얻지 못했던 경험 중 가장 아쉬웠던 하나를 말씀해 주세요 (수업 "
        "프로젝트, 공모전, 인턴 등).",
    ),
    _T.RESPONSIBILITY: (
        "맡은 일을 끝까지 책임지고 해냈던 경험 중 가장 힘들었던 하나를 말씀해 주세요 (수업 "
        "프로젝트, 동아리, 인턴, 아르바이트 등).",
        "지키기 어려운 약속이나 마감을 끝내 지켜 낸 경험 중 가장 기억에 남는 하나를 말씀해 "
        "주세요 (수업 프로젝트, 동아리, 인턴 등).",
        "아무도 맡지 않으려던 일을 먼저 맡아 끝까지 해낸 경험 중 가장 기억에 남는 하나를 말씀해 "
        "주세요 (수업 프로젝트, 동아리, 인턴 등).",
    ),
    _T.PROBLEM_SOLVING: (
        "문제를 주도적으로 해결했던 경험 중 가장 어려웠던 하나를 말씀해 주세요 (수업 프로젝트, "
        "동아리, 인턴, 캡스톤디자인 등).",
        "일의 방법이나 프로세스를 개선했던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 "
        "프로젝트, 동아리, 인턴, 아르바이트 등).",
        "{직무} 직무와 관련된 문제를 스스로 해결했던 경험 중 가장 기억에 남는 하나를 말씀해 "
        "주세요 (수업 프로젝트, 인턴 등).",
    ),
    _T.ETHICS: (
        "편법의 유혹이 있었지만 정직한 방법을 택했던 경험 중 가장 기억에 남는 하나를 말씀해 "
        "주세요 (수업 프로젝트, 동아리, 인턴, 아르바이트 등).",
        "원칙을 지키느라 손해를 감수했던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 "
        "프로젝트, 동아리, 인턴 등).",
        "규칙이나 약속을 지키기 어려운 상황에서 끝까지 지켰던 경험 중 가장 기억에 남는 하나를 "
        "말씀해 주세요 (수업 프로젝트, 동아리, 아르바이트 등).",
    ),
}

_SITUATIONAL_TEXTS: dict[PersonalityTopic, tuple[str, ...]] = {
    _T.COLLABORATION: (
        "당신은 팀 프로젝트의 팀원입니다. 발표 이틀 전, 팀원 한 명이 맡은 부분을 아직 시작하지도 "
        "못했다고 털어놓았습니다. 다른 팀원들도 각자 일이 많습니다. 어떻게 하시겠습니까?",
        "인턴으로 {직무} 직무의 업무를 돕고 있습니다. 옆 팀과 함께 하는 일인데 상대 팀이 요청한 "
        "자료를 계속 보내 주지 않습니다. 어떻게 하시겠습니까?",
        "팀 프로젝트에서 당신이 생각한 방식과 다른 방식으로 하자고 팀원 대부분이 의견을 "
        "모았습니다. 당신은 그 방식에 아직 확신이 없습니다. 어떻게 하시겠습니까?",
    ),
    _T.CONFLICT: (
        "동아리 행사를 준비하는 중 역할을 나눴는데, 한 팀원은 자기 몫이 너무 많다고 불만을 "
        "말하고 다른 팀원은 지금 분담이 가장 효율적이라고 합니다. 어떻게 하시겠습니까?",
        "마찰이 있었던 동료와 같은 팀으로 프로젝트를 계속하라는 지도교수님의 요청을 받았습니다. "
        "두 사람 사이는 아직 어색합니다. 어떻게 하시겠습니까?",
        "팀 프로젝트 회의에서 두 팀원이 서로 다른 방향을 고집하며 언성을 높이고 있고, 결정할 "
        "시간은 얼마 남지 않았습니다. 어떻게 하시겠습니까?",
    ),
    _T.FAILURE: (
        "당신이 맡아 진행한 팀 프로젝트 결과물에 중요한 오류가 있다는 것을 발표 직전에 "
        "발견했습니다. 고칠 시간은 충분하지 않습니다. 어떻게 하시겠습니까?",
        "인턴으로 처음 맡은 업무에서 실수로 잘못된 자료를 팀에 공유한 사실을 뒤늦게 알게 "
        "됐습니다. 아직 아무도 눈치채지 못했습니다. 어떻게 하시겠습니까?",
        "공모전을 준비하며 몇 주간 만든 방향이 중간 점검에서 심사 기준과 맞지 않는다는 말을 "
        "들었습니다. 남은 기간은 일주일입니다. 어떻게 하시겠습니까?",
    ),
    _T.RESPONSIBILITY: (
        "마감 이틀 전, 팀원 한 명이 맡은 기능이 아직 동작하지 않는다는 사실을 알게 됐습니다. "
        "어떻게 하시겠습니까?",
        "당신은 동아리 회계를 맡고 있습니다. 행사 직후 정산을 하다 영수증 한 장이 없어졌고 "
        "금액이 맞지 않는다는 것을 발견했습니다. 어떻게 하시겠습니까?",
        "인턴 마지막 주에 담당 업무를 인수인계하라는 요청을 받았는데, 같은 시간에 새로 급한 일도 "
        "맡게 됐습니다. 어떻게 하시겠습니까?",
    ),
    _T.PROBLEM_SOLVING: (
        "팀 프로젝트의 마감이 일주일 남았는데 자원이 부족해 계획한 기능을 모두 만들 수 없습니다. "
        "작업의 우선순위를 정해야 합니다. 어떻게 하시겠습니까?",
        "{직무} 직무와 관련된 프로젝트를 하던 중, 비슷한 결과물을 만든 다른 팀이 먼저 공개했다는 "
        "소식을 들었습니다. 어떻게 하시겠습니까?",
        "팀 프로젝트에서 사용자 조사 결과가 팀이 세운 가설과 정반대로 나왔습니다. 남은 기간은 "
        "열흘입니다. 어떻게 하시겠습니까?",
    ),
    _T.ETHICS: (
        "{직무} 직무 인턴으로 일하는데 선배가 규정에 맞지 않는 방법으로 일을 빨리 끝내라고 "
        "지시했습니다. 어떻게 하시겠습니까?",
        "팀 프로젝트 과제에서 팀원 한 명이 다른 팀의 결과물을 그대로 가져다 쓰자고 제안했습니다. "
        "다른 팀원들은 고민하고 있습니다. 어떻게 하시겠습니까?",
        "동아리에서 후원금을 받았는데, 선배가 일부를 정해진 용도 외에 쓰자고 제안했습니다. "
        "모두가 동의하는 분위기입니다. 어떻게 하시겠습니까?",
    ),
}

_BEHAVIORAL_RUBRIC = (R.COLLABORATION, R.SPECIFICITY, R.LEARNING)
_SITUATIONAL_RUBRIC = (R.UNDERSTANDING, R.REASONING, R.COLLABORATION)

_BASIC_ID = {
    CommonCategory.SELF_INTRODUCTION: "intro",
    CommonCategory.MOTIVATION: "motive",
    CommonCategory.STRENGTH_WEAKNESS: "strength",
    CommonCategory.FUTURE_PLAN: "plan",
    CommonCategory.CLOSING: "closing",
}


def _build_bank() -> tuple[BankQuestion, ...]:
    bank: list[BankQuestion] = []
    for category, entries in _BASIC_TEXTS.items():
        for n, (text, source) in enumerate(entries, 1):
            bank.append(
                BankQuestion(
                    f"basic-{_BASIC_ID[category]}-{n}",
                    category,
                    None,
                    text,
                    _BASIC_RUBRIC[category],
                    source,
                    _BASIC_INTENT[category],
                )
            )
    for topic, texts in _BEHAVIORAL_TEXTS.items():
        for n, text in enumerate(texts, 1):
            bank.append(
                BankQuestion(
                    f"beh-{topic.value}-{n}",
                    CommonCategory.PERSONALITY_BEHAVIORAL,
                    topic,
                    text,
                    _BEHAVIORAL_RUBRIC,
                    "NCS 문형",
                    "과거 경험으로 행동과 역할, 배운 점을 확인한다.",
                )
            )
    for topic, texts in _SITUATIONAL_TEXTS.items():
        for n, text in enumerate(texts, 1):
            bank.append(
                BankQuestion(
                    f"sit-{topic.value}-{n}",
                    CommonCategory.PERSONALITY_SITUATIONAL,
                    topic,
                    text,
                    _SITUATIONAL_RUBRIC,
                    "OPM 문형",
                    "상황을 어떻게 이해하고 어떤 기준으로 판단하는지 확인한다.",
                )
            )
    return tuple(bank)


COMMON_QUESTIONS: tuple[BankQuestion, ...] = _build_bank()
BANK_BY_ID: dict[str, BankQuestion] = {q.id: q for q in COMMON_QUESTIONS}


def clean_job_name(job: str | None) -> str:
    """Job name for `{직무}`: trailing "직무" removed (texts add it), capped in length."""
    name = (job or "").strip()
    if name.endswith("직무"):
        name = name[: -len("직무")].strip()
    return name[:MAX_JOB_NAME_CHARS].strip() or DEFAULT_JOB


def to_planned(question: BankQuestion, job: str | None = None) -> PlannedQuestion:
    """Turn a bank entry into a PlannedQuestion, replacing `{직무}`."""
    name = clean_job_name(job)
    return PlannedQuestion(
        id=question.id,
        kind="common",
        subtype=question.category.value,
        text=question.text.replace(JOB_PLACEHOLDER, name),
        intent=question.intent,
        source_quote=None,
        rubric_items=list(question.rubric_items),
        parent_id=None,
        bank_id=question.id,
        round=1,
    )


def _pick(
    candidates: list[BankQuestion],
    job: str | None,
    exclude_ids: list[str],
    rng: random.Random,
) -> BankQuestion | None:
    """Pick one candidate, skipping excluded ids; when all are excluded take the oldest."""
    if not candidates:
        return None
    excluded = set(exclude_ids)
    pool = [q for q in candidates if q.id not in excluded]
    if not pool:
        last_used = {qid: index for index, qid in enumerate(exclude_ids)}
        return min(candidates, key=lambda q: last_used[q.id])
    templated = [JOB_PLACEHOLDER in q.text for q in pool]
    if job and job.strip():
        weights = [JOB_QUESTION_WEIGHT if t else 1 for t in templated]
    elif not all(templated):
        weights = [0 if t else 1 for t in templated]
    else:
        weights = [1] * len(pool)
    return rng.choices(pool, weights=weights, k=1)[0]


def sample_common(
    composition: Composition,
    job: str | None,
    exclude_ids: list[str],
    rng: random.Random,
) -> list[PlannedQuestion]:
    """Choose the common questions for one interview, in interview order.

    `exclude_ids` is ordered oldest to newest. Behavioral and situational questions never
    share a topic. With a job given, `{직무}` questions are weighted up; without one they are
    avoided while plain alternatives remain.
    """
    by_category: dict[CommonCategory, list[BankQuestion]] = {}
    for q in COMMON_QUESTIONS:
        by_category.setdefault(q.category, []).append(q)

    picked: list[BankQuestion] = []

    def take(candidates: list[BankQuestion]) -> BankQuestion | None:
        chosen = _pick(candidates, job, exclude_ids, rng)
        if chosen is not None:
            picked.append(chosen)
        return chosen

    if composition.common_basic > 0:
        take(by_category[CommonCategory.SELF_INTRODUCTION])
        others = [
            CommonCategory.MOTIVATION,
            CommonCategory.STRENGTH_WEAKNESS,
            CommonCategory.FUTURE_PLAN,
        ]
        for _ in range(composition.common_basic - 1):
            chosen = take([q for c in others for q in by_category[c]])
            if chosen is None:
                break
            others.remove(chosen.category)

    used_topics: set[PersonalityTopic | None] = set()
    for category, count in (
        (CommonCategory.PERSONALITY_BEHAVIORAL, composition.personality_behavioral),
        (CommonCategory.PERSONALITY_SITUATIONAL, composition.personality_situational),
    ):
        for _ in range(count):
            chosen = take([q for q in by_category[category] if q.topic not in used_topics])
            if chosen is None:
                break
            used_topics.add(chosen.topic)

    if composition.include_closing:
        take(by_category[CommonCategory.CLOSING])

    return composition.order_questions([to_planned(q, job) for q in picked])
