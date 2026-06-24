import { useEffect } from "react";
import type {
  FeedbackSeverity,
  GazeStatus,
  RealtimeFeedback,
  SpeechPaceStatus,
} from "../types";

const gazeStatuses: GazeStatus[] = [
  "center",
  "center",
  "left",
  "right",
  "away",
  "down",
];
const speechStatuses: SpeechPaceStatus[] = [
  "normal",
  "normal",
  "fast",
  "slow",
];
function pick<T>(items: T[]) {
  return items[Math.floor(Math.random() * items.length)];
}

function severityFor(
  gaze: GazeStatus,
  speech: SpeechPaceStatus
): FeedbackSeverity {
  if (gaze === "away" || speech === "fast") {
    return "danger";
  }

  if (gaze !== "center" || speech === "slow") {
    return "warning";
  }

  return "info";
}

export function useMockFeedback(
  isActive: boolean,
  sessionId: string | null,
  onFeedback: (feedback: RealtimeFeedback) => void
) {
  useEffect(() => {
    if (!isActive || !sessionId) {
      return;
    }

    const createFeedback = () => {
      const gaze = pick(gazeStatuses);
      const speech = pick(speechStatuses);
      const severity = severityFor(gaze, speech);

      onFeedback({
        type: "feedback",
        sessionId,
        timestamp: Date.now(),
        severity,
        gaze: {
          status: gaze,
          confidence: Number((0.72 + Math.random() * 0.24).toFixed(2)),
          message:
            gaze === "center"
              ? "시선이 안정적입니다."
              : "시선을 화면 중앙으로 되돌려보세요.",
        },
        speech: {
          pace: speech,
          syllablesPerSecond:
            speech === "fast" ? 6.2 : speech === "slow" ? 2.1 : 4.1,
          message:
            speech === "normal"
              ? "발화 속도가 적절합니다."
              : "발화 속도를 조금 조정해보세요.",
        },
        filler: {
          totalCount: 0,
          counts: {},
        },
        message:
          severity === "info"
            ? "현재 흐름이 안정적입니다."
            : "시선과 발화 속도를 점검해보세요.",
      });
    };

    createFeedback();
    const intervalId = window.setInterval(
      createFeedback,
      1000 + Math.random() * 1000
    );

    return () => window.clearInterval(intervalId);
  }, [isActive, onFeedback, sessionId]);
}
