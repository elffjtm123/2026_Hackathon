import type {FaceFeatures} from '../face-features/features';
import type {PulseResult} from '../pulse/signal';
import {deliveryForUser,type DeliveryMetrics,type DeliveryRow} from '../delivery/metrics.ts';
import type {PracticeSummary} from '../../lib/realtimeProtocol';

export type FaceSample = {time:number; eyeWide:number};
export type PulseSample = {time:number; bpm:number};
export type SessionSignals = {faces:FaceSample[]; pulses:PulseSample[]};
const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v);
const clamp=(v:number)=>Math.max(-1,Math.min(1,v));
const mean=(v:number[])=>v.reduce((a,b)=>a+b,0)/Math.max(1,v.length);
const median=(v:number[])=>{const s=[...v].sort((a,b)=>a-b);return s.length?(s[Math.floor((s.length-1)/2)]+s[Math.floor(s.length/2)])/2:0;};
const pair=(v:Record<string,number>,key:string)=>(v[key+'Left']+v[key+'Right'])/2;

// Bounded in-memory measurements only. Repeated UI refreshes never count as new pulse estimates.
export class SessionSignalRecorder {
  private data:SessionSignals={faces:[],pulses:[]};
  private lastFace=-Infinity;
  private lastPulse='';
  reset(){this.data={faces:[],pulses:[]};this.lastFace=-Infinity;this.lastPulse='';}
  face(result:FaceFeatures){
    const t=result.timestampMs,c=result.coefficients;
    if(result.status!=='observed'||!finite(t)||!c||t-this.lastFace<180)return;
    const sample={time:t,eyeWide:pair(c,'eyeWide')};
    if(!Object.values(sample).every(finite))return;
    this.lastFace=t;this.data.faces.push(sample);this.data.faces=this.data.faces.slice(-20000);
  }
  pulse(result:PulseResult,now:number){
    const age=result.ageSeconds??result.diagnostics?.resultAgeSeconds;
    // A model estimate is new per completed window; a browser POS estimate per new camera frames.
    const key=[result.model,result.diagnostics?.resets,result.modelWindows,
      result.model==='POS'?result.diagnostics?.totalFrames:''].join(':');
    if(result.status!=='observed'||result.held||result.ended||!finite(result.bpm)||!finite(age)
      ||age<0||age>6.5||!finite(result.modelWindows)||key===this.lastPulse)return;
    this.lastPulse=key;this.data.pulses.push({time:now-age*1000,bpm:result.bpm});
    this.data.pulses=this.data.pulses.slice(-7200);
  }
  snapshot():SessionSignals{return {faces:[...this.data.faces],pulses:[...this.data.pulses]};}
}

export type ActivationLevel='higher'|'similar'|'lower';
export type ActivationPoint={startMs:number;endMs:number;status:'compared'|'insufficient';inBaseline:boolean;
  level:ActivationLevel|null;label:string;activation:number|null;missing:string[];
  // Voice evidence relative to the speaker's own baseline; loudness only when AGC was confirmed off.
  evidence:{voicedMs:number;faceCoverage:number;f0Semitones:number|null;rateChange:number|null;loudnessDb:number|null};
  contributions:{voice:number;face:number|null}|null;
  // Reference trend only (unvalidated rPPG). Never part of activation and never exported.
  pulse:{count:number;bpm:number|null}};
export type ActivationAnalysis={version:'voice-activation.v2';status:'ok'|'not-enough-data';
  baseline:{windowCount:number;required:number;startsAtMs:number};points:ActivationPoint[];
  comparedCount:number;overall:number|null;label:string};

// Early speech is not the speaker's usual voice (our AI Hub check: F0 about half a semitone lower
// in the first 30 s), so the baseline is the median of qualified windows that start at or after it.
export const BASELINE_START_MS=30000;
export const BASELINE_MIN_WINDOWS=3;
const LEVEL_THRESHOLD=.2;

export function activationLabel(level:ActivationLevel|null):string{
  if(level==='higher')return '본인 기준보다 목소리 활성도가 높음';
  if(level==='lower')return '본인 기준보다 목소리 활성도가 낮음';
  if(level==='similar')return '본인 기준과 목소리 활성도가 비슷함';
  return '판단 보류';
}
const levelOf=(activation:number):ActivationLevel=>activation>=LEVEL_THRESHOLD?'higher':activation<=-LEVEL_THRESHOLD?'lower':'similar';

// The backend reports observed_ms, the span between the first and last observed frame in a slot.
// A partial first slot is observed up to its end; any other partial slot from its start.
function observedRange(row:DeliveryRow,index:number,count:number):[number,number]|null{
  const start=row.start_ms,end=row.end_ms;
  if(!finite(start)||!finite(end)||end<=start)return null;
  const observed=finite(row.observed_ms)?Math.max(0,Math.min(end-start,row.observed_ms)):end-start;
  if(observed<=0)return null; // nothing observed in the slot: withhold the window
  if(observed>=end-start)return [start,end];
  return index===0&&count>1?[end-observed,end]:[start,start+observed];
}

type Window={point:ActivationPoint;f0:number;rate:number;loudness:number|null;eye:number|null};
export function analyzeActivation(signals:SessionSignals,delivery?:DeliveryMetrics):ActivationAnalysis{
  const rows=delivery?.windows?.windows??[];
  const points:ActivationPoint[]=[],qualified:Window[]=[];
  rows.forEach((row,index)=>{
    const range=observedRange(row,index,rows.length);
    if(!range)return;
    const [start,end]=range;
    const faces=signals.faces.filter(v=>v.time>=start&&v.time<end);
    const pulses=signals.pulses.filter(v=>v.time>=start&&v.time<end);
    // 200 ms sampling buckets avoid overstating coverage from clustered frames.
    const buckets=new Set(faces.map(v=>Math.floor((v.time-start)/200)));
    const faceCoverage=Math.min(1,buckets.size*200/(end-start));
    const f0=finite(row.f0_median_hz)&&row.f0_median_hz>0?row.f0_median_hz:null;
    const rate=finite(row.articulation_rate)&&row.articulation_rate>0?row.articulation_rate:null;
    const voicedMs=finite(row.voiced_ms)?row.voiced_ms:0;
    const missing:string[]=[];
    if(end-start<5000)missing.push('비교 구간 5초 미만');
    if(voicedMs<1000||f0===null||rate===null)missing.push('음성·음높이 근거 부족');
    const point:ActivationPoint={startMs:start,endMs:end,status:'insufficient',inBaseline:false,level:null,
      label:activationLabel(null),activation:null,missing,
      evidence:{voicedMs,faceCoverage,f0Semitones:null,rateChange:null,loudnessDb:null},contributions:null,
      pulse:{count:pulses.length,bpm:pulses.length?median(pulses.map(p=>p.bpm)):null}};
    points.push(point);
    if(missing.length)return;
    point.inBaseline=start>=BASELINE_START_MS;
    qualified.push({point,f0:f0!,rate:rate!,loudness:finite(row.loudness_dbfs)?row.loudness_dbfs:null,
      eye:faceCoverage>=.5?mean(faces.map(v=>v.eyeWide)):null});
  });
  const base=qualified.filter(v=>v.point.inBaseline);
  const baseline={windowCount:base.length,required:BASELINE_MIN_WINDOWS,startsAtMs:BASELINE_START_MS};
  if(base.length<BASELINE_MIN_WINDOWS){
    for(const v of qualified)v.point.missing.push(`30초 이후 개인 기준 구간 ${BASELINE_MIN_WINDOWS}개 필요`);
    return {version:'voice-activation.v2',status:'not-enough-data',baseline,points,comparedCount:0,overall:null,
      label:'근거 부족 · 30초 이후 구간이 부족해 개인 기준을 만들지 못했습니다'};
  }
  const values=(pick:(v:Window)=>number|null)=>base.flatMap(v=>{const x=pick(v);return x===null?[]:[x];});
  const refF0=median(values(v=>v.f0)),refRate=median(values(v=>v.rate));
  const loudBase=values(v=>v.loudness),eyeBase=values(v=>v.eye);
  const refLoud=delivery?.agc_on===false&&loudBase.length>=BASELINE_MIN_WINDOWS?median(loudBase):null;
  const refEye=eyeBase.length>=BASELINE_MIN_WINDOWS?median(eyeBase):null;
  for(const v of qualified){
    const f0Semitones=12*Math.log2(v.f0/refF0),rateChange=v.rate/refRate-1;
    const loudnessDb=refLoud!==null&&v.loudness!==null?v.loudness-refLoud:null;
    const terms:[number,number][]=[[clamp(f0Semitones/4),.45],[clamp(rateChange/.25),.35]];
    if(loudnessDb!==null)terms.push([clamp(loudnessDb/6),.2]);
    const voice=terms.reduce((s,[x,w])=>s+x*w,0)/terms.reduce((s,[,w])=>s+w,0);
    const face=refEye!==null&&v.eye!==null?clamp((v.eye-refEye)/.25):null;
    const activation=face===null?voice:clamp(.9*voice+.1*face);
    const level=levelOf(activation);
    Object.assign(v.point,{status:'compared',activation,level,label:activationLabel(level),
      contributions:{voice,face},evidence:{...v.point.evidence,f0Semitones,rateChange,loudnessDb}});
  }
  const compared=qualified.map(v=>v.point);
  const duration=compared.reduce((sum,p)=>sum+p.endMs-p.startMs,0);
  const overall=compared.reduce((s,p)=>s+p.activation!*(p.endMs-p.startMs),0)/duration;
  return {version:'voice-activation.v2',status:'ok',baseline,points,comparedCount:compared.length,overall,
    label:activationLabel(levelOf(overall))};
}

// User-triggered export. Pulse estimates are not part of the end report (see
// docs/pretrained-presentation-pulse.md), and delivery measures withheld from users stay out.
export function insightsExport(sessionId:string,analysis:ActivationAnalysis,coaching:Coaching,delivery?:DeliveryMetrics){
  return {schema:'session-insights.v2',sessionId,
    method:'Rule-based voice activation relative to the speaker\'s own session baseline (windows from 30 s); not validated',
    analysis:{...analysis,points:analysis.points.map(point=>{const copy:Partial<ActivationPoint>={...point};delete copy.pulse;return copy;})},
    coaching,delivery:deliveryForUser(delivery)};
}

export type Coaching={strengths:string[];improvements:string[];nextPractice:string[]};
export function coachingFor(summary:PracticeSummary):Coaching{
  const strengths:string[]=[],improvements:string[]=[],nextPractice:string[]=[];
  if(summary.incomplete)improvements.push('일부 분석이 미완료여서 확인된 지표만 반영했습니다.');
  if(summary.gazeStatus==='disabled')improvements.push('시선 분석이 꺼져 있어 이번 시선 평가는 제공하지 않습니다.');
  else if(!finite(summary.gazeCoverageRatio)||summary.gazeCoverageRatio<.5)
    improvements.push('시선 관찰 근거가 부족합니다. 얼굴 위치와 조명을 확인한 뒤 다시 연습해 주세요.');
  else if(finite(summary.gazeAwayRatio)){
    const value=Math.round(summary.gazeAwayRatio*100);
    if(value>20){improvements.push(`유효 관찰 중 시선 이탈이 ${value}%였습니다. 대본을 확인한 뒤 카메라 방향으로 시선을 회복해 보세요.`);nextPractice.push('대본 한 문장을 읽은 뒤 카메라 방향으로 시선을 되돌리는 연습을 합니다.');}
    else strengths.push(`유효 관찰 구간의 ${100-value}%에서 시선이 보정 기준 근처에 있었습니다.`);
  }
  const rate=summary.averageSyllablesPerMinute;
  if(summary.speechStatus!=='disabled'&&finite(rate)){
    if(rate>360){improvements.push(`평균 ${Math.round(rate)}음절/분으로 현재 속도 설정 상한(360)을 넘었습니다.`);nextPractice.push('문장 끝에서 짧게 쉬며 같은 대본을 다시 읽고 속도 변화를 비교합니다.');}
    else if(rate<140){improvements.push(`평균 ${Math.round(rate)}음절/분으로 현재 속도 설정 하한(140)보다 느렸습니다.`);nextPractice.push('문장을 의미 단위로 묶어 읽고 과도하게 긴 쉼이 줄었는지 확인합니다.');}
    else strengths.push(`평균 발화 속도 ${Math.round(rate)}음절/분이 현재 설정 범위 안에 있었습니다.`);
  }else improvements.push('발화 속도를 산출할 근거가 부족하거나 기능이 꺼져 있습니다.');
  if(!['disabled','unavailable'].includes(summary.fillerStatus??'')&&summary.fillerWordCounts!==null){
    const total=Object.values(summary.fillerWordCounts).reduce((a,b)=>a+b,0);
    if(total>0){improvements.push(`받아쓰기에 남은 습관어가 ${total}회 검출됐습니다. 실제 발화보다 적게 집계될 수 있습니다.`);nextPractice.push('습관어가 나오는 구간을 짧은 무음으로 바꾸어 한 번 더 연습합니다.');}
    else strengths.push('받아쓰기에서 습관어가 검출되지 않았습니다. STT에서 생략된 표현은 포함되지 않습니다.');
  }
  if(finite(summary.scriptCompletionRatio)&&summary.scriptCompletionRatio>=.8)strengths.push(`대본 진행률 ${Math.round(summary.scriptCompletionRatio*100)}%를 확인했습니다.`);
  if(!nextPractice.length)nextPractice.push('같은 대본으로 한 번 더 연습하고 시선·속도·습관어 결과를 비교합니다.');
  return {strengths:strengths.slice(0,3),improvements:improvements.slice(0,4),nextPractice:nextPractice.slice(0,3)};
}
