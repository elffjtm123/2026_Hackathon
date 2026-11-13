import type {FaceFeatures} from '../face-features/features';
import type {PulseResult} from '../pulse/signal';
import type {DeliveryMetrics, DeliveryRow} from '../delivery/metrics';
import type {PracticeSummary} from '../../lib/realtimeProtocol';

export type FaceSample = {time:number; smile:number; frown:number; brow:number; eyeWide:number};
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
    const sample={time:t,smile:pair(c,'mouthSmile'),frown:pair(c,'mouthFrown'),
      brow:pair(c,'browDown'),eyeWide:pair(c,'eyeWide')};
    if(!Object.values(sample).every(finite))return;
    this.lastFace=t;this.data.faces.push(sample);this.data.faces=this.data.faces.slice(-20000);
  }
  pulse(result:PulseResult,now:number){
    const age=result.ageSeconds??result.diagnostics?.resultAgeSeconds;
    const key=[result.model,result.diagnostics?.resets,result.modelWindows].join(':');
    if(result.status!=='observed'||result.held||result.ended||!finite(result.bpm)||!finite(age)
      ||age<0||age>6.5||!finite(result.modelWindows)||key===this.lastPulse)return;
    this.lastPulse=key;this.data.pulses.push({time:now-age*1000,bpm:result.bpm});
    this.data.pulses=this.data.pulses.slice(-7200);
  }
  snapshot():SessionSignals{return {faces:[...this.data.faces],pulses:[...this.data.pulses]};}
}

export type AffectPoint={startMs:number;endMs:number;status:'baseline'|'estimated'|'insufficient';
  label:string;valence:number|null;arousal:number|null;missing:string[];
  evidence:{faceCoverage:number;pulseCount:number;pulseBpm:number|null;f0:number|null;loudness:number|null;rate:number|null};
  contributions?:{pulse:number;voice:number;face:number}};
export type AffectAnalysis={version:'circumplex-rules.v1';points:AffectPoint[];baselineCount:number;
  estimatedCount:number;coverage:number;dominant:string;overall:{valence:number;arousal:number}|null};

export function affectLabel(valence:number,arousal:number):string{
  if(Math.abs(valence)<.2||Math.abs(arousal)<.2)return '중립·혼합 경향';
  if(arousal>=.2)return valence>=.2?'활기·기대 경향':'긴장·불편 경향';
  return valence>=.2?'차분·편안 경향':'저활성·불편 경향';
}

export function analyzeAffect(signals:SessionSignals,delivery?:DeliveryMetrics):AffectAnalysis{
  const rows=delivery?.windows?.windows??[];
  const points:AffectPoint[]=[], baselines:{pulse:number;f0:number;rate:number;loudness:number|null;alpha:number|null;eye:number}[]=[];
  for(const row of rows){
    const start=row.start_ms,end=Math.min(row.end_ms??0,(row.start_ms??0)+(row.observed_ms??0));
    if(!finite(start)||!finite(end)||end<=start)continue;
    const faces=signals.faces.filter(v=>v.time>=start&&v.time<end);
    const pulses=signals.pulses.filter(v=>v.time>=start&&v.time<end);
    // 200 ms sampling buckets avoid overstating coverage from clustered frames.
    const buckets=new Set(faces.map(v=>Math.floor((v.time-start)/200)));
    const faceCoverage=Math.min(1,buckets.size*200/(end-start));
    const f0=finite(row.f0_median_hz)?row.f0_median_hz:null, rate=finite(row.articulation_rate)?row.articulation_rate:null;
    const loudness=finite(row.loudness_dbfs)?row.loudness_dbfs:null;
    const missing:string[]=[];
    if(end-start<5000)missing.push('비교 구간 5초 미만');
    if(faceCoverage<.5)missing.push('표정 유효 관찰 50% 미만');
    if(!pulses.length)missing.push('해당 구간의 새 맥박 추정 없음');
    if((row.voiced_ms??0)<1000||f0===null||f0<=0||rate===null||rate<=0)missing.push('음성·음높이 근거 부족');
    const point:AffectPoint={startMs:start,endMs:end,status:'insufficient',label:'판단 보류',valence:null,arousal:null,missing,
      evidence:{faceCoverage,pulseCount:pulses.length,pulseBpm:pulses.length?median(pulses.map(p=>p.bpm)):null,f0,loudness,rate}};
    if(missing.length){points.push(point);continue;}
    const current={pulse:point.evidence.pulseBpm!,f0:f0!,rate:rate!,loudness,
      alpha:finite(row.alpha_ratio_db)?row.alpha_ratio_db:null,eye:mean(faces.map(v=>v.eyeWide))};
    if(baselines.length<3){
      // Only complete 10 s slots establish the initial personal comparison reference.
      if(end-start<9500){point.missing.push('기준 구간은 완전한 10초 필요');points.push(point);continue;}
      baselines.push(current);point.status='baseline';point.label='개인 비교 기준 수집';points.push(point);continue;
    }
    const reference=(key:'pulse'|'f0'|'rate'|'eye')=>median(baselines.map(v=>v[key]));
    const pulse=clamp((current.pulse-reference('pulse'))/15);
    const voiceTerms:[number,number][]=[
      [clamp(12*Math.log2(current.f0/reference('f0'))/4),.45],
      [clamp((current.rate/reference('rate')-1)/.25),.35],
    ];
    const baseLoud=baselines.flatMap(v=>v.loudness===null?[]:[v.loudness]);
    if(delivery?.agc_on===false&&loudness!==null&&baseLoud.length===3)voiceTerms.push([clamp((loudness-median(baseLoud))/6),.2]);
    const voice=voiceTerms.reduce((s,[v,w])=>s+v*w,0)/voiceTerms.reduce((s,[,w])=>s+w,0);
    const face=clamp((current.eye-reference('eye'))/.25);
    const valence=clamp(1.6*mean(faces.map(v=>v.smile-v.frown))-.25*mean(faces.map(v=>v.brow)));
    const arousal=clamp(.45*pulse+.45*voice+.1*face);
    point.status='estimated';point.valence=valence;point.arousal=arousal;point.label=affectLabel(valence,arousal);
    point.contributions={pulse,voice,face};points.push(point);
  }
  const estimated=points.filter(v=>v.status==='estimated');
  const duration=estimated.reduce((sum,p)=>sum+p.endMs-p.startMs,0);
  const overall=duration?{valence:estimated.reduce((s,p)=>s+p.valence!*(p.endMs-p.startMs),0)/duration,
    arousal:estimated.reduce((s,p)=>s+p.arousal!*(p.endMs-p.startMs),0)/duration}:null;
  const counts=new Map<string,number>();for(const p of estimated)counts.set(p.label,(counts.get(p.label)??0)+p.endMs-p.startMs);
  const order=[...counts].sort((a,b)=>b[1]-a[1]);
  const dominant=order.length?(order[1]?.[1]===order[0][1]?'여러 경향 혼재':order[0][0]):'측정 근거 부족';
  return {version:'circumplex-rules.v1',points,baselineCount:baselines.length,estimatedCount:estimated.length,
    coverage:points.length?estimated.length/points.length:0,dominant,overall};
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
