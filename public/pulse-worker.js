/* Full frames stay here. EfficientPhys sends 72x72 RGB crops to loopback only. */
/* global Vision */
importScripts('/pulse-assets/vision_bundle.js', '/pulse-assets/signal.js', '/pulse-assets/regions.js', '/pulse-assets/face-features.js');
const { PulseBuffer, estimatePulse, emptyPulse, estimateNeuralPulse, mergeNeuralWindow, PulseSmoother } = self.PulseSignal;
const { pulseRegions, FaceCropTracker } = self.PulseRegions;
const faceCropTracker = new FaceCropTracker();
const featureTracker = new self.FaceFeatures.FaceFeatureTracker();
let featuresEnabled = false, pulseEnabled = true, featureDelegate = 'CPU', lastFeatureDisplay = -Infinity, detectionCost = 0;
let faceAssessment = null;
const buffer = new PulseBuffer();
let detector, previous, lastAnalysis = -Infinity, lastDisplay = -Infinity, lastResult = emptyPulse(), epoch = 0;
let totalFrames = 0, acceptedFrames = 0, frameTimes = [], boxes = [], lightLevel = null, frameTime = 0;
let cachedFaces = [], lastDetection = -Infinity;
let mode = 'pos', segment = 0, neuralBusy = false, crops = [], wave = [], neuralWindows = 0;
let lastInference = null, lastFrameAccepted = -Infinity;
let lastNeuralAttempt = -Infinity;
let profile = {name:'EfficientPhys · UBFC-rPPG', size:72, durationMs:3000, outputs:90};
let resets = 0, resetReason = '', lastOutputTime = null, updateSeconds = null;
const smoother = new PulseSmoother();
const canvas = new OffscreenCanvas(320, 240);
const ctx = canvas.getContext('2d', {willReadFrequently: true});
const cropCanvas = new OffscreenCanvas(72,72), cropContext = cropCanvas.getContext('2d',{willReadFrequently:true});

function clearNeural(reason = '영상 수집 재시작') {
  if (crops.length || wave.length) { resets++; resetReason = reason; }
  segment++; crops = []; wave = []; neuralWindows = 0; lastInference = null;
  smoother.reset(); lastResult = emptyPulse(reason); lastOutputTime = null; updateSeconds = null;
  neuralBusy = false; lastFrameAccepted = -Infinity;
  self.postMessage({type:'neural-reset',segment,epoch});
}

function diagnostics() {
  const span = (frameTimes.at(-1) - frameTimes[0]) / 1000;
  return {inputFps: span > 0 ? (frameTimes.length - 1) / span : 0, totalFrames, acceptedFrames,
    regions: boxes, light: lightLevel, green: buffer.samples.slice(-90).map(v => v.regions[0][1]),
    resets, resetReason, resultAgeSeconds: wave.length ? Math.max(0,(frameTime-wave.at(-1).time)/1000) : null, updateSeconds,
    captureSeconds: crops.length>1 ? (crops.at(-1).time-crops[0].time)/1000 : 0,
    faceAssessment: faceAssessment ? {eyePixels:faceAssessment.eyePixels,faceWidth:faceAssessment.faceWidth,faceHeight:faceAssessment.faceHeight,warning:faceAssessment.warning,reason:faceAssessment.reason} : null};
}

function display(result) {
  if (mode === 'efficientphys' && result.bpm !== null && frameTime-(wave.at(-1)?.time??-Infinity)>6500) {
    result={...result,bpm:null,status:'unreliable',reason:'맥박 모델 결과 갱신이 늦어 이전 수치를 숨깁니다.'};
  }
  self.postMessage({type: 'result', epoch, result: {...result, model: mode === 'efficientphys' ? profile.name : 'POS',
    runtime: mode === 'efficientphys' ? 'ONNX Runtime CPU' : '브라우저 신호 처리',
    inferenceMs: lastInference, modelWindows: neuralWindows, diagnostics: diagnostics()}});
  lastDisplay = frameTime;
}
function reject(reason, hard = false) {
  if (mode === 'efficientphys' && (hard || frameTime-lastFrameAccepted>250) && (crops.length || wave.length)) clearNeural(reason);
  if (hard || frameTime - (buffer.samples.at(-1)?.time ?? -Infinity) > 250) buffer.reset();
  lastResult = {...emptyPulse(reason), status: 'unreliable',
    seconds: buffer.samples.length > 1 ? (buffer.samples.at(-1).time - buffer.samples[0].time) / 1000 : 0};
  if (frameTime - lastDisplay >= 250) display(lastResult);
}

function patch(region, pixels, width, height) {
  if (!region.valid) return null;
  const x1 = Math.round(region.x * width), x2 = x1 + Math.round(region.width * width);
  const y1 = Math.round(region.y * height), y2 = y1 + Math.round(region.height * height);
  const mean = [0, 0, 0]; let count = 0, clipped = 0;
  // No fixed skin-colour threshold: anatomical regions, all RGB samples retained.
  for (let y = y1; y < y2; y++) for (let x = x1; x < x2; x++) {
    const at = (y * width + x) * 4;
    const r = pixels[at], g = pixels[at + 1], b = pixels[at + 2];
    mean[0] += r; mean[1] += g; mean[2] += b;
    if (Math.min(r, g, b) < 4 || Math.max(r, g, b) > 251) clipped++;
    count++;
  }
  return {rgb: mean.map(v => v / count), clipping: clipped / count};
}

self.onmessage = async ({data}) => {
  if (data.type === 'init') {
    mode = data.mode ?? 'pos';
    featuresEnabled = data.featuresEnabled === true; pulseEnabled = data.pulseEnabled !== false;
    if (data.profile) profile = data.profile;
    cropCanvas.width = cropCanvas.height = profile.size;
    try {
      const files = await Vision.FilesetResolver.forVisionTasks('/pulse-assets/wasm');
      const createDetector = delegate => Vision.FaceLandmarker.createFromOptions(files, {
          baseOptions: {modelAssetPath: '/pulse-assets/face_landmarker.task', delegate},
          runningMode: 'VIDEO', numFaces: 2, minFaceDetectionConfidence: 0.65,
          minFacePresenceConfidence: 0.65, minTrackingConfidence: 0.65,
          outputFaceBlendshapes: featuresEnabled, outputFacialTransformationMatrixes: featuresEnabled,
        });
      featureDelegate = featuresEnabled ? 'GPU' : 'CPU';
      try { detector = await createDetector(featureDelegate); }
      catch (error) {
        if (featureDelegate !== 'GPU') throw error;
        featureDelegate = 'CPU'; detector = await createDetector('CPU');
      }
      self.postMessage({type: 'ready'});
    } catch { self.postMessage({type: 'error', message: '얼굴 모델 준비 실패 · npm run prepare:pulse-assets와 브라우저 WebGL 지원을 확인해 주세요.'}); }
    return;
  }
  if (data.type === 'pulse-enabled') {
    pulseEnabled = data.enabled === true;
    if (!pulseEnabled) { clearNeural('맥박 분석 중지'); buffer.reset(); }
    return;
  }
  if (data.type === 'reset') {
    featureTracker.interrupt();
    epoch = data.epoch ?? 0; buffer.reset(); previous = undefined; lastResult = emptyPulse(); faceCropTracker.reset(); faceAssessment=null;
    lastAnalysis = lastDisplay = -Infinity; frameTimes = []; boxes = []; lightLevel = null;
    totalFrames = acceptedFrames = 0; cachedFaces = []; lastDetection = -Infinity; clearNeural(data.reason); return;
  }
  if (data.type === 'neural-error' && data.segment === segment && data.epoch === epoch) {
    neuralBusy = false; lastResult = {...emptyPulse(data.message),status:'unreliable'}; display(lastResult); return;
  }
  if (data.type === 'neural-output' && pulseEnabled && data.segment === segment && data.epoch === epoch) {
    neuralBusy = false; const output = data.output;
    if (!Array.isArray(output.values) || output.values.length !== profile.outputs || output.values.some(v=>!Number.isFinite(v))) return;
    if (wave.length && output.start_ms-wave.at(-1).time>250) { resets++; resetReason='실제 모델 결과 사이에 250ms 이상 누락'; smoother.reset(); }
    wave = mergeNeuralWindow(wave, output.start_ms, output.values);
    updateSeconds = lastOutputTime === null ? null : (frameTime-lastOutputTime)/1000;
    lastOutputTime = frameTime;
    neuralWindows++; lastInference=output.inference_ms; lastResult=smoother.add(estimateNeuralPulse(wave));
    display(lastResult); return;
  }
  if (data.type !== 'frame') return;
  const {bitmap, time} = data;
  epoch = data.epoch ?? 0;
  frameTime = time; totalFrames++;
  frameTimes = [...frameTimes, time].filter(v => v >= time - 2000);
  boxes = []; lightLevel = null;
  try {
    if (!detector) throw new Error('Model not ready');
    const width = 320, height = Math.round(width * bitmap.height / bitmap.width);
    if (canvas.height !== height) canvas.height = height;
    ctx.drawImage(bitmap, 0, 0, width, height);
    // Face geometry at ~10Hz; colour sampling on every captured frame. Calling
    // the landmark model for every RGB sample can halve the sampling FPS.
    // CPU fallback limits face-model duty cycle so RGB sampling has time to continue.
    const faceInterval = featuresEnabled ? featureDelegate === 'CPU' ? Math.max(65, detectionCost * 4) : 65
      : mode === 'efficientphys' ? 200 : 100;
    if (time - lastDetection >= faceInterval || time < lastDetection) {
      const detectionStarted = Date.now();
      const detection = detector.detectForVideo(canvas, time);
      detectionCost = detectionCost * .7 + (Date.now() - detectionStarted) * .3;
      cachedFaces = detection.faceLandmarks;
      lastDetection = time;
      // Share the existing detector/canvas. Expression validity is independent of rPPG gates.
      if (featuresEnabled) {
        let brightness = null;
        if (cachedFaces.length === 1) {
          const face = cachedFaces[0];
          const x1 = Math.max(0, Math.floor(Math.min(...face.map(v=>v.x))*width));
          const y1 = Math.max(0, Math.floor(Math.min(...face.map(v=>v.y))*height));
          const x2 = Math.min(width, Math.ceil(Math.max(...face.map(v=>v.x))*width));
          const y2 = Math.min(height, Math.ceil(Math.max(...face.map(v=>v.y))*height));
          if (x2>x1 && y2>y1) {
            const pixels=ctx.getImageData(x1,y1,x2-x1,y2-y1).data;
            let sum=0; for(let i=0;i<pixels.length;i+=4) sum+=(pixels[i]+pixels[i+1]+pixels[i+2])/3;
            brightness=sum/(pixels.length/4);
          }
        }
        const result=featureTracker.add(detection,time,data.sessionTimeMs??time,width,height,brightness);
        if (time-lastFeatureDisplay>=180 || result.status!=='observed') {
          self.postMessage({type:'face-features',epoch,result:{...result,delegate:featureDelegate}});
          lastFeatureDisplay=time;
        }
      }
    }
    if (!pulseEnabled) return;
    const faces = cachedFaces;
    if (faces.length !== 1) { previous = undefined; faceCropTracker.reset(); faceAssessment=null; reject(faces.length ? '한 명만 화면에 들어와 주세요.' : '얼굴을 찾지 못했습니다. 정면을 유지해 주세요.', true); return; }
    const face = faces[0], left = face[33], right = face[263], nose = face[1];
    boxes = pulseRegions(face, width, height);
    const size = Math.hypot(right.x - left.x, right.y - left.y);
    const center = {x: (left.x + right.x) / 2, y: (left.y + right.y) / 2, size};
    const motion = previous ? Math.hypot(center.x - previous.x, center.y - previous.y) / size : 0;
    const scale = previous ? Math.abs(size - previous.size) / size : 0;
    const rolled = Math.abs(right.y - left.y) / size > 0.3;
    const turned = Math.abs(nose.x - center.x) / size > 0.3;
    if (mode === 'efficientphys') {
      faceAssessment=faceCropTracker.update(face,width,height,lastDetection);
      if (!faceAssessment.crop) { reject(faceAssessment.reason,true); previous=center; return; }
    } else if (size < 0.15 || rolled || turned || motion > 0.065 || scale > 0.1) {
      reject('움직임·얼굴 각도 또는 크기 불안정 · 카메라를 정면으로 보고 잠시 멈춰 주세요.');
      previous = center; return;
    }
    const pixels = ctx.getImageData(0, 0, width, height).data;
    // Forehead below hairline, left cheek, right cheek; avoid eyes and mouth.
    const patches = boxes.map(region => patch(region, pixels, width, height));
    const regions = mode==='efficientphys' ? patches.filter(v=>v && v.clipping<=.15) : patches;
    if (regions.length < (mode==='efficientphys'?2:3) || regions.some(v=>!v)) { reject('밝기를 확인할 얼굴 영역이 부족합니다. 얼굴이 잘 보이도록 해 주세요.'); return; }
    const light = regions.reduce((sum, v) => sum + v.rgb.reduce((a, b) => a + b, 0) / 3, 0) / regions.length;
    lightLevel = light;
    if (light < 18 || light > 235 || regions.some(v => v.clipping > 0.15)) {
      reject('너무 어둡거나 과노출입니다. 일정한 전면 조명을 사용해 주세요.'); return;
    }
    previous = center;
    buffer.add({time, light, regions: [0,1,2].map(i=>(patches[i] ?? regions[0]).rgb)});
    acceptedFrames++;
    if (mode === 'efficientphys') {
      if (time-lastFrameAccepted>250 && crops.length) clearNeural('유효 영상 사이에 250ms 이상 누락');
      lastFrameAccepted=time;
      // Expanded square face crop, 72x72 RGB; matches the official model input.
      const {x,y,side}=faceAssessment.crop;
      const size=profile.size;
      cropContext.drawImage(canvas,x,y,side,side,0,0,size,size);
      const rgba=cropContext.getImageData(0,0,size,size).data, rgb=new Uint8Array(size*size*3);
      for(let i=0,j=0;i<rgba.length;i+=4){rgb[j++]=rgba[i];rgb[j++]=rgba[i+1];rgb[j++]=rgba[i+2];}
      crops.push({time,rgb});
      crops=crops.filter(v=>v.time>=time-profile.durationMs-120).slice(-(size===128?181:121));
      // Sliding windows, requested every second, one request in flight. No backlog.
      if(crops.length>1 && time-crops[0].time>=profile.durationMs && !neuralBusy && time-lastNeuralAttempt>=1000){
        const fps=(crops.length-1)*1000/(time-crops[0].time);
        if(fps<15){lastResult={...emptyPulse('영상 수집 속도가 부족합니다. 다른 카메라 탭을 종료하고 조명·30fps 설정을 확인해 주세요.'),status:'unreliable'};}
        else {
          const count=crops.length, frameBytes=size*size*3, packet=new ArrayBuffer(8+count*(8+frameBytes)), header=new DataView(packet);
          new Uint8Array(packet,0,4).set([69,80,48,size===128?50:49]); header.setUint16(4,count,true); header.setUint16(6,0,true);
          crops.forEach((frame,i)=>{header.setFloat64(8+i*8,frame.time,true); new Uint8Array(packet,8+count*8+i*frameBytes,frameBytes).set(frame.rgb);});
          neuralBusy=true; lastNeuralAttempt=time; self.postMessage({type:'neural-chunk',packet,segment,epoch},[packet]);
        }
      }
      if(time-lastDisplay>=250){
        const seconds=wave.length>1 ? (wave.at(-1).time-wave[0].time)/1000 : 0;
        const preparing=neuralBusy ? '첫 모델 추론 처리 중' : `첫 영상 블록 ${(Math.max(0,time-(crops[0]?.time??time))/1000).toFixed(1)}/${(profile.durationMs/1000).toFixed(1)}초 준비`;
        display({...lastResult,seconds,reason: lastResult.status==='collecting' ? neuralWindows ? `${profile.name} 분석 중 · 완료 창 ${neuralWindows}개 · 실제 맥파 ${seconds.toFixed(1)}/6초 (잠정값)` : preparing : lastResult.reason});
      }
      return;
    }
    const duration = buffer.samples.length > 1 ? (buffer.samples.at(-1).time - buffer.samples[0].time) / 1000 : 0;
    if (duration < 15 && lastResult.bpm !== null) lastResult = emptyPulse();
    if (time - lastAnalysis >= 1000) {
      lastAnalysis = time; lastResult = estimatePulse(buffer.samples);
    }
    if (time - lastDisplay >= 250) {
      const seconds = duration;
      display({...lastResult, seconds, reason: seconds < 15 ? `얼굴 영역 추적 중 · 신호 ${seconds.toFixed(1)} / 15초 수집` : lastResult.reason});
    }
  } catch {
    featureTracker.interrupt();
    if(featuresEnabled) self.postMessage({type:'face-features-error',epoch});
    if(pulseEnabled) reject('프레임 분석 실패 · 브라우저의 카메라·WebGL 지원을 확인해 주세요.');
  }
  finally { bitmap.close(); self.postMessage({type: 'ack'}); }
};
