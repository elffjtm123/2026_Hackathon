import { useCallback, useEffect, useRef, useState } from "react";
import type {
  BackendClientEvent,
  ClientRealtimeMessage,
  ConnectionStatus,
  PracticeMode,
  PresentationFeatureSettings,
  RealtimeFeedback,
  SessionCompletionReport,
  ServerRealtimeMessage,
} from "../types";

const feedbackWsUrl =
  (import.meta.env?.VITE_FEEDBACK_WS_URL as string | undefined) ??
  "ws://127.0.0.1:8000/api/v1/ws/practice-demo";

export function toBackendEvent(message: ClientRealtimeMessage): BackendClientEvent {
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
    event: "session.end",
    timestamp_ms: message.timestamp,
    data: { sessionId: message.sessionId },
  };
}

export function useFeedbackSocket(
  onFeedback: (feedback: RealtimeFeedback) => void
) {
  const socketRef = useRef<WebSocket | null>(null);
  const completionRef = useRef<{
    resolve: (report: SessionCompletionReport) => void;
    reject: (error: Error) => void;
    timeoutId: number;
  } | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const send = useCallback((message: ClientRealtimeMessage) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(toBackendEvent(message)));
    }
  }, []);

  const sendTranscript = useCallback((
    text: string,
    isFinal = true,
    durationMs?: number
  ) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      const event: BackendClientEvent = {
        event: isFinal ? "transcript.final" : "transcript.partial",
        timestamp_ms: Date.now(),
        data: { text, durationMs },
      };
      socketRef.current.send(JSON.stringify(event));
    }
  }, []);

  const sendVideoFrame = useCallback(async (payload: Blob) => {
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      return false;
    }

    const buffer = await payload.arrayBuffer();
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      return false;
    }
    const timestamp = BigInt(Date.now());
    const bytes = new Uint8Array(9 + buffer.byteLength);
    bytes[0] = 0x01;
    new DataView(bytes.buffer).setBigUint64(1, timestamp, false);
    bytes.set(new Uint8Array(buffer), 9);
    socketRef.current.send(bytes);
    return true;
  }, []);

  const sendAudioChunk = useCallback(async (payload: Blob) => {
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      return false;
    }

    const buffer = await payload.arrayBuffer();
    if (socketRef.current?.readyState !== WebSocket.OPEN) {
      return false;
    }
    const timestamp = BigInt(Date.now());
    const bytes = new Uint8Array(9 + buffer.byteLength);
    bytes[0] = 0x02;
    new DataView(bytes.buffer).setBigUint64(1, timestamp, false);
    bytes.set(new Uint8Array(buffer), 9);
    socketRef.current.send(bytes);
    return true;
  }, []);

  const finish = useCallback((sessionId: string) => {
    return new Promise<SessionCompletionReport>((resolve, reject) => {
      if (socketRef.current?.readyState !== WebSocket.OPEN) {
        reject(new Error("WebSocket이 연결되어 있지 않습니다."));
        return;
      }
      const timeoutId = window.setTimeout(() => {
        completionRef.current = null;
        reject(new Error("세션 분석 완료 응답 시간이 초과되었습니다."));
      }, 10_000);
      completionRef.current = { resolve, reject, timeoutId };
      socketRef.current.send(
        JSON.stringify(
          toBackendEvent({
            type: "session.end",
            sessionId,
            timestamp: Date.now(),
          })
        )
      );
    });
  }, []);

  const disconnect = useCallback(() => {
    if (completionRef.current) {
      window.clearTimeout(completionRef.current.timeoutId);
      completionRef.current.reject(new Error("세션 완료 전에 연결이 종료되었습니다."));
      completionRef.current = null;
    }
    socketRef.current?.close();
    socketRef.current = null;
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

          if (message.type === "session.completed") {
            const pending = completionRef.current;
            if (pending) {
              window.clearTimeout(pending.timeoutId);
              completionRef.current = null;
              pending.resolve(message.report);
            }
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
    sendAudioChunk,
    finish,
  };
}
