import type { PracticeSummary } from "../types";

type SessionSummaryProps = {
  summary: PracticeSummary | null;
};

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}분 ${remainingSeconds}초`;
}

function formatPercent(ratio: number | null | undefined) {
  return ratio == null ? '분석 없음' : `${Math.round(ratio * 100)}%`;
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
          <dt>유효 관찰 중 시선 이탈 비율</dt>
          <dd>{summary.gazeStatus === 'disabled' ? '비활성' : formatPercent(summary.gazeAwayRatio)}</dd>
        </div>
        <div>
          <dt>시선 관찰 범위</dt>
          <dd>{formatPercent(summary.gazeCoverageRatio)}</dd>
        </div>
        <div>
          <dt>대본과 인식 결과 일치도</dt>
          <dd>{formatAccuracy(summary.pronunciationAccuracy)}</dd>
        </div>
        <div>
          <dt>속도 경고</dt>
          <dd>{summary.speechPaceWarningCount == null ? '분석 없음' : `${summary.speechPaceWarningCount}회`}</dd>
        </div>
        <div>
          <dt>평균 발화 속도</dt>
          <dd>{summary.speechStatus === 'disabled' ? '비활성' : summary.averageSyllablesPerMinute == null ? '분석 없음' : `${Math.round(summary.averageSyllablesPerMinute)}음절/분`}</dd>
        </div>
        <div>
          <dt>습관어</dt>
          <dd>
            {summary.fillerStatus === 'disabled' ? '비활성' : summary.fillerWordCounts === null ? '분석 없음' : Object.entries(summary.fillerWordCounts)
              .map(([word, count]) => `${word} ${count}회`)
              .join(", ") || "검출 0회"}
          </dd>
        </div>
        <div><dt>실제 대본 진행률</dt><dd>{formatPercent(summary.scriptCompletionRatio)}</dd></div>
      </dl>
      {summary.incomplete ? (
        <p className="error-text">일부 분석이 완료되지 않아 현재까지의 결과만 표시합니다.</p>
      ) : null}
      <div className="transcript-summary">
        <p>대본 일치도는 STT 텍스트 비교이며 발음 정확도를 의미하지 않습니다. 받아쓰기는 이 화면에서만 확인하며 새 리포트에는 저장하지 않습니다.</p>
        <h3>받아쓰기 결과</h3>
        <p>{summary.transcript ?? "인식된 음성이 없습니다."}</p>
      </div>
    </section>
  );
}
