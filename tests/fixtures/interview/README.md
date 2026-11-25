# 면접 연습 샘플 문서

모든 인물·학교·회사·연락처는 가상입니다. 실존 인물의 이름, 연락처, 학교, 회사명은 들어 있지 않습니다.

문서 내용은 공개된 개발자 이력서의 요소(프로젝트 유형, 문제와 해결 방식, 기술 스택)를 익명화하고 문장을 바꿔 쓴 뒤 여러 출처를 섞어 만들었습니다. 고유한 수치는 다른 값으로 바꿨고, 한 사람이 특정되지 않도록 세부 내용을 조합했습니다. 이력서의 섹션 구조(요약, 경력, 경험, 학력, ETC)는 공개된 가상 이력서 양식을 따랐고 그 문구는 쓰지 않았습니다.

| 세트 | 직무 | 이력서 | 자기소개서 | 포트폴리오 |
|---|---|---|---|---|
| `a_ai_engineer` | AI/ML 엔지니어 신입 | `resume.pdf` | `cover_letter.docx` | `portfolio.txt` |
| `b_backend` | 백엔드 개발자 신입(인턴 포함) | `resume.docx`(표 포함) | `cover_letter.txt` | `portfolio.pdf` |
| `c_frontend` | 프론트엔드 개발자 신입~2년차 | `resume.txt` | `cover_letter.pdf` | `portfolio.docx`(표 포함) |

`extra/` 는 오류·검증 테스트용입니다.

- `short.txt`: 일부러 짧은 문서
- `banned_topics_cover_letter.txt`: 가족·고향·나이·결혼 언급(질문 생성 금지 주제 검증용)
- `image_only.pdf`: 텍스트 층이 없는 PDF(스캔본 대용)
- `not_a_document.pdf`: PNG 헤더만 있는 파일을 `.pdf`로 이름만 바꾼 것

## 다시 만들기

내용 원본은 `src/` 의 텍스트 파일이고, 바이너리는 아래 명령으로 생성합니다.

```
.venv310/bin/python scripts/make_interview_fixtures.py
```

PDF에는 `reportlab`(dev 의존성)이 필요합니다. 글꼴은 reportlab 내장 CID 글꼴(`HYSMyeongJo-Medium`)을 이름으로만 참조하고 파일에 넣지 않으므로 저장소에 글꼴 데이터가 들어가지 않습니다.
