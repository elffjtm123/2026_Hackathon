import { useEffect, useRef, useState, type RefObject } from 'react';
import { emptyPulse, PulseReadoutMemory, type PulseResult } from './signal';
import { pulseModels, type PulseModelId } from './models';
import { emptyFaceFeatures, type FaceFeatures } from '../face-features/features';

export type FaceFeatureOptions = {enabled: boolean; onResult: (result: FaceFeatures) => void; sessionTime?: () => number};

export function usePulse(stream: MediaStream | null, enabled: boolean,
  mode: 'pos' | 'efficientphys' = 'pos', videoRef?: RefObject<HTMLVideoElement | null>, modelId: PulseModelId = 'ma_ubfc_tscan',
  faceFeatures?: FaceFeatureOptions) {
  const [result, setResult] = useState<PulseResult>(emptyPulse);
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
    let disposed = false, busy = false, ready = false, failed = false;
    let lastFrame = -1, lastAck = performance.now(), handle = 0, epoch = 0;
    const sharedVideo = videoRef?.current;
    const video = sharedVideo ?? document.createElement('video');
    if (!video.requestVideoFrameCallback) {
      featureOptions.current?.onResult(emptyFaceFeatures('실제 영상 프레임 시각을 읽을 수 없습니다.', 'unavailable'));
      setResult({...emptyPulse('실제 영상 프레임 시각을 읽을 수 없는 브라우저입니다. 최신 Chrome/Edge를 사용해 주세요.'), status: 'unreliable'}); return;
    }
    if (!sharedVideo) { video.muted = true; video.playsInline = true; video.srcObject = stream; }
    const worker = new Worker('/pulse-worker.js');
    let neuralRequest: AbortController | null = null;
    let activeSegment = 0;
    let pulseFailed = false, lastFeatures = performance.now(), lastFeatureTime: number | null = null, pulseCheck = 0;
    const api = `${((import.meta.env?.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8000/api/v1').replace(/\/$/,'')}/pulse`;
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
    const initTimeout = window.setTimeout(() => failure('맥박 분석 모델 준비 시간이 초과되었습니다. 기능을 껐다 켜서 재시도해 주세요.'), 30000);
    worker.onerror = () => failure('맥박 분석 워커 준비 실패 · 로컬 자산과 브라우저 지원을 확인해 주세요.');
    worker.onmessage = ({data}) => {
      if (disposed || failed) return;
      if (data.type === 'ready') {
        ready = true; lastAck = performance.now(); window.clearTimeout(initTimeout);
        if (pulseEnabled.current && !pulseFailed) setResult(emptyPulse('정면을 유지하며 안정된 영상 15초를 모으고 있습니다.'));
      }
      if (data.type === 'ack') { busy = false; lastAck = performance.now(); }
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
      const destination = new URL(api);
      if(!['127.0.0.1','localhost','[::1]'].includes(destination.hostname)) {
        pulseFailure('얼굴 크롭은 로컬 백엔드에만 전송할 수 있습니다.');
      } else void fetch(`${api}/model?model_id=${modelId}`).then(async response=>{
        const status=await response.json();
        if(!response.ok || !status.available) throw new Error(status.error?.message ?? 'EfficientPhys 가중치가 준비되지 않았습니다.');
      }).catch(error=>{if(!disposed && check===pulseCheck && pulseEnabled.current) pulseFailure(error instanceof Error ? error.message : '맥박 백엔드 연결 실패');});
    };
    pulseControl.current = next => {
      pulseCheck++; pulseFailed = false; neuralRequest?.abort(); neuralRequest=null; memory.current.reset();
      worker.postMessage({type:'pulse-enabled',enabled:next});
      setResult(emptyPulse(next ? '맥박 신호를 새로 수집합니다.' : '맥박 분석 꺼짐'));
      if(next) checkPulse();
    };
    checkPulse();
    worker.postMessage({type: 'init', mode, profile, featuresEnabled, pulseEnabled: enabled && !pulseFailed});
    void video.play().catch(() => failure('카메라 재생을 시작하지 못했습니다.'));
    const tick = async (_now: number, metadata: VideoFrameCallbackMetadata) => {
      if (disposed || failed) return;
      handle = video.requestVideoFrameCallback((now, frame) => { void tick(now, frame); });
      const time = metadata.mediaTime * 1000;
      if (!ready || busy || video.readyState < 2 || time === lastFrame || document.hidden) return;
      if (mode === 'efficientphys' && time - lastFrame < 31) return;
      lastFrame = time; busy = true;
      const frameEpoch = epoch;
      try {
        const bitmap = await createImageBitmap(video, {resizeWidth:320,
          resizeHeight:Math.max(1,Math.round(320*video.videoHeight/video.videoWidth))});
        if (disposed || failed || frameEpoch !== epoch) { bitmap.close(); busy = false; return; }
        worker.postMessage({type: 'frame', bitmap, time, sessionTimeMs: featureOptions.current?.sessionTime?.() ?? time, epoch: frameEpoch}, [bitmap]);
      } catch { failure('카메라 프레임을 읽을 수 없습니다.'); }
    };
    handle = video.requestVideoFrameCallback((now, frame) => { void tick(now, frame); });
    const reset = () => {
      if (disposed || failed) return;
      epoch++;
      lastFeatures = performance.now();
      featureOptions.current?.onResult({...emptyFaceFeatures(document.hidden ? '탭이 숨겨져 표정 관찰을 멈췄습니다.' : '영상 갱신이 중단되었습니다.', 'stale'), timestampMs: lastFeatureTime});
      neuralRequest?.abort(); neuralRequest=null;
      worker.postMessage({type: 'reset', epoch, reason: document.hidden ? '탭이 숨겨져 수집 재시작' : '영상 갱신 중단으로 수집 재시작'});
      setResult(memory.current.update(emptyPulse(document.hidden ? '다른 탭에서는 분석을 멈춥니다.' : '영상이 중단되었습니다. 신호를 다시 수집합니다.'),performance.now()));
    };
    const watchdog = window.setInterval(() => {
      if (featuresEnabled && !failed && ready && performance.now() - lastFeatures > 1500)
        featureOptions.current?.onResult({...emptyFaceFeatures('표정 관찰이 1.5초 이상 갱신되지 않았습니다.', 'stale'), timestampMs: lastFeatureTime});
      setResult(previous=>previous.held ? memory.current.update(previous,performance.now()) : previous);
      if (ready && performance.now() - lastAck > 1500) reset();
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
