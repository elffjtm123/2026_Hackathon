import { apiBase } from '../../lib/apiBase.ts';

export const modelThemes = [
  { id: 'service_qwen', name: '현재 서비스', label: 'Qwen3-ASR-0.6B · Q8_0 · speech.cpp',
    tag: '현재 서비스 기준', accent: '#24665d', tint: '#edf6f1', experiment: false,
    description: '최신 서비스: 발화 단위 STT, 의미 묶음 요약, 시선 분석과 종료 리포트를 사용합니다.' },
  { id: 'qwen_q8', name: 'Qwen Q8', label: 'Qwen3-ASR-0.6B · Q8_0',
    tag: '양자화 실행 설정', accent: '#6d45a5', tint: '#f4effa', experiment: true,
    description: 'Qwen의 Q8 가중치를 llama.cpp CPU로 실행합니다.' },
  { id: 'whisper_small_int8', name: 'Whisper Small', label: 'Whisper small · INT8',
    tag: '정확도·속도 균형', accent: '#2c5ca0', tint: '#edf3fb', experiment: true,
    description: 'faster-whisper의 small 모델을 CPU INT8로 실행합니다.' },
  { id: 'whisper_base_int8', name: 'Whisper Base', label: 'Whisper base · INT8',
    tag: '더 작은 모델', accent: '#9a5a22', tint: '#fbf3e9', experiment: true,
    description: '작은 base 모델로 실제 연습의 누락과 응답 속도를 확인합니다.' },
  { id: 'zipformer_int8', name: 'Korean Zipformer', label: '한국어 Zipformer · INT8',
    tag: '한국어 경량 모델', accent: '#a33e63', tint: '#faeef3', experiment: true,
    description: 'sherpa-onnx 한국어 모델을 공통 VAD의 확정 발화 단위로 실행합니다.' },
] as const;

export type ModelId = typeof modelThemes[number]['id'];
export type ModelTheme = typeof modelThemes[number];
export function findTheme(id: string): ModelTheme | undefined {
  return modelThemes.find(theme => theme.id === id);
}
export function themeFromHash(hash: string): ModelTheme | undefined {
  if (hash === '#practice') return modelThemes[0];
  return hash.startsWith('#practice/') ? findTheme(hash.slice('#practice/'.length)) : undefined;
}
export const modelApiBase = `${apiBase}/stt-experiments`;

export type ModelAvailability = { id: string; available: boolean; reason: string; label: string };
export async function readModelAvailability(): Promise<{models: ModelAvailability[]; busy: boolean}> {
  const response = await fetch(`${modelApiBase}/models`);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message ?? '모델 상태를 확인하지 못했습니다.');
  return body;
}

// Only experiment themes depend on the local-only experiments API. The service theme must start
// even where that API answers 404 (production, experiments disabled) or 403 (non-loopback client).
export async function ensureThemeReady(theme: ModelTheme,
    read: typeof readModelAvailability = readModelAvailability): Promise<void> {
  if (!theme.experiment) return;
  const models = await read();
  const selected = models.models.find(model => model.id === theme.id);
  if (models.busy) throw new Error('다른 연습이나 비교 실험이 진행 중입니다. 종료 후 다시 시작해 주세요.');
  if (!selected?.available) throw new Error(selected?.reason || '선택한 모델이 준비되지 않았습니다.');
}

// The service model is the backend default, so its sessions carry no STT selection at all.
export function sttModelIdFor(theme: ModelTheme): ModelId | undefined {
  return theme.experiment ? theme.id : undefined;
}
