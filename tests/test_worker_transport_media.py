from uuid import UUID

import pytest

from app.ai.base import MediaPayload
from app.ai.worker_transport import ProtocolError, decode_media, media_metadata


def metadata(**changes):
    media = MediaPayload(UUID(int=1), 0, b"", format="pcm16")
    return {**media_metadata(media), **changes}


@pytest.mark.parametrize("reason", [None, "endpoint", "max_length", "flush"])
def test_known_cut_reasons_are_accepted(reason):
    assert decode_media(metadata(cut_reason=reason), b"").cut_reason == reason


@pytest.mark.parametrize("reason", ["bogus", "", 3, ["flush"]])
def test_unknown_cut_reason_is_a_protocol_error(reason):
    with pytest.raises(ProtocolError):
        decode_media(metadata(cut_reason=reason), b"")
