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
    quality?: number; confidence?: number; calibrated?: boolean; syllables_per_minute?: number | null;
    pace?: SpeechPaceStatus; utterance_id?: string; revision?: number; transcript_snapshot?: string;
    filler_counts_total?: Record<string, number>; filler_status?:string; warning_episode_count?: number;
    filler_words?: {word: string; count: number}[]; pronunciation_clarity_score?: number; method?: string };
};

// Adapt canonical model data for existing presentation widgets, not a second wire protocol.
export function feedbackForUi(event: RealtimeEvent): RealtimeFeedback {
  if (event.event === 'script.progress') return {type:'feedback', sessionId:event.session_id,
    timestamp:event.timestamp_ms, source:'script_sync', severity:'info',
    scriptProgress:event.data as ScriptProgress};
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
    const rate = m.syllables_per_minute;
    const counts = m.filler_counts_total ?? Object.fromEntries((m.filler_words ?? []).map(item => [item.word, item.count]));
    feedback.utteranceId = m.utterance_id;
    feedback.revision = m.revision;
    feedback.transcriptSnapshot = m.transcript_snapshot;
    feedback.speech = {pace: m.pace ?? 'unknown',
      syllablesPerSecond: m.pace === 'unknown' || rate == null ? undefined : rate / 60,
      warningEpisodeCount: m.warning_episode_count, message: data.message};
    const unavailable = m.filler_status === 'unavailable' || m.filler_status === 'disabled';
    feedback.filler = {totalCount: unavailable ? null : Object.values(counts).reduce((a, b) => a+b, 0),
      counts:unavailable ? null : counts,status:m.filler_status};
  }
  if (data.source === 'pronunciation') feedback.pronunciation = {
    accuracy: m.pronunciation_clarity_score, method: m.method, message: data.message};
  return feedback;
}

export function completionForUi(data: Record<string, unknown>): SessionCompletionReport {
  const report = data as {transcript?: string; gaze_away_count?: number; gaze_away_duration_ms?: number;
    average_syllables_per_minute?: number | null; filler_word_counts?: Record<string, number> | null; incomplete?: boolean;
    summary?: {duration_ms?:number};
    pronunciation_clarity_score?:number | null; script_completion_ratio?:number | null;
    gaze_metrics?:{away_ratio?:number | null; coverage_ratio?:number | null; status?:string};
    speech_rate_metrics?: {warning_episode_count?: number;status?:string;filler_status?:string}};
  return {transcript: report.transcript ?? null,
    speech: {averageSyllablesPerMinute: report.average_syllables_per_minute ?? null,
      warningEpisodeCount: ['disabled','unavailable'].includes(report.speech_rate_metrics?.status ?? '') ? null : report.speech_rate_metrics?.warning_episode_count ?? null,
      status:report.speech_rate_metrics?.status},
    filler: {counts: report.filler_word_counts ?? null,status:report.speech_rate_metrics?.filler_status},
    incomplete: report.incomplete !== false,
    durationMs:report.summary?.duration_ms,
    pronunciationAccuracy:report.pronunciation_clarity_score ?? null,
    scriptCompletionRatio:report.script_completion_ratio ?? null,
    gaze:{awayCount:report.gaze_away_count ?? 0,awayDurationMs:report.gaze_away_duration_ms ?? 0,
      awayRatio:report.gaze_metrics?.away_ratio ?? null,coverageRatio:report.gaze_metrics?.coverage_ratio ?? null,
      status:report.gaze_metrics?.status}};
}

export function summaryForUi(sessionId: string, report: SessionCompletionReport | null,
  elapsedSeconds: number, ephemeralTranscript: string | null): PracticeSummary {
  return {sessionId,durationSeconds:report?.durationMs == null ? elapsedSeconds : Math.floor(report.durationMs / 1000),
    gazeAwayRatio:report?.gaze.awayRatio ?? null,gazeCoverageRatio:report?.gaze.coverageRatio ?? null,
    gazeStatus:report?.gaze.status,speechStatus:report?.speech.status,fillerStatus:report?.filler.status,
    pronunciationAccuracy:report?.pronunciationAccuracy ?? null,
    scriptCompletionRatio:report?.scriptCompletionRatio ?? null,
    speechPaceWarningCount:report?.speech.warningEpisodeCount ?? null,
    averageSyllablesPerMinute:report?.speech.averageSyllablesPerMinute ?? null,
    fillerWordCounts:report?.filler.counts ?? null,
    transcript:report?.transcript ?? ephemeralTranscript,incomplete:report?.incomplete ?? true};
}

export type SpeechPaceStatus = "slow" | "normal" | "fast" | "unknown";

export type FeedbackSeverity = "info" | "warning" | "danger";

export type PracticeMode = "interview" | "presentation";

export type PresentationFeatureSettings = {
  karaokeGuideEnabled: boolean;
  keywordHintEnabled: boolean;
};

export type RealtimeFeedback = {
  scriptProgress?: ScriptProgress;
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
    warningEpisodeCount?: number;
    syllablesPerSecond?: number;
    message?: string;
  };
  filler?: {
    latestWord?: string;
    totalCount: number | null;
    counts?: Record<string, number> | null;
    status?:string;
  };
  pronunciation?: {
    accuracy?: number | null;
    message?: string | null;
    method?: string | null;
  };
  transcript?: string | null;
  transcriptSnapshot?: string;
  utteranceId?: string;
  revision?: number;
  message?: string;
};

export type ConnectionStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

export type ScriptProgress = {
  current_token_index: number | null;
  current_sentence_index: number | null;
  alignment_status: 'matched' | 'uncertain';
  progress_ratio: number;
  expected_progress_ratio: number;
  pace_status: string;
};

export type PracticeSummary = {
  sessionId: string;
  durationSeconds: number;
  gazeAwayRatio: number | null;
  gazeCoverageRatio?: number | null;
  gazeStatus?: string;
  speechStatus?: string;
  fillerStatus?: string;
  scriptCompletionRatio?: number | null;
  pronunciationAccuracy: number | null;
  speechPaceWarningCount: number | null;
  averageSyllablesPerMinute: number | null;
  fillerWordCounts: Record<string, number> | null;
  transcript: string | null;
  incomplete: boolean;
};

export type SessionCompletionReport = {
  durationMs?:number;
  pronunciationAccuracy?:number | null;
  scriptCompletionRatio?:number | null;
  transcript: string | null;
  gaze: {
    awayCount: number;
    awayDurationMs: number;
    awayRatio?:number | null;
    coverageRatio?:number | null;
    status?:string;
  };
  speech: {
    averageSyllablesPerMinute: number | null;
    warningEpisodeCount?: number | null;
    status?:string;
  };
  filler: {
    counts: Record<string, number> | null;
    status?:string;
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
