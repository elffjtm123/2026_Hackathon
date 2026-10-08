import { useMemo } from "react";
import { analyzeScript, formatTime } from "../scriptTools";
import type { ScriptProgress } from '../../../lib/realtimeProtocol';

type KaraokeGuideProps = {
  script: string;
  timeLimitSeconds: number;
  elapsedSeconds: number;
  karaokeEnabled: boolean;
  keywordHintEnabled: boolean;
  progress?: ScriptProgress;
  sentenceHints?: Record<number, string>;
};

export function KaraokeGuide({
  script,
  timeLimitSeconds,
  elapsedSeconds,
  karaokeEnabled,
  keywordHintEnabled,
  progress,
  sentenceHints = {},
}: KaraokeGuideProps) {
  const plan = useMemo(
    () => analyzeScript(script, timeLimitSeconds),
    [script, timeLimitSeconds]
  );
  const currentIndex = progress?.current_token_index ?? -1;
  const actualPercent = Math.round((progress?.progress_ratio ?? 0) * 100);
  const remainingSeconds = Math.max(0, timeLimitSeconds - elapsedSeconds);

  let lastSentenceEnd = -1;
  for (let index = 0; index < currentIndex; index += 1) {
    if (/[.!?。！？]+$/.test(plan.timeline[index]?.text ?? "")) {
      lastSentenceEnd = index;
    }
  }
  const sentenceStart = Math.max(0, lastSentenceEnd + 1);
  const sentenceEndOffset = plan.timeline
    .slice(Math.max(0, currentIndex))
    .findIndex((item) => /[.!?。！？]+$/.test(item.text));
  const sentenceEnd =
    sentenceEndOffset >= 0 ? Math.max(0, currentIndex) + sentenceEndOffset + 1 : plan.timeline.length;
  const sentenceTokens = plan.timeline.slice(
    sentenceStart,
    Math.min(plan.timeline.length, sentenceEnd)
  );
  const hint = progress?.current_sentence_index == null ? '' : sentenceHints[progress.current_sentence_index]?.trim();

  if ((!karaokeEnabled && !keywordHintEnabled) || !plan.normalizedScript) {
    return null;
  }

  return (
    <section className="karaoke-guide" aria-label="발표 진행 오버레이">
      <div className="progress-track">
        <span style={{ width: `${actualPercent}%` }} />
      </div>
      {keywordHintEnabled ? (
        <div className="keyword-hints" aria-live="polite">
          <span>{currentIndex < 0 ? '인식된 대본 위치 대기' : hint || '힌트 미설정 · 대본을 확인하세요.'}</span>
        </div>
      ) : (
        <div className="karaoke-line" aria-live="polite">
          {currentIndex < 0 ? <span>인식된 대본 위치 대기</span> : sentenceTokens.length ? (
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
        <span>실제 진행 {actualPercent}% · {progress?.alignment_status === 'uncertain' ? '정렬 불확실 · 마지막 위치 유지' : currentIndex < 0 ? '인식 대기' : '대본 위치 확인'}</span>
        <span>목표 진행 {Math.min(100, Math.round(elapsedSeconds / Math.max(timeLimitSeconds, 1) * 100))}%</span>
        <span>{formatTime(elapsedSeconds)} / {formatTime(timeLimitSeconds)}</span>
        <span>남은 시간 {formatTime(remainingSeconds)}</span>
        <span>목표 속도 {plan.targetSyllablesPerMinute} 음절/분</span>
      </div>
    </section>
  );
}
