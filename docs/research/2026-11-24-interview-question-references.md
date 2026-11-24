# 면접 질문 레퍼런스 조사 (모의면접 질문 설계용)

- 조사일: 2026-11-24
- 목적: 모의면접 기능의 4가지 질문 유형(공통 기본, 공통 인성, 서류 기반, 꼬리 질문)에 대해, 신뢰할 수 있는 자료에 실제로 나오는 질문 예시, 질문 문형 규칙, 꼬리 질문 패턴을 모은다.
- 표기 규칙
  - **[1차]** 자료를 만든 기관·회사·저자의 원문을 직접 확인한 것.
  - **[2차]** 언론 기사·민간 사이트 등 다른 곳을 거쳐 전달된 것. "자주 나온다"는 보조 근거로만 쓴다.
  - **(요약)** 원문이 길어 뜻만 옮긴 것. 따옴표 안은 원문을 15단어 미만으로 그대로 옮긴 것이다.
  - **미확인**: 원문을 직접 읽지 못했거나 서지 정보를 확인하지 못한 것.
  - 영어 원문 질문에는 한국어 번역을 붙였다.

---

## 1. 요약

1. 공공(NCS·블라인드 채용)과 해외 기업·기관(OPM, Google, GitLab, Amazon) 자료 모두 면접 질문을 **경험형(과거에 실제로 한 일)** 과 **상황형(가정 상황에서 어떻게 할지)** 두 축으로 나눈다. 우리 계획의 "경험형/상황형" 구분과 일치한다. [NCS](https://www.ncs.go.kr/blind/bl02/RH-103-003-04.scdo), [OPM](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf), [Google re:Work](https://rework.withgoogle.com/intl/en/guides/a-guide-to-structured-interviewing-for-better-hiring-practices), [GitLab](https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/)
2. 경험형 질문은 "~했던 경험을 말해 주십시오" / "Tell me about a time…" 형태로 **경험 하나만** 묻고, 상황·행동·결과(STAR)를 끌어내도록 쓴다. OPM은 "most, last, worst, best" 같은 최상급 표현으로 특정 사례 하나를 고르게 하라고 권한다. [OPM](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf)
3. 상황형 질문은 실제 직무에서 일어날 법한 **구체적 장면(누가, 무슨 문제)** 을 먼저 주고 "어떻게 하시겠습니까?"로 끝난다. 정답이 쉽게 보이지 않는 딜레마여야 한다. [OPM](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf), [Oostrom et al. 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC4856718)
4. 꼬리 질문(probe)은 **미리 정해 두는 것**이 원칙이고, 목적은 빠진 STAR 조각을 채우고 **"우리가 했다"를 "내가 한 일"로 좁히는 것**이다. 유도·반박하는 꼬리 질문은 금지한다. [OPM](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf), [Amazon](https://www.aboutamazon.com/news/workplace/recruiters-offer-their-best-tips-for-interviewing-at-amazon)
5. 서류(이력서·프로젝트) 기반 질문은 서류의 주장을 **검증**하는 용도로 쓰며(Google), 역할·참여자·구체적 행동·수치를 캐묻는 꼬리 질문과 짝을 이룬다(Amazon, OPM). [Google re:Work](https://rework.withgoogle.com/intl/en/guides/a-guide-to-structured-interviewing-for-better-hiring-practices)
6. 국내에서 "자주 묻는 질문"의 근거는 대부분 2차 자료다. 사람인 2015년 조사에서는 지원동기(57.9%), 직무에 대한 생각(52.8%), 직무 관련 강점(47.2%) 순이었고 첫 질문은 자기소개가 가장 많았다. 압박 질문 유형 1위는 꼬리물기형(53.3%)이었다. [2차: 파이낸셜뉴스](https://www.fnnews.com/news/201510191014023359), [2차: 뉴스토마토](https://newstomato.com/ReadNews.aspx?no=609973)
7. 금지 주제: 채용절차법 제4조의3은 직무와 무관한 신체조건, 출신지역·혼인여부·재산, 가족의 학력·직업·재산을 **서류에 쓰게 하거나 증빙으로 받는 것**을 금지한다. 면접에서 묻지 말라는 규정은 공공기관 블라인드 채용 지침에서 나온다. 우리 질문 생성기는 두 범위를 모두 금지 목록에 넣어야 한다. [법령](https://www.law.go.kr/법령/채용절차의공정화에관한법률/제4조의3), [정책브리핑](https://www.korea.kr/briefing/policyBriefingView.do?newsId=156213395)

---

## 2. 유형별 질문 예시와 스타일

> 아래 표에는 출처에 실제로 있는 질문만 넣었다. 출처의 원칙을 적용해 우리가 새로 만든 예시는 5장에 따로 모으고 "자체 작성"이라고 표시했다.

### 2-1. 공통 기본 질문 (자기소개, 지원 동기, 강점·약점, 입사 후 포부, 마무리)

이 유형은 1차 공식 가이드에 구체적인 문항이 거의 없다. 빈도 근거는 국내 2차 조사가 대부분이다. NCS 포털은 "자기소개 및 자신만의 장점"을 묻는 방식을 **기존(전통적) 면접**의 예로 들고, 직무 역량 중심 질문과 대비시킨다. [NCS](https://www.ncs.go.kr/blind/bl02/RH-103-003-04.scdo)

| 질문 | 스타일/의도 | 출처 |
|---|---|---|
| 자기소개 | 면접 첫 질문으로 가장 많이 쓰인다. 지원 회사와 연결한 자기소개를 선호한다는 응답이 51.8%였다. | [2차] 사람인 인사담당자 299명 조사(2015), [파이낸셜뉴스](https://www.fnnews.com/news/201510191014023359) |
| 지원동기 | 신입 면접에서 "반드시 묻는 질문" 1위(57.9%, 복수응답). | [2차] 같은 조사, [파이낸셜뉴스](https://www.fnnews.com/news/201510191014023359) |
| "Why Amazon?" (왜 아마존인가?) | 형식적 질문이 아니라 실제로 평가하는 질문이라고 리크루터가 설명한다. | [1차] [About Amazon, 11 interview tips](https://www.aboutamazon.com/news/workplace/recruiters-offer-their-best-tips-for-interviewing-at-amazon) |
| 직무에 대한 생각 | 2위(52.8%). 직무 이해도를 본다. | [2차] [파이낸셜뉴스](https://www.fnnews.com/news/201510191014023359) |
| 직무 관련 본인의 강점 | 3위(47.2%). "장점 일반"이 아니라 **직무와 연결된** 강점을 묻는 형태. | [2차] [파이낸셜뉴스](https://www.fnnews.com/news/201510191014023359) |
| 자기소개 및 자신만의 장점은 무엇인가? | NCS 포털이 **기존 면접** 예시로 든 문항. 직무와 동떨어진 일반 질문은 주관적 판단에 의존하기 쉽다는 맥락. | [1차] [NCS 포털 면접유형](https://www.ncs.go.kr/blind/bl02/RH-103-003-04.scdo) |
| 회사 장단점, 기업 비전, 핵심사업, 기업문화, 인재상 | 회사 관련 질문 소재(회사 장단점 32.1%, 기업 비전 30.1% 등). 회사·직무 이해를 본다. | [2차] [파이낸셜뉴스](https://www.fnnews.com/news/201510191014023359) |
| (마무리) 지원자가 묻는 시간 | GitLab은 면접 끝에 지원자가 질문하도록 항상 권하고 솔직히 답하라고 한다. 시간 배분은 지원자 질문 5~10%. | [1차] [GitLab Handbook](https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/) |
| (마무리) 직무에 대한 비공식 대화와 지원자 질문 | OPM도 면접 시간 안에 지원자가 질문하는 시간을 넣으라고 한다. | [1차] [OPM 교육자료 32쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf) |

- **약점 질문**과 **입사 후 포부 질문**은 이번 조사에서 1차 자료의 구체적 문항을 찾지 못했다(7장 참고).
- 사람인 2015년 조사에서는 "가족 등 성장과정"(21.7%)도 상위 질문이었다. 이 항목은 현재 블라인드 채용 원칙과 충돌하므로 **우리 질문 풀에서 제외**해야 한다(4장 참고).

### 2-2. 공통 인성 질문 — 경험형 (behavioral)

정의: 직무 역량이 드러난 **과거 실제 행동**을 묻는다. 전제는 "과거 행동이 미래 행동을 가장 잘 예측한다"이다. [OPM 13쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf), [GitLab](https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/), [NCS](https://www.ncs.go.kr/blind/bl02/RH-103-003-04.scdo)

| 질문 | 스타일/의도 | 출처 |
|---|---|---|
| "어떤 일 또는 과제를 하면서 일의 프로세스나 방법을 개선했던 경험" | NCS 경험면접 **주질문** 예시. 경험 하나를 콕 집어 묻는다. | [1차] [NCS 포털](https://www.ncs.go.kr/blind/bl02/RH-103-003-04.scdo) |
| "어떤 일 또는 과제를 하면서 많은 시행착오를 겪었던 경험" | NCS 경험면접 주질문 예시(실패·어려움 경험). | [1차] [NCS 포털](https://www.ncs.go.kr/blind/bl02/RH-103-003-04.scdo) |
| "Describe a situation in which you dealt with individuals who were difficult…" (까다롭거나 적대적이거나 괴로워하는 사람을 상대했던 상황을 설명해 주십시오.) | OPM의 대인관계 역량 경험형 예시. 원문은 뒤에 "누가 관여했고, 어떤 행동을 했고, 결과는?"을 붙여 STAR를 유도한다. | [1차] [OPM 교육자료 16쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf), [OPM 예시](https://www.opm.gov/policy-data-oversight/assessment-and-selection/examples/structured-interview-example.pdf) |
| "Tell me about a time your behavior had a positive impact on your team." (당신의 행동이 팀에 긍정적 영향을 준 때를 말해 주세요.) | Google re:Work의 경험형 예시(협업). | [1차] [Google re:Work](https://rework.withgoogle.com/intl/en/guides/a-guide-to-structured-interviewing-for-better-hiring-practices) |
| "Can you tell me about a time when…?" (…했던 때를 말해 줄 수 있나요?) | GitLab이 제시한 경험형 질문의 기본 문형. 질문 전에 STAR 구조로 답해 달라고 짧게 안내하라고 한다. | [1차] [GitLab Handbook](https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/) |
| 위험을 감수했다가 실패하거나 실수했고, 그 결과 성장한 구체적 사례 (요약) | Amazon은 지원자에게 실패·실수 사례를 준비하라고 권한다. "It's okay to talk about failure." | [1차] [About Amazon, 11 interview tips](https://www.aboutamazon.com/news/workplace/recruiters-offer-their-best-tips-for-interviewing-at-amazon) |
| 과거의 성공·어려움과 그것을 어떻게 처리했는지 (요약) | Amazon 행동 질문의 일반 정의. 질문은 Leadership Principles(리더십 원칙)에 맞춰진다. | [1차] [About Amazon, 11 interview tips](https://www.aboutamazon.com/news/workplace/recruiters-offer-their-best-tips-for-interviewing-at-amazon), [About Amazon, interview guide](https://www.aboutamazon.com/news/workplace/amazon-interview-guide) |

**문형 규칙 (경험형)**
- 직무 분석에서 나온 역량에 묶고, 열린 질문으로, 짧고 분명하게, 전문용어 없이 쓴다. [OPM 11쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf), [OPM FAQ](https://www.opm.gov/frequently-asked-questions/assessment-policy-faq/structured-interviews/how-do-i-create-structured-interview-questions/)
- 최상급 표현(most, last, worst, least, best)으로 특정 사례 하나를 고르게 한다. 예: "가장 최근에", "가장 어려웠던". [OPM 11쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf)
- 답이 상황/과제, 행동, 결과(STAR) 세 조각을 담도록 질문을 설계한다. [OPM 12쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf)
- 구조화 면접에 잘 맞는 역량은 팀워크, 구두 의사소통, 대인관계, 갈등관리, 설득·협상이다. 한 면접에서 보통 4~6개 역량을 본다. [OPM 10쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf)
- 지원자에게 들려줄 이야기가 없을 수도 있다. 그것도 하나의 데이터로 기록하고 다음 질문으로 넘어가며, 예비 질문을 준비해 둔다. [GitLab](https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/)

### 2-3. 공통 인성 질문 — 상황형 (situational / hypothetical)

정의: 실제 직무에서 있을 법한 장면이나 딜레마를 주고 **어떻게 하겠는지** 묻는다. 전제는 "의도가 실제 행동과 밀접하다"이다. [OPM 13쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf) 지원자가 과거에 비슷한 기회를 가졌는지와 관계없이 접근 방식을 볼 수 있다는 장점이 있다. [GitLab](https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/)

| 질문 | 스타일/의도 | 출처 |
|---|---|---|
| 몹시 화난 민원인이 찾아와, 5일 전 보냈다는 연체 수표를 못 받았고 갚을 돈이 있는데 아무도 안 도와준다고 한다. 어떻게 하겠는가? (요약) | OPM 상황형 예시(대인관계 역량). 동료가 실제로 침착하게 대응한 **결정적 사건(critical incident)** 을 가정 질문으로 바꿨다. "How would you handle this situation?"으로 끝난다. | [1차] [OPM 교육자료 18쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf) |
| 마감이 촉박하고 자원이 부족한 프로젝트를 맡았다면, 작업 우선순위를 어떻게 정하겠는가? (요약) | GitLab 상황형 예시(우선순위·판단). | [1차] [GitLab Handbook](https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/) |
| 이메일 제품을 맡고 있는데 경쟁사가 월 5달러 요금을 받기 시작했다. "How would you assess the situation…?" (상황을 어떻게 판단하고 팀에 무엇을 제안하겠는가?) (요약+일부 인용) | Google re:Work 상황형 예시(문제 해결). 장면을 주고, 판단 과정과 제안을 함께 묻는다. | [1차] [Google re:Work](https://rework.withgoogle.com/intl/en/guides/a-guide-to-structured-interviewing-for-better-hiring-practices) |
| 배관공사 담당자로서 야간 공사 중 기능공 실수로 소화수가 새어 인근 시설에 피해가 나고 있다. 긴급 처리 프로세스를 설명하라. (요약) | NCS 상황면접 예시. 역할(담당자), 사건, 피해를 주고 처리 절차를 묻는다. | [1차] [NCS 포털](https://www.ncs.go.kr/blind/bl02/RH-103-003-04.scdo) |

**문형 규칙 (상황형)**
- 직무 분석·직무기술서에서 역량과 과업을 고르고, 현장에서 본 효과적/비효과적 행동 사례(결정적 사건)를 써서 가정 질문으로 고쳐 쓴다. [OPM 17쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf)
- 상황은 현실적이되 특정 기술이나 직무 전용 지식 없이도 답할 수 있어야 하고, 정답보다 **분석 과정**을 평가할 수 있어야 한다. 직무 경험만으로 풀리지 않을 만큼 복잡해야 한다. [Google re:Work](https://rework.withgoogle.com/intl/en/guides/a-guide-to-structured-interviewing-for-better-hiring-practices)
- 상황면접(Latham et al., 1980 계열)은 직무 분석에서 나온 가정 상황으로, **바람직한 반응이 쉽게 드러나지 않는** 업무 딜레마를 제시한다고 설명된다. [Oostrom et al. 2016, J Bus Psychol 31:279-291](https://pmc.ncbi.nlm.nih.gov/articles/PMC4856718)
- 같은 논문의 연구 절차에서 면접관은 질문을 인쇄된 그대로 읽고, 바꿔 말하거나 추가 단서를 주지 않았다. [Oostrom et al. 2016](https://pmc.ncbi.nlm.nih.gov/articles/PMC4856718)
- "선택지를 주는 딜레마(A안/B안 중 무엇을 고르겠는가)" 형식은 이번에 확인한 1차 자료에 명시적 예시가 없었다. 다만 Google re:Work 꼬리 질문의 "장단점"·"고려 요인" 묻기가 비슷한 기능을 한다(3장).

### 2-4. 서류 기반 질문 — 직무 지식과 프로젝트·활동 경험

| 질문/지침 | 스타일/의도 | 출처 |
|---|---|---|
| 직무 관련 지식(33.4%), 보유하고 있는 기술(19.4%) | 국내 신입 면접에서 자주 묻는 직무 질문 소재. | [2차] [파이낸셜뉴스](https://www.fnnews.com/news/201510191014023359) |
| 역할 관련 지식은 **경험형 질문으로 이력서의 주장을 검증**한다. (요약) | 서류 내용을 그대로 믿지 말고 과거 행동 질문으로 확인하라는 원칙. | [1차] [Google re:Work](https://rework.withgoogle.com/intl/en/guides/a-guide-to-structured-interviewing-for-better-hiring-practices) |
| "…who was working on the project and how you delivered tangible results." (프로젝트에 누가 참여했고, 당신이 어떻게 실질적 결과를 냈는지 알고 싶다.) | 프로젝트 질문에서 **참여자 구성과 본인 기여**를 분리해 듣는다. | [1차] [About Amazon, 11 interview tips](https://www.aboutamazon.com/news/workplace/recruiters-offer-their-best-tips-for-interviewing-at-amazon) |
| "Let us know what you actually did." (당신이 실제로 한 일을 알려 달라.) | 팀 성과를 인정하되 본인 행동을 구체적으로 말하라는 요구. "I"로 말하라고 권한다. | [1차] [About Amazon, 11 interview tips](https://www.aboutamazon.com/news/workplace/recruiters-offer-their-best-tips-for-interviewing-at-amazon), [About Amazon, interview guide](https://www.aboutamazon.com/news/workplace/amazon-interview-guide) |
| 삼성 직무역량면접: 평가 항목 "전공 역량, 직무 동기", 전공별 문제 풀이 후 발표와 질의응답 | 국내 대기업 공식 안내. 직무 지식을 **문제 풀이 + 질의응답**으로 확인한다. 구체 질문은 공개하지 않는다. | [1차] [삼성전자 채용 안내](https://www.samsung.com/sec/about-us/careers/hiring-process-information/kr) |
| 기술적인 이야기를 비전공 면접관도 이해하게 설명하는가? 결과가 측정되었는가? | GitLab이 경험형 답변을 들을 때 보라고 한 점검 항목. 기술 설명력과 결과 검증을 본다. | [1차] [GitLab Handbook](https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/) |
| 서면 자료와 답변이 일치하지 않는지 | GitLab이 보안 관점(대리 응시·허위 신원)에서 주의하라고 한 신호 중 하나. 서류 기반 질문이 **서류와 답변의 일관성**을 확인하는 데 쓰인다는 근거. | [1차] [GitLab Handbook](https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/) |

- "왜 그 기술(X)을 선택했는가"를 직접 예시로 든 국내외 **기업 공식 자료는 찾지 못했다**(7장). 판단 근거를 묻는 기능은 Google re:Work 꼬리 질문("어떤 요인을 고려했나", "장단점은")과 OPM 상황형 꼬리 질문("어떤 요인이 행동 방침에 영향을 주나", "다른 방법은")이 대신 뒷받침한다(3장).

### 2-5. 답변 기반 꼬리 질문

유형 자체의 패턴은 3장에 정리했다. 국내 빈도 근거로, 사람인 2015년 조사(인사담당자 266명)에서 압박 질문을 쓴다는 기업 중 가장 많이 쓰는 유형은 **꼬리물기형(53.3%)** 이었다. 직전 답변을 더 구체적으로 파고드는 방식이다. [2차: 뉴스토마토](https://newstomato.com/ReadNews.aspx?no=609973)

---

## 3. 꼬리 질문 패턴

OPM은 꼬리 질문(probe)을 **미리 정해 두고**, 질문마다 허용되는 꼬리 질문 목록을 만들라고 한다. 꼬리 질문은 답을 분명히 하거나, 주제에서 벗어난 지원자를 되돌리거나, 정보를 더 얻을 때만 쓴다. [OPM 19·35쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf) Google도 미리 정한 꼬리 질문이 답의 구체성을 높인다고 하며, 첫 질문이 다루지 못한 속성을 꼬리 질문으로 채우라고 한다. [Google re:Work](https://rework.withgoogle.com/intl/en/guides/a-guide-to-structured-interviewing-for-better-hiring-practices) 구조화 면접 연구에서도 "probing, follow-up, prompting, elaboration"은 독립된 연구 주제로 다뤄진다. [Levashina et al. 2014 초록](https://doi.org/10.1111/peps.12052)

| 패턴 | 드러내려는 것 | 예시 | 출처 |
|---|---|---|---|
| 상황 확인 (S/T) | 맥락, 관련자, 원인 | "Who was involved?" (누가 관여했나?) / "What factors led up to this situation?" (어떤 요인으로 그 상황이 생겼나?) | [1차] [OPM 21쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf) |
| 본인 역할 좁히기 (A) | **개인 기여와 팀 성과 분리** | "What was your role?" (당신의 역할은?) / "How did you respond?" (어떻게 대응했나?) | [1차] [OPM 21쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf) |
| "우리"를 "나"로 | 개인 기여 분리 | 지원자가 "we did…", "our group…"이라고 하면 확인 질문을 한다. (규칙) | [1차] [OPM 20쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf) |
| 참여자·기여 확인 | 개인 기여 분리 | 누가 참여했는지, 당신이 구체적으로 무엇을 했는지, 결과와 영향은 무엇이었는지 (요약) | [1차] [About Amazon, 11 interview tips](https://www.aboutamazon.com/news/workplace/recruiters-offer-their-best-tips-for-interviewing-at-amazon) |
| 모호함 파고들기 | 준비된/일반론 답변 걸러내기 | 답이 모호하면 확인 질문을 한다. (규칙) Amazon: "We want to know the numbers." (숫자를 알고 싶다) | [1차] [OPM 20쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf), [About Amazon](https://www.aboutamazon.com/news/workplace/recruiters-offer-their-best-tips-for-interviewing-at-amazon) |
| 깊이 부족 지적 | 일반론 답변 걸러내기 | Amazon 리크루터: 많은 지원자가 충분히 깊이 들어가지 않는 것이 큰 실수라고 한다. 한 질문에 **한 상황**을 자세히 말하라고 권한다. | [1차] [About Amazon, 11 interview tips](https://www.aboutamazon.com/news/workplace/recruiters-offer-their-best-tips-for-interviewing-at-amazon), [About Amazon, interview guide](https://www.aboutamazon.com/news/workplace/amazon-interview-guide) |
| 노력·이유 묻기 | 행동의 판단 근거 | "당시 그 일을 더 잘하기 위해 어떤 노력을 했습니까? 그렇게 행동한 이유는 무엇입니까?" | [1차] [NCS 세부질문 1](https://www.ncs.go.kr/blind/bl02/RH-103-003-04.scdo) |
| 시행착오 대처·우선 고려사항 | 문제 해결, 판단 기준 | "시행착오를 겪었을 때, 어떻게 대처했습니까? 가장 중요하게 고려한 점은?" | [1차] [NCS 세부질문 2](https://www.ncs.go.kr/blind/bl02/RH-103-003-04.scdo) |
| 결과와 후속조치 | 결과, 학습 | "결과적으로 만족할만한 성과를 달성했습니까? 결과에 따라 후속조치를 한 사례가 있습니까?" | [1차] [NCS 세부질문 3](https://www.ncs.go.kr/blind/bl02/RH-103-003-04.scdo) |
| 결과·반성 (R) | 결과, 학습 | "What was the outcome?" (결과는?) / "Is there anything you would have done differently?" (다르게 했을 점은?) | [1차] [OPM 21쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf) |
| 목표·주변 반응·다음 계획 | 판단 근거, 협업, 학습 | "What was your primary goal and why?" (주된 목표와 이유는?) / "How did your teammates respond?" (팀원들은 어떻게 반응했나?) / "Moving forward, what's your plan?" (앞으로의 계획은?) | [1차] [Google re:Work](https://rework.withgoogle.com/intl/en/guides/a-guide-to-structured-interviewing-for-better-hiring-practices) |
| 상황형: 원인·핵심 쟁점 | 상황 이해 | "Why do you believe this situation occurred?" (왜 이런 상황이 생겼다고 보나?) / "What do you consider to be the most critical issues…?" (가장 중요한 쟁점은?) | [1차] [OPM 22쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf) |
| 상황형: 첫 행동·영향 요인·대안 | 판단 근거, 대안 검토 | "What is the first thing you would say or do?" (가장 먼저 무엇을 하겠나?) / "What factors would affect your course of action?" (어떤 요인이 행동에 영향을 주나?) / "What other actions could you take?" (다른 방법은?) | [1차] [OPM 22쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf) |
| 상황형: 수용·효과 예측 | 결과 예측, 이해관계자 고려 | "How do you think your action would be received?" (그 행동이 어떻게 받아들여질까?) / "What do you consider as benefits of your action?" (그 행동의 이점은?) | [1차] [OPM 22쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf) |
| 상황형: 고려 요인·장단점·지속가능성·조직 영향 | 판단 근거, 트레이드오프 | "What are the pros and the cons of your recommendation?" (제안의 장단점은?) 외에 고려 요인, 지속 가능성, 조직 전체 영향을 묻는 꼬리 질문 (요약) | [1차] [Google re:Work](https://rework.withgoogle.com/intl/en/guides/a-guide-to-structured-interviewing-for-better-hiring-practices) |
| 결과 측정·검증 | 결과의 구체성, 준비된 답 걸러내기 | GitLab 점검 항목: 결과가 있었나, 이야기가 끝나지 않았나, 결과를 측정했나, 처음에 기대치가 있었나 (요약) | [1차] [GitLab Handbook](https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/) |
| 이해 확인 되묻기 | 의사소통, 오해 방지 | 끼어들지 말고, 이해한 내용을 설명해 지원자가 바로잡게 한다. (요약) | [1차] [GitLab Handbook](https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/) |
| 꼬리물기 | 직전 답변의 구체화 | "지금 답변한 내용에서 좀 더 구체적으로 질문할게요." | [2차] 사람인 조사 보도, [뉴스토마토](https://newstomato.com/ReadNews.aspx?no=609973) |

**꼬리 질문에서 하지 말 것**
- 답을 암시하는 유도형 꼬리 질문 금지. [OPM 20쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf)
- 지원자의 말에 말이나 표정으로 반박하지 않는다. [OPM 20쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf)
- 질문 방식·몸짓·꼬리 질문으로 "사회적으로 바람직한 답"을 알려 주지 않는다. [OPM 35쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf)
- 예/아니오 답을 원할 때가 아니면 열린 질문으로 묻는다. [OPM 20쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf)

---

## 4. 질문 작성 규칙

### Do

- 모든 질문을 직무 역량에 연결한다. 직무와 관련 없는 요인은 묻지 않는다. [OPM 11·36쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf), [GitLab](https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/)
- 열린 질문, 짧고 분명하게, 적절한 읽기 수준, 전문용어 없이. 남이 소리 내 읽어 보고 이해되는지 검토한다. [OPM FAQ](https://www.opm.gov/frequently-asked-questions/assessment-policy-faq/structured-interviews/how-do-i-create-structured-interview-questions/)
- 경험형은 최상급 표현으로 사례 하나를 고르게 하고, STAR 세 조각을 끌어내게 쓴다. [OPM 11·12쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf)
- 모든 지원자에게 같은 질문을 같은 순서로 묻고, 같은 평정척도와 기준으로 평가한다. [OPM 5쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf) NCS도 직무 역량에 초점을 둔 구체적 질문과 체계적 평가를 기존 면접과 대비한다. [NCS](https://www.ncs.go.kr/blind/bl02/RH-103-003-04.scdo)
- 평정척도는 3~7단계, 최소 3단계에 이름을 붙이고, 단계별 **예시 답변(행동 기준)** 을 만든다. OPM 예시는 5점 척도에 "긴장도가 낮은/중간/높은 대인 상황을 다룬다" 식의 기준을 붙였다. [OPM 23~25쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf), [OPM 예시](https://www.opm.gov/policy-data-oversight/assessment-and-selection/examples/structured-interview-example.pdf)
- 평가할 때 한 역량 점수가 다른 역량 점수에 번지는 후광 효과, 모두 중간 점수를 주는 중앙 경향 등을 피한다. [OPM 48~49쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf)
- 경험형 질문을 시작하기 전에 STAR 구조로 답해 달라고 짧게 안내한다. [GitLab](https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/)

### Don't

- 유도형·반박형 꼬리 질문 금지(3장).
- 직무와 무관한 개인 신상 질문 금지. 구체 범위는 아래.

**한국 법령 (law.go.kr에서 원문 확인)**

- 「채용절차의 공정화에 관한 법률」 제4조의3(출신지역 등 개인정보 요구 금지) [시행 2020. 5. 26., 법률 제17326호]: 구인자는 구직자에게 직무 수행에 필요하지 않은 다음 정보를 **기초심사자료에 기재하도록 요구하거나 입증자료로 수집**하면 안 된다. [법령 원문](https://www.law.go.kr/법령/채용절차의공정화에관한법률/제4조의3)
  1. 구직자 본인의 용모·키·체중 등의 신체적 조건
  2. 구직자 본인의 출신지역·혼인여부·재산
  3. 구직자 본인의 직계 존비속 및 형제자매의 학력·직업·재산
  - "기초심사자료"는 응시원서, 이력서, 자기소개서를 말한다(제2조 제3호). 위반 시 500만원 이하 과태료(제17조 제2항 제3호). 상시 30명 이상 근로자를 쓰는 사업장에 적용(제3조). [법령 원문](https://www.law.go.kr/법령/채용절차의공정화에관한법률)
  - **주의**: 이 조문은 서류·증빙을 대상으로 하며 면접 질문을 직접 규정하지는 않는다. 면접 질문 금지는 아래 정책 지침에서 나온다.
- 「남녀고용평등과 일·가정 양립 지원에 관한 법률」 제7조: 모집·채용 시 남녀 차별 금지, 직무에 필요 없는 용모·키·체중 등 신체 조건과 미혼 조건 제시·요구 금지. [시행 2026. 9. 18. 기준 원문](https://www.law.go.kr/법령/남녀고용평등과일·가정양립지원에관한법률/제7조)
- 「고용상 연령차별금지 및 고령자고용촉진에 관한 법률」 제4조의4: 합리적 이유 없이 연령을 이유로 모집·채용에서 차별 금지. [법령 원문](https://www.law.go.kr/법령/고용상연령차별금지및고령자고용촉진에관한법률/제4조의4)

**공공 부문 블라인드 채용 지침 (면접 질문 직접 규정)**

- 2017년 정부 블라인드 채용 추진방안: 면접위원에게 응시자의 인적정보 제공을 금지하는 블라인드 면접, 인성·직무능력의 체계적 평가, 면접관 사전교육. [1차: 정책브리핑, 2017-07-05](https://www.korea.kr/briefing/policyBriefingView.do?newsId=156213395)
- 공공기관 채용공고 첨부 "블라인드 채용 설명 자료"(기관명은 문서에서 확인 안 됨): 면접위원은 응시자의 인적사항을 질문하면 안 되고, 차별 소지가 있는 질문은 삼간다. 예시로 **성별, 연령(학번 포함), 학력(학위소지), 출신지역, 병역, 결혼여부**를 든다. 응시자가 친인척, 성장배경, 가족관계 등을 의도적으로 말하면 제지한다. [1차(기관 미확인): 사람인 게시 첨부 PDF](https://dym-upload.saramin.co.kr/upload/dym2_5/645/3459/filedown/2025-04-08/djto03.pdf)

**해외 기업·기관 지침 (참고)**

- OPM: 나이, 성별, 인종, 출신국, 종교, 혼인·가족 상태, 장애·건강 상태, 그 밖의 직무 무관 요인에 대해 질문하거나 언급하지 말 것. [OPM 36쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf)
- GitLab: 보호 대상 특성(나이, 인종, 성별, 성정체성, 종교, 성적 지향, 혼인·가족 상태, 임신, 출신국, 혈통, 장애)에 관한 질문 금지. 특정 명절을 묻는 식의 가벼운 아이스브레이커도 보호 정보를 끌어낼 수 있어 피한다. 지원자가 스스로 꺼내면 인정하고 직무 주제로 돌린 뒤 **기록하지 않는다**. [GitLab](https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/)
- 삼성: 합리적 이유 없이 성별, 신앙, 연령, 신체조건, 사회적 신분, 출신지역, 학력 등으로 차별하지 않는다고 밝힌다. [삼성 채용 공정성 안내](https://www.samsungcareers.com/guide/fairness)

---

## 5. 우리 계획에 반영할 점

> 이 장의 예시 문장은 위 출처의 원칙을 적용해 **자체 작성**한 것이다. 출처에 있는 문장이 아니다.

### 유형별

1. **공통 기본 질문**
   - 1차 자료상 구조화 정도가 가장 낮은 유형이다(NCS가 "기존 면접" 예로 든다). 그래서 일반형("장점이 뭔가요?")보다 **직무와 회사에 묶은 형태**로 바꿔 쓴다. 사람인 조사에서도 상위 질문은 "직무 관련 강점", "직무에 대한 생각"처럼 직무에 묶여 있었다.
   - 자체 작성 예: "지원하신 직무에서 본인의 강점이 가장 잘 드러났던 경험 하나를 말씀해 주세요." (강점 질문을 경험형으로 전환)
   - 마무리는 "마지막으로 하고 싶은 말"보다 **지원자가 질문하는 시간**을 기본으로 둔다(GitLab, OPM). 점수에는 넣지 않거나 "질문·직무 이해"만 가볍게 본다.
   - "성장과정·가족" 질문은 생성 금지 목록에 넣는다.
2. **공통 인성 — 경험형**
   - 문형: "~했던 경험 중 **가장** ~했던 한 가지를 말씀해 주세요" (최상급 + 하나). 한 질문에 역량 하나만 담는다.
   - 질문 풀은 OPM이 구조화 면접에 적합하다고 한 역량(팀워크, 의사소통, 대인관계, 갈등관리, 설득)과 우리 범주(협업, 갈등, 실패, 책임감)를 대응시킨다. 실패 질문은 Amazon처럼 "무엇을 배웠는가"까지 묻는다.
   - 자체 작성 예: "팀 프로젝트에서 의견이 가장 크게 엇갈렸던 순간 하나를 말씀해 주세요."
3. **공통 인성 — 상황형**
   - 장면을 먼저 주고(역할, 사건, 제약), 마지막 문장은 "어떻게 하시겠습니까?" 하나로 끝낸다. 정답이 뻔하지 않은 딜레마로 만든다.
   - 직무 지식 없이도 답할 수 있게 쓴다(Google). 신입·학생 대상이므로 팀 프로젝트, 동아리, 인턴 장면을 쓴다.
   - 자체 작성 예: "마감 이틀 전, 팀원 한 명이 맡은 기능이 아직 동작하지 않는다는 사실을 알게 됐습니다. 어떻게 하시겠습니까?"
4. **서류 기반 질문**
   - 목적을 "서류 주장 검증"으로 둔다(Google). 프로젝트 질문의 기본 꼬리 질문 세트는 **참여자 구성 → 내 역할 → 내가 실제로 한 일 → 새로 배운 것** 순으로 고정한다(Amazon, OPM). 결과 수치는 우리 방침대로 가중치를 낮게 둔다.
   - "왜 기술 X를 택했나"는 1차 출처가 없으므로 **판단 근거 꼬리 질문**("어떤 대안을 고려했나요?", "그 선택의 단점은 무엇이었나요?")으로 구현한다. OPM·Google 꼬리 질문 문형이 근거다.
   - 서류에 적힌 내용과 답변이 어긋나면 그 부분을 다시 묻는다(GitLab의 일관성 신호).
5. **꼬리 질문**
   - 꼬리 질문은 **미리 정한 목록에서 고르는 방식**을 기본으로 한다(OPM, Google). LLM이 자유 생성하더라도 아래 트리거 → 패턴 매핑을 제약으로 준다.
     - 답변에 "우리", "저희 팀"만 있고 "제가"가 없다 → 본인 역할 좁히기("그중 본인이 직접 맡은 부분은 무엇이었나요?")
     - 답이 일반론(구체 장면·숫자·시점 없음) → 모호함 파고들기("가장 기억에 남는 한 장면을 구체적으로 말씀해 주세요.")
     - STAR 중 빠진 조각이 있다 → 해당 조각 질문(OPM S/T·A·R 꼬리 질문)
     - 결과는 있으나 배움이 없다 → "다시 한다면 무엇을 다르게 하시겠어요?"(OPM)
     - 상황형에서 행동 하나만 말했다 → "다른 방법도 있었을까요?", "그 행동이 상대에게 어떻게 받아들여질까요?"(OPM)
   - 유도형("~하셨죠?"), 반박형("그건 틀린 것 같은데요") 꼬리 질문은 생성 금지. 압박 면접 모드를 따로 두더라도 기본값에서는 쓰지 않는다.
   - 꼬리 질문 수는 질문당 상한을 둔다(OPM은 면접관이 정해진 질문만 순서대로 묻게 한다). 구체 상한은 우리가 정할 값이다.

### 채점 5개 항목과의 대응

| 채점 항목 | 근거가 되는 질문/꼬리 질문 | 출처 |
|---|---|---|
| 질문·직무 이해 | 지원동기, 직무에 대한 생각, 상황형의 "가장 중요한 쟁점은?" | 사람인(2차), OPM 22쪽 |
| 문제 해결과 판단 근거 | 상황형 전반, "그렇게 행동한 이유", "가장 중요하게 고려한 점", "어떤 요인을 고려했나", 장단점 | NCS 세부질문, OPM 22쪽, Google re:Work |
| 경험·행동의 구체성 | 경험형 주질문(최상급+하나), "What was your role?", "우리→나" 확인, 모호함 파고들기 | OPM 11·20·21쪽, Amazon, NCS |
| 결과와 학습 | "What was the outcome?", "다르게 했을 점", "후속조치를 한 사례", 실패에서 배운 점 | OPM 21쪽, NCS 세부질문 3, Amazon |
| 협업과 의사소통 | "팀원들은 어떻게 반응했나", 대인관계·갈등 경험형, 비전공자에게 이해되게 설명하는가 | Google re:Work, OPM 16쪽, GitLab |

- OPM은 질문별로 단계별 **예시 답변(행동 기준)** 을 미리 만들고 답변을 그것과 비교하라고 한다. 우리 5개 항목에도 1/3/5점 수준의 예시 답변을 붙이면 LLM 채점 일관성이 높아질 것으로 보인다(이 효과는 우리 환경에서 검증하지 않았다). [OPM 24~25·50쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf)
- 후광 효과 방지: 항목별로 따로 채점하고, 한 항목 점수를 다른 항목 근거로 쓰지 않게 프롬프트를 나눈다. [OPM 48쪽](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf)

---

## 부록 A. NCS 경험·상황면접 예시문항 첨부파일 확인 (2026-11-24)

[1차] NCS 포털 면접문항 예시문항 게시판의 두 첨부파일을 내려받아 읽고 삭제했다. 원본은 저장소에 두지 않는다.

- 「경험면접_직업기초능력+10분야.zip」, 「상황면접_직업기초능력.zip」: 각각 PDF 10개(2018-10-15 작성). 직업기초능력 10개(의사소통, 수리, 문제해결, 자기개발, 자원관리, 대인관계, 정보, 기술, 조직이해, 직업윤리)마다 「면접 도구」(주질문·세부질문)와 「평가도구」(평가준거·수준)가 한 파일에 있다.
- 출처: https://www.ncs.go.kr/blind/blp/bbs_lib_list.do?libDstinCd=56

### A-1. 문항 구조

- 능력마다 주질문 2~3개, 그 아래 **공통 세부질문 세트** 하나가 붙는다. 세부질문은 STAR 단계별로 묶여 있다.
- 경험면접 세부질문 단계: [상황 및 문제] → [역할] → [행동] → [결과]
  - 상황 및 문제: 언제, 어느 단체에서, 누구와 겪은 일인지, 그때 든 생각
  - 역할: 그 단체에서 맡은 역할, 지시를 받거나 내린 적이 있는지
  - 행동: 문제를 해결한 과정을 순서대로, 더 잘하려고 한 노력, 그 행동의 의도, 가장 어려웠던 점
  - 결과: 결과가 어땠는지, **아쉬웠던 점과 개선할 점**
- 상황면접 세부질문 단계: [상황 및 과제] → [역할] → [행동] → [결과]
  - 상황 및 과제: 이 상황의 핵심 과제가 무엇이라고 보는지
  - 역할: 파악해야 할 핵심 이해관계자가 누구인지
  - 행동: 과제를 더 잘 수행하려는 노력, 그 행동의 의도
  - 결과: **행동의 결과와 성과를 어떻게 예상하는지**
- 경험면접 주질문은 "~한 경험이 있다면 말씀해 주시기 바랍니다" 형태이고, 괄호로 경험 출처 예시(대학생활, 인턴십, 아르바이트, 교육경험, 캡스톤디자인 등)를 붙여 신입 지원자가 사례를 고를 수 있게 한다.
- 상황면접 주질문은 지원자의 역할(예: 물품 담당자, 상품개발팀 팀원, 프로젝트 팀장)과 사건, 제약(예산 없음, 상사의 지속적 요구, 이해관계 충돌)을 3~5문장으로 준 뒤 "어떻게 대처(해결, 진행)하시겠습니까?"로 끝난다.

### A-2. 주질문 주제 (요약, 우리 공통 인성 질문과 관련 있는 것 위주)

| 능력 | 경험면접 주제 | 상황면접 주제 |
|---|---|---|
| 대인관계 | 다양한 팀원과 문제를 개선한 경험(역할·수행 내용), 팀 프로젝트 갈등을 해결한 경험 | 일부에게만 불리한 자원 배분에 대한 불만 예상, 마찰 있는 동료와 계속 일하라는 팀장 요청 |
| 문제해결 | 조직 생활 중 문제를 주도적으로 해결한 경험, 가장 어려웠던 도전, 팀 과제 문제를 중재한 경험 | 퇴사자 업무 관련 민원에 대한 상사의 답변 독촉, 경쟁사 유사 제품 출시 임박 |
| 의사소통 | 불만 사항을 직접 소통해 해결한 경험, 고령자에게 새 기술을 설명한 경험, 요구사항 조율 경험 | 선배의 반복된 반려에 대한 소통, 더 나은 대안을 거부하는 상대 설득 |
| 자원관리 | 일정 변경 요구에 시간·자원을 조율한 경험, 급한 일을 시간 배분으로 완수한 경험 | 퇴사자 업무까지 맡아 과부하일 때 시간 배분 기준, 예산에 없는 전문가 검토 필요 |
| 자기개발 | 약점을 보완하려고 교육받은 경험, 자기개발로 성과를 낸 경험 | 입사 후 경력 목표와 계획, 가장 보완할 점과 받고 싶은 교육 |
| 기술 | 관습적 기술 대신 새 기술·장비를 적용한 경험 | 최신 기술 동향 파악 방법, 벤치마킹 대상 기술 선정 기준 |
| 정보 | 정보 수집으로 팀 과제에 기여한 경험 | 새 소프트웨어를 고르고 익히는 방법 |
| 직업윤리 | 편법의 유혹을 이기고 정직한 방법을 택한 경험, 지키기 어려운 약속을 지킨 경험 | 고객에게 불리한 재고 판매, 상사의 규정 위반 지시 |
| 조직이해 | 소속 조직의 가치 중 자신과 맞는 것 | 성과 경쟁 속 업무 배분 기준 |
| 수리 | 통계 분석·해석 경험 | 평균의 한계, 예산 부족 시 표본 조사 |

### A-3. 평가도구

- 능력마다 세부 능력 3~5개(예: 대인관계 → 팀워크, 리더십, 갈등관리, 협상, 고객서비스)와 각 평가준거가 있다. 평가준거는 같은 세부 능력을 낮은 수준(확인·인식) → 중간(분석·공유) → 높은 수준(종합·최적 선택·적용)의 행동 세 줄로 적는다.
- 수준은 5단계(탁월 100, 우수 80, 보통 70, 미흡 50, 기준미달 40점)이고, 기준은 "평가준거에 따른 기대행동이 얼마나 관찰되었는가"(완벽하게 → 상당히 → 약간 → 거의 안 됨 → 전혀 안 됨)다.
- 즉 점수는 답변의 인상이 아니라 **답변에서 관찰된 행동**에 근거한다. 각 능력에 「평가의 주안점」 목록이 따로 붙는다.

### A-4. 우리 계획에 반영할 점

1. 경험형 인성 질문의 추가 질문 세트를 NCS 세부질문 단계(상황 및 문제 → 역할 → 행동 → 결과)로 맞춘다. 특히 [역할] 단계는 우리 "본인 역할" 추가 질문의 공식 근거가 되고, [결과] 단계의 "아쉬웠던 점·개선할 점"은 우리 "배운 점" 추가 질문과 같은 목적이다.
2. 상황형 추가 질문에 NCS의 세 가지를 넣는다: 핵심 과제가 무엇인지, 핵심 이해관계자가 누구인지, 행동의 결과를 어떻게 예상하는지. 상황형에서도 "예상 결과"는 묻되 실제 결과·배운 점은 묻지 않는다.
3. 경험형 주질문에 경험 출처 예시(수업 프로젝트, 동아리, 인턴, 아르바이트 등)를 괄호로 붙여 학생도 답할 사례를 고르기 쉽게 한다.
4. 상황형 주질문은 NCS처럼 역할·사건·제약을 담은 3~5문장으로 쓴다(우리 계획의 200자 제한과 맞음). NCS 예시는 회사 업무 장면이 많으므로 학생 대상 연습에서는 팀 프로젝트·동아리 장면으로 바꾼다.
5. 등급 기준은 NCS처럼 "기대행동이 얼마나 관찰되었는가"로 정의하고, 각 평가 항목에 낮은·중간·높은 수준 행동을 적는다. 이것이 LLM 채점에서 답변 근거 문장을 요구하는 방식과 맞는다.
6. 인성 질문 주제 목록은 대인관계·문제해결·의사소통·자원관리·자기개발·직업윤리 주제에서 고른다. 수리·정보·조직이해는 직무에 따라 선택한다.

---

## 6. 출처 목록

접근 일자는 모두 2026-11-24.

### 1차 자료

| 출처 | URL | 비고 |
|---|---|---|
| U.S. OPM, *Structured Interviews* (교육 슬라이드, 52쪽, 2011년 작성 메타데이터) | https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/structured-interviews.pdf | 경험형/상황형 정의, 예시 질문, 꼬리 질문, 금지 질문, 평정 오류. 쪽 번호는 슬라이드 번호 |
| U.S. OPM, *Structured Interview: Example Question* | https://www.opm.gov/policy-data-oversight/assessment-and-selection/examples/structured-interview-example.pdf | 주질문·꼬리 질문·5점 척도 예시 |
| U.S. OPM FAQ, *How do I create structured interview questions?* | https://www.opm.gov/frequently-asked-questions/assessment-policy-faq/structured-interviews/how-do-i-create-structured-interview-questions/ | 질문 작성 규칙 |
| Google re:Work, *A guide to structured interviewing* | https://rework.withgoogle.com/intl/en/guides/a-guide-to-structured-interviewing-for-better-hiring-practices | 경험형/상황형 예시와 꼬리 질문 |
| GitLab Handbook, *Conducting a GitLab Interview* | https://handbook.gitlab.com/handbook/hiring/conducting-a-gitlab-interview/ | 경험형·상황형 문형, 점검 항목, 금지 질문 |
| About Amazon, *11 Amazon interview tips from recruiters and hiring managers* (2021-01-26 게시, 2024-02-06 수정) | https://www.aboutamazon.com/news/workplace/recruiters-offer-their-best-tips-for-interviewing-at-amazon | Amazon 공식 뉴스룸. dive deep, I vs we, 실패 |
| About Amazon, *Your complete guide to the Amazon interview process* (2025-04-08) | https://www.aboutamazon.com/news/workplace/amazon-interview-guide | STAR, "I" 진술, 한 상황 2~3분 |
| Amazon, *Interview loop* (atoz.amazon) | https://atoz.amazon/en-us/jobs/hiring-process/interview-loop | 주제 목록만 확인(세부 내용 없음) |
| 한국산업인력공단 NCS 포털, 채용전형 단계 > 면접유형 | https://www.ncs.go.kr/blind/bl02/RH-103-003-04.scdo | 경험면접 주질문·세부질문, 상황면접 예시 |
| NCS 포털, 면접문항 예시문항 게시판 | https://www.ncs.go.kr/blind/blp/bbs_lib_list.do?libDstinCd=56 | 경험·상황면접 직업기초능력 첨부파일(zip, PDF 각 10개)을 내려받아 확인 후 삭제. 내용은 부록 A |
| 국가법령정보센터, 채용절차의 공정화에 관한 법률 | https://www.law.go.kr/법령/채용절차의공정화에관한법률/제4조의3 | 제2조, 제3조, 제4조의3, 제17조 원문 확인 |
| 국가법령정보센터, 남녀고용평등법 제7조 | https://www.law.go.kr/법령/남녀고용평등과일·가정양립지원에관한법률/제7조 | 시행 2026. 9. 18. 판 |
| 국가법령정보센터, 고령자고용법 제4조의4 | https://www.law.go.kr/법령/고용상연령차별금지및고령자고용촉진에관한법률/제4조의4 | 시행 2022. 6. 10. 판 |
| 대한민국 정책브리핑, 블라인드 채용 추진방안 브리핑 (2017-07-05) | https://www.korea.kr/briefing/policyBriefingView.do?newsId=156213395 | 블라인드 면접, 면접관 사전교육 |
| 공공기관 채용공고 첨부 "블라인드 채용 설명 자료" (기관명 미확인, PDF 생성 2025-04-07) | https://dym-upload.saramin.co.kr/upload/dym2_5/645/3459/filedown/2025-04-08/djto03.pdf | 면접 금지 질문 예시. 게시 기관을 확인하지 못해 신뢰도 한 단계 낮게 본다 |
| 삼성전자, 채용 안내 | https://www.samsung.com/sec/about-us/careers/hiring-process-information/kr | 종합면접 구성·평가 항목 |
| 삼성 채용, 공정채용 안내 | https://www.samsungcareers.com/guide/fairness | 차별 금지 문구 |

### 학술 자료 (서지 정보는 Crossref API로 DOI 확인)

| 서지 | DOI | 확인 범위 |
|---|---|---|
| Latham, G. P., Saari, L. M., Pursell, E. D., & Campion, M. A. (1980). The situational interview. *Journal of Applied Psychology, 65*(4), 422–427. | https://doi.org/10.1037/0021-9010.65.4.422 | 서지만 확인. 초록·본문 미확인 |
| Janz, T. (1982). Initial comparisons of patterned behavior description interviews versus unstructured interviews. *Journal of Applied Psychology, 67*(5), 577–580. | https://doi.org/10.1037/0021-9010.67.5.577 | 서지만 확인. 초록·본문 미확인 |
| Campion, M. A., Palmer, D. K., & Campion, J. E. (1997). A review of structure in the selection interview. *Personnel Psychology, 50*(3), 655–702. | https://doi.org/10.1111/j.1744-6570.1997.tb00709.x | 서지와 초록 확인(OpenAlex). 초록: 구조의 15개 구성요소를 제시. 개별 요소 본문 미확인 |
| Levashina, J., Hartwell, C. J., Morgeson, F. P., & Campion, M. A. (2014). The structured employment interview: Narrative and quantitative review of the research literature. *Personnel Psychology, 67*(1), 241–293. | https://doi.org/10.1111/peps.12052 | 서지와 초록 확인(OpenAlex). 초록: 상황형 vs 과거행동형 비교, 꼬리 질문(probing, follow-up)을 주요 주제로 다룸. 결론 본문 미확인. Crossref 온라인 게재일은 2013-10-07 |
| Oostrom, J. K., Melchers, K. G., Ingold, P. V., & Kleinmann, M. (2016). Why do situational interviews predict performance? *Journal of Business and Psychology, 31*, 279–291. | https://doi.org/10.1007/s10869-015-9410-0 (본문: https://pmc.ncbi.nlm.nih.gov/articles/PMC4856718) | 본문 확인(오픈 액세스). 상황면접 설명에 사용 |

### 2차 자료 (국내 "빈출" 보조 근거)

| 출처 | URL | 비고 |
|---|---|---|
| 파이낸셜뉴스, 사람인 인사담당자 299명 신입 면접 조사 보도 (2015-10-19) | https://www.fnnews.com/news/201510191014023359 | 반드시 묻는 질문 순위, 첫 질문 자기소개. 조사가 오래됨 |
| 뉴스토마토, 사람인 인사담당자 266명 압박 질문 조사 보도 (2015-12-21) | https://newstomato.com/ReadNews.aspx?no=609973 | 꼬리물기형 53.3% |

---

## 7. 확인하지 못한 것

- **NCS 직무별(예: "30. 일반판매") 경험·상황면접 첨부파일**: 직업기초능력 두 파일만 확인했다(부록 A). 직무별 문항과 토론·발표면접 파일은 열지 않았다.
- **고용노동부 공정채용 가이드북 / 블라인드 채용 가이드북 원문**: 웹 검색으로 원문 PDF를 찾지 못했다. 행정안전부 「지방공공기관 블라인드 채용 가이드북」(2017) 사본 링크(incruit)는 접속이 거부됐다. 이 가이드북의 질문 예시는 미확인.
- **채용절차법이 면접 질문에도 적용되는지**: 제4조의3 문언은 기초심사자료(응시원서·이력서·자기소개서) 기재 요구와 입증자료 수집만 다룬다. 면접에서 같은 정보를 묻는 행위에 대한 고용노동부 해석은 찾지 못했다.
- **약점 질문, 입사 후 포부 질문의 1차 근거**: 공식 가이드나 기업 공식 페이지에서 구체 문항을 찾지 못했다. 사람인 조사 보도의 "미래 비전"(30.1%)이 지원자의 입사 후 포부를 뜻하는지, 회사의 미래 비전을 뜻하는지도 기사만으로는 불분명하다.
- **"왜 그 기술을 선택했나" 류 기술 질문의 공식 출처**: 토스·우아한형제들·카카오·네이버 공식 기술블로그나 채용 페이지에서 해당 질문을 예시로 든 글을 찾지 못했다. 검색에 나온 것은 개인 블로그와 강의 클립뿐이라 인용하지 않았다.
- **카카오·네이버·LG 공식 면접 안내**: 카카오는 보도자료 검색 요약에서 "코딩테스트 → 1·2차 인터뷰" 순서만 보였고 페이지를 직접 열지 않았다. 네이버·LG는 확인하지 못했다.
- **Microsoft, Meta, Google careers 공식 면접 준비 페이지**: Google careers 페이지는 본문이 스크립트로 렌더링돼 읽지 못했다. Microsoft 페이지는 403/타임아웃으로 열리지 않았다. Meta는 시도하지 않았다.
- **Amazon의 "Tell me about a time…" 구체 문항**: Amazon 공식 페이지에서는 행동 질문의 정의와 답변 지침만 확인했고, 리더십 원칙별 구체 질문 문장은 확인하지 못했다.
- **Latham et al. (1980), Janz (1982) 본문 내용**: DOI·서지는 확인했지만 초록과 본문을 읽지 못했다. 이 문서에서 두 논문의 내용은 OPM 교육자료의 전제 설명과 Oostrom et al. (2016)의 2차 서술에만 기대고 있다.
- **Campion et al. (1997)의 15개 구성요소 중 꼬리 질문(prompting/follow-up) 관련 요소의 정확한 권고 내용**: 초록만 확인했다.
- **사람인 조사의 최신판**: 확인한 조사는 2015년 자료다. 이후 조사 결과는 찾지 못했다.
