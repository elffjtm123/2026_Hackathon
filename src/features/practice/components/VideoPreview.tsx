import { useEffect, useRef } from "react";

type VideoPreviewProps = {
  stream: MediaStream | null;
};

export function VideoPreview({ stream }: VideoPreviewProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

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
