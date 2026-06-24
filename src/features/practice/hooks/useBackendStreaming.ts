import { useEffect } from "react";

type UseBackendStreamingOptions = {
  isActive: boolean;
  stream: MediaStream | null;
  sendVideoFrame: (payload: Blob) => void;
  sendAudioChunk: (payload: Blob) => void;
};

const AUDIO_CHUNK_MS = 4000;
type AudioContextConstructor = new () => AudioContext;

function mergeAudioBuffers(buffers: Float32Array[]) {
  const length = buffers.reduce((sum, buffer) => sum + buffer.length, 0);
  const merged = new Float32Array(length);
  let offset = 0;
  for (const buffer of buffers) {
    merged.set(buffer, offset);
    offset += buffer.length;
  }
  return merged;
}

function writeAscii(view: DataView, offset: number, value: string) {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index));
  }
}

function encodeWav(samples: Float32Array, sampleRate: number) {
  const bytesPerSample = 2;
  const blockAlign = bytesPerSample;
  const buffer = new ArrayBuffer(44 + samples.length * bytesPerSample);
  const view = new DataView(buffer);
  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + samples.length * bytesPerSample, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * blockAlign, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, samples.length * bytesPerSample, true);

  let offset = 44;
  for (const sample of samples) {
    const clipped = Math.max(-1, Math.min(1, sample));
    view.setInt16(offset, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true);
    offset += bytesPerSample;
  }
  return new Blob([view], { type: "audio/wav" });
}

export function useBackendStreaming({
  isActive,
  stream,
  sendVideoFrame,
  sendAudioChunk,
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

  useEffect(() => {
    if (!isActive || !stream || !stream.getAudioTracks().length) {
      return;
    }

    const browserWindow = window as Window &
      typeof globalThis & {
        webkitAudioContext?: AudioContextConstructor;
    };
    const AudioContextConstructor =
      browserWindow.AudioContext ?? browserWindow.webkitAudioContext;
    if (!AudioContextConstructor) {
      return;
    }
    const audioContext = new AudioContextConstructor();
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    const silentOutput = audioContext.createGain();
    silentOutput.gain.value = 0;
    let buffers: Float32Array[] = [];
    let bufferedMs = 0;

    const flushAudio = () => {
      if (!buffers.length) {
        return;
      }

      const samples = mergeAudioBuffers(buffers);
      buffers = [];
      bufferedMs = 0;
      sendAudioChunk(encodeWav(samples, audioContext.sampleRate));
    };

    processor.onaudioprocess = (event: AudioProcessingEvent) => {
      const input = event.inputBuffer.getChannelData(0);
      buffers.push(new Float32Array(input));
      bufferedMs += input.length / audioContext.sampleRate * 1000;
      if (bufferedMs >= AUDIO_CHUNK_MS) {
        flushAudio();
      }
    };

    source.connect(processor);
    processor.connect(silentOutput);
    silentOutput.connect(audioContext.destination);

    return () => {
      flushAudio();
      processor.disconnect();
      silentOutput.disconnect();
      source.disconnect();
      void audioContext.close();
    };
  }, [isActive, sendAudioChunk, stream]);
}
