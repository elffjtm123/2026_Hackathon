export type GazeStatus =
  | "center"
  | "left"
  | "right"
  | "up"
  | "down"
  | "away"
  | "unknown";

export type SessionPhase = 'preparing' | 'calibrating' | 'running' | 'draining' | 'completed' | 'failed';
export type ModuleStatus = { provider: string; model: string | null; device: string | null;
  status: 'ready' | 'unavailable'; reason: string | null };
export type SessionReadyData = { sessionId: string; timestampMs: number; modules: Record<string, ModuleStatus> };
export type RealtimeEvent = { event: string; version: number; session_id: string; sequence: number;
  timestamp_ms: number; module: string; level: string; data: Record<string, unknown> };

type BackendFeedbackData = {
  source: string; level: string; message: string; transcript?: string;
  metrics: { gaze_direction?: GazeStatus; attention_state?: 'unknown' | 'baseline' | 'camera' | 'screen' | 'away';
    head_direction?: GazeStatus; gaze_angles?: {yaw: number | null; pitch: number | null};
    face_detection_confidence?: number | null; quality_flags?: string[];
    recalibration_required?: boolean; calibration_progress?: number; calibration_target?: number;
    quality_measurements?: Record<string, number>;
    face_detected?: boolean; head_pose?: {yaw: number | null; pitch: number | null; roll: number | null};
    quality?: number; confidence?: number; calibrated?: boolean; syllables_per_minute?: number;
    filler_words?: {word: string; count: number}[]; pronunciation_clarity_score?: number; method?: string };
};

// Adapt canonical model data for existing presentation widgets, not a second wire protocol.
export function feedbackForUi(event: RealtimeEvent): RealtimeFeedback {
  const data = event.data as unknown as BackendFeedbackData;
  const m = data.metrics;
  const feedback: RealtimeFeedback = {type: 'feedback', sessionId: event.session_id,
    source: data.source, timestamp: event.timestamp_ms, severity: data.level === 'danger' ? 'danger' : data.level === 'warning' ? 'warning' : 'info',
    message: data.message, transcript: data.transcript};
  if (data.source === 'gaze') feedback.gaze = {
    status: m.attention_state === 'away' ? 'away' : m.gaze_direction ?? 'unknown',
    faceDetected: m.face_detected === true, headPose: m.head_pose ?? {yaw: null, pitch: null, roll: null},
    direction: m.gaze_direction ?? 'unknown', attentionState: m.attention_state ?? 'unknown',
    quality: m.quality ?? 0, calibrated: m.calibrated === true, message: data.message,
    headDirection: m.head_direction ?? 'unknown', gazeAngles: m.gaze_angles,
    faceDetectionConfidence: m.face_detection_confidence ?? null, qualityFlags: m.quality_flags ?? [],
    recalibrationRequired: m.recalibration_required === true, calibrationProgress: m.calibration_progress,
    calibrationTarget: m.calibration_target, qualityMeasurements: m.quality_measurements};
  if (data.source === 'speech_rate') {
    const rate = m.syllables_per_minute ?? 0;
    const counts = Object.fromEntries((m.filler_words ?? []).map(item => [item.word, item.count]));
    feedback.speech = {pace: rate === 0 ? 'unknown' : rate > 360 ? 'fast' : rate < 140 ? 'slow' : 'normal', syllablesPerSecond: rate / 60, message: data.message};
    feedback.filler = {totalCount: Object.values(counts).reduce((a, b) => a+b, 0), counts};
  }
  if (data.source === 'pronunciation') feedback.pronunciation = {
    accuracy: m.pronunciation_clarity_score, method: m.method, message: data.message};
  return feedback;
}

export function completionForUi(data: Record<string, unknown>): SessionCompletionReport {
  const report = data as {transcript?: string; gaze_away_count?: number; gaze_away_duration_ms?: number;
    average_syllables_per_minute?: number; filler_word_counts?: Record<string, number>; incomplete?: boolean};
  return {transcript: report.transcript ?? null, gaze: {awayCount: report.gaze_away_count ?? 0, awayDurationMs: report.gaze_away_duration_ms ?? 0},
    speech: {averageSyllablesPerMinute: report.average_syllables_per_minute ?? 0},
    filler: {counts: report.filler_word_counts ?? {}}, incomplete: report.incomplete !== false};
}

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
    attentionState: "unknown" | "baseline" | "camera" | "screen" | "away";
    headDirection?: GazeStatus;
    gazeAngles?: {yaw: number | null; pitch: number | null};
    faceDetectionConfidence?: number | null;
    qualityFlags?: string[];
    recalibrationRequired?: boolean;
    calibrationProgress?: number;
    calibrationTarget?: number;
    qualityMeasurements?: Record<string, number>;
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
