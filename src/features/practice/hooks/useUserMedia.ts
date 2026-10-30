import { useCallback, useEffect, useRef, useState } from "react";
import { acceptCurrentMedia, MICROPHONE_CONSTRAINTS } from '../sessionLifecycle.ts';

export function mediaErrorMessage(error: unknown) {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError" || error.name === "SecurityError") {
      return "카메라와 마이크 권한이 필요합니다. 브라우저 설정에서 권한을 허용해 주세요.";
    }
    if (error.name === "NotFoundError") {
      return "사용할 수 있는 카메라 또는 마이크를 찾지 못했습니다.";
    }
    if (error.name === "NotReadableError") {
      return "카메라 또는 마이크를 다른 앱이 사용 중입니다.";
    }
  }
  return "카메라/마이크를 시작하지 못했습니다. 장치와 브라우저 권한을 확인해 주세요.";
}

export function useUserMedia() {
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const generationRef = useRef(0);
  const contextRef = useRef<AudioContext | null>(null);
  const [audioContext, setAudioContext] = useState<AudioContext | null>(null);

  const stopMedia = useCallback(() => {
    generationRef.current++;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setStream(null);
    const context = contextRef.current;
    contextRef.current = null;
    setAudioContext(null);
    if (context && context.state !== 'closed') void context.close().catch(() => undefined);
  }, []);

  const startMedia = useCallback(async () => {
    setError(null);

    if (!navigator.mediaDevices?.getUserMedia) {
      const message = "이 브라우저는 카메라/마이크 접근을 지원하지 않습니다.";
      setError(message);
      throw new Error(message);
    }

    stopMedia();
    const generation = generationRef.current;
    let acquired: MediaStream | null = null;
    try {
      let context: AudioContext;
      try { context = new AudioContext({sampleRate: 16000}); }
      catch { context = new AudioContext(); }
      contextRef.current = context;
      const resumed = context.resume();
      void resumed.catch(() => undefined);
      const nextStream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: MICROPHONE_CONSTRAINTS,
      });
      acquired = nextStream;
      acceptCurrentMedia(nextStream, generation, generationRef.current);
      await resumed;
      acceptCurrentMedia(nextStream, generation, generationRef.current);
      if (context.state !== 'running') {
        nextStream.getTracks().forEach(track => track.stop());
        throw new Error('오디오 장치를 시작하지 못했습니다.');
      }
      streamRef.current = nextStream;
      setStream(nextStream);
      setAudioContext(context);
      return nextStream;
    } catch (mediaError) {
      acquired?.getTracks().forEach(track => track.stop());
      if (generation === generationRef.current) {
        const message = mediaErrorMessage(mediaError);
        setError(message);
        stopMedia();
      }
      throw mediaError;
    }
  }, [stopMedia]);

  useEffect(() => stopMedia, [stopMedia]);

  return {
    stream,
    audioContext,
    isActive: stream !== null,
    error,
    startMedia,
    stopMedia,
  };
}
