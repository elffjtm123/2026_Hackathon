import json
from uuid import UUID, uuid4

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select

from app.core.security import decode_token
from app.db.models.session import PracticeSession, SessionStatus
from app.realtime.events import ClientEvent, RealtimeEvent

router = APIRouter(tags=["realtime"])


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
        analysis_settings = session.settings

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
