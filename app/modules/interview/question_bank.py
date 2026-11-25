"""Common question bank and sampling.

The bank is the final list the user reviewed on 2026-11-25 (128 questions; per-group sizes
are pinned in tests/test_interview_question_bank.py). Question ids are stored in users'
browser history, so an existing id must keep its meaning and a removed id stays retired:
never renumber or reuse ids. Revised questions keep their id; new ones take a new id.
Each question carries a `source`: "NCS 문형" (wording or topic follows the NCS 직업기초능력
경험·상황면접 예시문항), "OPM 문형" (follows OPM structured-interview phrasing) or "자체 작성".
Texts follow plan section 4.0: behavioral questions pick one experience and list example
sources in parentheses; situational questions give role, incident and constraint in a student
scene and end with a single "어떻게 하시겠습니까?"; a few approved final texts deviate from
that wording (see the allow-lists in the tests). `{직무}` is replaced by the job name.
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
    CommonCategory.VALUES: (R.UNDERSTANDING, R.COLLABORATION),
    CommonCategory.CLOSING: (),
}
_BASIC_INTENT = {
    CommonCategory.SELF_INTRODUCTION: "직무와 연결해 자신을 소개하는지 확인한다.",
    CommonCategory.MOTIVATION: "직무와 조직에 대한 이해가 지원 동기에 드러나는지 확인한다.",
    CommonCategory.STRENGTH_WEAKNESS: "강점·약점을 구체적 경험으로 설명하는지 확인한다.",
    CommonCategory.FUTURE_PLAN: "입사 후 목표가 구체적이고 직무와 맞는지 확인한다.",
    CommonCategory.VALUES: "일에 대한 가치관과 함께 일하는 방식을 구체적으로 설명하는지 확인한다.",
    CommonCategory.CLOSING: "지원자가 질문하는 시간이다. 평가하지 않는다.",
}

_BASIC_TEXTS: dict[CommonCategory, tuple[tuple[str, str, str], ...]] = {
    CommonCategory.SELF_INTRODUCTION: (
        ("basic-intro-1", "1분 동안 {직무} 직무에 지원한 본인을 소개해 주세요.", "자체 작성"),
        (
            "basic-intro-2",
            "본인을 가장 잘 나타내는 키워드 하나를 골라 자기소개를 해 주세요.",
            "자체 작성",
        ),
        ("basic-intro-3", "1분 동안 자기소개를 해 주세요.", "자체 작성"),
        (
            "basic-intro-5",
            "지금까지의 경험 중 본인을 가장 잘 보여 주는 한 가지를 중심으로 자기소개를 해 주세요.",
            "자체 작성",
        ),
        (
            "basic-intro-6",
            "친구나 동료가 본인을 어떻게 소개할지 떠올리며 자기소개를 해 주세요.",
            "자체 작성",
        ),
        (
            "basic-intro-8",
            "학교나 활동에서 맡아 온 역할을 중심으로 1분 동안 자기소개를 해 주세요.",
            "자체 작성",
        ),
        (
            "basic-intro-10",
            "{직무} 직무 면접관이 꼭 기억했으면 하는 점을 넣어 자기소개를 해 주세요.",
            "자체 작성",
        ),
        ("basic-intro-11", "30초 안에 핵심만 담아 본인을 소개해 주세요.", "자체 작성"),
    ),
    CommonCategory.MOTIVATION: (
        ("basic-motive-1", "{직무} 직무에 지원한 이유는 무엇인가요?", "자체 작성"),
        (
            "basic-motive-2",
            "많은 직무 중에서 {직무} 직무를 선택하게 된 계기를 말씀해 주세요.",
            "자체 작성",
        ),
        ("basic-motive-5", "이 직무를 준비하면서 가장 흥미로웠던 순간은 언제인가요?", "자체 작성"),
        (
            "basic-motive-6",
            "{직무} 직무에서 하게 될 일 중 가장 끌리는 일은 무엇인가요?",
            "자체 작성",
        ),
        (
            "basic-motive-7",
            "{직무} 직무를 위해 지금까지 어떤 준비를 해 오셨는지 말씀해 주세요.",
            "자체 작성",
        ),
        (
            "basic-motive-8",
            "다른 직무가 아니라 이 직무가 잘 맞는다고 생각하는 이유는 무엇인가요?",
            "자체 작성",
        ),
        (
            "basic-motive-11",
            "{직무} 직무에서 가장 중요하다고 생각하는 핵심 역량은 무엇이며, 그 이유는 무엇인가요?",
            "자체 작성",
        ),
        (
            "basic-motive-12",
            "{직무} 직무를 수행할 때 가장 어렵거나 힘들 것 같은 부분은 무엇이며, 어떻게 대처할 "
            "계획인가요?",
            "자체 작성",
        ),
    ),
    CommonCategory.STRENGTH_WEAKNESS: (
        (
            "basic-strength-2",
            "본인의 약점을 보완하려고 노력했던 경험 하나를 말씀해 주세요.",
            "자체 작성",
        ),
        (
            "basic-strength-3",
            "동료나 팀원에게 가장 자주 들었던 본인의 강점 하나를 사례와 함께 말씀해 주세요.",
            "자체 작성",
        ),
        (
            "basic-strength-5",
            "{직무} 직무에 도움이 될 본인의 강점 하나를 경험과 함께 말씀해 주세요.",
            "자체 작성",
        ),
        (
            "basic-strength-6",
            "본인의 약점 때문에 어려움을 겪었던 경험 하나를 말씀해 주세요.",
            "자체 작성",
        ),
        (
            "basic-strength-9",
            "{직무} 직무에서 가장 보완해야 한다고 생각하는 본인의 부족한 점은 무엇인가요?",
            "NCS 문형",
        ),
        (
            "basic-strength-10",
            "다른 지원자와 구별되는 본인만의 강점 하나를 근거와 함께 말씀해 주세요.",
            "자체 작성",
        ),
        (
            "basic-strength-11",
            "본인의 강점이 오히려 약점이나 방해로 작용했던 경험이 있다면 말씀해 주세요.",
            "자체 작성",
        ),
        (
            "basic-strength-12",
            "주변 사람들에게 자주 듣는 본인의 아쉬운 점이나 피드백은 무엇이며, 어떻게 받아들이고 "
            "있나요?",
            "자체 작성",
        ),
    ),
    CommonCategory.FUTURE_PLAN: (
        ("basic-plan-1", "입사 후 첫 1년 동안 이루고 싶은 목표는 무엇인가요?", "자체 작성"),
        (
            "basic-plan-2",
            "{직무} 직무에서 3년 뒤 어떤 모습으로 성장하고 싶은지 말씀해 주세요.",
            "자체 작성",
        ),
        ("basic-plan-5", "입사 후 직무 역량을 키우기 위해 어떤 계획을 갖고 있나요?", "NCS 문형"),
        ("basic-plan-7", "입사 후 팀에 가장 먼저 기여하고 싶은 부분은 무엇인가요?", "자체 작성"),
        ("basic-plan-10", "입사 후 첫 3개월 동안 어떻게 업무에 적응할 계획인가요?", "자체 작성"),
        (
            "basic-plan-11",
            "입사 후 본인이 원하지 않는 업무나 단순 반복 업무를 맡게 된다면 어떻게 임하시겠습니까?",
            "자체 작성",
        ),
    ),
    CommonCategory.VALUES: (
        ("basic-values-1", "본인이 생각하는 '일을 잘하는 사람'의 기준은 무엇인가요?", "자체 작성"),
        (
            "basic-values-2",
            "함께 일하고 싶은 동료와, 반대로 함께 일하기 어려운 동료는 어떤 유형인가요?",
            "자체 작성",
        ),
        (
            "basic-values-3",
            "일을 할 때 본인이 가장 중요하게 여기는 가치나 원칙은 무엇인가요?",
            "자체 작성",
        ),
        (
            "basic-values-4",
            "업무나 과제를 할 때 AI 도구를 활용한다면, 본인만의 기준이나 주의하는 점은 무엇인가요?",
            "자체 작성",
        ),
    ),
    CommonCategory.CLOSING: (
        ("basic-closing-1", "마지막으로 저희에게 궁금한 점이 있으면 질문해 주세요.", "OPM 문형"),
        (
            "basic-closing-3",
            "{직무} 직무와 관련해 궁금한 점이 있으면 편하게 질문해 주세요.",
            "OPM 문형",
        ),
        ("basic-closing-8", "면접을 보면서 새로 궁금해진 점이 있으면 질문해 주세요.", "OPM 문형"),
        (
            "basic-closing-11",
            "마지막으로 면접에서 미처 하지 못한 말이나 꼭 강조하고 싶은 점이 있다면 말씀해 주세요.",
            "자체 작성",
        ),
    ),
}

_T = PersonalityTopic
_BEHAVIORAL_TEXTS: dict[PersonalityTopic, tuple[tuple[str, str, str], ...]] = {
    _T.COLLABORATION: (
        (
            "beh-collaboration-1",
            "팀으로 일하면서 본인의 행동이 팀에 가장 긍정적인 영향을 줬던 경험 하나를 말씀해 "
            "주세요 (수업 프로젝트, 동아리, 인턴 등).",
            "NCS 문형",
        ),
        (
            "beh-collaboration-2",
            "여러 사람과 함께 목표를 이뤄 냈던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리, 인턴 등).",
            "NCS 문형",
        ),
        (
            "beh-collaboration-3",
            "다양한 배경이나 강점을 가진 팀원들과 협력해 과제를 해결했던 경험 중 가장 기억에 남는 "
            "하나를 말씀해 주세요 (수업 프로젝트, 동아리, 아르바이트 등).",
            "NCS 문형",
        ),
        (
            "beh-collaboration-6",
            "다른 사람과 소통하며 일을 진행한 경험 중 가장 어려웠던 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리, 아르바이트 등).",
            "NCS 문형",
        ),
        (
            "beh-collaboration-7",
            "팀원이 어려움을 겪을 때 도왔던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리, 인턴 등).",
            "자체 작성",
        ),
        (
            "beh-collaboration-10",
            "팀에서 정보나 의견을 가장 적극적으로 공유했던 경험 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리, 인턴 등).",
            "자체 작성",
        ),
        (
            "beh-collaboration-11",
            "팀을 이끈 경험 중 가장 어려웠던 하나를 말씀해 주세요 (수업 프로젝트, 동아리 등).",
            "자체 작성",
        ),
    ),
    _T.CONFLICT: (
        (
            "beh-conflict-1",
            "팀 프로젝트에서 의견이 가장 크게 엇갈렸던 순간 하나를 말씀해 주세요 (수업 프로젝트, "
            "동아리, 인턴 등).",
            "NCS 문형",
        ),
        (
            "beh-conflict-2",
            "함께 일하는 사람과 갈등이 있었지만 조율해서 풀었던 경험 중 가장 어려웠던 하나를 "
            "말씀해 주세요 (수업 프로젝트, 동아리, 인턴 등).",
            "NCS 문형",
        ),
        (
            "beh-conflict-3",
            "팀원 사이의 갈등을 중재했던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리, 인턴 등).",
            "NCS 문형",
        ),
        (
            "beh-conflict-5",
            "까다롭거나 화가 난 사람을 상대한 경험 중 가장 힘들었던 하나를 말씀해 주세요 "
            "(아르바이트, 동아리, 인턴 등).",
            "OPM 문형",
        ),
        (
            "beh-conflict-6",
            "상대를 설득해 의견 차이를 좁힌 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리 등).",
            "자체 작성",
        ),
        (
            "beh-conflict-7",
            "내 의견이 받아들여지지 않았지만 팀의 결정을 따른 경험 중 가장 기억에 남는 하나를 "
            "말씀해 주세요 (수업 프로젝트, 동아리 등).",
            "자체 작성",
        ),
        (
            "beh-conflict-8",
            "역할 분담에 대한 불만이 생겼던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리 등).",
            "자체 작성",
        ),
        (
            "beh-conflict-11",
            "팀 프로젝트에서 참여도가 낮거나 소극적인 팀원을 이끌어 함께 과제를 끝낸 경험 하나를 "
            "말씀해 주세요 (수업 프로젝트, 동아리, 인턴 등).",
            "자체 작성",
        ),
    ),
    _T.FAILURE: (
        (
            "beh-failure-1",
            "계획대로 되지 않아 가장 크게 실패했다고 느낀 경험 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리, 인턴, 아르바이트 등).",
            "NCS 문형",
        ),
        (
            "beh-failure-3",
            "도전했다가 기대한 결과를 얻지 못했던 경험 중 가장 아쉬웠던 하나를 말씀해 주세요 (수업 "
            "프로젝트, 공모전, 인턴 등).",
            "NCS 문형",
        ),
        (
            "beh-failure-5",
            "일정이나 목표를 지키지 못한 경험 중 가장 아쉬웠던 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리, 인턴 등).",
            "자체 작성",
        ),
        (
            "beh-failure-6",
            "같은 실수를 반복하지 않으려고 방법을 바꾼 경험 중 가장 기억에 남는 하나를 말씀해 "
            "주세요 (수업 프로젝트, 인턴 등).",
            "자체 작성",
        ),
        (
            "beh-failure-7",
            "실패한 뒤 다시 도전해 결과를 바꾼 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 "
            "프로젝트, 공모전, 인턴 등).",
            "자체 작성",
        ),
        (
            "beh-failure-9",
            "시행착오 끝에 방법을 찾아낸 경험 중 가장 오래 걸렸던 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리, 인턴 등).",
            "NCS 문형",
        ),
        (
            "beh-failure-10",
            "다른 사람의 지적을 받고 일하는 방식을 고친 경험 중 가장 기억에 남는 하나를 말씀해 "
            "주세요 (수업 프로젝트, 동아리, 인턴 등).",
            "자체 작성",
        ),
        (
            "beh-failure-11",
            "본인의 실수가 아닌 예상치 못한 외부 변수로 계획이 틀어졌을 때 대처하고 극복한 경험 "
            "하나를 말씀해 주세요 (수업 프로젝트, 동아리, 인턴 등).",
            "자체 작성",
        ),
    ),
    _T.RESPONSIBILITY: (
        (
            "beh-responsibility-1",
            "맡은 일을 끝까지 책임지고 해냈던 경험 중 가장 힘들었던 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리, 인턴, 아르바이트 등).",
            "NCS 문형",
        ),
        (
            "beh-responsibility-2",
            "지키기 어려운 약속이나 마감을 끝내 지켜 낸 경험 중 가장 기억에 남는 하나를 말씀해 "
            "주세요 (수업 프로젝트, 동아리, 인턴 등).",
            "NCS 문형",
        ),
        (
            "beh-responsibility-3",
            "아무도 맡지 않으려던 일을 먼저 맡아 끝까지 해낸 경험 중 가장 기억에 남는 하나를 "
            "말씀해 주세요 (수업 프로젝트, 동아리, 인턴 등).",
            "NCS 문형",
        ),
        (
            "beh-responsibility-5",
            "여러 일이 몰렸을 때 우선순위를 정해 해낸 경험 중 가장 바빴던 하나를 말씀해 주세요 "
            "(학업, 동아리, 인턴 등).",
            "NCS 문형",
        ),
        (
            "beh-responsibility-8",
            "맡은 일의 실수를 발견하고 직접 바로잡은 경험 중 가장 기억에 남는 하나를 말씀해 주세요 "
            "(수업 프로젝트, 인턴 등).",
            "자체 작성",
        ),
        (
            "beh-responsibility-9",
            "스스로 정한 목표를 끝까지 지킨 경험 중 가장 힘들었던 하나를 말씀해 주세요 (학업, "
            "자격증 준비, 동아리 등).",
            "자체 작성",
        ),
    ),
    _T.PROBLEM_SOLVING: (
        (
            "beh-problem_solving-2",
            "일의 방법이나 프로세스를 개선했던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리, 인턴, 아르바이트 등).",
            "NCS 문형",
        ),
        (
            "beh-problem_solving-3",
            "{직무} 직무와 관련된 문제를 스스로 해결했던 경험 중 가장 기억에 남는 하나를 말씀해 "
            "주세요 (수업 프로젝트, 인턴 등).",
            "NCS 문형",
        ),
        (
            "beh-problem_solving-4",
            "문제의 원인을 직접 찾아 해결한 경험 중 가장 오래 걸렸던 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리, 인턴 등).",
            "NCS 문형",
        ),
        (
            "beh-problem_solving-6",
            "새로운 기술이나 도구를 배워 문제를 해결한 경험 중 가장 기억에 남는 하나를 말씀해 "
            "주세요 (수업 프로젝트, 인턴 등).",
            "NCS 문형",
        ),
        (
            "beh-problem_solving-7",
            "{직무} 직무와 관련해 새로운 방법을 시도한 경험 중 가장 기억에 남는 하나를 말씀해 "
            "주세요 (수업 프로젝트, 인턴 등).",
            "자체 작성",
        ),
        (
            "beh-problem_solving-8",
            "한정된 시간과 자원으로 과제를 해낸 경험 중 가장 어려웠던 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리 등).",
            "자체 작성",
        ),
        (
            "beh-problem_solving-11",
            "데이터나 객관적 근거를 분석해 문제를 해결하거나 의사결정을 내린 경험 하나를 말씀해 "
            "주세요 (수업 프로젝트, 공모전, 인턴 등).",
            "자체 작성",
        ),
    ),
    _T.ETHICS: (
        (
            "beh-ethics-1",
            "편법의 유혹이 있었지만 정직한 방법을 택했던 경험 중 가장 기억에 남는 하나를 말씀해 "
            "주세요 (수업 프로젝트, 동아리, 인턴, 아르바이트 등).",
            "NCS 문형",
        ),
        (
            "beh-ethics-2",
            "원칙을 지키느라 손해를 감수했던 경험 중 가장 기억에 남는 하나를 말씀해 주세요 (수업 "
            "프로젝트, 동아리, 인턴 등).",
            "NCS 문형",
        ),
        (
            "beh-ethics-4",
            "규정이나 절차를 지키느라 일이 더뎌졌지만 끝까지 따랐던 경험 중 가장 기억에 남는 "
            "하나를 말씀해 주세요 (수업 프로젝트, 인턴, 아르바이트 등).",
            "자체 작성",
        ),
        (
            "beh-ethics-6",
            "잘못된 일을 알게 되어 바로잡거나 알린 경험 중 가장 용기가 필요했던 하나를 말씀해 "
            "주세요 (수업 프로젝트, 동아리, 인턴 등).",
            "자체 작성",
        ),
        (
            "beh-ethics-9",
            "공동 작업에서 역할이나 몫을 공정하게 나눈 경험 중 가장 기억에 남는 하나를 말씀해 "
            "주세요 (수업 프로젝트, 동아리 등).",
            "자체 작성",
        ),
    ),
}

_SITUATIONAL_TEXTS: dict[PersonalityTopic, tuple[tuple[str, str, str], ...]] = {
    _T.COLLABORATION: (
        (
            "sit-collaboration-1",
            "당신은 팀 프로젝트의 팀원입니다. 발표 이틀 전, 팀원 한 명이 맡은 부분을 아직 "
            "시작하지도 못했다고 털어놓았습니다. 다른 팀원들도 각자 일이 많습니다. 어떻게 "
            "하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-collaboration-2",
            "인턴으로 {직무} 직무의 업무를 돕고 있습니다. 옆 팀과 함께 하는 일인데 상대 팀이 "
            "요청한 자료를 계속 보내 주지 않습니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-collaboration-3",
            "팀 프로젝트에서 당신이 생각한 방식과 다른 방식으로 하자고 팀원 대부분이 의견을 "
            "모았습니다. 당신은 그 방식에 아직 확신이 없습니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-collaboration-5",
            "{직무} 직무 인턴인 당신에게 두 선배가 서로 다른 업무를 동시에 요청했습니다. 둘 다 "
            "오늘 안에 끝내 달라고 합니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-collaboration-6",
            "팀 프로젝트에서 한 팀원이 회의에는 거의 오지 않지만 결과물은 잘 내고 있습니다. 다른 "
            "팀원들은 불공평하다고 느낍니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-collaboration-7",
            "당신은 팀 프로젝트의 팀장입니다. 가장 경험이 적은 팀원이 맡은 일을 어려워하면서도 "
            "도움을 요청하지 않습니다. 마감은 일주일 남았습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-collaboration-8",
            "다른 학과 학생들과 하는 프로젝트에서 쓰는 용어와 일하는 방식이 달라 회의마다 오해가 "
            "생깁니다. 중간 발표가 일주일 남았습니다. 어떻게 하시겠습니까?",
            "NCS 문형",
        ),
    ),
    _T.CONFLICT: (
        (
            "sit-conflict-1",
            "동아리 행사를 준비하는 중 역할을 나눴는데, 한 팀원은 자기 몫이 너무 많다고 불만을 "
            "말하고 다른 팀원은 지금 분담이 가장 효율적이라고 합니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-conflict-2",
            "마찰이 있었던 동료와 같은 팀으로 프로젝트를 계속하라는 지도교수님의 요청을 "
            "받았습니다. 두 사람 사이는 아직 어색합니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-conflict-3",
            "팀 프로젝트 회의에서 두 팀원이 서로 다른 방향을 고집하며 언성을 높이고 있고, 결정할 "
            "시간은 얼마 남지 않았습니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-conflict-4",
            "인턴 중 당신이 낸 아이디어를 선배가 팀 회의에서 자기 아이디어처럼 발표했습니다. 팀은 "
            "그 아이디어를 좋게 평가하고 있습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-conflict-5",
            "팀 프로젝트에서 팀장이 회의마다 혼자 결정을 내려 팀원들이 불만을 털어놓고 있습니다. "
            "한 팀원이 당신에게 의견을 물어 왔습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-conflict-6",
            "동아리 회장과 부회장이 행사 방향을 두고 대립하며 각자 당신에게 자기 편을 들어 달라고 "
            "합니다. 행사까지 2주가 남았습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-conflict-7",
            "팀 프로젝트 기여도 평가에서 한 팀원이 당신의 기여를 낮게 평가했다는 사실을 알게 "
            "됐습니다. 제출은 사흘 뒤입니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-conflict-8",
            "인턴으로 일하는 팀에서 두 선배가 서로 다른 방식으로 일하라고 지시해 당신의 업무가 "
            "멈췄습니다. 둘 다 자기 방식이 맞다고 합니다. 어떻게 하시겠습니까?",
            "NCS 문형",
        ),
        (
            "sit-conflict-9",
            "스터디 모임에서 한 팀원이 다른 팀원의 발표를 모두 앞에서 강하게 비판해 분위기가 "
            "얼어붙었습니다. 비판받은 팀원은 말이 없습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-conflict-11",
            "열심히 준비한 결과물에 대해 선배가 이유를 구체적으로 설명하지 않고 부정적으로만 "
            "평가했습니다. 어떻게 대응하시겠습니까?",
            "자체 작성",
        ),
    ),
    _T.FAILURE: (
        (
            "sit-failure-1",
            "당신이 맡아 진행한 팀 프로젝트 결과물에 중요한 오류가 있다는 것을 발표 직전에 "
            "발견했습니다. 고칠 시간은 충분하지 않습니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-failure-2",
            "인턴으로 처음 맡은 업무에서 실수로 잘못된 자료를 팀에 공유한 사실을 뒤늦게 알게 "
            "됐습니다. 아직 아무도 눈치채지 못했습니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-failure-5",
            "공모전 중간 평가에서 팀의 아이디어가 이미 있는 것이라는 지적을 받았습니다. 팀원들은 "
            "의욕을 잃었고 마감은 2주 남았습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-failure-6",
            "인턴으로 맡은 첫 결과물을 선배에게 냈는데 처음부터 다시 하라는 말을 들었습니다. 다시 "
            "할 시간은 이틀뿐입니다. 어떻게 하시겠습니까?",
            "NCS 문형",
        ),
        (
            "sit-failure-7",
            "당신이 기획한 동아리 행사의 신청자가 예상보다 훨씬 적습니다. 행사는 일주일 뒤이고 "
            "장소와 예산은 이미 확정했습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-failure-8",
            "팀 발표 중 당신이 맡은 부분의 수치가 틀렸다는 질문을 받았습니다. 발표는 절반이 남았고 "
            "팀원들이 당신을 보고 있습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-failure-9",
            "팀 프로젝트 제출 파일이 마감 직전에 당신의 실수로 손상됐습니다. 백업은 하루 전 "
            "버전뿐이고 남은 시간은 두 시간입니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-failure-10",
            "인턴 업무에서 당신이 낸 제안이 실제로 시도됐지만 기대한 효과가 나오지 않았습니다. "
            "팀은 결과를 정리하는 회의를 열려고 합니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
    ),
    _T.RESPONSIBILITY: (
        (
            "sit-responsibility-2",
            "당신은 동아리 회계를 맡고 있습니다. 행사 직후 정산을 하다 영수증 한 장이 없어졌고 "
            "금액이 맞지 않는다는 것을 발견했습니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-responsibility-3",
            "인턴 마지막 주에 담당 업무를 인수인계하라는 요청을 받았는데, 같은 시간에 새로 급한 "
            "일도 맡게 됐습니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-responsibility-5",
            "팀 프로젝트에서 팀원 한 명이 갑자기 빠지면서 그 몫이 당신에게 넘어왔습니다. 당신의 "
            "시험 기간과도 겹칩니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-responsibility-6",
            "동아리 물품 관리를 맡고 있는데 행사 후 장비 하나가 파손된 채 반납됐습니다. 누가 "
            "그랬는지 모르고 아무도 말하지 않습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-responsibility-8",
            "인턴 업무 제출까지 한 시간 남았는데 결과물에서 아쉬운 점이 보입니다. 더 다듬으면 "
            "기한을 넘길 수 있습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-responsibility-11",
            "아르바이트나 인턴으로 일하는 매장에서 정산 중 손님에게 거스름돈을 더 내준 사실을 알게 "
            "됐습니다. 손님은 이미 떠났고 매장에서는 아직 아무도 모릅니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
    ),
    _T.PROBLEM_SOLVING: (
        (
            "sit-problem_solving-1",
            "팀 프로젝트의 마감이 일주일 남았는데 자원이 부족해 계획한 범위를 모두 완성할 수 "
            "없습니다. 작업의 우선순위를 정해야 합니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-problem_solving-2",
            "{직무} 직무와 관련된 프로젝트를 하던 중, 비슷한 결과물을 만든 다른 팀이 먼저 "
            "공개했다는 소식을 들었습니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-problem_solving-3",
            "팀 프로젝트에서 사용자 조사 결과가 팀이 세운 가설과 정반대로 나왔습니다. 남은 기간은 "
            "열흘입니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-problem_solving-4",
            "당신은 동아리 행사 담당자입니다. 행사 하루 전 예약한 장소가 취소됐다는 연락을 "
            "받았습니다. 참가 신청자는 이미 오십 명입니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-problem_solving-5",
            "예산이 정해진 팀 프로젝트에서 꼭 필요한 도구의 비용이 예상보다 두 배 비쌉니다. 추가 "
            "예산은 받을 수 없습니다. 어떻게 하시겠습니까?",
            "NCS 문형",
        ),
        (
            "sit-problem_solving-6",
            "인턴으로 일하는데 외부 고객이나 파트너의 불만이 접수됐고 담당자는 자리에 없습니다. "
            "답변 기한은 오늘 오후이고 따를 기준은 없습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-problem_solving-7",
            "팀이 새 소프트웨어를 써 보기로 했는데 사용법을 아는 사람이 없고 마감은 열흘 "
            "남았습니다. 기존 방식으로 돌아갈지 고민입니다. 어떻게 하시겠습니까?",
            "NCS 문형",
        ),
        (
            "sit-problem_solving-8",
            "조사 결과 두 방안의 장단점이 비슷해 팀이 결정을 못 내리고 있습니다. 결정 시한은 "
            "내일이고 추가 조사할 시간은 없습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-problem_solving-9",
            "팀 프로젝트의 설문 응답이 목표의 절반밖에 모이지 않았습니다. 마감은 사흘 남았고 더 "
            "모으기는 어렵습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-problem_solving-10",
            "당신이 맡은 업무 방식이 비효율적이라는 것을 알았지만 선배는 지금 방식을 유지하라고 "
            "합니다. 개선안은 아직 검증되지 않았습니다. 어떻게 하시겠습니까?",
            "NCS 문형",
        ),
        (
            "sit-problem_solving-11",
            "인턴으로 새 업무를 맡았는데 목표와 기준이 모호하고, 지시한 선배는 종일 회의 중이라 "
            "바로 묻기 어렵습니다. 마감은 내일 오전입니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
    ),
    _T.ETHICS: (
        (
            "sit-ethics-1",
            "{직무} 직무 인턴으로 일하는데 선배가 규정에 맞지 않는 방법으로 일을 빨리 끝내라고 "
            "지시했습니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-ethics-2",
            "팀 프로젝트 과제에서 팀원 한 명이 다른 팀의 결과물을 그대로 가져다 쓰자고 "
            "제안했습니다. 다른 팀원들은 고민하고 있습니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-ethics-3",
            "동아리에서 후원금을 받았는데, 선배가 일부를 정해진 용도 외에 쓰자고 제안했습니다. "
            "모두가 동의하는 분위기입니다. 어떻게 하시겠습니까?",
            "OPM 문형",
        ),
        (
            "sit-ethics-5",
            "인턴으로 일하는데 선배가 고객에게는 불리하지만 팀 실적에는 도움이 되는 안내 방식을 "
            "권합니다. 거절하면 어색해질 수 있습니다. 어떻게 하시겠습니까?",
            "NCS 문형",
        ),
        (
            "sit-ethics-7",
            "인턴 중 접한 회사 내부 자료를 친구가 과제에 써도 되냐고 묻습니다. 공개되지 않은 "
            "자료이지만 친구의 마감이 급합니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-ethics-8",
            "팀 프로젝트에 참여하지 않은 팀원의 이름도 함께 올리자고 다수가 말합니다. 반대하면 팀 "
            "분위기가 나빠질 수 있습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
        (
            "sit-ethics-9",
            "동아리 지출 내역을 정리하다 선배가 개인 비용을 행사비로 처리한 것으로 보이는 항목을 "
            "발견했습니다. 확실한 증거는 없습니다. 어떻게 하시겠습니까?",
            "자체 작성",
        ),
    ),
}

_R = RubricItem
# Failure and responsibility are scored on the story itself; problem solving and ethics add
# the reasoning behind the choice. Collaboration and conflict keep 협업과 의사소통.
_BEHAVIORAL_RUBRIC: dict[PersonalityTopic, tuple[RubricItem, ...]] = {
    _T.COLLABORATION: (_R.COLLABORATION, _R.SPECIFICITY, _R.LEARNING),
    _T.CONFLICT: (_R.COLLABORATION, _R.SPECIFICITY, _R.LEARNING),
    _T.FAILURE: (_R.SPECIFICITY, _R.LEARNING),
    _T.RESPONSIBILITY: (_R.SPECIFICITY, _R.LEARNING),
    _T.PROBLEM_SOLVING: (_R.REASONING, _R.SPECIFICITY, _R.LEARNING),
    _T.ETHICS: (_R.REASONING, _R.SPECIFICITY, _R.LEARNING),
}
_SITUATIONAL_RUBRIC = (R.UNDERSTANDING, R.REASONING, R.COLLABORATION)


def _build_bank() -> tuple[BankQuestion, ...]:
    bank: list[BankQuestion] = []
    for category, basic in _BASIC_TEXTS.items():
        for qid, text, source in basic:
            bank.append(
                BankQuestion(
                    qid,
                    category,
                    None,
                    text,
                    _BASIC_RUBRIC[category],
                    source,
                    _BASIC_INTENT[category],
                )
            )
    for topic, behavioral in _BEHAVIORAL_TEXTS.items():
        for qid, text, source in behavioral:
            bank.append(
                BankQuestion(
                    qid,
                    CommonCategory.PERSONALITY_BEHAVIORAL,
                    topic,
                    text,
                    _BEHAVIORAL_RUBRIC[topic],
                    source,
                    "과거 경험으로 행동과 역할, 배운 점을 확인한다.",
                )
            )
    for topic, situational in _SITUATIONAL_TEXTS.items():
        for qid, text, source in situational:
            bank.append(
                BankQuestion(
                    qid,
                    CommonCategory.PERSONALITY_SITUATIONAL,
                    topic,
                    text,
                    _SITUATIONAL_RUBRIC,
                    source,
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
            CommonCategory.VALUES,
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
