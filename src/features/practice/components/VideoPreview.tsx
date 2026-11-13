import { useEffect, useRef, type RefObject } from "react";

type VideoPreviewProps = {
  stream: MediaStream | null;
  videoRef?: RefObject<HTMLVideoElement | null>;
};

export function VideoPreview({ stream, videoRef: suppliedRef }: VideoPreviewProps) {
  const localRef = useRef<HTMLVideoElement | null>(null);
  const videoRef = suppliedRef ?? localRef;

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.srcObject = stream;
    }
  }, [stream, videoRef]);

  return (
    <video
      ref={videoRef}
      className="video-preview"
      muted
      autoPlay
      playsInline
    />
  );
}
