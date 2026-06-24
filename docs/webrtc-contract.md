# WebRTC 연동 계약 초안

이번 MVP는 WebSocket 피드백 수신과 Mock 피드백을 우선 구현한다. WebRTC 송출은 signaling 서버 계약이 확정된 뒤 추가한다.

## Signaling endpoint

```txt
ws://localhost:8000/ws/signaling
```

## Client -> Server

- `offer`
- `ice-candidate`
- `session.end`

## Server -> Client

- `answer`
- `ice-candidate`
- `feedback`

## 예상 구조

- `RTCPeerConnection` 생성
- `getUserMedia`로 얻은 audio/video track을 peer connection에 추가
- DataChannel 이름은 `feedback`
- AI 결과는 DataChannel 또는 별도 WebSocket으로 수신
