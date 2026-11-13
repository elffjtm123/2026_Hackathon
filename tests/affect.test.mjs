import assert from 'node:assert/strict';
import test from 'node:test';
import {SessionSignalRecorder,analyzeAffect,coachingFor} from '../src/features/affect/analysis.ts';
import {deliveryForUi} from '../src/features/delivery/metrics.ts';
import {completionForUi,summaryForUi} from '../src/lib/realtimeProtocol.ts';

function data({high=true,positive=true}={}){
 const signals={faces:[],pulses:[]},windows=[];
 for(let i=0;i<4;i++){
  for(let t=i*10000;t<(i+1)*10000;t+=200)signals.faces.push({time:t,smile:positive?.6:.02,frown:positive?.02:.6,brow:.1,eyeWide:.1});
  signals.pulses.push({time:i*10000+5000,bpm:i<3?80:high?100:60});
  windows.push({start_ms:i*10000,end_ms:(i+1)*10000,observed_ms:10000,voiced_ms:5000,
   f0_median_hz:i<3?200:high?260:150,articulation_rate:i<3?240:high?320:180,loudness_dbfs:i<3?-25:high?-19:-31});
 }
 return {signals,metrics:{status:'unavailable',agc_on:false,report:{total_voiced_ms:20000,sentences:[],baseline:{},bursts:[]},windows:{window_ms:10000,baseline:{},windows}}};
}
test('three complete personal-reference windows precede every combined estimate; four quadrant directions are explicit',()=>{
 for(const [high,positive,label] of [[true,true,'활기·기대 경향'],[true,false,'긴장·불편 경향'],[false,true,'차분·편안 경향'],[false,false,'저활성·불편 경향']]){
  const {signals,metrics}=data({high,positive});const result=analyzeAffect(signals,metrics);
  assert.equal(result.baselineCount,3);assert.equal(result.estimatedCount,1);assert.equal(result.dominant,label);
  assert.ok(result.points.slice(0,3).every(p=>p.status==='baseline'&&p.arousal===null));
 }
});
test('missing contemporaneous physiology or face observations withholds classification instead of filling zeros',()=>{
 const {signals,metrics}=data();signals.pulses=[];
 const result=analyzeAffect(signals,metrics);assert.equal(result.estimatedCount,0);assert.equal(result.overall,null);
 assert.ok(result.points.every(p=>p.missing.includes('해당 구간의 새 맥박 추정 없음')));
 const partial=data();partial.signals.faces=partial.signals.faces.filter(p=>p.time%10000<2000);
 assert.equal(analyzeAffect(partial.signals,partial.metrics).estimatedCount,0);
});
test('AGC-on or unreported gain excludes loudness; constant pitch/rate/pulse cannot imply higher arousal from gain alone',()=>{
 for(const agc_on of [true,null]){
  const {signals,metrics}=data();metrics.agc_on=agc_on;
  metrics.windows.windows[3]={...metrics.windows.windows[0],start_ms:30000,end_ms:40000,loudness_dbfs:-5};
  signals.pulses.at(-1).bpm=80;
  assert.equal(analyzeAffect(signals,metrics).points.at(-1).arousal,0);
 }
});
test('replayed, provisional, ended and held BPM are excluded from multimodal recordings',()=>{
 const recorder=new SessionSignalRecorder();
 const result={status:'observed',bpm:80,model:'test',modelWindows:12,ageSeconds:.5,diagnostics:{resets:0}};
 recorder.pulse(result,1000);recorder.pulse(result,1500);
 recorder.pulse({...result,held:true,modelWindows:13},2000);
 recorder.pulse({...result,status:'provisional',modelWindows:13},2000);
 recorder.pulse({...result,ended:true,modelWindows:13},2000);
 assert.equal(recorder.snapshot().pulses.length,1);
 assert.equal(recorder.snapshot().pulses[0].time,500);recorder.reset();assert.equal(recorder.snapshot().pulses.length,0);
});
test('short partial time slots are not treated as complete calibration windows',()=>{
 const {signals,metrics}=data();metrics.windows.windows[0].observed_ms=3000;
 assert.equal(analyzeAffect(signals,metrics).estimatedCount,0);
});
test('final coaching distinguishes missing measurements from measured zero and produces actionable targets',()=>{
 const absent={incomplete:true,gazeCoverageRatio:0,gazeAwayRatio:null,speechStatus:'unavailable',averageSyllablesPerMinute:null,fillerWordCounts:null};
 const missing=coachingFor(absent);assert.equal(missing.strengths.length,0);assert.match(missing.improvements.join(' '),/부족/);
 const value=coachingFor({...absent,incomplete:false,gazeCoverageRatio:.9,gazeAwayRatio:.4,speechStatus:'observed',averageSyllablesPerMinute:400,fillerWordCounts:{음:3}});
 assert.equal(value.nextPractice.length,3);assert.match(value.improvements.join(' '),/3회/);assert.match(value.improvements.join(' '),/400/);
});
test('delivery result survives both UI mappings; nonfinite values remain missing, measured zeros remain zero',()=>{
 const parsed=deliveryForUi({status:'unavailable',agc_on:false,report:{total_voiced_ms:1500,sentences:[{pause_count:0,pvq:NaN}]},windows:{windows:[]}});
 assert.equal(parsed.report.sentences[0].pause_count,0);assert.equal(parsed.report.sentences[0].pvq,null);
 const report=completionForUi({delivery_metrics:parsed});const summary=summaryForUi('x',report,1,null);
 assert.deepEqual(summary.deliveryMetrics,parsed);
});
