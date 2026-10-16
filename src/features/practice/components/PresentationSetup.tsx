import type {ScriptSummaryGroup, SummaryProgress} from '../scriptTools';

type PresentationSetupProps = {
  script: string;
  timeLimitSeconds: number;
  disabled: boolean;
  onScriptChange: (script: string) => void;
  onTimeLimitChange: (seconds: number) => void;
  groups: ScriptSummaryGroup[];
  onHintChange: (index: number, hint: string) => void;
  onSummarize: () => void;
  isSummarizing: boolean;
  summaryError: string | null;
  summaryProgress: SummaryProgress | null;
  summarySeconds: number | null;
};

export function PresentationSetup({
  script,
  timeLimitSeconds,
  disabled,
  onScriptChange,
  onTimeLimitChange,
  groups,
  onHintChange,
  onSummarize,
  isSummarizing,
  summaryError,
  summaryProgress,
  summarySeconds,
}: PresentationSetupProps) {
  return (
    <section className="presentation-setup" aria-label="발표 대본 설정">
      <div className="presentation-setup__time">
        <label htmlFor="time-limit">제한 시간</label>
        <div className="time-input-row">
          <input
            id="time-limit"
            type="number"
            min={30}
            max={1800}
            step={30}
            value={timeLimitSeconds}
            disabled={disabled}
            onChange={(event) => onTimeLimitChange(Number(event.target.value))}
          />
          <span>초</span>
        </div>
      </div>
      <div className="presentation-setup__script">
        <div className="script-heading">
          <label htmlFor="presentation-script">발표 대본</label>
          <button type="button" className="secondary-button" onClick={onSummarize}
            disabled={disabled || isSummarizing || !script.trim()}>
            {isSummarizing ? '요약 중…' : summarySeconds !== null ? '다시 요약' : '요약 시작'}
          </button>
        </div>
        <textarea
          id="presentation-script"
          value={script}
          disabled={disabled || isSummarizing}
          rows={5}
          onChange={(event) => onScriptChange(event.target.value)}
        />
      </div>
      <section className="presentation-summary" aria-label="의미 묶음 대본 요약" aria-busy={isSummarizing}>
        {summarySeconds !== null ? <p role="status">AI 초안 · 내용 확인 필요 · {summarySeconds.toFixed(2)}초 소요</p> : null}
        {isSummarizing ? <div className="summary-progress">
          <p role="status">{!summaryProgress || summaryProgress.stage === 'preparing' ? '요약 모델 준비 중…'
            : summaryProgress.stage === 'cleaning' ? '요약 모델 정리 중…'
            : `원문 ${summaryProgress.total_sentences}문장 중 ${summaryProgress.completed_sentences}문장 처리`}
            {summaryProgress?.failed_sentences ? ` · ${summaryProgress.failed_sentences}문장 직접 확인 필요` : ''}</p>
          <progress aria-label="원문 문장 처리 진행도" max={summaryProgress?.total_sentences || 1}
            value={summaryProgress?.stage === 'generating' || summaryProgress?.stage === 'cleaning'
              ? summaryProgress.completed_sentences : undefined} />
          <p>Qwen3.5-9B Q4_K_M · STT·시선 모델은 미로드 상태입니다. 정리가 끝나면 발표를 시작할 수 있습니다.</p>
        </div> : null}
        {summaryError ? <p className="error-banner" role="alert">{summaryError}</p> : null}
        <details className="summary-details" open>
          <summary>묶음 요약본 <span className="summary-close-label">접기</span><span className="summary-open-label">펼치기</span></summary>
          <p>이어지는 설명을 한 묶음으로 요약합니다. 요약을 직접 입력하거나 수정하세요. 대본 수정 시 초기화됩니다.</p>
        {groups.map((group, index) => <label className="summary-sentence" key={`${group.start_sentence}-${group.end_sentence}`}>
          <span>{group.start_sentence === group.end_sentence ? `${group.start_sentence + 1}번 문장`
            : `${group.start_sentence + 1}~${group.end_sentence + 1}번 문장`} · {group.original}</span>
          <textarea aria-label={`${index + 1}번 묶음 요약 힌트`} maxLength={160} rows={2}
            placeholder="이 구간에서 말할 내용을 요약하세요."
            disabled={disabled || isSummarizing} value={group.hint ?? ''}
            onChange={event => onHintChange(index, event.target.value)} />
          {group.error ? <span className="summary-sentence__error">{group.error}</span> : null}
        </label>)}
        </details>
      </section>
    </section>
  );
}
