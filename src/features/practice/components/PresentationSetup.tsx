import {scriptSentences} from '../scriptTools';

type PresentationSetupProps = {
  script: string;
  timeLimitSeconds: number;
  disabled: boolean;
  onScriptChange: (script: string) => void;
  onTimeLimitChange: (seconds: number) => void;
  sentenceHints: Record<number, string>;
  onHintChange: (index: number, hint: string) => void;
  onSummarize: () => void;
  isSummarizing: boolean;
  summaryError: string | null;
  sentenceErrors: Record<number, string>;
  summarySeconds: number | null;
};

export function PresentationSetup({
  script,
  timeLimitSeconds,
  disabled,
  onScriptChange,
  onTimeLimitChange,
  sentenceHints,
  onHintChange,
  onSummarize,
  isSummarizing,
  summaryError,
  sentenceErrors,
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
      <section className="presentation-summary" aria-label="문장별 대본 요약" aria-busy={isSummarizing}>
        <h3>문장별 요약본</h3>
        <p>원문별 요약을 직접 입력하거나 자동 생성한 내용을 수정하세요. 대본 수정 시 요약은 초기화됩니다.</p>
        {summarySeconds !== null ? <p role="status">AI 초안 · 내용 확인 필요 · {summarySeconds.toFixed(2)}초 소요</p> : null}
        {isSummarizing ? <p role="status">Qwen3.5-0.8B로 요약 중입니다. 모델 정리가 끝나면 발표를 시작할 수 있습니다.</p> : null}
        {summaryError ? <p className="error-banner" role="alert">{summaryError}</p> : null}
        {scriptSentences(script).map((sentence, index) => <label className="summary-sentence" key={index}>
          <span>{index + 1}. {sentence}</span>
          <textarea aria-label={`${index + 1}번 문장 요약 힌트`} maxLength={160} rows={2}
            placeholder="이 문장의 요약을 입력하세요."
            disabled={disabled || isSummarizing} value={sentenceHints[index] ?? ''}
            onChange={event => onHintChange(index, event.target.value)} />
          {sentenceErrors[index] ? <span className="summary-sentence__error">{sentenceErrors[index]}</span> : null}
        </label>)}
      </section>
    </section>
  );
}
