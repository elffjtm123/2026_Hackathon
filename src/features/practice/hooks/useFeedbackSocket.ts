import { useCallback, useEffect, useRef, useState } from "react";
import type {
  BackendClientEvent,
  ClientRealtimeMessage,
  ConnectionStatus,
  PracticeMode,
  PresentationFeatureSettings,
  RealtimeFeedback,
  ServerRealtimeMessage,
} from "../types";

const feedbackWsUrl =
  (import.meta.env.VITE_FEEDBACK_WS_URL as string | undefined) ??
  "ws://127.0.0.1:8000/api/v1/ws/practice-demo";

function toBackendEvent(message: ClientRealtimeMessage): BackendClientEvent {
  if (message.type === "session.start") {
    return {
      event: "session.start",
      timestamp_ms: message.timestamp,
      data: {
        sessionId: message.sessionId,
        mode: message.mode,
      },
    };
  }

  if (message.type === "client.ping") {
    return {
      event: "ping",
      timestamp_ms: message.timestamp,
      data: {},
    };
  }

  return {
    event: "ping",
    timestamp_ms: message.timestamp,
    data: {},
  };
}

export function useFeedbackSocket(
  onFeedback: (feedback: RealtimeFeedback) => void
) {
  const socketRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const send = useCallback((message: ClientRealtimeMessage) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(toBackendEvent(message)));
    }
  }, []);

  const sendTranscript = useCallback((text: string, isFinal = true) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      const event: BackendClientEvent = {
        event: isFinal ? "transcript.final" : "transcript.partial",
        timestamp_ms: Date.now(),
        data: { text },
      };
      socketRef.current.send(JSON.stringify(event));
    }
  }, []);

  const sendVideoFrame = useCallback((payload: Blob) => {
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      return;
    }

    void payload.arrayBuffer().then((buffer) => {
      const timestamp = BigInt(Date.now());
      const bytes = new Uint8Array(9 + buffer.byteLength);
      bytes[0] = 0x01;
      new DataView(bytes.buffer).setBigUint64(1, timestamp, false);
      bytes.set(new Uint8Array(buffer), 9);
      socketRef.current?.send(bytes);
    });
  }, []);

  const disconnect = useCallback(() => {
    socketRef.current?.close();
    socketRef.current = null;
    setStatus((current) => (current === "idle" ? current : "disconnected"));
  }, []);

  const connect = useCallback(
    (
      sessionId: string,
      mode: PracticeMode,
      settings: PresentationFeatureSettings
    ) => {
      if (!feedbackWsUrl) {
        setStatus("disconnected");
        setError(null);
        return false;
      }

      setStatus("connecting");
      setError(null);

      const socket = new WebSocket(feedbackWsUrl);
      socketRef.current = socket;

      socket.onopen = () => {
        setStatus("connected");
        send({
          type: "session.start",
          sessionId,
          mode,
          settings,
          timestamp: Date.now(),
        });
      };

      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(String(event.data)) as ServerRealtimeMessage;
          if (message.type === "feedback") {
            onFeedback(message);
            return;
          }

          setError(message.message);
        } catch {
          setError("알 수 없는 WebSocket 메시지를 수신했습니다.");
        }
      };

      socket.onerror = () => {
        setStatus("error");
        setError("WebSocket 연결에 실패했습니다. Mock 피드백으로 전환합니다.");
      };

      socket.onclose = () => {
        setStatus((current) =>
          current === "error" ? "error" : "disconnected"
        );
      };

      return true;
    },
    [onFeedback, send]
  );

  useEffect(() => disconnect, [disconnect]);

  return {
    status,
    error,
    connect,
    disconnect,
    send,
    sendTranscript,
    sendVideoFrame,
  };
}
