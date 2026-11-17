import { pulseModels } from '../../pulse/models';
import { pulsePrivacyNote } from '../../pulse/pulseReport';
import { faceFeaturePrivacy } from '../../face-features/privacyNote';

// How camera data is handled by the always-on pulse and face analyses, in the estimator's current mode.
export function DataNotes({pulseMode}: {pulseMode: 'pos' | 'efficientphys'}) {
  const model = pulseModels.find(item => item.id === 'ma_ubfc_tscan')!;
  return <details className="data-notes">
    <summary>데이터 처리 안내</summary>
    <p>{pulsePrivacyNote(pulseMode, model.size)}</p>
    <p>{faceFeaturePrivacy}</p>
  </details>;
}
