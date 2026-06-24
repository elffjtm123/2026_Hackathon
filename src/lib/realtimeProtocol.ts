export type GazeStatus =
  | "center"
  | "left"
  | "right"
  | "up"
  | "down"
  | "away"
  | "unknown";

export type SpeechPaceStatus = "slow" | "normal" | "fast" | "unknown";

export type FeedbackSeverity = "info" | "warning" | "danger";

export type PracticeMode = "interview" | "presentation";

export type RealtimeFeedback = {
  type: "feedback";
  sessionId: string;
  timestamp: number;
  severity: FeedbackSeverity;
  gaze: {
    status: GazeStatus;
    confidence?: number;
    message?: string;
  };
  speech: {
    pace: SpeechPaceStatus;
    syllablesPerSecond?: number;
    message?: string;
  };
  filler: {
    latestWord?: string;
    totalCount: number;
    counts?: Record<string, number>;
  };
  message?: string;
};

export type ConnectionStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

export type PracticeSummary = {
  sessionId: string;
  durationSeconds: number;
  gazeAwayCount: number;
  speechPaceWarningCount: number;
  fillerTotalCount: number;
};

export type ClientRealtimeMessage =
  | {
      type: "session.start";
      sessionId: string;
      mode: PracticeMode;
      timestamp: number;
    }
  | {
      type: "session.end";
      sessionId: string;
      timestamp: number;
    }
  | {
      type: "client.ping";
      sessionId: string;
      timestamp: number;
    };

export type BackendClientEvent =
  | {
      event: "session.start";
      timestamp_ms: number;
      data: {
        sessionId: string;
        mode: PracticeMode;
      };
    }
  | {
      event: "transcript.partial" | "transcript.final";
      timestamp_ms: number;
      data: {
        text: string;
      };
    }
  | {
      event: "ping";
      timestamp_ms: number;
      data: Record<string, never>;
    };

export type ServerRealtimeMessage =
  | RealtimeFeedback
  | {
      type: "error";
      message: string;
    };
