import {scriptSentences} from '../scriptTools';

type PresentationSetupProps = {
  script: string;
  timeLimitSeconds: number;
  disabled: boolean;
  onScriptChange: (script: string) => void;
  onTimeLimitChange: (seconds: number) => void;
  sentenceHints: Record<number, string>;
  onHintChange: (index: number, hint: string) => void;
};

export function PresentationSetup({
  script,
  timeLimitSeconds,
  disabled,
  onScriptChange,
  onTimeLimitChange,
  sentenceHints,
  onHintChange,
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
      <details className="presentation-setup__script">
        <summary>문장별 요약 힌트 작성</summary>
        <p>예: 부정: 원본 영상·음성 저장 안 함. 자동 생성하지 않으며, 대본 수정 시 힌트는 초기화됩니다.</p>
        {scriptSentences(script).map((sentence, index) => <label key={index}>
          <span>{index + 1}. {sentence}</span>
          <input aria-label={`${index + 1}번 문장 요약 힌트`} maxLength={160}
            disabled={disabled} value={sentenceHints[index] ?? ''}
            onChange={event => onHintChange(index, event.target.value)} />
        </label>)}
      </details>
      <div className="presentation-setup__script">
        <label htmlFor="presentation-script">발표 대본</label>
        <textarea
          id="presentation-script"
          value={script}
          disabled={disabled}
          rows={5}
          onChange={(event) => onScriptChange(event.target.value)}
        />
      </div>
    </section>
  );
}
