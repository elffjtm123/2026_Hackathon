import json
import time
from typing import Any
from uuid import UUID, uuid4

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select

from app.ai.mock import MockGazeAdapter, MockSpeechAdapter
from app.core.security import decode_token
from app.db.models.session import PracticeSession, SessionStatus
from app.realtime.events import ClientEvent, RealtimeEvent
from app.realtime.pipeline import SessionPipeline

router = APIRouter(tags=["realtime"])


def _frontend_feedback(event: RealtimeEvent) -> dict[str, Any] | None:
    if event.event == "error":
        return {
            "type": "error",
            "message": str(event.data.get("message", "실시간 처리 오류가 발생했습니다.")),
        }
    if event.event != "feedback":
        return None

    source = str(event.data.get("source", ""))
    level = str(event.data.get("level", "info"))
    metrics = event.data.get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}

    severity = "danger" if level == "danger" else "warning" if level == "warning" else "info"
    gaze_status = "unknown"
    speech_pace = "unknown"
    syllables_per_second = None
    filler_words: dict[str, int] = {}

    if source == "gaze":
        direction = str(metrics.get("direction", "unknown"))
        gaze_status = "away" if metrics.get("away") else direction
        if gaze_status not in {"center", "left", "right", "up", "down", "away"}:
            gaze_status = "unknown"
        speech_pace = "normal"

    if source == "speech_rate":
        gaze_status = "center"
        syllables_per_minute = float(metrics.get("syllables_per_minute", 0) or 0)
        syllables_per_second = round(syllables_per_minute / 60, 2)
        if syllables_per_minute == 0:
            speech_pace = "unknown"
        elif syllables_per_minute > 360:
            speech_pace = "fast"
        elif syllables_per_minute < 140:
            speech_pace = "slow"
        else:
            speech_pace = "normal"
        for item in metrics.get("filler_words", []):
            if isinstance(item, dict):
                word = str(item.get("word", ""))
                count = int(item.get("count", 0) or 0)
                if word:
                    filler_words[word] = count

    return {
        "type": "feedback",
        "sessionId": str(event.session_id),
        "source": source,
        "timestamp": event.timestamp_ms or int(time.time() * 1000),
        "severity": severity,
        "gaze": {
            "status": gaze_status,
            "confidence": metrics.get("confidence"),
            "message": event.data.get("message") if source == "gaze" else None,
        },
        "speech": {
            "pace": speech_pace,
            "syllablesPerSecond": syllables_per_second,
            "message": event.data.get("message") if source == "speech_rate" else None,
        },
        "filler": {
            "latestWord": next(iter(filler_words), None),
            "totalCount": sum(filler_words.values()),
            "counts": filler_words,
        },
        "message": str(event.data.get("message", "")),
    }


@router.websocket("/ws/practice-demo")
async def practice_demo_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = websocket.app.state.settings
    session_id = uuid4()
    try:
        from app.ai.video_gaze import VideoGazeAdapter

        gaze = VideoGazeAdapter()
    except Exception:
        gaze = MockGazeAdapter()
    pipeline = SessionPipeline(
        session_id,
        settings,
        websocket.app.state.state_store,
        gaze,
        MockSpeechAdapter(),
        {
            "gaze_enabled": True,
            "speech_rate_enabled": True,
            "filler_detection_enabled": True,
        },
    )
    await pipeline.start()
    subscriber_id = f"demo-{uuid4()}"

    async def send(event: RealtimeEvent) -> None:
        feedback = _frontend_feedback(event)
        if feedback is not None:
            await websocket.send_json(feedback)

    pipeline.subscribe(subscriber_id, send)
    await pipeline.emit("session.ready", pipeline.elapsed_ms(), {"transport": "practice-demo"})

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            raw_bytes = message.get("bytes")
            raw_text = message.get("text")

            if raw_bytes is not None:
                if len(raw_bytes) < 9 or len(raw_bytes) > settings.max_media_message_bytes:
                    await pipeline.emit_error("INVALID_MEDIA", "영상 메시지가 올바르지 않습니다.")
                    continue
                payload_type = raw_bytes[0]
                timestamp_ms = int.from_bytes(raw_bytes[1:9], "big", signed=False)
                if payload_type == 0x01:
                    await pipeline.push_video(timestamp_ms, raw_bytes[9:])
                elif payload_type == 0x02:
                    await pipeline.push_audio(timestamp_ms, raw_bytes[9:])
                else:
                    await pipeline.emit_error(
                        "INVALID_PAYLOAD_TYPE", "지원하지 않는 미디어 타입입니다."
                    )
                continue

            if raw_text is None:
                await pipeline.emit_error("INVALID_MESSAGE", "메시지가 올바르지 않습니다.")
                continue

            try:
                client_event = ClientEvent.model_validate(json.loads(raw_text))
            except (json.JSONDecodeError, ValidationError):
                await pipeline.emit_error(
                    "INVALID_MESSAGE", "JSON 메시지 형식이 올바르지 않습니다."
                )
                continue

            if client_event.event == "ping":
                await pipeline.emit("pong", client_event.timestamp_ms, {})
            elif client_event.event == "session.start":
                await pipeline.emit("session.started", client_event.timestamp_ms, client_event.data)
            elif client_event.event in {"transcript.partial", "transcript.final"}:
                text = str(client_event.data.get("text", ""))
                if len(text) > 10_000:
                    await pipeline.emit_error("TRANSCRIPT_TOO_LARGE", "텍스트가 너무 깁니다.")
                else:
                    await pipeline.push_audio(client_event.timestamp_ms, text.encode())
    except WebSocketDisconnect:
        pass
    finally:
        pipeline.unsubscribe(subscriber_id)
        await pipeline.stop()
        if hasattr(gaze, "close"):
            gaze.close()


@router.websocket("/ws/sessions/{session_id}")
async def session_websocket(websocket: WebSocket, session_id: UUID, token: str) -> None:
    settings = websocket.app.state.settings
    try:
        claims = decode_token(token, "access", settings)
    except jwt.PyJWTError:
        await websocket.close(code=4401, reason="invalid token")
        return
    async with websocket.app.state.database.sessions() as db:
        session = await db.scalar(
            select(PracticeSession).where(
                PracticeSession.id == session_id, PracticeSession.user_id == claims.subject
            )
        )
        if session is None:
            await websocket.close(code=4404, reason="session not found")
            return
        if session.status not in {SessionStatus.created, SessionStatus.active}:
            await websocket.close(code=4409, reason="session is not active")
            return
        connection_count = websocket.app.state.websocket_counts.get(session_id, 0)
        if connection_count >= settings.max_connections_per_session:
            await websocket.close(code=4429, reason="too many connections")
            return
        if session.status == SessionStatus.created:
            from app.services.session_service import activate_session

            await activate_session(db, session)
        analysis_settings = {
            **session.settings,
            "script": session.active_script,
            "time_limit_seconds": session.time_limit_seconds,
        }

    await websocket.accept()
    websocket.app.state.websocket_counts[session_id] = connection_count + 1
    pipeline = await websocket.app.state.pipelines.get_or_create(session_id, analysis_settings)
    subscriber_id = f"ws-{uuid4()}"

    async def send(event: RealtimeEvent) -> None:
        await websocket.send_text(event.model_dump_json())

    pipeline.subscribe(subscriber_id, send)
    ready = await pipeline.emit("session.ready", pipeline.elapsed_ms(), {"transport": "websocket"})
    if subscriber_id not in pipeline.subscribers:
        await websocket.send_text(ready.model_dump_json())
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            allowed = await websocket.app.state.state_store.allow_realtime_message(
                claims.subject, settings.max_realtime_messages_per_second
            )
            if not allowed:
                await pipeline.emit_error("RATE_LIMITED", "메시지 전송 속도가 너무 빠릅니다.")
                continue
            raw_bytes = message.get("bytes")
            raw_text = message.get("text")
            if raw_bytes is not None:
                if len(raw_bytes) > settings.max_media_message_bytes:
                    await pipeline.emit_error("PAYLOAD_TOO_LARGE", "미디어 메시지가 너무 큽니다.")
                    continue
                if len(raw_bytes) < 9:
                    await pipeline.emit_error(
                        "INVALID_MEDIA_HEADER", "미디어 헤더가 올바르지 않습니다."
                    )
                    continue
                payload_type = raw_bytes[0]
                timestamp_ms = int.from_bytes(raw_bytes[1:9], "big", signed=False)
                if payload_type == 0x01:
                    await pipeline.push_video(timestamp_ms, raw_bytes[9:])
                elif payload_type == 0x02:
                    await pipeline.push_audio(timestamp_ms, raw_bytes[9:])
                else:
                    await pipeline.emit_error(
                        "INVALID_PAYLOAD_TYPE", "지원하지 않는 미디어 타입입니다."
                    )
                continue
            if raw_text is None or len(raw_text.encode()) > settings.max_json_message_bytes:
                await pipeline.emit_error("INVALID_MESSAGE", "메시지가 올바르지 않습니다.")
                continue
            try:
                client_event = ClientEvent.model_validate(json.loads(raw_text))
            except (json.JSONDecodeError, ValidationError):
                await pipeline.emit_error(
                    "INVALID_MESSAGE", "JSON 메시지 형식이 올바르지 않습니다."
                )
                continue
            if client_event.event == "ping":
                await pipeline.emit("pong", client_event.timestamp_ms, {})
            elif client_event.event in {"transcript.partial", "transcript.final"}:
                text = str(client_event.data.get("text", ""))
                if len(text) > 10_000:
                    await pipeline.emit_error("TRANSCRIPT_TOO_LARGE", "텍스트가 너무 깁니다.")
                else:
                    await pipeline.push_audio(client_event.timestamp_ms, text.encode())
    except WebSocketDisconnect:
        pass
    finally:
        pipeline.unsubscribe(subscriber_id)
        websocket.app.state.websocket_counts[session_id] = max(
            0, websocket.app.state.websocket_counts.get(session_id, 1) - 1
        )
