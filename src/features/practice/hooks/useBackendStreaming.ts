import { useEffect } from "react";

type UseBackendStreamingOptions = {
  isActive: boolean;
  stream: MediaStream | null;
  sendVideoFrame: (payload: Blob) => void;
};

export function useBackendStreaming({
  isActive,
  stream,
  sendVideoFrame,
}: UseBackendStreamingOptions) {
  useEffect(() => {
    if (!isActive || !stream) {
      return;
    }

    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;

    const canvas = document.createElement("canvas");
    canvas.width = 320;
    canvas.height = 240;

    void video.play();

    const videoIntervalId = window.setInterval(() => {
      const context = canvas.getContext("2d");
      if (!context || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
        return;
      }

      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(
        (blob) => {
          if (blob) {
            sendVideoFrame(blob);
          }
        },
        "image/jpeg",
        0.65
      );
    }, 200);

    return () => {
      window.clearInterval(videoIntervalId);
      video.pause();
      video.srcObject = null;
    };
  }, [isActive, sendVideoFrame, stream]);
}
