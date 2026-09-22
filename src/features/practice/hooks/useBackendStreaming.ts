import { useCallback, useEffect, useRef } from "react";
import {
  downsampleLinear,
  encodePcm16Wav,
  mergeAudioBuffers,
  takeNextAudioChunk,
} from "../audioTools";

type UseBackendStreamingOptions = {
  isActive: boolean;
  stream: MediaStream | null;
  sendVideoFrame: (payload: Blob) => Promise<boolean>;
  sendAudioChunk: (payload: Blob) => Promise<boolean>;
};

const AUDIO_CHUNK_SECONDS = 2;
const AUDIO_OVERLAP_SECONDS = 0.25;
const OUTPUT_SAMPLE_RATE = 16_000;
const VIDEO_INTERVAL_MS = 125;
type AudioContextConstructor = new () => AudioContext;

export function useBackendStreaming({
  isActive,
  stream,
  sendVideoFrame,
  sendAudioChunk,
}: UseBackendStreamingOptions) {
  const stopRef = useRef<() => Promise<void>>(async () => undefined);

  useEffect(() => {
    if (!isActive || !stream) {
      stopRef.current = async () => undefined;
      return;
    }

    let stopped = false;
    let stopPromise: Promise<void> | null = null;
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;

    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 480;
    void video.play();

    const videoIntervalId = window.setInterval(() => {
      const context = canvas.getContext("2d");
      if (
        stopped ||
        !context ||
        video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA
      ) {
        return;
      }

      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(
        (blob) => {
          if (blob && !stopped) {
            void sendVideoFrame(blob);
          }
        },
        "image/jpeg",
        0.65
      );
    }, VIDEO_INTERVAL_MS);

    const browserWindow = window as Window &
      typeof globalThis & {
        webkitAudioContext?: AudioContextConstructor;
      };
    const AudioContextConstructor =
      browserWindow.AudioContext ?? browserWindow.webkitAudioContext;
    const audioContext =
      AudioContextConstructor && stream.getAudioTracks().length
        ? new AudioContextConstructor()
        : null;
    const source = audioContext?.createMediaStreamSource(stream) ?? null;
    const processor = audioContext?.createScriptProcessor(4096, 1, 1) ?? null;
    const silentOutput = audioContext?.createGain() ?? null;
    let bufferedSamples = new Float32Array();
    let newSamplesSinceLastChunk = 0;
    let sendChain = Promise.resolve();

    const enqueueAudio = (samples: Float32Array) => {
      if (!audioContext || !samples.length) {
        return;
      }
      const wav = encodePcm16Wav(
        downsampleLinear(samples, audioContext.sampleRate, OUTPUT_SAMPLE_RATE),
        OUTPUT_SAMPLE_RATE
      );
      sendChain = sendChain.then(async () => {
        await sendAudioChunk(wav);
      });
    };

    if (audioContext && source && processor && silentOutput) {
      const chunkSize = Math.round(
        audioContext.sampleRate * AUDIO_CHUNK_SECONDS
      );
      const overlapSize = Math.round(
        audioContext.sampleRate * AUDIO_OVERLAP_SECONDS
      );
      silentOutput.gain.value = 0;

      processor.onaudioprocess = (event: AudioProcessingEvent) => {
        if (stopped) {
          return;
        }
        const input = new Float32Array(event.inputBuffer.getChannelData(0));
        bufferedSamples = mergeAudioBuffers([bufferedSamples, input]);
        newSamplesSinceLastChunk += input.length;

        while (true) {
          const next = takeNextAudioChunk(
            bufferedSamples,
            chunkSize,
            overlapSize
          );
          if (!next.chunk) {
            break;
          }
          enqueueAudio(next.chunk);
          bufferedSamples = next.remainder;
          newSamplesSinceLastChunk = Math.max(
            0,
            bufferedSamples.length - overlapSize
          );
        }
      };

      source.connect(processor);
      processor.connect(silentOutput);
      silentOutput.connect(audioContext.destination);
    }

    const stop = () => {
      if (stopPromise) {
        return stopPromise;
      }
      stopPromise = (async () => {
        stopped = true;
        window.clearInterval(videoIntervalId);
        video.pause();
        video.srcObject = null;

        if (processor) {
          processor.onaudioprocess = null;
          processor.disconnect();
        }
        silentOutput?.disconnect();
        source?.disconnect();

        if (newSamplesSinceLastChunk > 0) {
          const finalChunk = takeNextAudioChunk(
            bufferedSamples,
            Number.MAX_SAFE_INTEGER,
            0,
            true
          ).chunk;
          if (finalChunk) {
            enqueueAudio(finalChunk);
          }
        }
        bufferedSamples = new Float32Array();
        newSamplesSinceLastChunk = 0;
        await sendChain;
        if (audioContext && audioContext.state !== "closed") {
          await audioContext.close();
        }
      })();
      return stopPromise;
    };

    stopRef.current = stop;
    return () => {
      void stop();
    };
  }, [isActive, sendAudioChunk, sendVideoFrame, stream]);

  const stopStreaming = useCallback(async () => {
    await stopRef.current();
  }, []);

  return { stopStreaming };
}
