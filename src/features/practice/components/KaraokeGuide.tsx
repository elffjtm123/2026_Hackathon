import { useMemo } from "react";
import { analyzeScript, formatTime } from "../scriptTools";
import type { ScriptProgressMessage } from "../types";

type KaraokeGuideProps = {
  script: string;
  timeLimitSeconds: number;
  elapsedSeconds: number;
  karaokeEnabled: boolean;
  keywordHintEnabled: boolean;
  backendProgress: ScriptProgressMessage | null;
};

export function KaraokeGuide({
  script,
  timeLimitSeconds,
  elapsedSeconds,
  karaokeEnabled,
  keywordHintEnabled,
  backendProgress,
}: KaraokeGuideProps) {
  const plan = useMemo(
    () => analyzeScript(script, timeLimitSeconds),
    [script, timeLimitSeconds]
  );
  const elapsedMs = elapsedSeconds * 1000;
  const activeIndex = plan.timeline.findIndex(
    (item) => elapsedMs >= item.targetStartMs && elapsedMs < item.targetEndMs
  );
  const clockIndex =
    activeIndex >= 0
      ? activeIndex
      : elapsedMs >= timeLimitSeconds * 1000
        ? plan.timeline.length - 1
        : 0;
  const currentIndex = Math.min(
    Math.max(backendProgress?.current_token_index ?? clockIndex, 0),
    Math.max(plan.timeline.length - 1, 0)
  );
  const current = plan.timeline[currentIndex];
  const progress = Math.min(100, Math.round((elapsedSeconds / Math.max(timeLimitSeconds, 1)) * 100));
  const remainingSeconds = Math.max(0, timeLimitSeconds - elapsedSeconds);

  let lastSentenceEnd = -1;
  for (let index = 0; index <= currentIndex; index += 1) {
    if (/[.!?。！？]+$/.test(plan.timeline[index]?.text ?? "")) {
      lastSentenceEnd = index;
    }
  }
  const sentenceStart = Math.max(0, lastSentenceEnd + 1);
  const sentenceEndOffset = plan.timeline
    .slice(currentIndex)
    .findIndex((item) => /[.!?。！？]+$/.test(item.text));
  const sentenceEnd =
    sentenceEndOffset >= 0 ? currentIndex + sentenceEndOffset + 1 : currentIndex + 6;
  const sentenceTokens = plan.timeline.slice(
    sentenceStart,
    Math.min(plan.timeline.length, sentenceEnd)
  );
  const keywordHints = plan.timeline
    .slice(sentenceStart, Math.min(plan.timeline.length, sentenceEnd))
    .map((item) => item.text.replace(/[^\w가-힣]/g, ""))
    .filter((word) => word.length >= 2)
    .sort((left, right) => right.length - left.length)
    .slice(0, 4);

  if ((!karaokeEnabled && !keywordHintEnabled) || !plan.normalizedScript) {
    return null;
  }

  return (
    <section className="karaoke-guide" aria-label="발표 진행 오버레이">
      <div className="progress-track">
        <span style={{ width: `${progress}%` }} />
      </div>
      {keywordHintEnabled ? (
        <div className="keyword-hints" aria-live="polite">
          {keywordHints.length ? (
            keywordHints.map((word) => <span key={word}>{word}</span>)
          ) : (
            <span>{current ? current.text : "힌트 대기"}</span>
          )}
        </div>
      ) : (
        <div className="karaoke-line" aria-live="polite">
          {sentenceTokens.length ? (
            sentenceTokens.map((item) => (
              <span
                key={`${item.index}-${item.text}`}
                className={
                  item.index === currentIndex
                    ? "current"
                    : item.index < currentIndex
                      ? "past"
                      : ""
                }
              >
                {item.text}
              </span>
            ))
          ) : (
            <span>대본을 입력하세요.</span>
          )}
        </div>
      )}
      <div className="karaoke-stats">
        <span>{formatTime(elapsedSeconds)} / {formatTime(timeLimitSeconds)}</span>
        <span>남은 시간 {formatTime(remainingSeconds)}</span>
        <span>목표 속도 {plan.targetSyllablesPerMinute} 음절/분</span>
        {backendProgress ? (
          <span>
            실제 진행 {Math.round(backendProgress.progress_ratio * 100)}% · {backendProgress.pace_status}
          </span>
        ) : null}
      </div>
    </section>
  );
}
