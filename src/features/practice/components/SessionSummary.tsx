import type { PracticeSummary } from "../types";

type SessionSummaryProps = {
  summary: PracticeSummary | null;
};

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}분 ${remainingSeconds}초`;
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
          <dt>시선 이탈</dt>
          <dd>{summary.gazeAwayCount}회</dd>
        </div>
        <div>
          <dt>속도 경고</dt>
          <dd>{summary.speechPaceWarningCount}회</dd>
        </div>
        <div>
          <dt>습관어</dt>
          <dd>{summary.fillerTotalCount}회</dd>
        </div>
      </dl>
    </section>
  );
}
