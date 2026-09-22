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
