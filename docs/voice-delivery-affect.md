# Voice features, voice activation, and final coaching

Updated 2026-11-13. Covers the GitHub voice extraction changes, the end-of-session voice activation chart and the coaching popup. Everything here stays inside the rules of the [voice delivery design](superpowers/specs/2026-10-30-voice-delivery-design.md): no emotion labels, no first-30-second baseline, arousal-side signals only, and only the metrics that design marks as user-facing.

## Upstream source integrated

Fetched origin/main `e9f87b5`. Initially applied the voice-delivery commits `e0fdc1c`, `3c83077`, and `66d34d9` (40 changed paths), retaining the local model themes, Windows worker transport, native Qwen Q8, facial features and rPPG integration. For the requested branch publication, also merged the complete latest main, including its authentication hardening and legacy cleanup, into `codex/multimodal-session-feedback`. The branch is separate from main.

Includes `app/modules/delivery/`, frame VAD observations and cut reasons, Praat F0, FFT spectral balance, sentence/window aggregation, report persistence/schema/migration, microphone AGC reporting, AI Hub 71663 preparation/experiment/feature-extraction scripts and upstream tests/design notes. Actual AI Hub data were not downloaded and no emotion/grade model was trained.

File-based STT comparisons use the same `app.modules.speech.analysis.filler_counts` as the live service. The deleted legacy `stt.py` is no longer a dependency; actual repeated words remain in transcripts and are not added to filler counts.

Installed `praat-parselmouth` 0.4.7 in the existing venv. SciPy/numpy already existed. Existing SQLite data were backed up and migrated from 0003 to 0004, adding `delivery_metrics` with an empty default for old rows. The original local work and database backup are under ignored `.logs/voice-sync-20261113-115154/`.

## Voice behavior

The same 16 kHz mono PCM used for STT feeds the VAD/frame observer and delivery analyzer. There is no second microphone stream or duplicate STT. Acoustic processing runs in a thread after finalized utterances; failure marks delivery failed without taking the STT worker down. Original PCM is not persisted by this feature.

Outputs: voiced time, Korean syllables, speech rate including pauses, articulation rate excluding pauses, disfluency density, >=250 ms pauses, F0 median, PVQ, dBFS loudness, alpha ratio, Hammarberg index, relative F0 and relative loudness. Sentence rows link to current script progress; non-overlapping 10-second windows share the audio session origin. Window acoustic values require >=1 second of voiced time; the overall `observed` status requires >=60 seconds voiced. Partial results stay explicitly unavailable rather than inventing zeros. No jitter/shimmer/HNR was added.

Browser requests `autoGainControl: false`, reports the actual setting independently after permission acquisition, and does not hold up model preparation. The delivery toggle is locked during a session; the existing guide/hint toggles remain editable.

Authenticated sessions retain upstream end/report persistence. Upstream pipeline live events still exclude delivery features. Since the local demo has no authenticated REST report, its WebSocket wrapper adds sanitized delivery aggregates **only** to its completion response. `DeliveryReport` displays sentence/10-second tables and a user-triggered JSON download after ending. It does not show live voice scores.

### What users see (`deliveryForUser`)

The report and its JSON download hide PVQ, absolute loudness (dBFS), alpha ratio and Hammarberg index. These are still computed and stored for analysis, but the design withholds them: PVQ showed no relation to expert ratings, absolute loudness depends on the microphone and room, and spectral balance is not validated. Loudness appears only as `loudness_rel_db`, the change against this session's window baseline, and only when the applied microphone setting reports AGC off (`delivery_metrics.agc_on === false`, set from the `session.audio_settings` event). With AGC on or unreported, no loudness value is shown.

## Voice activation: `voice-activation.v2`

A rule-based, unvalidated description of how the speaker's voice in each 10-second window differs from their own voice in the same session. It names no emotion or inner state, and it is not a classifier.

- **Baseline.** The median of qualified windows that **start at or after 30 s**. Our AI Hub 71663 check found F0 about half a semitone lower in the first 30 s, so an early baseline would push every later window upward. Fewer than 3 eligible windows → the analysis returns `status: 'not-enough-data'` and the UI shows 근거 부족 instead of any number.
- **Qualified window.** At least 5 s observed, at least 1 s voiced, finite positive F0 and articulation rate. A partial first slot is aligned to the end of the slot (its observations end there); other partial slots are aligned to their start. Every qualified window, including those in the first 30 s, is compared against the baseline.
- **Activation.** Voice terms relative to the baseline: F0 change in semitones (scale 4 st, weight .45), articulation-rate change (25%, .35) and loudness change (6 dB, .2, only when AGC is confirmed off). When the face is visible for at least half of the window and the baseline has 3 such windows, eye-widening change adds 10%. Clipped to [-1, 1]; ±.2 or more is shown as 본인 기준보다 목소리 활성도가 높음/낮음, otherwise 비슷함. Weights and thresholds are initial engineering choices.
- **Pulse is not fused.** rPPG accuracy is unvalidated and a pulse rise must not be read as a state. The per-window median BPM is drawn as a separate reference trend labelled 참고용·미검증, on screen only. It is not part of activation and is not in the JSON export (see [pretrained-presentation-pulse.md](pretrained-presentation-pulse.md)).
- **No valence.** Facial smile/frown values are no longer recorded or used; the recorder keeps only timestamped eye-widening values and accepted BPM estimates, bounded and in memory.
- **Export.** `insightsExport` writes the activation analysis without pulse values, the coaching, and the `deliveryForUser` view of the delivery metrics.

## Final feedback

`SessionInsights` opens a native dialog after ending, re-openable from the report. It shows the voice activation result separately from coaching based on measured gaze coverage/deviation, existing pace settings (140/360 syllables/min), recognized filler counts and script progress. Missing/disabled inputs are not reported as good measured zero. It offers concrete next-practice actions rather than conclusions about personality or ability. Speech clarity remains a script/STT agreement estimate.

## Evidence and limits

- Backend regression (`.venv310/bin/python -m pytest -q`) passes with platform-specific skips; existing Starlette/httpx and SciPy deprecation warnings remain.
- Real public Korean audio smoke: Qwen Q8 on Vulkan0 produced a nonempty transcript; delivery observed 2,880 ms voiced, F0 about 268.1 Hz, loudness about -18.0 dBFS, and spectral/window features; completion succeeded and model processes returned idle. Overall delivery status correctly remained unavailable for this short sample. This checks integration, not acoustic/affect accuracy against a sensor or human annotation.
- The real public result is in `tests/fixtures/voice-delivery-public.json`; no user recording is included.
- `tests/session-insights-smoke.html` has synthetic eye-openness/pulse/voice examples (voice activation above, below and similar to the baseline, too little data after 30 s, missing pulse) for popup UI QA, plus the real public voice result (too short for a baseline, so activation is withheld). It never requests camera/microphone.
- No true heart rate, relation of voice activation to any human rating, or accuracy of full concurrent camera/audio inference was validated.

## References

- [Project upstream](https://github.com/elffjtm123/2026_Hackathon)
- [Barrett et al., Emotional Expressions Reconsidered (2019)](https://www.psychologicalscience.org/journals/pspi/1529100619832930/)
- [Praat-Parselmouth](https://github.com/YannickJadoul/Parselmouth)

Model/code/dataset licenses remain their upstream terms; Praat-Parselmouth uses GPLv3-or-later. Research scripts do not grant AI Hub dataset access or imply that the service was trained on it.
