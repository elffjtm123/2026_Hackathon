# 실시간 미디어·피드백 계약

현재 브라우저 연습 화면은 WebSocket으로 영상·음성과 제어 이벤트를
전송한다. 인증 세션은 `RealtimeEvent`를 수신하고, 프론트 데모 endpoint는
이를 `RealtimeFeedback` 또는 `SessionCompletionMessage`로 변환한다.

## Endpoint

- 데모: `ws://127.0.0.1:8000/api/v1/ws/practice-demo`
- 인증 세션: `ws://127.0.0.1:8000/api/v1/ws/sessions/{session_id}?token={access_token}`
- WebRTC signaling: `POST /api/v1/sessions/{session_id}/webrtc/offer`

## Binary media frame

모든 binary message는 9-byte header 뒤에 payload를 붙인다.

| offset | size | 의미 |
|---:|---:|---|
| 0 | 1 byte | `0x01` JPEG video, `0x02` WAV audio |
| 1 | 8 bytes | `timestamp_ms`, unsigned big-endian |
| 9 | variable | media payload |

오디오 payload는 mono 16 kHz PCM16 WAV다. 브라우저는 2초 청크와 250 ms
중첩을 사용하며, 세션 종료 시 2초보다 짧은 마지막 청크도 먼저 전송한다.
비디오는 640×480 JPEG를 125 ms 간격으로 생성하며 서버는 가장 최신 프레임
하나만 대기열에 유지한다.

## ClientEvent

JSON 제어 메시지는 `event`, `timestamp_ms`, `data`를 갖는다.

```json
{"event":"ping","timestamp_ms":1000,"data":{}}
```

```json
{"event":"session.end","timestamp_ms":8500,"data":{}}
```

`session.end`를 보낸 뒤에는 추가 media를 전송하지 않는다. 서버는 이미 받은
오디오·영상 대기열을 처리하고 `session.completed`를 보낸다.

## RealtimeEvent feedback

피드백은 source별로 독립적이다. `gaze` 이벤트는 이전 `speech_rate`를,
`speech_rate` 이벤트는 이전 `gaze`를 덮어쓰지 않는다.

```json
{
  "event": "feedback",
  "module": "gaze",
  "level": "info",
  "timestamp_ms": 2000,
  "data": {
    "source": "gaze",
    "message": "카메라를 안정적으로 바라보고 있어요.",
    "metrics": {
      "face_detected": true,
      "head_pose": {"yaw": 0.5, "pitch": -1.0, "roll": null},
      "gaze_direction": "center",
      "attention_state": "camera",
      "quality": 0.9,
      "confidence": 0.95,
      "calibrated": true,
      "away": false
    }
  }
}
```

시선 상태는 `unknown|camera|screen|away`로 구분한다. `face_detected=false`, 품질
부족, 보정 전 프레임은 시선 이탈 시간에 포함하지 않는다. `speech_rate`
피드백은 `syllables_per_minute`, `duration_sec`, `filler_words`, transcript를
포함할 수 있다.

## session.completed

인증 endpoint의 `RealtimeEvent.data.report`는 다음 집계값을 포함한다.

```json
{
  "event": "session.completed",
  "data": {
    "report": {
      "transcript": "음 저는 백엔드 개발자입니다",
      "gaze_away_count": 1,
      "gaze_away_duration_ms": 1500,
      "average_syllables_per_minute": 240.0,
      "filler_word_counts": {"음": 1},
      "incomplete": false
    }
  }
}
```

프론트 데모 endpoint는 이 값을 `SessionCompletionMessage.report`의
`transcript`, `gaze`, `speech`, `filler`, `incomplete`로 변환한다. `incomplete=true`는
종료 유예 시간 내에 모든 대기열을 소비하지 못했다는 뜻이다.

## 브라우저 종료 순서

1. 음성 처리기를 멈추고 남은 샘플을 16 kHz WAV로 flush한다.
2. 모든 오디오 `send()` Promise가 완료될 때까지 기다린다.
3. 카메라·마이크 track을 중지한다.
4. `session.end`를 보내고 `session.completed`를 기다린다.
5. 최종 report를 UI에 저장한 뒤 WebSocket을 닫는다.
