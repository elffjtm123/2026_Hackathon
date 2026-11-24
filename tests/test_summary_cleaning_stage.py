import os

import pytest

from app.ai.script_summary import LocalScriptSummarizer
from app.core.config import Settings
from app.core.errors import AppError
from tests.test_local_llm import write_assets


@pytest.mark.asyncio
async def test_cleaning_stage_is_reported_before_the_server_is_terminated(
    tmp_path, monkeypatch
) -> None:
    # SIGTERM-ignoring server keeps its process alive for ~5s of cleanup after the timeout.
    server, model, pid_file = write_assets(tmp_path, ignore_sigterm=True)
    alive_at_cleaning: list[bool] = []

    def on_progress(update: dict) -> None:
        if update["stage"] == "cleaning":
            try:
                os.kill(int(pid_file.read_text()), 0)
                alive_at_cleaning.append(True)
            except ProcessLookupError:
                alive_at_cleaning.append(False)

    service = LocalScriptSummarizer(
        Settings(
            _env_file=None,
            summary_server_path=str(server),
            summary_model_path=str(model),
            summary_timeout_seconds=1.5,
        )
    )
    # The fake server hangs on prompts starting with "hang", so the summary times out alive.
    monkeypatch.setattr("app.ai.script_summary.INSTRUCTION", "hang")
    with pytest.raises(AppError) as info:
        await service.summarize("대기 문장.", on_progress)
    assert info.value.code == "SUMMARY_TIMEOUT"
    assert alive_at_cleaning and alive_at_cleaning[0] is True
