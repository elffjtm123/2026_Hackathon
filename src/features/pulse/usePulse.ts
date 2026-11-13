import { useEffect, useRef, useState, type RefObject } from 'react';
import { emptyPulse, PulseReadoutMemory, type PulseResult } from './signal';
import { pulseModels, type PulseModelId } from './models';
import { emptyFaceFeatures, type FaceFeatures } from '../face-features/features';
import { apiBase } from '../../lib/apiBase';
import { checkPulseBackend } from './pulseMode';
import { FrameWatchdog, initTimeoutMs, unresponsiveWorkerAction, WORKER_HANG_MS, type FaceDelegate } from './frameWatchdog';

export const pulseApiBase = `${apiBase}/pulse`;

export type FaceFeatureOptions = {enabled: boolean; onResult: (result: FaceFeatures) => void; sessionTime?: () => number};

export function usePulse(stream: MediaStream | null, enabled: boolean,
  mode: 'pos' | 'efficientphys' = 'pos', videoRef?: RefObject<HTMLVideoElement | null>, modelId: PulseModelId = 'ma_ubfc_tscan',
  faceFeatures?: FaceFeatureOptions, onBackendUnavailable?: (reason: string) => void) {
  const [result, setResult] = useState<PulseResult>(emptyPulse);
  // When set, a backend model that cannot run is handed to the caller instead of failing.
  const backendUnavailable = useRef(onBackendUnavailable); backendUnavailable.current = onBackendUnavailable;
  const memory = useRef(new PulseReadoutMemory());
  const lastModel = useRef(modelId);
  const featureOptions = useRef(faceFeatures); featureOptions.current = faceFeatures;
  const featureMemory = useRef<FaceFeatures | null>(null);
  const featuresEnabled = faceFeatures?.enabled === true;
  const pulseEnabled = useRef(enabled); pulseEnabled.current = enabled;
  const pulseControl = useRef<((next: boolean) => void) | null>(null);
  const running = enabled || featuresEnabled;
  useEffect(() => { pulseControl.current?.(enabled); }, [enabled]);
  useEffect(() => {
    if (lastModel.current !== modelId) { memory.current.reset(); lastModel.current=modelId; }
    if ((!enabled && !featuresEnabled) || !stream) {
      featureOptions.current?.onResult(!featuresEnabled ? emptyFaceFeatures('표정 특징 추출 꺼짐', 'off') : featureMemory.current
        ? {...featureMemory.current, status: 'ended', coefficients: null, headPose: null, reason: '연습 종료 · 마지막 관찰 구간의 통계입니다.'}
        : emptyFaceFeatures());
      if (!featuresEnabled) featureMemory.current = null;
      if (!enabled) memory.current.reset();
      setResult(enabled ? memory.current.finish(performance.now()) ?? emptyPulse('연습을 시작하면 기존 카메라 영상을 함께 분석합니다.') : emptyPulse('실험 기능 꺼짐')); return;
    }
    memory.current.reset();
    featureMemory.current = null;
    featureOptions.current?.onResult(emptyFaceFeatures(featuresEnabled ? '표정 모델 준비 중…' : '표정 특징 추출 꺼짐', featuresEnabled ? 'waiting' : 'off'));
    const profile = pulseModels.find(v=>v.id===modelId)!;
    if (!window.Worker || !window.createImageBitmap || !window.OffscreenCanvas) {
      featureOptions.current?.onResult(emptyFaceFeatures('이 브라우저는 Worker·OffscreenCanvas를 지원하지 않습니다.', 'unavailable'));
      setResult({...emptyPulse('이 브라우저는 Worker·OffscreenCanvas를 지원하지 않습니다.'), status: 'unreliable'}); return;
    }
    let disposed = false, busy = false, ready = false, failed = false, cpuRetried = false;
    let lastFrame = -1, handle = 0, epoch = 0, initTimeout = 0;
    // workerDelegate: what the current worker runs on (requested, then confirmed by 'ready').
    let watch = new FrameWatchdog(performance.now()), workerDelegate: FaceDelegate = 'GPU';
    const sharedVideo = videoRef?.current;
    const video = sharedVideo ?? document.createElement('video');
    if (!video.requestVideoFrameCallback) {
      featureOptions.current?.onResult(emptyFaceFeatures('실제 영상 프레임 시각을 읽을 수 없습니다.', 'unavailable'));
      setResult({...emptyPulse('실제 영상 프레임 시각을 읽을 수 없는 브라우저입니다. 최신 Chrome/Edge를 사용해 주세요.'), status: 'unreliable'}); return;
    }
    if (!sharedVideo) { video.muted = true; video.playsInline = true; video.srcObject = stream; }
    let worker: Worker;
    let neuralRequest: AbortController | null = null;
    let activeSegment = 0;
    let pulseFailed = false, lastFeatures = performance.now(), lastFeatureTime: number | null = null, pulseCheck = 0;
    const api = pulseApiBase;
    setResult(emptyPulse('브라우저 전용 얼굴 모델 준비 중…'));
    const failure = (reason: string) => {
      if (disposed) return;
      failed = true; setResult(memory.current.update({...emptyPulse(reason), status: 'unreliable'},performance.now()));
      featureOptions.current?.onResult(emptyFaceFeatures(reason, 'unavailable'));
      window.clearTimeout(initTimeout);
      neuralRequest?.abort();
      worker.terminate();
    };
    const pulseFailure = (reason: string) => {
      if (!featuresEnabled) { failure(reason); return; }
      pulseFailed = true; neuralRequest?.abort(); neuralRequest = null;
      worker.postMessage({type: 'pulse-enabled', enabled: false});
      setResult(memory.current.update({...emptyPulse(reason), status: 'unreliable'}, performance.now()));
    };
    const onMessage = ({data}: MessageEvent) => {
      if (disposed || failed) return;
      if (data.type === 'ready') {
        ready = true; if (data.delegate === 'CPU') workerDelegate = 'CPU'; window.clearTimeout(initTimeout);
        watch = new FrameWatchdog(performance.now()); lastFeatures = performance.now();
        if (pulseEnabled.current && !pulseFailed) setResult(emptyPulse('정면을 유지하며 안정된 영상 15초를 모으고 있습니다.'));
      }
      if (data.type === 'ack') { busy = false; watch.frameSettled(performance.now()); }
      if (data.type === 'face-features' && featuresEnabled && data.epoch === epoch && !document.hidden) {
        lastFeatures = performance.now(); lastFeatureTime = data.result.timestampMs;
        featureMemory.current = data.result;
        featureOptions.current?.onResult(data.result);
      }
      if (data.type === 'face-features-error' && featuresEnabled && data.epoch === epoch) {
        featureOptions.current?.onResult(emptyFaceFeatures('프레임에서 표정 특징을 추출하지 못했습니다.', 'unavailable'));
      }
      if (data.type === 'result' && pulseEnabled.current && !pulseFailed && data.epoch === epoch && !document.hidden) {
        setResult(memory.current.update(data.result,performance.now()));
      }
      if (data.type === 'error') failure(data.message);
      if (data.type === 'neural-reset') { activeSegment = data.segment; neuralRequest?.abort(); neuralRequest = null; }
      if (data.type === 'neural-chunk' && pulseEnabled.current && !pulseFailed && data.epoch === epoch && mode === 'efficientphys') {
        const segment = data.segment, requestEpoch = epoch;
        activeSegment = segment;
        neuralRequest?.abort();
        const controller = new AbortController(); neuralRequest = controller;
        const timeout = window.setTimeout(()=>controller.abort(),30000);
        void fetch(`${api}/infer?model_id=${modelId}`, {method:'POST',headers:{'Content-Type':'application/octet-stream'},
          body:data.packet,signal:controller.signal}).then(async response=>{
          const output=await response.json();
          if(!response.ok) throw new Error(output.error?.message ?? 'EfficientPhys 추론 요청 실패');
          if(!disposed && !failed && requestEpoch===epoch && activeSegment===segment)
            worker.postMessage({type:'neural-output',output,epoch:requestEpoch,segment});
        }).catch(error=>{
          if(!disposed && !failed && requestEpoch===epoch && activeSegment===segment && neuralRequest===controller)
            worker.postMessage({type:'neural-error',epoch:requestEpoch,segment,
              message:controller.signal.aborted ? 'EfficientPhys 응답 시간이 초과되었습니다.' : error instanceof Error ? error.message : '맥박 모델 연결 실패'});
        }).finally(()=>{window.clearTimeout(timeout); if(neuralRequest===controller) neuralRequest=null;});
      }
    };
    const checkPulse = () => {
      const check = ++pulseCheck;
      if (!pulseEnabled.current || mode !== 'efficientphys') return;
      void checkPulseBackend(api, modelId).then(status=>{
        if(status.ok || disposed || check!==pulseCheck || !pulseEnabled.current) return;
        if(backendUnavailable.current) backendUnavailable.current(status.reason);
        else pulseFailure(status.reason);
      });
    };
    pulseControl.current = next => {
      pulseCheck++; pulseFailed = false; neuralRequest?.abort(); neuralRequest=null; memory.current.reset();
      worker.postMessage({type:'pulse-enabled',enabled:next});
      setResult(emptyPulse(next ? '맥박 신호를 새로 수집합니다.' : '맥박 분석 꺼짐'));
      if(next) checkPulse();
    };
    // cpuOnly: a fresh worker after a GPU worker stopped answering in init or on a frame.
    const startWorker = (cpuOnly: boolean) => {
      ready = false; busy = false;
      // Without face features the worker always runs the face model on CPU.
      workerDelegate = cpuOnly || !featuresEnabled ? 'CPU' : 'GPU';
      window.clearTimeout(initTimeout);
      initTimeout = window.setTimeout(() => recoverUnresponsiveWorker('init'), initTimeoutMs(workerDelegate));
      const next = new Worker('/pulse-worker.js');
      worker = next;
      // A terminated worker's late messages must not touch the replacement's state.
      next.onerror = () => { if (worker === next) failure('맥박 분석 워커 준비 실패 · 로컬 자산과 브라우저 지원을 확인해 주세요.'); };
      next.onmessage = event => { if (worker === next) onMessage(event); };
      next.postMessage({type: 'init', mode, profile, featuresEnabled, pulseEnabled: pulseEnabled.current && !pulseFailed,
        ...(cpuOnly ? {delegate: 'CPU'} : {})});
    };
    checkPulse();
    startWorker(false);
    void video.play().catch(() => failure('카메라 재생을 시작하지 못했습니다.'));
    const tick = async (_now: number, metadata: VideoFrameCallbackMetadata) => {
      if (disposed || failed) return;
      handle = video.requestVideoFrameCallback((now, frame) => { void tick(now, frame); });
      const time = metadata.mediaTime * 1000;
      if (!ready || busy || video.readyState < 2 || time === lastFrame || document.hidden) return;
      if (mode === 'efficientphys' && time - lastFrame < 31) return;
      lastFrame = time; busy = true; watch.frameStarted(performance.now());
      const frameEpoch = epoch;
      try {
        const bitmap = await createImageBitmap(video, {resizeWidth:320,
          resizeHeight:Math.max(1,Math.round(320*video.videoHeight/video.videoWidth))});
        if (disposed || failed || frameEpoch !== epoch) { bitmap.close(); busy = false; watch.frameSettled(performance.now()); return; }
        worker.postMessage({type: 'frame', bitmap, time, sessionTimeMs: featureOptions.current?.sessionTime?.() ?? time, epoch: frameEpoch}, [bitmap]);
      } catch { failure('카메라 프레임을 읽을 수 없습니다.'); }
    };
    handle = video.requestVideoFrameCallback((now, frame) => { void tick(now, frame); });
    const restartCollection = () => {
      if (disposed || failed) return;
      epoch++;
      lastFeatures = performance.now();
      featureOptions.current?.onResult({...emptyFaceFeatures(document.hidden ? '탭이 숨겨져 표정 관찰을 멈췄습니다.' : '영상 갱신이 중단되었습니다.', 'stale'), timestampMs: lastFeatureTime});
      neuralRequest?.abort(); neuralRequest=null;
      worker.postMessage({type: 'reset', epoch, reason: document.hidden ? '탭이 숨겨져 수집 재시작' : '영상 갱신 중단으로 수집 재시작'});
      setResult(memory.current.update(emptyPulse(document.hidden ? '다른 탭에서는 분석을 멈춥니다.' : '영상이 중단되었습니다. 신호를 다시 수집합니다.'),performance.now()));
    };
    // Hidden tab and ended track: restart collection and give the video a fresh stall window.
    const reset = () => { watch.restart(performance.now()); restartCollection(); };
    const processingReason = '얼굴 모델이 프레임을 처리하는 중입니다. 잠시만 기다려 주세요.';
    // A stuck GPU warm-up blocks init before 'ready', so an init timeout takes the same CPU retry as a hung frame.
    const recoverUnresponsiveWorker = (stage: 'init' | 'frame') => {
      if (disposed || failed) return;
      const seconds = (stage === 'init' ? initTimeoutMs(workerDelegate) : WORKER_HANG_MS) / 1000;
      if (unresponsiveWorkerAction({delegate: workerDelegate, cpuRetried}) === 'fail') {
        failure(stage === 'init' ? '맥박 분석 모델 준비 시간이 초과되었습니다. 기능을 껐다 켜서 재시도해 주세요.'
          : `얼굴 모델이 ${seconds}초 넘게 응답하지 않아 분석을 멈췄습니다. 기능을 껐다 켜서 재시도해 주세요.`); return;
      }
      cpuRetried = true; worker.terminate(); epoch++;
      neuralRequest?.abort(); neuralRequest = null;
      const reason = stage === 'init' ? `얼굴 모델 GPU 준비가 ${seconds}초 넘게 끝나지 않아 CPU 모드로 다시 준비합니다…`
        : `얼굴 모델이 ${seconds}초 넘게 응답하지 않아 CPU 모드로 다시 준비합니다…`;
      if (featuresEnabled) featureOptions.current?.onResult({...emptyFaceFeatures(reason, 'waiting'), timestampMs: lastFeatureTime});
      if (pulseEnabled.current && !pulseFailed) setResult(memory.current.update(emptyPulse(reason), performance.now()));
      startWorker(true);
    };
    const watchdog = window.setInterval(() => {
      const now = performance.now();
      // A frame still in flight is model work, not a stopped video: no reset, its result still counts.
      const verdict = ready && !failed && !document.hidden ? watch.check(now) : 'ok';
      if (verdict === 'hung') { recoverUnresponsiveWorker('frame'); return; }
      if (featuresEnabled && !failed && ready && now - lastFeatures > 1500)
        featureOptions.current?.onResult(verdict === 'slow' ? {...emptyFaceFeatures(processingReason, 'waiting'), timestampMs: lastFeatureTime}
          : {...emptyFaceFeatures('표정 관찰이 1.5초 이상 갱신되지 않았습니다.', 'stale'), timestampMs: lastFeatureTime});
      // Keep the last collection counters so the panel does not flash "0/0 frames · 0.0s" while a frame is in flight.
      if (verdict === 'slow' && pulseEnabled.current && !pulseFailed) setResult(previous => memory.current.update(
        {...emptyPulse(processingReason), seconds: previous.seconds, diagnostics: previous.diagnostics}, now));
      else setResult(previous=>previous.held ? memory.current.update(previous,now) : previous);
      if (verdict === 'stall') restartCollection();
    }, 500);
    document.addEventListener('visibilitychange', reset);
    const track = stream.getVideoTracks()[0];
    track?.addEventListener('ended', reset);
    return () => {
      disposed = true; video.cancelVideoFrameCallback(handle); window.clearInterval(watchdog); window.clearTimeout(initTimeout);
      document.removeEventListener('visibilitychange', reset); track?.removeEventListener('ended', reset);
      neuralRequest?.abort(); worker.terminate();
      pulseControl.current = null;
      if (!sharedVideo) { video.pause(); video.srcObject = null; }
      // The shared practice stream belongs to useUserMedia, not this experiment.
    };
  }, [running, featuresEnabled, stream, mode, videoRef, modelId]);
  return result;
}
