export const pulseModels = [
  {id:'ma_ubfc_tscan', name:'TS-CAN · MA-UBFC-rPPG', size:72, durationMs:3000, outputs:90, note:'기본 모델 · Motion Matters 움직임 증강 학습'},
  {id:'ubfc_efficientphys', name:'EfficientPhys · UBFC-rPPG', size:72, durationMs:3000, outputs:90, note:'기존 실시간 추론 모델'},
  {id:'ubfc_tscan', name:'TS-CAN · UBFC-rPPG', size:72, durationMs:3000, outputs:90, note:'움직임·외관 두 경로로 맥파 추정'},
  {id:'ubfc_physformer', name:'PhysFormer · UBFC-rPPG', size:128, durationMs:160000/30, outputs:160, note:'Transformer 비교 모델 · CPU에서는 갱신이 느릴 수 있음'},
  {id:'pure_efficientphys', name:'EfficientPhys · PURE', size:72, durationMs:3000, outputs:90, note:'이전 가중치 · 비교 기준'},
] as const;
export type PulseModelId = typeof pulseModels[number]['id'];
