export type MediaPacket = {
  type: 1 | 2; sequence: number; timestampMs: number;
  startSample: number; sampleCount: number; payload: ArrayBuffer;
};

export function encodeMediaV2(packet: MediaPacket): ArrayBuffer {
  const {type, sequence, timestampMs, startSample, sampleCount, payload} = packet;
  if (![sequence, timestampMs, startSample, sampleCount].every(n => Number.isSafeInteger(n) && n >= 0)
      || sequence === 0 || sequence > 0xffffffff || payload.byteLength + 26 > 2 * 1024 * 1024
      || !payload.byteLength || (type !== 1 && type !== 2)
      || (type === 1 && (startSample !== 0 || sampleCount !== 0))
      || (type === 2 && (sampleCount === 0 || sampleCount > 16000 || payload.byteLength !== sampleCount * 2))) {
    throw new Error('올바르지 않은 미디어 패킷입니다.');
  }
  const buffer = new ArrayBuffer(26 + payload.byteLength);
  const view = new DataView(buffer);
  view.setUint8(0, 2); view.setUint8(1, type);
  view.setUint32(2, sequence); view.setBigUint64(6, BigInt(timestampMs));
  view.setBigUint64(14, BigInt(startSample)); view.setUint32(22, sampleCount);
  new Uint8Array(buffer).set(new Uint8Array(payload), 26);
  return buffer;
}
