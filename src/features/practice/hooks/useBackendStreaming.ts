import { useEffect, useRef } from "react";

type UseBackendStreamingOptions = {
  isActive: boolean;
  stream: MediaStream | null;
  transcriptText: string;
  sendTranscript: (text: string, isFinal?: boolean) => void;
  sendVideoFrame: (payload: Blob) => void;
};

export function useBackendStreaming({
  isActive,
  stream,
  transcriptText,
  sendTranscript,
  sendVideoFrame,
}: UseBackendStreamingOptions) {
  const textRef = useRef(transcriptText);

  useEffect(() => {
    textRef.current = transcriptText;
  }, [transcriptText]);

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

    const transcriptIntervalId = window.setInterval(() => {
      sendTranscript(textRef.current, true);
    }, 1200);

    return () => {
      window.clearInterval(videoIntervalId);
      window.clearInterval(transcriptIntervalId);
      video.pause();
      video.srcObject = null;
    };
  }, [isActive, sendTranscript, sendVideoFrame, stream]);
}
