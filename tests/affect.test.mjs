import assert from 'node:assert/strict';
import test, {after} from 'node:test';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';
import {SessionSignalRecorder,analyzeActivation,coachingFor,insightsExport} from '../src/features/affect/analysis.ts';
import {deliveryForUi} from '../src/features/delivery/metrics.ts';
import {completionForUi,summaryForUi} from '../src/lib/realtimeProtocol.ts';

// Words that name an emotion or inner state. Nothing user-visible may contain them.
const STATE_WORDS=/긴장|불안|불편|편안|활기|기대 경향|차분|저활성|쾌|감정|스트레스|정서/;

// n 10 s windows; f0(i), rate(i), loudness(i) and pulse(i) describe each window.
function session({n=8,f0=()=>200,rate=()=>240,loudness=()=>-25,pulse=()=>80,eye=()=>.1,agc_on=false}={}){
 const signals={faces:[],pulses:[]},windows=[];
 for(let i=0;i<n;i++){
  for(let t=i*10000;t<(i+1)*10000;t+=200)signals.faces.push({time:t,smile:.3,frown:.1,brow:.1,eyeWide:eye(i)});
  signals.pulses.push({time:i*10000+5000,bpm:pulse(i)});
  windows.push({start_ms:i*10000,end_ms:(i+1)*10000,observed_ms:10000,voiced_ms:5000,
   f0_median_hz:f0(i),articulation_rate:rate(i),loudness_dbfs:loudness(i)});
 }
 return {signals,metrics:{status:'unavailable',agc_on,report:{total_voiced_ms:n*5000,sentences:[],baseline:{},bursts:[]},windows:{window_ms:10000,baseline:{},windows}}};
}

test('the personal baseline uses only windows starting at or after 30 s, so a low-pitched opening does not lift later windows',()=>{
 // Opening 30 s is about 3 semitones lower; everything afterwards is the speaker's steady voice.
 const {signals,metrics}=session({f0:i=>i<3?170:200});
 const result=analyzeActivation(signals,metrics);
 assert.equal(result.status,'ok');
 assert.equal(result.baseline.windowCount,5);
 assert.deepEqual(result.points.map(p=>p.inBaseline),[false,false,false,true,true,true,true,true]);
 assert.ok(result.points.slice(3).every(p=>p.status==='compared'&&p.level==='similar'&&Math.abs(p.activation)<1e-9));
 assert.ok(result.points.slice(0,3).every(p=>p.level==='lower'));
});

test('a session without enough windows after 30 s reports not-enough-data instead of a number',()=>{
 const {signals,metrics}=session({n:5});
 const result=analyzeActivation(signals,metrics);
 assert.equal(result.status,'not-enough-data');
 assert.equal(result.baseline.windowCount,2);
 assert.equal(result.overall,null);
 assert.equal(result.comparedCount,0);
 assert.ok(result.points.every(p=>p.activation===null&&p.level===null));
 assert.match(result.label,/근거 부족/);
});

test('activation follows voice relative to the baseline; pulse is reference only and never moves it',()=>{
 const steady=session({n:8,pulse:i=>i===7?130:80});
 const a=analyzeActivation(steady.signals,steady.metrics).points.at(-1);
 assert.equal(a.activation,0);assert.equal(a.level,'similar');
 assert.equal(a.pulse.bpm,130);
 const noPulse=session({n:8});noPulse.signals.pulses=[];
 assert.equal(analyzeActivation(noPulse.signals,noPulse.metrics).status,'ok');
 const louder=session({n:8,f0:i=>i===7?260:200,rate:i=>i===7?320:240,loudness:i=>i===7?-19:-25});
 const high=analyzeActivation(louder.signals,louder.metrics).points.at(-1);
 assert.equal(high.level,'higher');assert.ok(high.activation>.5);
 assert.equal(high.label,'본인 기준보다 목소리 활성도가 높음');
 const quieter=session({n:8,f0:i=>i===7?150:200,rate:i=>i===7?180:240});
 assert.equal(analyzeActivation(quieter.signals,quieter.metrics).points.at(-1).label,'본인 기준보다 목소리 활성도가 낮음');
});

test('AGC-on or unreported gain excludes loudness from activation',()=>{
 for(const agc_on of [true,null]){
  const {signals,metrics}=session({agc_on,loudness:i=>i===7?-5:-25});
  const point=analyzeActivation(signals,metrics).points.at(-1);
  assert.equal(point.activation,0);assert.equal(point.evidence.loudnessDb,null);
 }
});

test('missing face observations drop only the small face term; missing voice withholds the window',()=>{
 const {signals,metrics}=session({eye:i=>i===7?.6:.1});
 const withFace=analyzeActivation(signals,metrics).points.at(-1);
 assert.ok(withFace.activation>0&&withFace.activation<=.1+1e-9);
 signals.faces=[];
 const noFace=analyzeActivation(signals,metrics);
 assert.equal(noFace.status,'ok');assert.equal(noFace.points.at(-1).activation,0);
 metrics.windows.windows[7]={...metrics.windows.windows[7],voiced_ms:500,f0_median_hz:null};
 const point=analyzeActivation(signals,metrics).points.at(-1);
 assert.equal(point.status,'insufficient');assert.equal(point.activation,null);
});

test('no label anywhere in the analysis names an emotion or state',()=>{
 for(const f0 of [()=>200,i=>i===7?300:200,i=>i===7?120:200]){
  const {signals,metrics}=session({f0});const result=analyzeActivation(signals,metrics);
  assert.doesNotMatch(JSON.stringify(result),STATE_WORDS);
 }
 const short=session({n:3});assert.doesNotMatch(JSON.stringify(analyzeActivation(short.signals,short.metrics)),STATE_WORDS);
});

test('a partial first window is aligned to the end of its slot, where its observations actually are',()=>{
 // Observation began at 4 s, so the first slot covers 4–10 s (observed_ms 6000), not 0–6 s.
 const {signals,metrics}=session();
 metrics.windows.windows[0].observed_ms=6000;
 signals.faces=signals.faces.filter(f=>f.time>=4000);
 signals.pulses[0].time=8000;
 const first=analyzeActivation(signals,metrics).points[0];
 assert.equal(first.startMs,4000);assert.equal(first.endMs,10000);
 assert.ok(first.evidence.faceCoverage>.95);
 assert.equal(first.pulse.count,1);
 // A partial last window keeps its observations at the start of the slot.
 metrics.windows.windows[7].observed_ms=3000;
 const last=analyzeActivation(signals,metrics).points.at(-1);
 assert.equal(last.startMs,70000);assert.equal(last.endMs,73000);
});

test('a slot with nothing observed is withheld rather than producing a NaN window',()=>{
 const {signals,metrics}=session();
 metrics.windows.windows[0].observed_ms=0;
 metrics.windows.windows[7].observed_ms=0;
 const points=analyzeActivation(signals,metrics).points;
 assert.equal(points.length,6);
 assert.deepEqual(points.map(p=>p.startMs),[10000,20000,30000,40000,50000,60000]);
 for(const p of points)assert.ok(Number.isFinite(p.evidence.faceCoverage));
});

test('the insights export carries no pulse values and no withheld voice measures',()=>{
 const {signals,metrics}=session();
 metrics.windows.windows=metrics.windows.windows.map(w=>({...w,pvq:.1,alpha_ratio_db:3,hammarberg_db:9,loudness_rel_db:1}));
 const analysis=analyzeActivation(signals,metrics);
 const json=JSON.stringify(insightsExport('s1',analysis,coachingFor({incomplete:false,fillerWordCounts:null}),metrics));
 assert.doesNotMatch(json,/bpm|pulse|맥박/i);
 assert.doesNotMatch(json,/pvq|loudness_dbfs|alpha_ratio|hammarberg/);
 assert.match(json,/loudness_rel_db/);
 assert.doesNotMatch(json,STATE_WORDS);
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

const cacheDir=await mkdtemp(join(tmpdir(),'affect-vite-'));
const server=await createServer({configFile:false,cacheDir,esbuild:{jsx:'automatic'},
 server:{middlewareMode:true,hmr:false,ws:false,watch:null},optimizeDeps:{noDiscovery:true}});
after(async()=>{await server.close();await rm(cacheDir,{recursive:true,force:true});});
const summaryFor=metrics=>({sessionId:'s1',durationSeconds:80,incomplete:false,transcript:null,pronunciationAccuracy:null,
 speechPaceWarningCount:null,averageSyllablesPerMinute:null,fillerWordCounts:null,gazeAwayRatio:null,deliveryMetrics:metrics});

test('session insights describe voice activation relative to the speaker and mark pulse as unverified reference',async()=>{
 const {SessionInsights}=await server.ssrLoadModule('/src/features/affect/SessionInsights.tsx');
 const {signals,metrics}=session({f0:i=>i===7?260:200});
 const html=renderToStaticMarkup(createElement(SessionInsights,{summary:summaryFor(metrics),signals}));
 assert.match(html,/목소리 활성도/);
 assert.match(html,/참고용·미검증/);
 assert.match(html,/30초/);
 assert.doesNotMatch(html,STATE_WORDS);
 const short=session({n:4});
 const empty=renderToStaticMarkup(createElement(SessionInsights,{summary:summaryFor(short.metrics),signals:short.signals}));
 assert.match(empty,/근거 부족/);
 assert.doesNotMatch(empty,STATE_WORDS);
});

test('browser POS estimates are each recorded, so the pulse trend survives a fallback from the model',()=>{
 const recorder=new SessionSignalRecorder();
 // POS never runs model windows; each new estimate comes from new camera frames.
 const pos={status:'observed',bpm:82,model:'POS',modelWindows:0,ageSeconds:0,diagnostics:{resets:0,totalFrames:300}};
 recorder.pulse(pos,1000);recorder.pulse(pos,1100);
 recorder.pulse({...pos,bpm:84,diagnostics:{resets:0,totalFrames:310}},2000);
 recorder.pulse({...pos,bpm:85,diagnostics:{resets:0,totalFrames:320}},3000);
 assert.deepEqual(recorder.snapshot().pulses.map(p=>p.bpm),[82,84,85]);
});
