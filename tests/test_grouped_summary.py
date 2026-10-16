import asyncio
import json

import httpx
import pytest

from app.ai.script_summary import LocalScriptSummarizer
from app.core.config import Settings


def service():
    return LocalScriptSummarizer(Settings(_env_file=None))


def test_group_ranges_preserve_repeated_original_sentences():
    item = service()._group(
        {"start_sentence": 0, "end_sentence": 1, "hint": "같은 설명 묶기"},
        ["같은 문장.", "같은 문장."],
        0,
        2,
    )
    assert item == {
        "start_sentence": 0,
        "end_sentence": 1,
        "original": "같은 문장. 같은 문장.",
        "hint": "같은 설명 묶기",
        "error": None,
    }


@pytest.mark.parametrize(
    "raw",
    [
        {"start_sentence": 1, "end_sentence": 1, "hint": "누락"},
        {"start_sentence": 0, "end_sentence": 2, "hint": "범위 초과"},
        {"start_sentence": 0, "end_sentence": -1, "hint": "역순"},
        {"start_sentence": False, "end_sentence": 1, "hint": "bool"},
        {"start_sentence": 0, "end_sentence": 1, "hint": " "},
        {"start_sentence": 0, "end_sentence": 1, "hint": "가" * 161},
    ],
)
def test_bad_group_boundaries_are_rejected(raw):
    with pytest.raises(ValueError):
        service()._group(raw, ["첫 문장.", "둘째 문장."], 0, 2)


@pytest.mark.asyncio
async def test_stream_validated_group_progress_before_generation_finishes():
    model = service()
    updates = []
    model._progress = updates.append
    first = json.dumps(
        {"start_sentence": 0, "end_sentence": 1, "hint": "문제와 해결"}, ensure_ascii=False
    )
    second = json.dumps(
        {"start_sentence": 2, "end_sentence": 2, "hint": "원본 미저장"}, ensure_ascii=False
    )

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            for fragment in ['{"groups":[', first, ",", second, "]}"]:
                chunk = {"choices": [{"delta": {"content": fragment}, "finish_reason": None}]}
                yield ("data: " + json.dumps(chunk) + "\n\n").encode()
                if fragment == first:
                    assert updates[-1]["completed_sentences"] == 2
                    assert updates[-1]["total_sentences"] == 3
            yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            yield b"data: [DONE]\n\n"

    async def handler(request):
        body = json.loads(request.content)
        assert body["stream"] is True
        return httpx.Response(200, stream=Stream())

    async with httpx.AsyncClient(
        base_url="http://model", transport=httpx.MockTransport(handler)
    ) as client:
        groups = await model._batch(client, "prompt", ["문제.", "해결.", "원본 미저장."], 0, 3)
    assert [g["end_sentence"] for g in groups] == [1, 2]
    assert updates[-1]["completed_sentences"] == 3


def test_ndjson_route_emits_progress_and_complete_after_model_cleanup(client, monkeypatch):
    async def summarize(script, on_progress=None):
        assert on_progress is not None
        on_progress(
            {
                "stage": "preparing",
                "completed_sentences": 0,
                "total_sentences": 2,
                "failed_sentences": 0,
            }
        )
        await asyncio.sleep(0)
        on_progress(
            {
                "stage": "cleaning",
                "completed_sentences": 2,
                "total_sentences": 2,
                "failed_sentences": 0,
            }
        )
        return {"normalized_script": script, "groups": [], "model": "test", "elapsed_seconds": 1}

    monkeypatch.setattr(client.app.state.script_summarizer, "summarize", summarize)
    response = client.post(
        "/api/v1/scripts/summarize",
        headers={"Origin": "http://testserver", "Accept": "application/x-ndjson"},
        json={"script": "첫 문장. 다음 문장."},
    )
    assert response.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["event"] for event in events] == ["progress", "progress", "complete"]
