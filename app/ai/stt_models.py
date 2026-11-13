"""The one list of selectable STT model IDs; MODEL_IDS and the start schema derive from it.

tests/test_stt_model_ids.py fails if src/features/model-themes/modelThemes.ts drifts.
"""

from typing import Literal, get_args

SttModelId = Literal[
    "service_qwen", "qwen_q8", "whisper_small_int8", "whisper_base_int8", "zipformer_int8"
]
MODEL_IDS: tuple[SttModelId, ...] = get_args(SttModelId)
