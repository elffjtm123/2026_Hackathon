import { useCallback, useEffect, useRef, useState } from "react";

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
      const message = mediaErrorMessage(mediaError);
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
