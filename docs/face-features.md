# Presentation facial movement features

The full practice page now extracts visible facial movement from its existing presentation video. This is feature extraction, not emotion recognition, medical diagnosis, or an interview score.

## Shared execution

- `PracticePage` passes its existing `presentationVideo` to `PulsePanel`/`usePulse`. No additional camera permission, camera stream, or face model instance is created for expressions.
- The existing browser worker enables `outputFaceBlendshapes` and `outputFacialTransformationMatrixes` on MediaPipe Face Landmarker. It keeps `numFaces: 2` so multiple faces can be rejected rather than mixing their features.
- Uses existing local `face_landmarker.task` and `@mediapipe/tasks-vision` 1.2.0/WASM assets. No runtime CDN or extra pretrained model download is required.
- GPU delegate is preferred while expression extraction is enabled; initialization failure falls back to CPU. CPU fallback budgets detector calls to leave time for RGB sampling. The UI reports observed analysis frequency and warns below 10 Hz because brief blinks can be missed.
- The face detector targets approximately 15 Hz, with UI updates limited to about 5 Hz. These are targets, not guarantees. The reported frequency is the actual processed observation rate.
- rPPG consumes RGB from the same worker. Turning pulse analysis off does not restart the expression tracker, and pulse model availability failure does not terminate expression extraction. Toggling expression extraction or changing the selected pulse model recreates the shared worker, beginning a new observation segment.
- Existing backend gaze/STT adapters, scoring and transport contracts are unchanged.

## Output and missingness

`src/features/face-features/features.ts` defines `face-features.v1`:

- All 52 named MediaPipe coefficients in the documented 0–1 range. They are not probabilities of emotion and are not interchangeable with FACS Action Units.
- Current head yaw/pitch/roll derived from the column-major transformation matrix, independently of eye/face movement coefficients. Does not replace MobileGaze.
- Capture media timestamp and the same session clock used by the existing WebSocket client.
- Face count, brightness, face pixel dimensions and quality flags. Rejects missing/multiple faces, invalid or incomplete coefficients, small/clipped faces, extreme head pose and unusable lighting. These are heuristic input checks, not calibrated accuracy confidence.
- Latest 10-second coefficient means, standard deviations and end-minus-start changes. These describe sampled frames, not an evenly sampled physiological signal.
- Valid-time coverage and eye-closed fraction based on observed intervals no longer than 200 ms. Unobserved time is not counted as open eyes or zero movement.
- Observed bilateral blink count: open <=0.25, closed >=0.55, close-to-reopen duration 50–800 ms. A gap, face loss or long closure interrupts the event. Thresholds are experimental and need user-video validation.
- Window blink rate is withheld until at least 5 seconds of valid time. It is a short-window extrapolation, not a session-wide measured rate.
- Head angular change per second from consecutive valid poses. Camera movement and tracking jitter can affect this proxy.

The hook marks results stale after 1.5 seconds without updates and clears current coefficients. Hidden tabs and ended camera tracks interrupt observation. Ending practice preserves only the final observation window in page memory and labels it ended; it does not claim a session average. Starting a new stream clears the previous segment. Features are not automatically persisted, transmitted to backend, or written to a report/database.

## UI / integration

The practice page includes an enabled-by-default “발표 중 표정 특징” panel for presentation and interview modes. It shows current eye/brow/mouth movements, observed blinks, valid-time coverage, a manually selected comparison baseline, and an expandable 52-feature table.

“특징 JSON 내려받기” explicitly downloads a snapshot (`presentation-features.v1`) containing the facial window and separately timestamped gaze/speech/pulse observations. It is not a full-session recording or a prealigned training sample. Historical rPPG is kept in a separately labelled field; stale gaze/utterance values are not exposed as current. Speech rate describes the last processed utterance, not instantaneous vocal activity. Raw video/audio and transcript are not included.

## Validation

- Feature tests cover all 52 coefficients, rolling time coverage, missing values, partial outputs, bilateral blink sequences, prolonged closure, dropped frames, pose matrix convention and stale multimodal snapshots.
- Worker regression uses the production worker with controlled detector outputs to verify feature extraction while pulse is off, GPU-to-CPU initialization fallback, and current-value clearing after face loss.
- `tests/pretrained-presentation-smoke.html` uses a public MediaPipe portrait with synthetic colour modulation and the real local MediaPipe model plus actual ONNX pulse API. This checks model/UI integration only. A static portrait does not validate real blinking, emotion, or biological pulse accuracy.
- No user camera or microphone is used for automated validation. Real user-video annotated blink/landmark evaluation and concurrent full STT/gaze workload measurements remain necessary.

## Sources

- [MediaPipe Face Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker)
- [Blendshape names](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/drawing_styles/face_landmarker/Blendshapes)
- [MediaPipe repository](https://github.com/google-ai-edge/mediapipe)

Existing local model/MediaPipe license notices continue to apply; see `public/PULSE-NOTICES.txt` and `public/pulse-licenses/`.
