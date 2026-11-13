import { useCallback, useEffect, useRef, useState } from 'react';
import workletUrl from '../practice/pcm-capture.worklet.ts?worker&url';
import { pcmWav } from './tools';

type RecorderResources = {
  stream: MediaStream; context: AudioContext; node?: AudioWorkletNode;
  source?: MediaStreamAudioSourceNode; gain?: GainNode; buffers: ArrayBuffer[]; bytes: number;
  flush?: () => void;
};

export function useExperimentRecorder(onAudio: (audio: Blob) => void) {
  const [recording, setRecording] = useState(false);
  const [starting, setStarting] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [level, setLevel] = useState(0);
  const callback = useRef(onAudio);
  callback.current = onAudio;
  const resources = useRef<RecorderResources | null>(null);
  const generation = useRef(0);
  const stopPromise = useRef<Promise<void> | null>(null);

  const cleanup = useCallback(() => {
    const current = resources.current;
    resources.current = null;
    if (!current) return;
    current.source?.disconnect(); current.node?.disconnect(); current.gain?.disconnect();
    if (current.node) current.node.port.onmessage = null;
    current.stream.getTracks().forEach(track => track.stop());
    void current.context.close().catch(() => undefined);
  }, []);

  const stop = useCallback(() => {
    if (stopPromise.current) return stopPromise.current;
    stopPromise.current = (async () => {
      const current = resources.current;
      try {
        if (!current?.node) return;
        await new Promise<void>((resolve, reject) => {
          const timeout = window.setTimeout(() => reject(new Error('녹음 마무리 시간이 초과되었습니다.')), 2000);
          current.flush = () => { clearTimeout(timeout); resolve(); };
          current.node!.port.postMessage({ event: 'flush' });
        });
        if (current.bytes < 3200) throw new Error('0.1초 이상 녹음해 주세요.');
        callback.current(pcmWav(current.buffers));
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : '녹음을 완료하지 못했습니다.');
      } finally {
        cleanup(); setRecording(false); setLevel(0);
      }
    })();
    return stopPromise.current;
  }, [cleanup]);

  const start = useCallback(async () => {
    if (resources.current) return;
    const token = ++generation.current;
    setStarting(true); setError(null); setSeconds(0); stopPromise.current = null;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      if (token !== generation.current) { stream.getTracks().forEach(track => track.stop()); return; }
      const context = new AudioContext();
      const current: RecorderResources = { stream, context, buffers: [], bytes: 0 };
      resources.current = current;
      await context.audioWorklet.addModule(workletUrl);
      if (token !== generation.current) return;
      const node = new AudioWorkletNode(context, 'pcm-capture', { channelCount: 1, channelCountMode: 'explicit' });
      current.node = node;
      current.source = context.createMediaStreamSource(stream);
      current.gain = context.createGain(); current.gain.gain.value = 0;
      node.port.onmessage = (event: MessageEvent<{ event: string; payload: ArrayBuffer }>) => {
        if (event.data.event === 'flushed') { current.flush?.(); return; }
        if (event.data.event !== 'pcm') return;
        const remaining = 60 * 32000 - current.bytes;
        const payload = event.data.payload.slice(0, Math.max(0, remaining));
        if (payload.byteLength) {
          current.buffers.push(payload); current.bytes += payload.byteLength;
          setSeconds(current.bytes / 32000);
          const values = new Int16Array(payload);
          let power = 0;
          for (const value of values) power += (value / 32768) ** 2;
          setLevel(Math.min(1, Math.sqrt(power / values.length) * 8));
        }
        if (current.bytes >= 60 * 32000) void stop();
      };
      current.source.connect(node); node.connect(current.gain); current.gain.connect(context.destination);
      await context.resume(); setRecording(true);
    } catch (cause) {
      cleanup(); setError(cause instanceof Error ? cause.message : '마이크를 시작하지 못했습니다.');
    } finally {
      if (token === generation.current) setStarting(false);
    }
  }, [cleanup, stop]);

  useEffect(() => () => { generation.current++; cleanup(); }, [cleanup]);
  return { recording, starting, seconds, level, error, start, stop };
}
