import { encodePcm16, mergeAudioBuffers, PcmResampler } from './audioTools';

declare const sampleRate: number;
declare class AudioWorkletProcessor { port: MessagePort; }
declare function registerProcessor(name: string, processor: typeof AudioWorkletProcessor): void;

class PcmCapture extends AudioWorkletProcessor {
  private resampler = new PcmResampler(sampleRate);
  private buffer = new Float32Array();
  private startSample = 0;
  private stopped = false;
  constructor() {
    super();
    this.port.onmessage = () => {
      this.stopped = true;
      this.append(this.resampler.flush());
      this.send(this.buffer.length);
      this.port.postMessage({event: 'flushed'});
    };
  }
  private append(samples: Float32Array) {
    this.buffer = mergeAudioBuffers([this.buffer, samples]);
    while (this.buffer.length >= 3200) this.send(3200);
  }
  private send(count: number) {
    if (!count) return;
    const payload = encodePcm16(this.buffer.slice(0, count));
    this.port.postMessage({event: 'pcm', startSample: this.startSample, sampleCount: count, payload}, [payload]);
    this.startSample += count;
    this.buffer = this.buffer.slice(count);
  }
  process(inputs: Float32Array[][]) {
    if (!this.stopped && inputs[0]?.[0]) this.append(this.resampler.push(inputs[0][0]));
    return true;
  }
}
registerProcessor('pcm-capture', PcmCapture);
