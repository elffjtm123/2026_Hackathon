import { useCallback, useEffect, useRef, useState } from "react";

export function useUserMedia() {
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const stopMedia = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setStream(null);
  }, []);

  const startMedia = useCallback(async () => {
    setError(null);

    if (!navigator.mediaDevices?.getUserMedia) {
      const message = "이 브라우저는 카메라/마이크 접근을 지원하지 않습니다.";
      setError(message);
      throw new Error(message);
    }

    try {
      stopMedia();
      const nextStream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: true,
      });
      streamRef.current = nextStream;
      setStream(nextStream);
      return nextStream;
    } catch (mediaError) {
      const message =
        mediaError instanceof Error
          ? mediaError.message
          : "카메라/마이크 권한을 얻지 못했습니다.";
      setError(message);
      throw mediaError;
    }
  }, [stopMedia]);

  useEffect(() => stopMedia, [stopMedia]);

  return {
    stream,
    isActive: stream !== null,
    error,
    startMedia,
    stopMedia,
  };
}
