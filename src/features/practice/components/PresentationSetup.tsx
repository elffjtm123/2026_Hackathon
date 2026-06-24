type PresentationSetupProps = {
  script: string;
  timeLimitSeconds: number;
  disabled: boolean;
  onScriptChange: (script: string) => void;
  onTimeLimitChange: (seconds: number) => void;
};

export function PresentationSetup({
  script,
  timeLimitSeconds,
  disabled,
  onScriptChange,
  onTimeLimitChange,
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
