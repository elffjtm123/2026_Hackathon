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

export type PresentationFeatureSettings = {
  karaokeGuideEnabled: boolean;
  keywordHintEnabled: boolean;
};

export type RealtimeFeedback = {
  type: "feedback";
  sessionId: string;
  source?: string;
  timestamp: number;
  severity: FeedbackSeverity;
  gaze?: {
    status: GazeStatus;
    faceDetected: boolean;
    headPose: {
      yaw: number | null;
      pitch: number | null;
      roll: number | null;
    };
    direction: GazeStatus;
    attentionState: "unknown" | "camera" | "screen" | "away";
    quality: number;
    confidence?: number;
    calibrated: boolean;
    message?: string;
  };
  speech?: {
    pace: SpeechPaceStatus;
    syllablesPerSecond?: number;
    message?: string;
  };
  filler?: {
    latestWord?: string;
    totalCount: number;
    counts?: Record<string, number>;
  };
  pronunciation?: {
    accuracy?: number | null;
    message?: string | null;
    method?: string | null;
  };
  transcript?: string | null;
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
  gazeAwayRatio: number;
  pronunciationAccuracy: number | null;
  speechPaceWarningCount: number;
  averageSyllablesPerMinute: number;
  fillerWordCounts: Record<string, number>;
  transcript: string | null;
  incomplete: boolean;
};

export type SessionCompletionReport = {
  transcript: string | null;
  gaze: {
    awayCount: number;
    awayDurationMs: number;
  };
  speech: {
    averageSyllablesPerMinute: number;
  };
  filler: {
    counts: Record<string, number>;
  };
  incomplete: boolean;
};

export type SessionCompletionMessage = {
  type: "session.completed";
  sessionId: string;
  timestamp: number;
  report: SessionCompletionReport;
};

export type ClientRealtimeMessage =
  | {
      type: "session.start";
      sessionId: string;
      mode: PracticeMode;
      settings: PresentationFeatureSettings;
      script?: string;
      timeLimitSeconds?: number;
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
        settings?: PresentationFeatureSettings;
        script?: string;
        timeLimitSeconds?: number;
      };
    }
  | {
      event: "session.end";
      timestamp_ms: number;
      data: {
        sessionId: string;
      };
    }
  | {
      event: "transcript.partial" | "transcript.final";
      timestamp_ms: number;
      data: {
        text: string;
        durationMs?: number;
      };
    }
  | {
      event: "ping";
      timestamp_ms: number;
      data: Record<string, never>;
    };

export type ServerRealtimeMessage =
  | RealtimeFeedback
  | SessionCompletionMessage
  | {
      type: "error";
      message: string;
    };
