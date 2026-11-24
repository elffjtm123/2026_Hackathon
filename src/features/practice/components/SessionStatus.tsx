import type { SessionPhase } from '../../../lib/realtimeProtocol';
import type { ConnectionStatus } from '../types';

type SessionStatusProps = {
  phase: SessionPhase;
  connectionStatus: ConnectionStatus;
  onRecalibrate: () => void;
};

// Preparation, calibration and draining messages with the recalibrate action beside them.
export function SessionStatus({phase, connectionStatus, onRecalibrate}: SessionStatusProps) {
  const canRecalibrate = ['calibrating', 'running'].includes(phase) && connectionStatus === 'connected';
  if (!canRecalibrate && !['preparing', 'calibrating', 'draining'].includes(phase)) return null;
  return <div className="session-status">
    {phase === 'preparing' ? <p role="status">음성·시선 모델을 준비 중입니다. 준비와 보정이 끝난 뒤 연습 시간이 시작됩니다.</p> : null}
    {phase === 'calibrating' ? <p role="status">카메라를 바라보며 보정 중입니다. 연습 시간은 보정 완료 후 시작합니다.</p> : null}
    {phase === 'draining' ? <p role="status">마지막 음성을 분석하고 있습니다.</p> : null}
    {canRecalibrate ? <button type="button" className="secondary-button" onClick={onRecalibrate}>다시 보정</button> : null}
  </div>;
}
