import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import * as signal from '../src/features/pulse/signal.ts';
import * as regions from '../src/features/pulse/regions.ts';
import * as faceFeatures from '../src/features/face-features/features.ts';

test('real worker feeds a smaller, moderately tilted face to the model instead of rejecting all frames',async()=>{
  const face=Array.from({length:478},()=>({x:.5,y:.5}));
  for(const [i,x,y] of [[33,.43,.43],[263,.57,.5],[10,.5,.22],[168,.5,.44],
    [50,.43,.58],[101,.46,.57],[280,.57,.58],[330,.54,.57],[1,.56,.51]]) face[i]={x,y};
  const replies=[];
  class Canvas {
    constructor(w,h){this.width=w;this.height=h;}
    getContext(){return {drawImage(){},getImageData(_x,_y,w,h){
      const data=new Uint8ClampedArray(w*h*4);data.fill(120);return {data};
    }};}
  }
  const self={PulseSignal:signal,PulseRegions:regions,FaceFeatures:faceFeatures,postMessage(message){replies.push(message);}};
  const context=vm.createContext({self,importScripts(){},OffscreenCanvas:Canvas,Vision:{
    FilesetResolver:{forVisionTasks:async()=>({})},
    FaceLandmarker:{createFromOptions:async()=>({detectForVideo(){return {faceLandmarks:[face]};}})},
  }});
  vm.runInContext(await readFile(new URL('../public/pulse-worker.js',import.meta.url),'utf8'),context);
  await self.onmessage({data:{type:'init',mode:'efficientphys',profile:{name:'TS-CAN · MA-UBFC-rPPG',size:72,durationMs:3000,outputs:90}}});
  for(let i=0;i<125;i++) await self.onmessage({data:{type:'frame',time:i*1000/30,bitmap:{width:640,height:480,close(){}},epoch:0}});
  assert.ok(replies.some(v=>v.type==='neural-chunk'),'usable smaller face never reached real model API');
  const result=replies.filter(v=>v.type==='result').at(-1).result;
  assert.ok(result.diagnostics.acceptedFrames>100);
  assert.equal(result.bpm,null,'no model response was supplied; never invent a number');
  assert.ok(result.diagnostics.faceAssessment.warning);
  assert.ok(result.diagnostics.faceAssessment.eyePixels<48);
});

test('shared worker extracts real-shaped coefficients while pulse is off; face loss clears current values',async()=>{
  const face=Array.from({length:478},(_,i)=>({x:i%2?.3:.7,y:i%3?.3:.7}));
  const categories=faceFeatures.blendshapeNames.map(categoryName=>({categoryName,score:categoryName==='jawOpen'?.6:.1}));
  let faces=[face], options;
  const replies=[];
  class Canvas {
    constructor(w,h){this.width=w;this.height=h;}
    getContext(){return {drawImage(){},getImageData(_x,_y,w,h){const data=new Uint8ClampedArray(w*h*4);data.fill(120);return {data};}};}
  }
  const self={PulseSignal:signal,PulseRegions:regions,FaceFeatures:faceFeatures,postMessage(message){replies.push(message);}};
  const context=vm.createContext({self,importScripts(){},OffscreenCanvas:Canvas,Vision:{
    FilesetResolver:{forVisionTasks:async()=>({})},
    FaceLandmarker:{createFromOptions:async(_resolver,input)=>{options=input;
      if(input.baseOptions.delegate==='GPU') throw new Error('GPU not available');
      return {detectForVideo(){return {faceLandmarks:faces,faceBlendshapes:[{categories}]};}};}},
  }});
  vm.runInContext(await readFile(new URL('../public/pulse-worker.js',import.meta.url),'utf8'),context);
  await self.onmessage({data:{type:'init',mode:'efficientphys',featuresEnabled:true,pulseEnabled:false}});
  for(let i=0;i<35;i++) await self.onmessage({data:{type:'frame',time:i*100,sessionTimeMs:5000+i*100,bitmap:{width:640,height:480,close(){}},epoch:0}});
  assert.equal(options.outputFaceBlendshapes,true);
  assert.equal(options.outputFacialTransformationMatrixes,true);
  const observed=replies.filter(v=>v.type==='face-features').at(-1).result;
  assert.equal(observed.status,'observed'); assert.equal(observed.coefficients.jawOpen,.6);
  assert.equal(observed.delegate,'CPU','GPU initialization failure falls back to real CPU inference');
  assert.equal(Object.keys(observed.coefficients).length,52);
  assert.equal(observed.timestampMs,8400);
  assert.equal(replies.some(v=>v.type==='neural-chunk'),false);
  faces=[];
  await self.onmessage({data:{type:'frame',time:3600,sessionTimeMs:8600,bitmap:{width:640,height:480,close(){}},epoch:0}});
  const missing=replies.filter(v=>v.type==='face-features').at(-1).result;
  assert.equal(missing.status,'unavailable'); assert.equal(missing.coefficients,null);
});

// Loads the real worker with a fake FaceLandmarker; `detect(delegate, stamp)` stands in for detectForVideo.
async function loadWorker(detect, {failCreate = () => false} = {}) {
  const replies = [], created = [], stamps = [];
  class Canvas {
    constructor(w,h){this.width=w;this.height=h;}
    getContext(){return {drawImage(){},getImageData(_x,_y,w,h){const data=new Uint8ClampedArray(w*h*4);data.fill(120);return {data};}};}
  }
  const self={PulseSignal:signal,PulseRegions:regions,FaceFeatures:faceFeatures,postMessage(message){replies.push(message);}};
  const context=vm.createContext({self,importScripts(){},OffscreenCanvas:Canvas,Vision:{
    FilesetResolver:{forVisionTasks:async()=>({})},
    FaceLandmarker:{createFromOptions:async(_resolver,input)=>{
      const delegate=input.baseOptions.delegate; created.push(delegate);
      if(failCreate(delegate)) throw new Error(`${delegate} not available`);
      return {close(){},detectForVideo(_image,stamp){
        if(stamps.length && stamp<=stamps.at(-1).stamp) throw new Error('timestamps must increase');
        stamps.push({delegate,stamp,ready:replies.some(v=>v.type==='ready')});
        return detect(delegate,stamp);
      }};
    }},
  }});
  vm.runInContext(await readFile(new URL('../public/pulse-worker.js',import.meta.url),'utf8'),context);
  return {self, replies, created, stamps};
}
const busyWait = ms => { const end = Date.now() + ms; while (Date.now() < end); };

test('init warms the detector up before ready, and a real first frame at mediaTime 0 still detects', async () => {
  const {self, replies, stamps} = await loadWorker(() => ({faceLandmarks: [], faceBlendshapes: []}));
  await self.onmessage({data:{type:'init',mode:'pos',featuresEnabled:true,pulseEnabled:false}});
  const warmups = stamps.filter(v => !v.ready);
  assert.ok(warmups.length >= 1 && warmups.length <= 2, 'one or two warm-up detects during init');
  assert.equal(replies.at(-1).type, 'ready');
  assert.equal(replies.at(-1).delegate, 'GPU');
  await self.onmessage({data:{type:'frame',time:0,sessionTimeMs:0,bitmap:{width:640,height:480,close(){}},epoch:0}});
  assert.equal(stamps.filter(v => v.ready).length, 1, 'the real frame reached the detector');
  assert.equal(replies.some(v => v.type === 'face-features-error'), false);
  assert.equal(replies.at(-1).type, 'ack');
});

test('a GPU delegate that stays slow after warm-up is replaced by CPU before ready', async () => {
  const {self, replies, created} = await loadWorker(delegate => {
    if (delegate === 'GPU') busyWait(300);
    return {faceLandmarks: [], faceBlendshapes: []};
  });
  await self.onmessage({data:{type:'init',mode:'pos',featuresEnabled:true,pulseEnabled:false}});
  assert.deepEqual(created, ['GPU', 'CPU']);
  assert.equal(replies.at(-1).type, 'ready');
  assert.equal(replies.at(-1).delegate, 'CPU');
});

test('a warm-up failure on GPU falls back to CPU; a CPU failure reports the existing error', async () => {
  const gpuBroken = await loadWorker(delegate => { if (delegate === 'GPU') throw new Error('shader'); return {faceLandmarks: []}; });
  await gpuBroken.self.onmessage({data:{type:'init',mode:'pos',featuresEnabled:true,pulseEnabled:false}});
  assert.equal(gpuBroken.replies.at(-1).delegate, 'CPU');
  const allBroken = await loadWorker(() => { throw new Error('wasm'); });
  await allBroken.self.onmessage({data:{type:'init',mode:'pos',featuresEnabled:true,pulseEnabled:false}});
  assert.equal(allBroken.replies.at(-1).type, 'error');
});

test('the hook can ask a fresh worker for CPU only after a hung GPU frame', async () => {
  const {self, replies, created} = await loadWorker(() => ({faceLandmarks: []}));
  await self.onmessage({data:{type:'init',mode:'pos',featuresEnabled:true,pulseEnabled:false,delegate:'CPU'}});
  assert.deepEqual(created, ['CPU']);
  assert.equal(replies.at(-1).delegate, 'CPU');
});
