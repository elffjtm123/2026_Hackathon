# 면접 연습 샘플 문서

모든 인물·학교·회사·연락처는 가상입니다(실존 인물 정보 없음). 공개 샘플을 찾지 않고 직접 만든 합성 문서입니다.

| 세트 | 직무 | 이력서 | 자기소개서 | 포트폴리오 |
|---|---|---|---|---|
| `a_ai_engineer` | AI 엔지니어 신입(프로젝트 다수) | `resume.pdf` | `cover_letter.docx` | `portfolio.txt` |
| `b_backend` | 백엔드 개발자 신입(인턴) | `resume.docx`(표 포함) | `cover_letter.txt` | `portfolio.pdf` |
| `c_planning` | 기획·마케팅(활동 중심) | `resume.txt` | `cover_letter.pdf` | `portfolio.docx`(표 포함) |

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
