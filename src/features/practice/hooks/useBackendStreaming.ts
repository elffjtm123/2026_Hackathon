import { useCallback, useEffect, useRef } from 'react';
import workletUrl from '../pcm-capture.worklet.ts?worker&url';
import { captureSize } from '../sessionLifecycle';
import type { MediaPacket } from '../../../lib/mediaProtocol';

type Options = {
  isActive: boolean; captureAudio: boolean; stream: MediaStream | null; audioContext: AudioContext | null;
  sessionTime: () => number;
  sendVideoFrame: (payload: Blob, timestampMs: number) => Promise<boolean>;
  sendAudioPacket: (packet: Omit<MediaPacket, 'type' | 'timestampMs'>) => void;
  awaitAudioAck: (sequence: number) => Promise<void>;
  onError: (error: Error) => void;
};

export function useBackendStreaming({isActive, captureAudio, stream, audioContext, sessionTime,
  sendVideoFrame, sendAudioPacket, awaitAudioAck, onError}: Options) {
  const stopVideoRef = useRef<() => void>(() => undefined);
  const stopAudioRef = useRef<(flush: boolean) => Promise<void>>(async () => undefined);
  useEffect(() => {
    if (!isActive || !stream) return;
    let stopped = false, encoding = false;
    const video = document.createElement('video');
    video.muted = true; video.playsInline = true; video.srcObject = stream;
    void video.play().catch(error => {if (!stopped) onError(error);});
    const canvas = document.createElement('canvas');
    const interval = setInterval(() => {
      if (stopped || encoding || !video.videoWidth || video.readyState < 2) return;
      const size = captureSize(video.videoWidth, video.videoHeight);
      canvas.width = size.width; canvas.height = size.height;
      const context = canvas.getContext('2d');
      if (!context) return;
      const timestamp = sessionTime();
      context.drawImage(video, 0, 0, size.width, size.height);
      encoding = true;
      canvas.toBlob(blob => {
        if (blob && !stopped) void sendVideoFrame(blob, timestamp).catch(onError).finally(() => {encoding = false;});
        else encoding = false;
      }, 'image/jpeg', .8);
    }, 125);
    const stop = () => {stopped = true; clearInterval(interval); video.pause(); video.srcObject = null;};
    stopVideoRef.current = stop;
    return stop;
  }, [isActive, stream, sessionTime, sendVideoFrame, onError]);

  useEffect(() => {
    if (!captureAudio || !stream || !audioContext) return;
    let stopped = false, sequence = 0;
    let node: AudioWorkletNode | null = null;
    let source: MediaStreamAudioSourceNode | null = null;
    let gain: GainNode | null = null;
    let flushDone: (() => void) | null = null;
    let stopPromise: Promise<void> | null = null;
    const cleanup = () => {source?.disconnect(); node?.disconnect(); gain?.disconnect(); if (node) node.port.onmessage = null;};
    const initialize = (async () => {
      await audioContext.audioWorklet.addModule(workletUrl);
      if (stopped || audioContext.state === 'closed') return;
      node = new AudioWorkletNode(audioContext, 'pcm-capture', {channelCount: 1, channelCountMode: 'explicit'});
      source = audioContext.createMediaStreamSource(stream);
      gain = audioContext.createGain(); gain.gain.value = 0;
      node.port.onmessage = (message: MessageEvent<{event: string; startSample: number; sampleCount: number; payload: ArrayBuffer}>) => {
        if (message.data.event === 'flushed') {flushDone?.(); return;}
        try {
          sendAudioPacket({sequence: ++sequence, startSample: message.data.startSample,
            sampleCount: message.data.sampleCount, payload: message.data.payload});
        } catch (error) {cleanup(); onError(error as Error);}
      };
      source.connect(node); node.connect(gain); gain.connect(audioContext.destination);
    })();
    void initialize.catch(error => {cleanup(); if (!stopped) onError(error as Error);});
    const stop = (flush: boolean) => {
      if (stopPromise) return stopPromise;
      stopped = true;
      stopPromise = (async () => {
        try {
          await initialize;
          if (flush && node) {
            await new Promise<void>((resolve, reject) => {
              const timeout = setTimeout(() => reject(new Error('마지막 음성 캡처 완료 시간이 초과되었습니다.')), 2000);
              flushDone = () => {clearTimeout(timeout); resolve();};
              node!.port.postMessage({event: 'flush'});
            });
            if (sequence) await awaitAudioAck(sequence);
          }
        } finally {cleanup();}
      })();
      return stopPromise;
    };
    stopAudioRef.current = stop;
    return () => {void stop(false).catch(() => undefined);};
  }, [captureAudio, stream, audioContext, sendAudioPacket, awaitAudioAck, onError]);
  const stopStreaming = useCallback(async () => {stopVideoRef.current(); await stopAudioRef.current(true);}, []);
  return {stopStreaming};
}
