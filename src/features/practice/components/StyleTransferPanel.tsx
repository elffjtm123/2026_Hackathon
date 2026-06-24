import { useMemo, useState } from "react";
import { analyzeScript, formatTime } from "../scriptTools";

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
  { value: "visionary_keynote", label: "비전 중심 키노트" },
  { value: "dream_oratory", label: "희망적 비전 연설" },
  { value: "wartime_resolve", label: "단호한 결의" },
  { value: "high_intensity_rally", label: "고강도 호소" },
];

const apiBaseUrl =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  "http://127.0.0.1:8000/api/v1";

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
  const [isTransforming, setIsTransforming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const plan = useMemo(
    () => analyzeScript(preview || currentScript, timeLimitSeconds),
    [currentScript, preview, timeLimitSeconds]
  );

  if (!enabled) {
    return null;
  }

  const handleTransform = async () => {
    setIsTransforming(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/scripts/style-transfer/demo`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          script: currentScript || originalScript,
          time_limit_seconds: timeLimitSeconds,
          style_vector: { [style]: 1 },
          intensity: 0.65,
        }),
      });
      const body = (await response.json()) as {
        transformed_script?: string;
        warnings?: string[];
        error?: { message?: string };
      };
      if (!response.ok || typeof body.transformed_script !== "string") {
        throw new Error(body.error?.message || "스타일 변환에 실패했습니다.");
      }
      setPreview(body.transformed_script);
      setWarnings(body.warnings ?? []);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "스타일 변환에 실패했습니다.");
    } finally {
      setIsTransforming(false);
    }
  };

  const handleReset = () => {
    setPreview("");
    setWarnings([]);
    setError(null);
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
          <button
            type="button"
            onClick={() => void handleTransform()}
            disabled={disabled || isTransforming || !currentScript.trim()}
          >
            {isTransforming ? "변환 중" : "미리보기"}
          </button>
          <button
            type="button"
            onClick={() => onApply(preview)}
            disabled={disabled || !preview}
          >
            적용
          </button>
          <button type="button" className="secondary-button" onClick={handleReset} disabled={disabled}>
            원상복귀
          </button>
        </div>
      </div>
      {error ? <p className="error-text">{error}</p> : null}
      {warnings.map((warning) => (
        <p className="muted-text" key={warning}>{warning}</p>
      ))}
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
