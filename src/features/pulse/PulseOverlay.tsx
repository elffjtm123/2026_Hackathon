import type { PulseResult } from './signal';

export function PulseOverlay({result, active}: {result: PulseResult; active: boolean}) {
  const numeric=(active || result.ended) && result.bpm !== null;
  return <aside className="presentation-pulse-overlay" aria-label="발표 영상 실시간 맥박">
    <span>맥박 · {result.model ?? 'MA-UBFC TS-CAN'}</span><strong>{numeric ? `${result.bpm} BPM` : '— BPM'}</strong>
    <small>{result.ended ? `종료 · 마지막 ${result.status==='provisional' ? '잠정값' : '추정값'}` : !active ? '발표 시작 대기' : result.held ? `이전 추정 · ${(result.ageSeconds??0).toFixed(1)}초 전 · 현재값 아님` : numeric ? result.status==='provisional' ? '잠정 추정 · 신호 품질 확인 중' : '주기성 양호 · 연구용 추정' : result.reason}</small>
  </aside>;
}
