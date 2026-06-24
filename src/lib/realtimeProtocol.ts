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
  styleTransferEnabled: boolean;
};

export type RealtimeFeedback = {
  type: "feedback";
  sessionId: string;
  source?: string;
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
  gazeAwayRatio: number;
  speechPaceWarningCount: number;
  fillerTotalCount: number;
};

export type ScriptProgressMessage = {
  type: "script.progress";
  sessionId: string;
  timestamp: number;
  current_token_index: number;
  current_sentence_index: number;
  expected_token_index: number;
  progress_ratio: number;
  expected_progress_ratio: number;
  pace_delta_ms: number;
  pace_status: "ahead" | "behind" | "on_time";
  active_text: string;
  next_text: string;
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
  | ScriptProgressMessage
  | {
      type: "error";
      message: string;
    };
