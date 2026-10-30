import asyncio
import contextlib
import ipaddress
import json
import time
from typing import Any
from uuid import UUID, uuid4

import jwt
from anyio import CancelScope
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import select
from starlette.types import Message

from app.ai.model_execution import finish
from app.core.security import decode_token
from app.db.models.session import PracticeSession, SessionStatus
from app.realtime.events import ClientEvent, RealtimeEvent, SessionStartData, V2ClientEvent
from app.realtime.media import decode_media_v2
from app.realtime.pipeline import SessionPipeline

router = APIRouter(tags=["realtime"])


async def _v2_session(
    websocket: WebSocket,
    session_id: UUID,
    stored_settings: dict[str, Any] | None = None,
    user_id: UUID | None = None,
) -> None:
    settings = websocket.app.state.settings
    pipeline = SessionPipeline(
        session_id,
        settings,
        websocket.app.state.state_store,
        websocket.app.state.gaze,
        websocket.app.state.speech,
        stored_settings or {},
        websocket.app.state.model_execution,
    )
    pipeline.protocol = 2
    subscriber = f"v2-{uuid4()}"
    send_lock = asyncio.Lock()

    async def send(event: RealtimeEvent) -> None:
        async with send_lock:
            await websocket.send_text(event.model_dump_json())

    pipeline.subscribe(subscriber, send)
    started = False
    client_sequence = 0
    calibration_timer: asyncio.Task[None] | None = None
    live_registered = False
    pending_message: Message | None = None
    # Latest audio settings that arrive while the model is still preparing (the pipeline may be
    # swapped). Only the last value matters, so a flooding client cannot grow memory.
    early_audio_settings: Any = None
    has_early_audio_settings = False

    async def prepare_or_cancel(operation: asyncio.Task[None]) -> bool:
        nonlocal client_sequence, pending_message, early_audio_settings, has_early_audio_settings
        receiving = asyncio.create_task(websocket.receive())
        try:
            while True:
                done, _ = await asyncio.wait(
                    (operation, receiving), return_when=asyncio.FIRST_COMPLETED
                )
                if receiving in done:
                    message = receiving.result()
                    if message.get("type") == "websocket.disconnect":
                        pipeline.incomplete = True
                        raise WebSocketDisconnect()
                    raw = message.get("text")
                    if raw is None or len(raw.encode()) > settings.max_json_message_bytes:
                        raise ValueError("SESSION_NOT_READY")
                    event = V2ClientEvent.model_validate(json.loads(raw))
                    if event.event == "session.end" and event.session_id in {None, session_id}:
                        if event.sequence <= client_sequence:
                            raise ValueError("INVALID_CONTROL_SESSION_OR_SEQUENCE")
                        client_sequence = event.sequence
                        pipeline.incomplete = True
                        return False
                    if event.event == "session.audio_settings" and event.session_id in {
                        None,
                        session_id,
                    }:
                        if event.sequence <= client_sequence:
                            raise ValueError("INVALID_CONTROL_SESSION_OR_SEQUENCE")
                        client_sequence = event.sequence
                        early_audio_settings = event.data.get("audio_settings")
                        has_early_audio_settings = True
                        # Always re-arm: the consumed message must never be re-captured.
                        receiving = asyncio.create_task(websocket.receive())
                        continue
                    if operation in done:
                        pending_message = message
                        await operation
                        return True
                    if event.event != "ping":
                        raise ValueError("SESSION_NOT_READY")
                    receiving = asyncio.create_task(websocket.receive())
                elif operation in done:
                    await operation
                    return True
        finally:
            if receiving.done() and not receiving.cancelled() and pending_message is None:
                with contextlib.suppress(Exception):
                    pending_message = receiving.result()
            receiving.cancel()
            if not operation.done():
                operation.cancel()

            async def settle() -> None:
                await asyncio.gather(operation, receiving, return_exceptions=True)

            await finish(asyncio.create_task(settle()))

    async def calibration_deadline() -> None:
        await asyncio.sleep(15)
        if pipeline.phase == "calibrating":
            pipeline.gaze_stabilizer.invalidate("timeout")
            await pipeline.emit_error(
                "CALIBRATION_TIMEOUT",
                "보정 시간이 초과되었습니다. 정면을 보고 ‘다시 보정’을 눌러 주세요.",
            )

    try:
        while True:
            message = pending_message if pending_message is not None else await websocket.receive()
            pending_message = None
            if message.get("type") == "websocket.disconnect":
                pipeline.incomplete = True
                break
            if (
                user_id is not None
                and not await websocket.app.state.state_store.allow_realtime_message(
                    user_id, settings.max_realtime_messages_per_second
                )
            ):
                pipeline.incomplete = True
                await pipeline.emit_error("RATE_LIMITED", "메시지 전송 속도가 너무 빠릅니다.")
                continue
            try:
                if message.get("bytes") is not None:
                    if len(message["bytes"]) > settings.max_media_message_bytes:
                        raise ValueError("PAYLOAD_TOO_LARGE")
                    media = decode_media_v2(message["bytes"], session_id, pipeline.audio_origin_ms)
                    await pipeline.accept_media(media)
                    continue
                raw = message.get("text")
                if raw is None or len(raw.encode()) > settings.max_json_message_bytes:
                    raise ValueError("INVALID_MESSAGE_SIZE")
                event = V2ClientEvent.model_validate(json.loads(raw))
                # The client may not know the session id yet (model still preparing).
                early_end = (
                    event.event in {"session.end", "session.audio_settings"}
                    and event.session_id is None
                )
                if event.sequence <= client_sequence or (
                    started and event.session_id != session_id and not early_end
                ):
                    raise ValueError("INVALID_CONTROL_SESSION_OR_SEQUENCE")
                if not early_end and event.timestamp_ms > pipeline.elapsed_ms() + 1000:
                    raise ValueError("INVALID_CONTROL_TIMESTAMP")
                client_sequence = event.sequence
                if event.event == "session.start":
                    if started:
                        raise ValueError("SESSION_ALREADY_STARTED")
                    if websocket.app.state.script_summarizer.busy:
                        raise ValueError("SUMMARY_BUSY")
                    data = SessionStartData.model_validate(event.data)
                    raw_audio_settings = event.data.get("audio_settings")
                    analysis = {
                        **data.settings.model_dump(),
                        "script": data.script,
                        "time_limit_seconds": data.time_limit_seconds,
                    }

                    async def prepare(
                        analysis_settings: dict[str, Any] = analysis,
                        raw_audio_settings: Any = raw_audio_settings,
                    ) -> None:
                        nonlocal pipeline, live_registered
                        if stored_settings is not None:
                            prepared = await websocket.app.state.pipelines.get_or_create(
                                session_id, stored_settings, protocol=2
                            )
                            pipeline.unsubscribe(subscriber)
                            pipeline = prepared
                            pipeline.subscribe(subscriber, send)
                        pipeline.update_analysis_settings(
                            stored_settings if stored_settings is not None else analysis_settings
                        )
                        pipeline.set_audio_settings(raw_audio_settings)
                        websocket.app.state.live_sessions.add(session_id)
                        live_registered = True
                        await pipeline.prepare()

                    if not await prepare_or_cancel(asyncio.create_task(prepare())):
                        await pipeline.stop()
                        break
                    started = True
                    if has_early_audio_settings:
                        pipeline.set_audio_settings(early_audio_settings)
                    await pipeline.emit(
                        "session.ready",
                        pipeline.elapsed_ms(),
                        {
                            "transport": "websocket",
                            "modules": {
                                name: module.model_dump()
                                for name, module in websocket.app.state.module_status.items()
                            },
                        },
                    )
                elif event.event == "session.audio_settings":
                    # Sent by the client once the microphone is acquired; may trail session.start.
                    # A late message after a failed prepare must not mask the real error.
                    if started:
                        pipeline.set_audio_settings(event.data.get("audio_settings"))
                elif event.event == "calibration.start":
                    if not started:
                        raise ValueError("SESSION_NOT_READY")
                    if calibration_timer:
                        calibration_timer.cancel()
                    await pipeline.start_calibration()
                    calibration_timer = asyncio.create_task(calibration_deadline())
                elif event.event == "session.end":
                    if not started:
                        raise ValueError("SESSION_NOT_READY")
                    if event.data.get("incomplete") is True:
                        pipeline.incomplete = True
                    await websocket.app.state.webrtc.close_session(session_id)
                    await pipeline.stop()
                    break
                elif event.event == "ping":
                    await pipeline.emit("pong", pipeline.elapsed_ms(), {})
                else:
                    raise ValueError("UNSUPPORTED_EVENT")
            except (ValueError, ValidationError) as exc:
                pipeline.incomplete = True
                code = "INVALID_SETTINGS" if isinstance(exc, ValidationError) else str(exc)
                modules = {
                    name: module.model_dump()
                    for name, module in websocket.app.state.module_status.items()
                }
                reasons = [
                    module.reason
                    for module in websocket.app.state.module_status.values()
                    if module.reason
                ]
                await pipeline.emit(
                    "error",
                    pipeline.elapsed_ms(),
                    {
                        "code": code,
                        "message": "; ".join(reasons)
                        if code == "MODEL_UNAVAILABLE_OR_BUSY" and reasons
                        else "실시간 입력 또는 모델 상태를 확인해 주세요.",
                        "modules": modules,
                    },
                )
    except WebSocketDisconnect:
        pipeline.incomplete = True
    finally:
        with CancelScope(shield=True):
            if calibration_timer:
                calibration_timer.cancel()
                await asyncio.gather(calibration_timer, return_exceptions=True)
            pipeline.unsubscribe(subscriber)
            if live_registered:
                await websocket.app.state.webrtc.close_session(session_id)
            try:
                await pipeline.stop()
            finally:
                if live_registered:
                    websocket.app.state.live_sessions.discard(session_id)


def _frontend_feedback(event: RealtimeEvent) -> dict[str, Any] | None:
    if event.event == "error":
        return {
            "type": "error",
            "message": str(event.data.get("message", "실시간 처리 오류가 발생했습니다.")),
        }
    if event.event == "session.completed":
        report = event.data.get("report", {})
        if not isinstance(report, dict):
            report = {}
        return {
            "type": "session.completed",
            "sessionId": str(event.session_id),
            "timestamp": event.timestamp_ms or int(time.time() * 1000),
            "report": {
                "transcript": report.get("transcript"),
                "gaze": {
                    "awayCount": int(report.get("gaze_away_count", 0) or 0),
                    "awayDurationMs": int(report.get("gaze_away_duration_ms", 0) or 0),
                },
                "speech": {
                    "averageSyllablesPerMinute": float(
                        report.get("average_syllables_per_minute", 0) or 0
                    ),
                },
                "filler": {
                    "counts": report.get("filler_word_counts", {}),
                },
                "incomplete": bool(report.get("incomplete", False)),
            },
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
    pronunciation_accuracy = None
    pronunciation_message = None
    pronunciation_method = None
    direction = "unknown"
    attention_state = "unknown"

    if source == "gaze":
        direction = str(metrics.get("gaze_direction", "unknown"))
        attention_state = str(metrics.get("attention_state", "unknown"))
        gaze_status = "away" if attention_state == "away" else direction
        if gaze_status not in {"center", "left", "right", "up", "down", "away"}:
            gaze_status = "unknown"

    if source == "speech_rate":
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

    if source == "pronunciation":
        score = metrics.get("pronunciation_clarity_score")
        if score is not None:
            pronunciation_accuracy = float(score)
        pronunciation_message = str(metrics.get("message", event.data.get("message", "")))
        pronunciation_method = metrics.get("method")

    feedback: dict[str, Any] = {
        "type": "feedback",
        "sessionId": str(event.session_id),
        "source": source,
        "timestamp": event.timestamp_ms or int(time.time() * 1000),
        "severity": severity,
        "transcript": event.data.get("transcript"),
        "message": str(event.data.get("message", "")),
    }
    if source == "gaze":
        feedback["gaze"] = {
            "status": gaze_status,
            "faceDetected": bool(metrics.get("face_detected", False)),
            "headPose": metrics.get("head_pose", {}),
            "direction": direction,
            "attentionState": attention_state,
            "quality": float(metrics.get("quality", 0) or 0),
            "confidence": metrics.get("confidence"),
            "calibrated": bool(metrics.get("calibrated", False)),
            "message": event.data.get("message"),
        }
    elif source == "speech_rate":
        feedback["speech"] = {
            "pace": speech_pace,
            "syllablesPerSecond": syllables_per_second,
            "message": event.data.get("message"),
        }
        feedback["filler"] = {
            "latestWord": next(iter(filler_words), None),
            "totalCount": sum(filler_words.values()),
            "counts": filler_words,
        }
    elif source == "pronunciation":
        feedback["pronunciation"] = {
            "accuracy": pronunciation_accuracy,
            "message": pronunciation_message,
            "method": pronunciation_method,
        }
    return feedback


@router.websocket("/ws/practice-demo")
async def practice_demo_websocket(websocket: WebSocket) -> None:
    try:
        loopback = (
            websocket.client is not None and ipaddress.ip_address(websocket.client.host).is_loopback
        )
    except ValueError:
        loopback = False
    settings = websocket.app.state.settings
    origin = websocket.headers.get("origin")
    if (
        settings.app_env != "development"
        or not loopback
        or (origin is not None and origin not in settings.cors_origins)
    ):
        await websocket.close(code=4403, reason="development endpoint")
        return
    await websocket.accept()
    settings = websocket.app.state.settings
    if websocket.query_params.get("protocol") == "2":
        await _v2_session(websocket, uuid4())
        return
    if websocket.app.state.script_summarizer.busy:
        await websocket.send_json(
            {"type": "error", "message": "요약 모델 정리가 끝난 뒤 시작해 주세요."}
        )
        await websocket.close(code=1013)
        return
    session_id = uuid4()
    gaze = websocket.app.state.gaze
    speech = websocket.app.state.speech
    pipeline = SessionPipeline(
        session_id,
        settings,
        websocket.app.state.state_store,
        gaze,
        speech,
        {
            "gaze_enabled": True,
            "speech_rate_enabled": True,
            "filler_detection_enabled": True,
        },
        websocket.app.state.model_execution,
    )
    subscriber_id = f"demo-{uuid4()}"

    async def send(event: RealtimeEvent) -> None:
        feedback = _frontend_feedback(event)
        if feedback is not None:
            await websocket.send_json(feedback)

    pipeline.subscribe(subscriber_id, send)
    websocket.app.state.live_sessions.add(session_id)
    try:
        await pipeline.start()
        await pipeline.emit("session.ready", pipeline.elapsed_ms(), {"transport": "practice-demo"})
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
            elif client_event.event == "session.start":
                try:
                    SessionStartData.model_validate(client_event.data)
                except ValidationError:
                    await pipeline.emit_error("INVALID_SETTINGS", "세션 설정이 올바르지 않습니다.")
                    continue
                settings_data = client_event.data.get("settings", {})
                analysis_updates = settings_data if isinstance(settings_data, dict) else {}
                if "karaokeGuideEnabled" in analysis_updates:
                    analysis_updates["karaoke_guide_enabled"] = analysis_updates[
                        "karaokeGuideEnabled"
                    ]
                analysis_updates["pronunciation_enabled"] = True
                pipeline.set_audio_settings(client_event.data.get("audio_settings"))
                pipeline.update_analysis_settings(
                    {
                        **analysis_updates,
                        "script": client_event.data.get("script"),
                        "time_limit_seconds": client_event.data.get("timeLimitSeconds"),
                    }
                )
                await pipeline.emit("session.started", client_event.timestamp_ms, client_event.data)
            elif client_event.event == "session.end":
                await websocket.app.state.webrtc.close_session(session_id)
                await pipeline.stop()
                break
    except ValueError as exc:
        await websocket.send_json(
            {
                "type": "error",
                "message": "모델을 준비하지 못했습니다. 다시 시도하세요.",
                "code": str(exc),
            }
        )
        await websocket.close(code=1013)
    except WebSocketDisconnect:
        pass
    finally:
        with CancelScope(shield=True):
            pipeline.unsubscribe(subscriber_id)
            await websocket.app.state.webrtc.close_session(session_id)
            try:
                await pipeline.stop()
            finally:
                websocket.app.state.live_sessions.discard(session_id)


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
        # Check and reserve under one lock: two simultaneous handshakes must not both
        # observe the same free slot.
        async with websocket.app.state.websocket_lock:
            connection_count = websocket.app.state.websocket_counts.get(session_id, 0)
            if connection_count >= settings.max_connections_per_session:
                await websocket.close(code=4429, reason="too many connections")
                return
            websocket.app.state.websocket_counts[session_id] = connection_count + 1
        if session.status == SessionStatus.created:
            from app.services.session_service import activate_session

            await activate_session(db, session)
        analysis_settings = {
            **session.settings,
            "script": session.active_script,
            "time_limit_seconds": session.time_limit_seconds,
        }

    try:
        await websocket.accept()
    except BaseException:
        # The reserved slot must be released if the handshake never completes.
        websocket.app.state.websocket_counts[session_id] = max(
            0, websocket.app.state.websocket_counts.get(session_id, 1) - 1
        )
        raise
    if websocket.query_params.get("protocol") == "2":
        try:
            await _v2_session(websocket, session_id, analysis_settings, claims.subject)
        finally:
            websocket.app.state.websocket_counts[session_id] = max(
                0, websocket.app.state.websocket_counts.get(session_id, 1) - 1
            )
        return
    try:
        pipeline = await websocket.app.state.pipelines.get_or_create(session_id, analysis_settings)
    except ValueError:
        try:
            await websocket.close(code=1013, reason="required model unavailable or busy")
        finally:
            websocket.app.state.websocket_counts[session_id] = max(
                0, websocket.app.state.websocket_counts.get(session_id, 1) - 1
            )
        return
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
            elif client_event.event == "session.end":
                await websocket.app.state.webrtc.close_session(session_id)
                await pipeline.stop()
                break
    except WebSocketDisconnect:
        pass
    finally:
        with CancelScope(shield=True):
            pipeline.unsubscribe(subscriber_id)
            remaining = max(0, websocket.app.state.websocket_counts.get(session_id, 1) - 1)
            websocket.app.state.websocket_counts[session_id] = remaining
            if remaining == 0:
                if pipeline.completed_report is None:
                    pipeline.incomplete = True
                await websocket.app.state.webrtc.close_session(session_id)
                # Retain the report for REST /complete, never the model weights.
                await pipeline.stop()
