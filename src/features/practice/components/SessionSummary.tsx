import type { PracticeSummary } from "../types";

type SessionSummaryProps = {
  summary: PracticeSummary | null;
};

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}분 ${remainingSeconds}초`;
}

function formatPercent(ratio: number) {
  return `${Math.round(ratio * 100)}%`;
}

function formatAccuracy(score: number | null) {
  return score === null ? "분석 없음" : `${Math.round(score)}점`;
}

export function SessionSummary({ summary }: SessionSummaryProps) {
  if (!summary) {
    return null;
  }

  return (
    <section className="summary-panel" aria-label="세션 요약">
      <h2>세션 요약</h2>
      <dl className="summary-grid">
        <div>
          <dt>총 진행 시간</dt>
          <dd>{formatDuration(summary.durationSeconds)}</dd>
        </div>
        <div>
          <dt>시선 이탈 비율</dt>
          <dd>{formatPercent(summary.gazeAwayRatio)}</dd>
        </div>
        <div>
          <dt>발음 정확도</dt>
          <dd>{formatAccuracy(summary.pronunciationAccuracy)}</dd>
        </div>
        <div>
          <dt>속도 경고</dt>
          <dd>{summary.speechPaceWarningCount}회</dd>
        </div>
        <div>
          <dt>평균 발화 속도</dt>
          <dd>{Math.round(summary.averageSyllablesPerMinute)}음절/분</dd>
        </div>
        <div>
          <dt>습관어</dt>
          <dd>
            {Object.entries(summary.fillerWordCounts)
              .map(([word, count]) => `${word} ${count}회`)
              .join(", ") || "없음"}
          </dd>
        </div>
      </dl>
      {summary.incomplete ? (
        <p className="error-text">일부 분석이 완료되지 않아 현재까지의 결과만 표시합니다.</p>
      ) : null}
      <div className="transcript-summary">
        <h3>받아쓰기 결과</h3>
        <p>{summary.transcript ?? "인식된 음성이 없습니다."}</p>
      </div>
    </section>
  );
}
