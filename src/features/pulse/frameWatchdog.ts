// Tells a stopped video apart from a face-model worker that is still busy with a frame.
// A first GPU detect can take seconds while shaders compile; that is not a video stall.
export const VIDEO_STALL_MS = 1500;
export const WORKER_HANG_MS = 10000;
/** ok: nothing to do · slow: frame in flight past VIDEO_STALL_MS · stall: idle worker, no new video (once per stall) · hung: frame in flight past WORKER_HANG_MS (once). */
export type FrameWatchVerdict = 'ok' | 'slow' | 'stall' | 'hung';

export class FrameWatchdog {
  private inFlightSince: number | null = null;
  private lastProgress: number;
  private stallReported = false;
  private hangReported = false;
  constructor(now: number) { this.lastProgress = now; }
  get inFlight() { return this.inFlightSince !== null; }
  frameStarted(now: number) { this.inFlightSince = now; this.lastProgress = now; this.stallReported = this.hangReported = false; }
  frameSettled(now: number) { this.inFlightSince = null; this.lastProgress = now; }
  /** After an external reset: a fresh stall window; an in-flight frame stays in flight. */
  restart(now: number) { this.lastProgress = now; this.stallReported = false; }
  check(now: number): FrameWatchVerdict {
    if (this.inFlightSince !== null) {
      if (now - this.inFlightSince <= VIDEO_STALL_MS) return 'ok';
      if (now - this.inFlightSince <= WORKER_HANG_MS || this.hangReported) return 'slow';
      this.hangReported = true;
      return 'hung';
    }
    if (this.stallReported || now - this.lastProgress <= VIDEO_STALL_MS) return 'ok';
    // One reset per stall; the next frame re-arms detection.
    this.stallReported = true;
    return 'stall';
  }
}

export type FaceDelegate = 'GPU' | 'CPU';
// A stuck first GPU detect blocks init before 'ready'; local assets plus shader warm-up normally finish in a few seconds,
// so 15s is ample and keeps the worst case (GPU timeout, then CPU init) at 45s.
export const GPU_INIT_TIMEOUT_MS = 15000;
export const CPU_INIT_TIMEOUT_MS = 30000;
export const initTimeoutMs = (delegate: FaceDelegate) => delegate === 'GPU' ? GPU_INIT_TIMEOUT_MS : CPU_INIT_TIMEOUT_MS;
/** A GPU worker that stops answering, in init or on a frame, gets one CPU retry; a CPU worker or a second hang fails. */
export function unresponsiveWorkerAction(worker: {delegate: FaceDelegate; cpuRetried: boolean}): 'retry-cpu' | 'fail' {
  return worker.delegate === 'GPU' && !worker.cpuRetried ? 'retry-cpu' : 'fail';
}
