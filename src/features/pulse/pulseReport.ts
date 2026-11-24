import { emptyPulse, type PulseResult } from './signal';

/** What a pulse consumer is told: the live result, or an empty one that says why there is none. */
export function pulseForReport(enabled: boolean, hasStream: boolean, result: PulseResult): PulseResult {
  return enabled && (hasStream || result.ended) ? result : emptyPulse(enabled ? '발표 시작 대기' : '맥박 분석 꺼짐');
}

// The first two sentences of the research-only caution, shown wherever a pulse reading appears.
export const pulseResearchCaution = '연구용 추정치입니다. 맥박 상승을 긴장·감정으로 판정하지 않으며, 의료 진단이나 면접 평가 점수에 사용하지 않습니다.';

// What happens to the camera frames, by estimator method; one source for the panel and the practice screen.
export function pulsePrivacyNote(mode: 'pos' | 'efficientphys', modelSize: number): string {
  const note = mode === 'efficientphys'
    ? `${modelSize}×${modelSize} RGB 얼굴 크롭은 이 컴퓨터의 로컬 백엔드에서만 추론합니다. 영상·맥파·BPM을 파일이나 DB에 저장하지 않고, 종료 시 마지막 값만 이 화면 메모리에 남깁니다. 인터넷 서버로 보내지 않습니다.`
    : '본 맥박 기능의 프레임·RGB 신호·생체 추정값은 브라우저 메모리에서만 처리하며 저장·외부 전송하지 않습니다.';
  return `${note} 기존 연습의 영상·음성은 원래처럼 로컬 백엔드로 전송됩니다.`;
}
