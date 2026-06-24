import type { PracticeMode } from "../types";

type SessionControlsProps = {
  mode: PracticeMode;
  isRunning: boolean;
  isStarting: boolean;
  elapsedSeconds: number;
  onModeChange: (mode: PracticeMode) => void;
  onStart: () => void;
  onEnd: () => void;
};

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(
    remainingSeconds
  ).padStart(2, "0")}`;
}

export function SessionControls({
  mode,
  isRunning,
  isStarting,
  elapsedSeconds,
  onModeChange,
  onStart,
  onEnd,
}: SessionControlsProps) {
  return (
    <section className="controls-bar" aria-label="세션 컨트롤">
      <div className="mode-tabs" role="tablist" aria-label="연습 모드">
        <button
          type="button"
          className={mode === "interview" ? "active" : ""}
          onClick={() => onModeChange("interview")}
          disabled={isRunning || isStarting}
        >
          면접
        </button>
        <button
          type="button"
          className={mode === "presentation" ? "active" : ""}
          onClick={() => onModeChange("presentation")}
          disabled={isRunning || isStarting}
        >
          발표
        </button>
      </div>

      <div className="timer" aria-label="진행 시간">
        {formatDuration(elapsedSeconds)}
      </div>

      <div className="control-actions">
        <button
          type="button"
          className="primary-button"
          onClick={onStart}
          disabled={isRunning || isStarting}
        >
          {isStarting ? "시작 중" : "시작"}
        </button>
        <button
          type="button"
          className="secondary-button"
          onClick={onEnd}
          disabled={!isRunning}
        >
          종료
        </button>
      </div>
    </section>
  );
}
