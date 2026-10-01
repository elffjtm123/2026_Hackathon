export function mergeAudioBuffers(buffers: Float32Array[]) {
  const length = buffers.reduce((sum, buffer) => sum + buffer.length, 0);
  const merged = new Float32Array(length);
  let offset = 0;
  for (const buffer of buffers) {
    merged.set(buffer, offset);
    offset += buffer.length;
  }
  return merged;
}

export function downsampleLinear(
  input: Float32Array,
  inputRate: number,
  outputRate: number
) {
  if (inputRate <= 0 || outputRate <= 0) {
    throw new RangeError("sample rate must be positive");
  }
  if (!input.length || inputRate === outputRate) {
    return input.slice();
  }

  const outputLength = Math.round(input.length * outputRate / inputRate);
  const output = new Float32Array(outputLength);
  const ratio = inputRate / outputRate;
  for (let index = 0; index < outputLength; index += 1) {
    const position = index * ratio;
    const left = Math.min(Math.floor(position), input.length - 1);
    const right = Math.min(left + 1, input.length - 1);
    const weight = position - left;
    output[index] = input[left] * (1 - weight) + input[right] * weight;
  }
  return output;
}

function writeAscii(view: DataView, offset: number, value: string) {
  for (let index = 0; index < value.length; index += 1) {
    view.setUint8(offset + index, value.charCodeAt(index));
  }
}

export function encodePcm16Wav(samples: Float32Array, sampleRate: number) {
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
    view.setInt16(
      offset,
      clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff,
      true
    );
    offset += bytesPerSample;
  }
  return new Blob([view], { type: "audio/wav" });
}

export function takeNextAudioChunk(
  input: Float32Array,
  chunkSize: number,
  overlapSize: number,
  flush = false
) {
  if (!input.length) {
    return { chunk: null, remainder: new Float32Array() };
  }
  if (input.length < chunkSize) {
    return flush
      ? { chunk: input, remainder: new Float32Array() }
      : { chunk: null, remainder: input };
  }

  const safeOverlap = Math.max(0, Math.min(overlapSize, chunkSize - 1));
  return {
    chunk: input.slice(0, chunkSize),
    remainder: input.slice(chunkSize - safeOverlap),
  };
}

// A bounded, continuous FIR resampler: retain fractional phase across worklet blocks.
export class PcmResampler {
  private samples: number[] = [];
  private offset = 0;
  private received = 0;
  private emitted = 0;
  private readonly ratio: number;
  private readonly cutoff: number;
  private readonly inputRate: number;
  constructor(inputRate: number) {
    this.inputRate = inputRate;
    if (!Number.isFinite(inputRate) || inputRate < 16000) throw new Error('지원하지 않는 샘플링 주파수');
    this.ratio = inputRate / 16000;
    this.cutoff = .45 / this.ratio;
  }
  push(input: Float32Array): Float32Array {
    if (this.inputRate === 16000) return input.slice();
    this.samples.push(...input);
    this.received += input.length;
    return this.read(false);
  }
  flush(): Float32Array {
    if (this.inputRate === 16000) return new Float32Array();
    return this.read(true);
  }
  private read(flush: boolean): Float32Array {
    const output: number[] = [];
    const target = Math.floor(this.received / this.ratio);
    while (this.emitted < target) {
      const position = this.emitted * this.ratio;
      if (!flush && position + 32 >= this.received) break;
      const center = Math.floor(position);
      let value = 0, sum = 0;
      for (let n = center - 31; n <= center + 32; n++) {
        const distance = n - position;
        const sinc = distance === 0 ? 2 * this.cutoff : Math.sin(2 * Math.PI * this.cutoff * distance) / (Math.PI * distance);
        const weight = sinc * (.5 + .5 * Math.cos(Math.PI * distance / 32));
        value += (this.samples[n - this.offset] ?? 0) * weight;
        sum += weight;
      }
      output.push(value / sum);
      this.emitted++;
    }
    const discard = Math.max(0, Math.floor(this.emitted * this.ratio) - 32 - this.offset);
    this.samples.splice(0, discard);
    this.offset += discard;
    return Float32Array.from(output);
  }
}

export function encodePcm16(samples: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  samples.forEach((sample, index) => {
    const clipped = Math.max(-1, Math.min(1, sample));
    view.setInt16(index * 2, clipped < 0 ? clipped * 32768 : clipped * 32767, true);
  });
  return buffer;
}
