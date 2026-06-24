import { useMemo, useState } from "react";
import { analyzeScript, formatTime, transformScript } from "../scriptTools";

type StyleTransferPanelProps = {
  originalScript: string;
  currentScript: string;
  timeLimitSeconds: number;
  disabled: boolean;
  enabled: boolean;
  onApply: (script: string) => void;
  onReset: () => void;
};

const styleOptions = [
  { value: "concise", label: "간결한 발표" },
  { value: "keynote", label: "키노트형 발표" },
  { value: "persuasive", label: "설득형 발표" },
  { value: "story", label: "스토리텔링형 발표" },
];

export function StyleTransferPanel({
  originalScript,
  currentScript,
  timeLimitSeconds,
  disabled,
  enabled,
  onApply,
  onReset,
}: StyleTransferPanelProps) {
  const [style, setStyle] = useState(styleOptions[0].value);
  const [preview, setPreview] = useState("");
  const plan = useMemo(
    () => analyzeScript(preview || currentScript, timeLimitSeconds),
    [currentScript, preview, timeLimitSeconds]
  );

  if (!enabled) {
    return null;
  }

  const handleTransform = () => {
    const transformed = transformScript(currentScript || originalScript, style);
    setPreview(transformed);
    onApply(transformed);
  };

  const handleReset = () => {
    setPreview("");
    onReset();
  };

  return (
    <section className="style-transfer-panel" aria-label="대본 스타일 전이">
      <div className="style-transfer-panel__header">
        <div>
          <p className="eyebrow">Style transfer</p>
          <h2>대본 스타일 전이</h2>
        </div>
        <div className="style-actions">
          <select
            value={style}
            disabled={disabled}
            onChange={(event) => setStyle(event.target.value)}
            aria-label="발표 스타일 선택"
          >
            {styleOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button type="button" onClick={handleTransform} disabled={disabled || !currentScript.trim()}>
            변환
          </button>
          <button type="button" className="secondary-button" onClick={handleReset} disabled={disabled}>
            원상복귀
          </button>
        </div>
      </div>
      <div className="style-preview">
        <label htmlFor="style-preview">변환된 대본</label>
        <textarea
          id="style-preview"
          value={preview}
          readOnly
          rows={5}
          placeholder="변환 버튼을 누르면 변환된 대본이 표시되고 자막에도 반영됩니다."
        />
      </div>
      <div className="karaoke-stats">
        <span>반영 속도 {plan.targetSyllablesPerMinute} 음절/분</span>
        <span>예상 길이 {formatTime(plan.estimatedDurationSeconds)}</span>
      </div>
    </section>
  );
}
