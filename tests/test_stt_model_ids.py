"""Python owns the STT model IDs; the start schema and the frontend theme list must agree."""

import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from app.ai.experimental_stt import LABELS, MODEL_IDS
from app.realtime.events import SessionStartData

THEMES = Path(__file__).resolve().parents[1] / "src/features/model-themes/modelThemes.ts"


def frontend_model_ids() -> list[str]:
    source = THEMES.read_text(encoding="utf-8")
    block = re.search(r"export const modelThemes = \[(.*?)\] as const;", source, re.S)
    assert block, "modelThemes array not found in modelThemes.ts"
    return re.findall(r"\bid:\s*'([^']+)'", block.group(1))


def test_frontend_theme_ids_match_python_model_ids_in_order():
    assert frontend_model_ids() == list(MODEL_IDS)


def test_start_schema_accepts_exactly_the_python_model_ids():
    annotation = SessionStartData.model_fields["stt_model_id"].annotation
    literal = next(arg for arg in get_args(annotation) if arg is not type(None))
    assert get_args(literal) == MODEL_IDS
    for model_id in MODEL_IDS:
        assert SessionStartData.model_validate({"stt_model_id": model_id}).stt_model_id == model_id
    with pytest.raises(ValidationError):
        SessionStartData.model_validate({"stt_model_id": "not_a_model"})


def test_every_model_id_has_a_label():
    assert set(LABELS) == set(MODEL_IDS)
