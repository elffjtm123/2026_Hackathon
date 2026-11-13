# Voice features, experimental affect, and final coaching

Updated 2026-11-13. The user requested the GitHub voice extraction changes, then explicitly requested a circumplex-style multimodal affect prototype and an end-of-session coaching popup.

## Upstream source integrated

Fetched origin/main `e9f87b5`. Applied the voice-delivery commits `e0fdc1c`, `3c83077`, and `66d34d9` (40 changed paths), retaining the local model themes, Windows worker transport, native Qwen Q8, facial features and rPPG integration. This is a voice-feature integration, not a full mirror of unrelated upstream cleanup/authentication commits. No changes were pushed.

Includes `app/modules/delivery/`, frame VAD observations and cut reasons, Praat F0, FFT spectral balance, sentence/window aggregation, report persistence/schema/migration, microphone AGC reporting, AI Hub 71663 preparation/experiment/feature-extraction scripts and upstream tests/design notes. Actual AI Hub data were not downloaded and no emotion/grade model was trained.

Installed `praat-parselmouth` 0.4.7 in the existing venv. SciPy/numpy already existed. Existing SQLite data were backed up and migrated from 0003 to 0004, adding `delivery_metrics` with an empty default for old rows. The original local work and database backup are under ignored `.logs/voice-sync-20261113-115154/`.

## Voice behavior

The same 16 kHz mono PCM used for STT feeds the VAD/frame observer and delivery analyzer. There is no second microphone stream or duplicate STT. Acoustic processing runs in a thread after finalized utterances; failure marks delivery failed without taking the STT worker down. Original PCM is not persisted by this feature.

Outputs: voiced time, Korean syllables, speech rate including pauses, articulation rate excluding pauses, disfluency density, >=250 ms pauses, F0 median, PVQ, dBFS loudness, alpha ratio, Hammarberg index, relative F0 and relative loudness. Sentence rows link to current script progress; non-overlapping 10-second windows share the audio session origin. Window acoustic values require >=1 second of voiced time; the overall `observed` status requires >=60 seconds voiced. Partial results stay explicitly unavailable rather than inventing zeros. No jitter/shimmer/HNR was added.

Browser requests `autoGainControl: false`, reports the actual setting independently after permission acquisition, and does not hold up model preparation. The delivery toggle is locked during a session; the existing guide/hint toggles remain editable.

Authenticated sessions retain upstream end/report persistence. Upstream pipeline live events still exclude delivery features. Since the local demo has no authenticated REST report, its WebSocket wrapper adds sanitized delivery aggregates **only** to its completion response. `DeliveryReport` displays sentence/10-second tables and a user-triggered JSON download after ending. It does not show live voice emotion scores.

## Experimental affect: `circumplex-rules.v1`

This extension follows the user's later request; the upstream design document's earlier no-emotion scope is not a restriction on this new requested prototype. It is not a pretrained or validated affect classifier.

- During running/draining, retain bounded in-memory, timestamped facial samples and distinct actual rPPG estimates. No automatic upload or database storage of these browser signals.
- Only rPPG status `observed`, not provisional/held/ended, age <=6.5 seconds, and a new model-window identity is accepted. Repeated displays of one value are deduplicated. Assign it using its measurement time, not the render time.
- Align browser samples to the backend voice windows. Require face coverage >=50% using 200 ms buckets, at least one new accepted BPM, >=1 second voice and finite positive F0/articulation rate. Comparison intervals shorter than 5 seconds are withheld.
- The first three complete valid 10-second windows establish a personal reference. They are not classified and are not assumed to be physiological rest. Later qualified windows are compared. Missing signals never become neutral emotion.
- Arousal is a weighted heuristic: 45% pulse change, 45% voice change, 10% eye widening. Change scales: 15 BPM, 4 semitones, 25% articulation-rate change, 6 dB. Voice uses F0/speed and loudness only when applied AGC is confirmed off.
- Valence is a facial-movement heuristic: `clip(1.6*mean(smile-frown)-0.25*mean(browDown))`. It is not a direct measure of subjective pleasantness.
- Both axes are clipped to [-1,1]. Axis magnitudes under .2 are labelled neutral/mixed; otherwise the four labels are activated/pleasant, activated/unpleasant, low-activation/pleasant, low-activation/unpleasant, shown in Korean as tendencies. These thresholds/weights are initial engineering choices, not coefficients validated by Russell's paper.
- Overall coordinates and dominant label are duration weighted across classified intervals. The display is radially bounded to the circle. Baseline/missing intervals do not contribute to a score.
- The UI exposes quality/missingness and the criteria, provides per-window selection and JSON export, and identifies the method as experimental. No probability, psychiatric diagnosis, employment eligibility, or ability score is inferred. Self-report labels and held-out user validation are future work.

## Final feedback

`SessionInsights` opens a native dialog after ending, re-openable from the report. It separates experimental affect from coaching based on measured gaze coverage/deviation, existing pace settings (140/360 syllables/min), recognized filler counts and script progress. Missing/disabled inputs are not reported as good measured zero. It offers concrete next-practice actions rather than conclusions about personality or ability. Speech clarity remains a script/STT agreement estimate.

## Evidence and limits

- Full backend regression: 436 passed, 4 platform skips. Existing Starlette/httpx and SciPy deprecation warnings remain.
- Real public Korean audio smoke: Qwen Q8 on Vulkan0 produced a nonempty transcript; delivery observed 2,880 ms voiced, F0 about 268.1 Hz, loudness about -18.0 dBFS, and spectral/window features; completion succeeded and model processes returned idle. Overall delivery status correctly remained unavailable for this short sample. This checks integration, not acoustic/affect accuracy against a sensor or human annotation.
- The real public result is in `tests/fixtures/voice-delivery-public.json`; no user recording is included.
- `tests/session-insights-smoke.html` has explicitly synthetic face/physiology/voice examples for quadrant, missingness and popup UI QA, plus the real public voice result with affect withheld because it has no face/pulse recording. It never requests camera/microphone.
- No actual user's emotional state, true heart rate, or accuracy of full concurrent camera/audio inference was validated. rPPG dropout remains a legitimate reason to withhold the combined estimate.

## References

- [Project upstream](https://github.com/elffjtm123/2026_Hackathon)
- [Russell, A circumplex model of affect (1980)](https://doi.org/10.1037/h0077714)
- [Barrett et al., Emotional Expressions Reconsidered (2019)](https://www.psychologicalscience.org/journals/pspi/1529100619832930/)
- [Praat-Parselmouth](https://github.com/YannickJadoul/Parselmouth)

Model/code/dataset licenses remain their upstream terms; Praat-Parselmouth uses GPLv3-or-later. Research scripts do not grant AI Hub dataset access or imply that the service was trained on it.
