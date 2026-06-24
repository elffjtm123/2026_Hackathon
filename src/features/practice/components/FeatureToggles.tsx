import type { PresentationFeatureSettings } from "../types";

type FeatureTogglesProps = {
  settings: PresentationFeatureSettings;
  disabled: boolean;
  onChange: (
    feature: keyof PresentationFeatureSettings,
    enabled: boolean
  ) => void;
};

type ToggleProps = {
  title: string;
  description: string;
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
};

function FeatureToggle({
  title,
  description,
  checked,
  disabled,
  onChange,
}: ToggleProps) {
  return (
    <label className="feature-toggle">
      <span className="feature-toggle__copy">
        <strong>{title}</strong>
        <span>{description}</span>
      </span>
      <span className="switch">
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span className="switch__track" aria-hidden="true" />
        <span className="switch__status">{checked ? "ON" : "OFF"}</span>
      </span>
    </label>
  );
}

export function FeatureToggles({
  settings,
  disabled,
  onChange,
}: FeatureTogglesProps) {
  return (
    <section className="feature-settings" aria-labelledby="feature-settings-title">
      <div className="feature-settings__header">
        <div>
          <p className="eyebrow">Presentation tools</p>
          <h2 id="feature-settings-title">발표 보조 기능</h2>
        </div>
        {disabled ? <span className="settings-lock">진행 중 잠김</span> : null}
      </div>
      <div className="feature-settings__grid">
        <FeatureToggle
          title="노래방식 발표 진행 가이드"
          description="대본과 제한시간을 기준으로 현재 읽을 위치와 속도를 안내합니다."
          checked={settings.karaokeGuideEnabled}
          disabled={disabled}
          onChange={(enabled) => onChange("karaokeGuideEnabled", enabled)}
        />
        <FeatureToggle
          title="주요 단어 힌트"
          description="전문 대신 현재 문장의 핵심 단어만 같은 위치에 표시합니다."
          checked={settings.keywordHintEnabled}
          disabled={disabled}
          onChange={(enabled) => onChange("keywordHintEnabled", enabled)}
        />
        <FeatureToggle
          title="대본 스타일 전이"
          description="여러 발표 스타일의 수사적 특성을 혼합해 대본 변환을 허용합니다."
          checked={settings.styleTransferEnabled}
          disabled={disabled}
          onChange={(enabled) => onChange("styleTransferEnabled", enabled)}
        />
      </div>
    </section>
  );
}
