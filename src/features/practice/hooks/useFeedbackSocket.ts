import { useCallback, useEffect, useRef, useState } from "react";
import type {
  BackendClientEvent,
  ClientRealtimeMessage,
  ConnectionStatus,
  PracticeMode,
  PresentationFeatureSettings,
  RealtimeFeedback,
  ScriptProgressMessage,
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
        settings: message.settings,
        script: message.script,
        timeLimitSeconds: message.timeLimitSeconds,
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
  const sessionStartedAtRef = useRef<number | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [scriptProgress, setScriptProgress] =
    useState<ScriptProgressMessage | null>(null);

  const elapsedTimestamp = useCallback(() => {
    const startedAt = sessionStartedAtRef.current;
    return startedAt === null ? 0 : Math.max(0, Math.round(performance.now() - startedAt));
  }, []);

  const send = useCallback((message: ClientRealtimeMessage) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(toBackendEvent(message)));
    }
  }, []);

  const sendTranscript = useCallback((text: string, isFinal = true) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      const event: BackendClientEvent = {
        event: isFinal ? "transcript.final" : "transcript.partial",
        timestamp_ms: elapsedTimestamp(),
        data: { text },
      };
      socketRef.current.send(JSON.stringify(event));
    }
  }, [elapsedTimestamp]);

  const sendVideoFrame = useCallback((payload: Blob) => {
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      return;
    }

    void payload.arrayBuffer().then((buffer) => {
      const timestamp = BigInt(elapsedTimestamp());
      const bytes = new Uint8Array(9 + buffer.byteLength);
      bytes[0] = 0x01;
      new DataView(bytes.buffer).setBigUint64(1, timestamp, false);
      bytes.set(new Uint8Array(buffer), 9);
      socketRef.current?.send(bytes);
    });
  }, [elapsedTimestamp]);

  const disconnect = useCallback(() => {
    socketRef.current?.close();
    socketRef.current = null;
    sessionStartedAtRef.current = null;
    setStatus((current) => (current === "idle" ? current : "disconnected"));
  }, []);

  const connect = useCallback(
    (
      sessionId: string,
      mode: PracticeMode,
      settings: PresentationFeatureSettings,
      script?: string,
      timeLimitSeconds?: number
    ) => {
      if (!feedbackWsUrl) {
        setStatus("disconnected");
        setError(null);
        return false;
      }

      setStatus("connecting");
      setError(null);
      setScriptProgress(null);
      sessionStartedAtRef.current = performance.now();

      const socket = new WebSocket(feedbackWsUrl);
      socketRef.current = socket;

      socket.onopen = () => {
        setStatus("connected");
        send({
          type: "session.start",
          sessionId,
          mode,
          settings,
          script,
          timeLimitSeconds,
          timestamp: 0,
        });
      };

      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(String(event.data)) as ServerRealtimeMessage;
          if (message.type === "feedback") {
            onFeedback(message);
            return;
          }

          if (message.type === "script.progress") {
            setScriptProgress(message);
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
    scriptProgress,
  };
}
