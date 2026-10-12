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
          description="인식된 대본 위치를 표시하고 제한시간의 목표 진행과 구분합니다."
          checked={settings.karaokeGuideEnabled}
          disabled={disabled}
          onChange={(enabled) => onChange("karaokeGuideEnabled", enabled)}
        />
        <FeatureToggle
          title="대본 요약 보기"
          description="발표 중 인식된 현재 문장에 연결된 요약을 표시합니다. 끄면 기존 대본 가이드를 사용합니다."
          checked={settings.keywordHintEnabled}
          disabled={disabled}
          onChange={(enabled) => onChange("keywordHintEnabled", enabled)}
        />
      </div>
    </section>
  );
}
