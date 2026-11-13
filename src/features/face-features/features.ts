// MediaPipe coefficients describe visible movement, not emotion probabilities or FACS AUs.
export const blendshapeNames = [
  '_neutral', 'browDownLeft', 'browDownRight', 'browInnerUp', 'browOuterUpLeft', 'browOuterUpRight',
  'cheekPuff', 'cheekSquintLeft', 'cheekSquintRight', 'eyeBlinkLeft', 'eyeBlinkRight',
  'eyeLookDownLeft', 'eyeLookDownRight', 'eyeLookInLeft', 'eyeLookInRight', 'eyeLookOutLeft',
  'eyeLookOutRight', 'eyeLookUpLeft', 'eyeLookUpRight', 'eyeSquintLeft', 'eyeSquintRight',
  'eyeWideLeft', 'eyeWideRight', 'jawForward', 'jawLeft', 'jawOpen', 'jawRight', 'mouthClose',
  'mouthDimpleLeft', 'mouthDimpleRight', 'mouthFrownLeft', 'mouthFrownRight', 'mouthFunnel',
  'mouthLeft', 'mouthLowerDownLeft', 'mouthLowerDownRight', 'mouthPressLeft', 'mouthPressRight',
  'mouthPucker', 'mouthRight', 'mouthRollLower', 'mouthRollUpper', 'mouthShrugLower',
  'mouthShrugUpper', 'mouthSmileLeft', 'mouthSmileRight', 'mouthStretchLeft', 'mouthStretchRight',
  'mouthUpperUpLeft', 'mouthUpperUpRight', 'noseSneerLeft', 'noseSneerRight',
] as const;

export type FeatureStatus = 'waiting' | 'observed' | 'unavailable' | 'stale' | 'ended' | 'off';
export type FeaturePose = {yaw: number; pitch: number; roll: number};
export type FaceFeatures = {
  schema: 'face-features.v1'; source: 'mediapipe-face-landmarker'; status: FeatureStatus; reason: string;
  timestampMs: number | null; mediaTimeMs: number | null; faceCount: number;
  coefficients: Record<string, number> | null; headPose: FeaturePose | null;
  quality: {brightness: number | null; faceWidthPx: number | null; faceHeightPx: number | null; flags: string[]};
  window: {startMs: number | null; endMs: number | null; durationSeconds: number; validSeconds: number;
    coverage: number; sampleCount: number; observedFps: number; mean: Record<string, number>;
    std: Record<string, number>; change: Record<string, number>; closedEyeRatio: number | null;
    blinkCount: number; blinksPerMinute: number | null; headMotionDegreesPerSecond: number | null};
  totalBlinks: number;
  delegate?: 'CPU' | 'GPU';
};

export function emptyFaceFeatures(reason = '연습을 시작하면 같은 발표 영상에서 표정 특징을 추출합니다.',
  status: FeatureStatus = 'waiting'): FaceFeatures {
  return {schema: 'face-features.v1', source: 'mediapipe-face-landmarker', status, reason,
    timestampMs: null, mediaTimeMs: null, faceCount: 0, coefficients: null, headPose: null,
    quality: {brightness: null, faceWidthPx: null, faceHeightPx: null, flags: []},
    window: {startMs: null, endMs: null, durationSeconds: 0, validSeconds: 0, coverage: 0,
      sampleCount: 0, observedFps: 0, mean: {}, std: {}, change: {}, closedEyeRatio: null,
      blinkCount: 0, blinksPerMinute: null, headMotionDegreesPerSecond: null}, totalBlinks: 0};
}

type Point = {x: number; y: number};
type Detection = {faceLandmarks?: Point[][];
  faceBlendshapes?: {categories: {categoryName: string; score: number}[]}[];
  facialTransformationMatrixes?: {data: ArrayLike<number>}[]};
type Sample = {time: number; session: number; values: Record<string, number> | null;
  pose: FeaturePose | null; weight: number; closed: boolean};
const round = (value: number) => Math.round(value * 10000) / 10000;

export function featurePose(data?: ArrayLike<number>): FeaturePose | null {
  if (!data || data.length !== 16 || Array.from(data).some(v => !Number.isFinite(v))) return null;
  // MediaPipe's Web matrix is column-major. Normalize per-axis scale before Euler extraction.
  const sx = Math.hypot(data[0], data[1], data[2]), sy = Math.hypot(data[4], data[5], data[6]);
  const sz = Math.hypot(data[8], data[9], data[10]);
  if (Math.min(sx, sy, sz) < 1e-6) return null;
  const deg = 180 / Math.PI;
  return {yaw: round(Math.asin(Math.max(-1, Math.min(1, data[2] / sx))) * deg),
    pitch: round(-Math.atan2(data[6] / sy, data[10] / sz) * deg),
    roll: round(Math.atan2(data[1] / sx, data[0] / sx) * deg)};
}

export class FaceFeatureTracker {
  private samples: Sample[] = [];
  private blinks: number[] = [];
  private total = 0;
  private started: number | null = null;
  private last: number | null = null;
  private wasValid = false;
  private openSeen = false;
  private closeStart: number | null = null;
  private lastResult: FaceFeatures = emptyFaceFeatures();

  interrupt(): void {
    this.wasValid = false; this.openSeen = false; this.closeStart = null;
  }

  add(result: Detection, time: number, session: number, width: number, height: number,
    brightness: number | null): FaceFeatures {
    if (!Number.isFinite(time) || !Number.isFinite(session) || (this.last !== null && time <= this.last)) {
      this.interrupt();
      return {...this.lastResult, status: 'unavailable', reason: '영상 시각이 갱신되지 않았습니다.', coefficients: null, headPose: null};
    }
    const dt = this.last === null ? 0 : time - this.last;
    this.last = time; this.started ??= time;
    if (dt > 200) this.interrupt();
    const faces = result.faceLandmarks ?? [], flags: string[] = [];
    let fw: number | null = null, fh: number | null = null;
    if (faces.length !== 1) flags.push(faces.length ? 'multiple_faces' : 'no_face');
    if (faces.length === 1) {
      const face = faces[0];
      if (face.length < 468 || face.some(p => !Number.isFinite(p.x) || !Number.isFinite(p.y))) flags.push('invalid_landmarks');
      else {
        const xs = face.map(p => p.x), ys = face.map(p => p.y);
        fw = (Math.max(...xs) - Math.min(...xs)) * width;
        fh = (Math.max(...ys) - Math.min(...ys)) * height;
        if (fw < 40 || fh < 48) flags.push('face_too_small');
        if (Math.min(...xs) < -.02 || Math.max(...xs) > 1.02 || Math.min(...ys) < -.02 || Math.max(...ys) > 1.02) flags.push('face_outside');
      }
    }
    if (brightness === null || !Number.isFinite(brightness)) flags.push('brightness_unavailable');
    else if (brightness < 18 || brightness > 235) flags.push('lighting');
    const categories = result.faceBlendshapes?.[0]?.categories ?? [];
    const values: Record<string, number> = {};
    for (const v of categories) if (Number.isFinite(v.score) && v.score >= 0 && v.score <= 1) values[v.categoryName] = v.score;
    if (blendshapeNames.some(name => values[name] === undefined)) flags.push('coefficients_unavailable');
    const pose = faces.length === 1 ? featurePose(result.facialTransformationMatrixes?.[0]?.data) : null;
    if (pose && (Math.abs(pose.yaw) > 45 || Math.abs(pose.pitch) > 40)) flags.push('large_pose');
    const valid = flags.length === 0;
    const weight = valid && this.wasValid && dt <= 200 ? dt : 0;
    if (!valid) this.interrupt();
    let closed = false;
    if (valid) {
      closed = Math.min(values.eyeBlinkLeft, values.eyeBlinkRight) >= .55;
      const opened = Math.max(values.eyeBlinkLeft, values.eyeBlinkRight) <= .25;
      if (closed && this.openSeen && this.closeStart === null) this.closeStart = time;
      if (opened) {
        if (this.closeStart !== null && time - this.closeStart >= 50 && time - this.closeStart <= 800) {
          this.total++; this.blinks.push(time);
        }
        this.closeStart = null; this.openSeen = true;
      }
      if (this.closeStart !== null && time - this.closeStart > 800) { this.closeStart = null; this.openSeen = false; }
    }
    this.wasValid = valid;
    this.samples.push({time, session, values: valid ? values : null, pose: valid ? pose : null, weight, closed});
    this.samples = this.samples.filter(v => v.time > time - 10000).slice(-300);
    this.blinks = this.blinks.filter(v => v > time - 10000);
    const usable = this.samples.filter(v => v.values !== null);
    const mean: Record<string, number> = {}, std: Record<string, number> = {}, change: Record<string, number> = {};
    for (const name of blendshapeNames) if (usable.length) {
      const series = usable.map(v => v.values![name]), avg = series.reduce((a, b) => a + b, 0) / series.length;
      mean[name] = round(avg); std[name] = round(Math.sqrt(series.reduce((sum, v) => sum + (v - avg) ** 2, 0) / series.length));
      change[name] = round(series.at(-1)! - series[0]);
    }
    const start = Math.max(this.started, time - 10000), span = time - start;
    const weightInWindow = (v: Sample) => Math.min(v.weight, Math.max(0, v.time - start));
    const validMs = this.samples.reduce((sum, v) => sum + weightInWindow(v), 0);
    const closedMs = this.samples.reduce((sum, v) => sum + (v.closed ? weightInWindow(v) : 0), 0);
    let motion = 0, motionMs = 0;
    for (let i = 1; i < this.samples.length; i++) {
      const a = this.samples[i - 1], b = this.samples[i];
      if (a.pose && b.pose && b.weight > 0) {
        motion += Math.hypot(b.pose.yaw - a.pose.yaw, b.pose.pitch - a.pose.pitch, b.pose.roll - a.pose.roll);
        motionMs += b.time - a.time;
      }
    }
    const reasons: Record<string, string> = {no_face: '얼굴을 찾지 못했습니다.', multiple_faces: '한 명의 얼굴만 화면에 들어오도록 해 주세요.',
      face_too_small: '얼굴이 작습니다. 카메라에 조금 가까이 와 주세요.', lighting: '얼굴 밝기를 확인해 주세요.',
      large_pose: '얼굴 각도가 커 표정 특징을 보류합니다.', face_outside: '얼굴 전체가 보이도록 해 주세요.'};
    this.lastResult = {schema: 'face-features.v1', source: 'mediapipe-face-landmarker',
      status: valid ? 'observed' : 'unavailable', reason: valid ? '같은 발표 영상에서 표정 움직임을 관찰하고 있습니다.' : reasons[flags[0]] ?? '표정 특징을 추출할 수 없습니다.',
      timestampMs: session, mediaTimeMs: time, faceCount: faces.length,
      coefficients: valid ? Object.fromEntries(blendshapeNames.map(name => [name, round(values[name])])) : null,
      headPose: valid ? pose : null,
      quality: {brightness, faceWidthPx: fw, faceHeightPx: fh, flags}, totalBlinks: this.total,
      window: {startMs: session - span, endMs: session, durationSeconds: span / 1000, validSeconds: validMs / 1000,
        coverage: span > 0 ? Math.min(1, validMs / span) : 0, sampleCount: usable.length,
        observedFps: span > 0 ? Math.max(0, this.samples.length - 1) * 1000 / span : 0,
        mean, std, change, closedEyeRatio: validMs >= 1000 ? closedMs / validMs : null,
        blinkCount: this.blinks.length, blinksPerMinute: validMs >= 5000 ? this.blinks.length * 60000 / validMs : null,
        headMotionDegreesPerSecond: motionMs >= 1000 ? motion * 1000 / motionMs : null}};
    return this.lastResult;
  }
}
