"""Measure interview generation timings with the real local model (plan stage 7).

For each sample document set (tests/fixtures/interview/{a,b,c}_*):
  1. question plan (model load, material extraction, question generation, cleanup)
  2. round-break follow-up generation on synthetic answers (model load + calls)
  3. evaluation of 8 main answers + up to 2 follow-up answers (model load + calls + summary)

Answers are written text (no audio), so speech recognition, realtime model restart and
auto-advance accuracy are not measured here. llama-server RSS is sampled every 0.5 s.

Usage: .venv310/bin/python scripts/experiment_interview.py [--sets a_ai_engineer ...] [--out PATH]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ai.interview_llm import InterviewLlm  # noqa: E402
from app.ai.local_llm import LocalLlm  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.modules.interview.composition import Composition  # noqa: E402
from app.modules.interview.documents import DocumentExtractor, DocumentKind  # noqa: E402
from app.modules.interview.questions import (  # noqa: E402
    FinalUtterance,
    ItemRecord,
    PlannedQuestion,
)

FIXTURES = ROOT / "tests/fixtures/interview"
KINDS = {
    "cover_letter": DocumentKind.COVER_LETTER,
    "resume": DocumentKind.RESUME,
    "portfolio": DocumentKind.PORTFOLIO,
}

# Synthetic answers by style; cycled over the questions so every run has a mix.
ANSWERS: dict[str, str] = {
    "good": (
        "작년 2학기 캡스톤 프로젝트에서 저는 네 명 중 백엔드를 맡았습니다. "
        "배포 직전에 응답 시간이 3초까지 늘어나는 문제가 생겼고, 제가 로그를 보고 "
        "같은 쿼리가 반복 호출되는 것을 찾았습니다. 캐시와 인덱스 두 가지를 비교했는데 "
        "데이터가 자주 바뀌어서 인덱스를 골랐고, 응답 시간을 0.4초로 줄였습니다. "
        "이 일로 추측보다 측정을 먼저 해야 한다는 것을 배웠고, 이후에는 기능을 만들 때 "
        "처음부터 응답 시간을 기록하고 있습니다. 팀원들과는 매일 짧게 진행 상황을 공유했습니다."
    ),
    "generic": (
        "저는 항상 책임감을 가지고 열심히 하는 편입니다. 팀 프로젝트에서도 우리 팀은 "
        "서로 소통을 많이 했고 좋은 결과를 얻었습니다. 그 과정에서 협업의 중요성을 "
        "배웠고 앞으로도 성실하게 일하고 싶습니다. 어려운 일이 있어도 포기하지 않습니다."
    ),
    "short": "네 열심히 하겠습니다.",
    "none": "",
}
STYLE_CYCLE = ["good", "generic", "good", "short", "good", "generic", "none", "good"]


class RssSampler:
    """Peak RSS of llama-server processes (children of this process) and of this process."""

    def __init__(self) -> None:
        self.peak_server_mb = 0.0
        self.peak_self_mb = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        me = psutil.Process()
        while not self._stop.wait(0.5):
            try:
                self.peak_self_mb = max(self.peak_self_mb, me.memory_info().rss / 2**20)
                total = 0.0
                for child in me.children(recursive=True):
                    if "llama" in child.name():
                        total += child.memory_info().rss / 2**20
                self.peak_server_mb = max(self.peak_server_mb, total)
            except psutil.Error:
                pass

    def __enter__(self) -> RssSampler:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()


class StageTimer:
    """Record the elapsed time at which each progress stage first starts."""

    def __init__(self) -> None:
        self.start = time.monotonic()
        self.events: list[dict[str, Any]] = []

    def __call__(self, event: dict[str, Any]) -> None:
        self.events.append({**event, "t": round(time.monotonic() - self.start, 2)})


def load_documents(set_dir: Path) -> list[Any]:
    files = []
    for path in sorted(set_dir.iterdir()):
        kind = KINDS.get(path.stem)
        if kind is not None:
            files.append((kind, path.name, path.read_bytes()))
    return DocumentExtractor().extract_many(files)


def make_item(question: PlannedQuestion, style: str, start_ms: int) -> ItemRecord:
    text = ANSWERS[style]
    utterances = []
    if text:
        duration = max(2000, len(text) * 150)
        utterances = [
            FinalUtterance(
                "u-" + question.id,
                start_ms + 3000,
                start_ms + 3000 + duration,
                text,
                int(duration * 0.8),
            )
        ]
    end = utterances[-1].end_ms + 4000 if utterances else start_ms + 20000
    return ItemRecord(
        question=question,
        shown_ms=start_ms,
        answer_started_ms=utterances[0].start_ms if utterances else None,
        ended_ms=end,
        advance_reason="silence" if text else "no_response",
        replay_used=False,
        utterances=utterances,
        transcript=text,
    )


def jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(getattr(k, "value", k)): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return getattr(value, "value", value)


async def run_set(name: str, interview: InterviewLlm, llm: LocalLlm) -> dict[str, Any]:
    result: dict[str, Any] = {"set": name}
    documents = load_documents(FIXTURES / name)
    result["document_chars"] = sum(len(d.text) for d in documents)

    # 1. plan
    timer = StageTimer()
    with RssSampler() as rss:
        plan = await interview.plan(documents, None, Composition(), [], timer)
    result["plan"] = {
        "seconds": round(time.monotonic() - timer.start, 2),
        "stages": timer.events,
        "warnings": list(plan.warnings),
        "questions": [
            {
                "id": q.id,
                "kind": q.kind,
                "subtype": q.subtype,
                "text": q.text,
                "source_quote": q.source_quote,
            }
            for q in plan.questions
        ],
        "peak_server_mb": round(rss.peak_server_mb),
    }

    items = []
    styles: dict[str, str] = {}
    clock = 0
    for index, question in enumerate(plan.questions):
        style = STYLE_CYCLE[index % len(STYLE_CYCLE)] if question.rubric_items else "good"
        item = make_item(question, style, clock)
        items.append(item)
        styles[question.id] = style
        clock = item.ended_ms + 1000

    # 2. round-break follow-ups (model load + calls; realtime restart not included)
    start = time.monotonic()
    with RssSampler() as rss:
        async with llm.loaded() as session:
            loaded_at = time.monotonic()
            follow_ups = await interview.follow_ups(items, session)
            generated_at = time.monotonic()
    result["follow_ups"] = {
        "load_seconds": round(loaded_at - start, 2),
        "generate_seconds": round(generated_at - loaded_at, 2),
        "total_seconds": round(time.monotonic() - start, 2),
        "questions": [
            {
                "parent_id": q.parent_id,
                "gap": q.subtype,
                "text": q.text,
                "answer_quote": q.source_quote,
            }
            for q in follow_ups
        ],
        "peak_server_mb": round(rss.peak_server_mb),
    }
    for question in follow_ups:
        item = make_item(question, "good", clock)
        items.append(item)
        styles[question.id] = "good"
        clock = item.ended_ms + 1000

    # 3. evaluation (8 main + follow-ups)
    timer = StageTimer()
    with RssSampler() as rss:
        async with llm.loaded() as session:
            timer({"stage": "loaded"})
            evaluation = await interview.evaluate(items, session, timer)
            timer({"stage": "evaluated"})
    result["evaluation"] = {
        "seconds": round(time.monotonic() - timer.start, 2),
        "stages": timer.events,
        "styles": styles,
        "result": jsonable(evaluation),
        "peak_server_mb": round(rss.peak_server_mb),
    }
    return result


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sets", nargs="*", default=["a_ai_engineer", "b_backend", "c_frontend"])
    parser.add_argument("--out", default=str(ROOT / "experiments/interview/timings.json"))
    args = parser.parse_args()
    settings = get_settings()
    llm = LocalLlm(settings)
    interview = InterviewLlm(
        llm,
        timeout_seconds=settings.interview_plan_timeout_seconds,
        evaluation_timeout_seconds=settings.interview_evaluation_timeout_seconds,
    )
    results = []
    for name in args.sets:
        print(f"== {name}", flush=True)
        result = await run_set(name, interview, llm)
        print(
            json.dumps(
                {k: v for k, v in result.items() if k == "set" or k == "document_chars"}
                | {
                    "plan_s": result["plan"]["seconds"],
                    "follow_up_s": result["follow_ups"]["total_seconds"],
                    "evaluation_s": result["evaluation"]["seconds"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        results.append(result)
    out = Path(args.out)
    text = json.dumps(results, ensure_ascii=False, indent=2)
    await asyncio.to_thread(out.parent.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(out.write_text, text)
    print(f"wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
