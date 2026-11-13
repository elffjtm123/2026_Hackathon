// Independent implementation of the POS projection in Wang et al. (2017),
// DOI 10.1109/TBME.2016.2609282. No pyVHR/rPPG-Toolbox code is bundled.
export type RGB = [number, number, number];
export type PulseSample = { time: number; regions: RGB[]; light: number };
export type PulseResult = {
  status: 'collecting' | 'unreliable' | 'provisional' | 'observed'; reason: string;
  bpm: number | null; seconds: number; fps: number; snr: number | null;
  waveform: number[];
  model?: string; runtime?: string; inferenceMs?: number; modelWindows?: number;
  rawBpm?: number; ended?: boolean;
  held?: boolean; ageSeconds?: number; readingStatus?: 'observed' | 'provisional';
  diagnostics?: {
    inputFps: number; totalFrames: number; acceptedFrames: number;
    regions: {name: string; x: number; y: number; width: number; height: number; valid: boolean}[];
    light: number | null; green: number[];
    resets?: number; resetReason?: string; resultAgeSeconds?: number | null; updateSeconds?: number | null; captureSeconds?: number;
    faceAssessment?: {eyePixels:number;faceWidth:number;faceHeight:number;warning:string;reason:string} | null;
  };
};
export const emptyPulse = (reason = '카메라를 켜고 정면을 유지해 주세요.'): PulseResult => ({
  status: 'collecting', reason, bpm: null, seconds: 0, fps: 0, snr: null, waveform: [],
});
const average = (x: number[]) => x.reduce((a, b) => a + b, 0) / Math.max(1, x.length);
const deviation = (x: number[]) => { const m = average(x); return Math.sqrt(average(x.map(v => (v - m) ** 2))); };

export function posSignal(rgb: RGB[], fps: number): number[] {
  const out = Array(rgb.length).fill(0) as number[];
  const weights = Array(rgb.length).fill(0) as number[];
  const length = Math.round(1.6 * fps);
  for (let start = 0; start + length <= rgb.length; start++) {
    const window = rgb.slice(start, start + length);
    const means = [0, 1, 2].map(c => average(window.map(v => v[c])));
    if (means.some(v => v <= 0 || !Number.isFinite(v))) continue;
    const normalized = window.map(v => v.map((x, c) => x / means[c]));
    const x = normalized.map(v => v[1] - v[2]);
    const y = normalized.map(v => -2 * v[0] + v[1] + v[2]);
    const alpha = deviation(x) / Math.max(deviation(y), 1e-12);
    const h = x.map((v, i) => v + alpha * y[i]);
    const center = average(h);
    h.forEach((v, i) => { out[start + i] += v - center; weights[start + i]++; });
  }
  return out.map((v, i) => weights[i] ? v / weights[i] : 0);
}

function spectrum(signal: number[], fps: number) {
  const n = signal.length;
  const mean = average(signal);
  const slope = signal.reduce((sum, v, i) => sum + (i - (n - 1) / 2) * (v - mean), 0)
    / Math.max(1, n * (n * n - 1) / 12);
  const x = signal.map((v, i) => (v - mean - slope * (i - (n - 1) / 2))
    * (0.5 - 0.5 * Math.cos(2 * Math.PI * i / (n - 1))));
  const powers: number[] = [];
  for (let bpm = 45; bpm <= 180; bpm++) {
    let real = 0, imaginary = 0;
    x.forEach((v, i) => {
      const angle = 2 * Math.PI * bpm / 60 * i / fps;
      real += v * Math.cos(angle); imaginary += v * Math.sin(angle);
    });
    powers.push(real * real + imaginary * imaginary);
  }
  const peak = powers.indexOf(Math.max(...powers));
  const signalPower = powers.reduce((sum, p, i) => sum + (Math.abs(i - peak) <= 6 ? p : 0), 0);
  const noise = powers.reduce((sum, p, i) => sum + (Math.abs(i - peak) > 6 ? p : 0), 0);
  const snr = 10 * Math.log10(Math.max(signalPower, 1e-20) / Math.max(noise, 1e-20));
  return { bpm: peak + 45, snr, amplitude: deviation(x), x };
}

export function estimatePulse(samples: PulseSample[]): PulseResult {
  const seconds = samples.length < 2 ? 0 : (samples.at(-1)!.time - samples[0].time) / 1000;
  const fps = seconds ? (samples.length - 1) / seconds : 0;
  const result = { ...emptyPulse(), seconds, fps };
  if (seconds < 15) return { ...result, reason: `안정된 영상 수집 중 · ${seconds.toFixed(1)} / 15초` };
  const gaps = samples.slice(1).map((v, i) => v.time - samples[i].time);
  if (fps < 15 || gaps.some(v => v > 250 || v <= 0)) return {
    ...result, status: 'unreliable', reason: '프레임 부족 또는 시간 간격 불안정 · 15fps 이상 필요',
  };
  const light = samples.map(v => v.light);
  if (deviation(light) / Math.max(average(light), 1) > 0.035) return {
    ...result, status: 'unreliable', reason: '조명 변화가 큽니다. 일정한 전면 조명을 사용해 주세요.',
  };
  // Uniform resampling by real capture timestamps, not by callback count.
  const count = Math.floor(seconds * 30) + 1;
  let cursor = 0;
  const traces = [0, 1, 2].map(region => Array.from({length: count}, (_, i): RGB => {
    const time = samples[0].time + i * 1000 / 30;
    if (region > 0 && i === 0) cursor = 0;
    while (cursor + 1 < samples.length - 1 && samples[cursor + 1].time < time) cursor++;
    const a = samples[cursor], b = samples[cursor + 1];
    const t = Math.max(0, Math.min(1, (time - a.time) / (b.time - a.time)));
    return a.regions[region].map((v, c) => v + t * (b.regions[region][c] - v)) as RGB;
  }));
  const estimates = traces.map(trace => spectrum(posSignal(trace, 30), 30));
  const reliable = estimates.filter(v => v.snr >= 3 && v.amplitude > 1e-5 && v.bpm > 47 && v.bpm < 178);
  const agreement = reliable.filter(v => reliable.some(other => other !== v && Math.abs(other.bpm - v.bpm) <= 6));
  if (agreement.length < 2) return {
    ...result, status: 'unreliable', reason: '맥파 신호 또는 얼굴 부위 간 일치도가 부족합니다.',
  };
  const bpm = Math.round(average(agreement.map(v => v.bpm)));
  const best = agreement.reduce((a, b) => a.snr > b.snr ? a : b);
  const scale = Math.max(...best.x.map(Math.abs), 1e-12);
  return { ...result, status: 'observed', reason: '실험용 추정 · 의료 측정값이 아닙니다.', bpm,
    snr: Math.round(best.snr * 10) / 10,
    waveform: best.x.slice(-150).filter((_, i) => i % 2 === 0).map(v => v / scale) };
}

export class PulseBuffer {
  samples: PulseSample[] = [];
  reset() { this.samples = []; }
  add(sample: PulseSample) {
    const previous = this.samples.at(-1);
    if (previous && (sample.time <= previous.time || sample.time - previous.time > 250)) this.reset();
    if (sample.regions.length !== 3 || !Number.isFinite(sample.time)
      || !Number.isFinite(sample.light) || sample.regions.some(v => v.length !== 3 || v.some(x => !Number.isFinite(x) || x <= 0))) {
      this.reset(); return;
    }
    this.samples.push(sample);
    this.samples = this.samples.filter(v => v.time >= sample.time - 20000).slice(-1000);
  }
}

export function estimateNeuralPulse(samples: {time: number; value: number}[]): PulseResult {
  const seconds = samples.length > 1 ? (samples.at(-1)!.time - samples[0].time) / 1000 : 0;
  const base = {...emptyPulse(), seconds, fps: seconds > 0 ? (samples.length - 1) / seconds : 0};
  if (seconds < 6) return {...base, reason: `첫 잠정값을 위한 실제 모델 신호 수집 · ${seconds.toFixed(1)} / 6초`};
  if (samples.some((v,i) => !Number.isFinite(v.value) || !Number.isFinite(v.time)
    || i > 0 && (v.time <= samples[i-1].time || v.time - samples[i-1].time > 250)))
    return {...base, status: 'unreliable', reason: '맥파 결과가 누락되거나 시간 순서가 불안정합니다.'};
  let integrated = 0;
  const values = samples.map(v => (integrated += v.value)); // DiffNormalized model output.
  // Clip boundaries can be a few milliseconds apart. Respect their timestamps
  // instead of treating every returned model value as an exactly timed camera frame.
  let cursor = 0;
  const uniform = Array.from({length:Math.floor(seconds*30)+1},(_,i)=>{
    const time=samples[0].time+i*1000/30;
    while(cursor+1<samples.length-1 && samples[cursor+1].time<time) cursor++;
    const alpha=Math.max(0,Math.min(1,(time-samples[cursor].time)/(samples[cursor+1].time-samples[cursor].time)));
    return values[cursor]+alpha*(values[cursor+1]-values[cursor]);
  });
  const full = spectrum(uniform, 30);
  const middle = Math.floor(uniform.length / 2);
  const first = spectrum(uniform.slice(0,middle),30), last = spectrum(uniform.slice(middle),30);
  const candidate = full.snr >= 0 && full.amplitude > 1e-5 && full.bpm > 47 && full.bpm < 178;
  const reliable = seconds >= 15 && full.snr >= 3 && candidate
    && Math.abs(first.bpm-last.bpm) <= 12 && Math.abs(first.bpm-full.bpm) <= 12;
  const scale = Math.max(...full.x.map(Math.abs), 1e-12);
  const issue = full.amplitude <= 1e-5 ? '모델 출력의 변화가 너무 약합니다.'
    : full.bpm <= 47 || full.bpm >= 178 ? '최대 주파수가 탐색 경계에 있어 맥박으로 구분하기 어렵습니다.'
    : full.snr < 0 ? '맥파 대역의 반복 신호가 부족합니다.'
    : seconds < 15 ? '짧은 구간의 잠정값입니다. 15초 이상 모아 주기성을 추가 검사합니다.'
    : '구간별 주기 또는 신호 품질이 불안정한 잠정값입니다.';
  return {...base, status: reliable ? 'observed' : candidate ? 'provisional' : 'unreliable', bpm: candidate ? full.bpm : null,
    rawBpm: candidate ? full.bpm : undefined,
    reason: reliable ? '실제 모델 추정 · 주기성 검사 통과 (센서 대비 정확도 검증 아님)' : issue,
    snr: Number.isFinite(full.snr) ? Math.round(full.snr*10)/10 : null,
    waveform: full.x.slice(-150).filter((_,i) => i%2===0).map(v=>v/scale)};
}

// Overlapping inference must not count the same seconds twice or append old replies.
export function mergeNeuralWindow(previous: {time:number; value:number}[], start: number, values: number[]) {
  if (!Number.isFinite(start) || !values.length || values.some(v => !Number.isFinite(v))) return previous;
  const end = start + (values.length-1)*1000/30;
  if (previous.length && end <= previous.at(-1)!.time) return previous;
  const contiguous = !previous.length || start-previous.at(-1)!.time <= 250;
  const prefix = contiguous ? previous.filter(v => v.time < start) : [];
  return [...prefix, ...values.map((value,i)=>({time:start+i*1000/30,value}))].filter(v=>v.time>=end-20000);
}

// Display filter only: quality is always evaluated on the unsmoothed signal.
export class PulseSmoother {
  recent: number[] = [];
  value: number | null = null;
  reset() { this.recent=[]; this.value=null; }
  add(result: PulseResult): PulseResult {
    if (result.bpm === null) { this.reset(); return result; }
    this.recent = [...this.recent,result.bpm].slice(-3);
    const sorted = [...this.recent].sort((a,b)=>a-b);
    const median = sorted[Math.floor(sorted.length/2)];
    this.value = this.value === null ? median : this.value*0.65+median*0.35;
    return {...result,rawBpm:result.bpm,bpm:Math.round(this.value)};
  }
}

// A previous estimate remains explicitly historical during a dropout. Never
// feed held values back into the estimator, smoothing, or baseline selection.
export class PulseReadoutMemory {
  last: {result:PulseResult; at:number} | null = null;
  reset() { this.last=null; }
  update(result:PulseResult, now:number): PulseResult {
    if (result.bpm !== null && !result.held && (result.status==='observed'||result.status==='provisional')) {
      this.last={result,at:now-Math.max(0,result.diagnostics?.resultAgeSeconds??0)*1000};
      return {...result,held:false,ageSeconds:Math.max(0,result.diagnostics?.resultAgeSeconds??0)};
    }
    if (!this.last) return result;
    const previous=this.last.result;
    return {...result,bpm:previous.bpm,rawBpm:previous.rawBpm,waveform:previous.waveform,held:true,
      model:previous.model,readingStatus:previous.status==='observed'?'observed':'provisional',
      ageSeconds:Math.max(0,(now-this.last.at)/1000)};
  }
  finish(now:number): PulseResult | null {
    return this.last ? {...this.last.result,ended:true,held:false,ageSeconds:Math.max(0,(now-this.last.at)/1000)} : null;
  }
}
