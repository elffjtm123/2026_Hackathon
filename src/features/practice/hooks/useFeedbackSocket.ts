import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ClientRealtimeMessage,
  ConnectionStatus,
  PracticeMode,
  RealtimeFeedback,
  ServerRealtimeMessage,
} from "../types";

const feedbackWsUrl = import.meta.env.VITE_FEEDBACK_WS_URL as
  | string
  | undefined;

export function useFeedbackSocket(
  onFeedback: (feedback: RealtimeFeedback) => void
) {
  const socketRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [error, setError] = useState<string | null>(null);

  const send = useCallback((message: ClientRealtimeMessage) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify(message));
    }
  }, []);

  const disconnect = useCallback(() => {
    socketRef.current?.close();
    socketRef.current = null;
    setStatus((current) => (current === "idle" ? current : "disconnected"));
  }, []);

  const connect = useCallback(
    (sessionId: string, mode: PracticeMode) => {
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
  };
}
