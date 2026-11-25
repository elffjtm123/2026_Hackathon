import type {MediaPacket} from '../../lib/mediaProtocol.ts';

// The audio counters belong to the capture and follow the session clock: `sequence` counts packets
// and `startSample` counts 16 kHz samples since capture began. Neither is ever paused or reset by a
// round break (the server acknowledges and drops audio sent during a break, and the first packet
// after it is checked against the sample position, which must not go backwards).
type PcmMessage = {startSample: number; sampleCount: number; payload: ArrayBuffer};
export type AudioPacket = Omit<MediaPacket, 'type' | 'timestampMs'>;

export function createAudioPacketForwarder(send: (packet: AudioPacket) => void) {
  let sequence = 0;
  return (message: PcmMessage) => send({sequence: ++sequence, startSample: message.startSample,
    sampleCount: message.sampleCount, payload: message.payload});
}

export const audioPacketTimestamp = (audioOriginMs: number, startSample: number) =>
  audioOriginMs + Math.floor(startSample * 1000 / 16000);

// `session.running` sets the audio origin and `session.resumed` repeats it; nothing else changes it.
export function audioOriginAfterEvent(event: {event: string; data: Record<string, unknown>}, current: number): number {
  if (event.event !== 'session.running' && event.event !== 'session.resumed') return current;
  const origin = Number(event.data.audio_origin_ms);
  return Number.isFinite(origin) ? origin : current;
}
