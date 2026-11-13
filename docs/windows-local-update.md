# Windows local integration (2026-10-16)

Upstream integrated: `c677d2f` (origin/main). All five upstream commits since
`3c514d3` are included; no changes were pushed to GitHub.

## Included changes

- speech.cpp 0.8.8 / C API 3, Qwen3-ASR-0.6B Q8_0, VAD utterance segmentation.
- Transcript energy/length safety checks, actual repetitions retained.
- Grouped script summaries, editable hints and actual-STT-based progression.
- Exclusive summary/realtime process ownership and cancellation-safe cleanup.
- Nullable report v2 fields and preserved incomplete state; old DB rows retained.
- Internal speech pace/volume change detector remains internal, as upstream specifies.
  It is NOT an emotion/stress classifier and is not displayed as a new score.

## Local adaptations

- Windows native STT DLL and Vulkan device reporting; Intel Arc is detected.
- Authenticated loopback IPC replaces Unix sockets on Windows only. A random
  per-launch token is passed through the child's environment and checked before
  any model settings/media are exchanged. Unix behavior remains unchanged.
- Windows Python venv redirector is bypassed while retaining the venv context,
  so the PID owned and reaped by the backend is the actual model process.
- Child model consoles are hidden. No camera/microphone permissions are granted
  by update scripts; automated smoke tests use the existing public audio fixture.
- Existing model themes and fixed-recording comparison remain available. Live
  candidates reuse current safety checks and final-utterance postprocessing.
  The baseline is now the current native Q8 service, NOT the old FP32 model.
- Live comparisons use VAD utterances; file experiments still use fixed chunks.
  Candidate comparisons can include the shared realtime Q8/gaze worker in RAM;
  their RSS is not a standalone-model memory measurement.

## Local startup

Run `npm run dev:backend` and `npm run dev -- --host 127.0.0.1` in this folder.
Open `http://127.0.0.1:5173/#practice/service_qwen` for the current service,
`http://127.0.0.1:5173/#models` for preserved model themes, or
`http://127.0.0.1:5173/#stt-experiments` for fixed-recording comparisons.
Model status is `idle` while unused; real weights load when practice starts,
then are released after draining the last utterance.

Runtime/model paths are configured in the ignored local `.env`. No credentials
are included here. speech.cpp uses `.models/speech/v0.8.8-win/speech.dll`;
the summary server uses `.models/llama-win-vulkan/b11429/llama-server.exe`.

Verified local assets (SHA-256, compared with publisher metadata):

- Native STT: sakasegawa/Qwen3-ASR-0.6B-GGUF, revision
  `ee78f8709547f39bea3b924a16c72403826cac92`, 841,502,336 bytes,
  `416e10c15b4a3d9002bd337d18fc450233fdf68502b6e10d1379d2789838afd0`.
- Summary: unsloth/Qwen3.5-9B-GGUF, revision
  `3885219b6810b007914f3a7950a8d1b469d598a5`, 5,680,522,464 bytes,
  `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`.
- Runtime releases: speech.cpp v0.8.8 Windows x64 Vulkan and llama.cpp b11429
  Windows x64 Vulkan. The STT and summary models are different models with
  different jobs; the 0.6B ASR is not used as a text summarizer.

## Recovery

Original edited files and the pre-migration SQLite database are preserved under
`../sync-backups/20261016-170252/`. Git stash
`pre-upstream-sync-20261016-local-model-themes` is retained as an additional backup.
Do not re-apply it over this integration without inspecting differences.

Database schema was inspected against the prior metadata, stamped at revision
0002, then migrated to 0003. The original unversioned database was auto-created;
no historical rows were deleted or replaced.

## Validation

`npm run build`, `node --test tests/*.test.mjs`, `.venv/Scripts/python.exe -m pytest`.
For actual-model smoke testing (public fixture only):
`.venv/Scripts/python.exe scripts/smoke_updated_service.py`.
Camera direction accuracy and real microphone performance still require a user
field check; successful loading/tests do not establish measurement accuracy.

Integration test result: backend 310 passed / 3 platform-specific skipped;
frontend 49 passed; production build passed. The public-audio WebSocket smoke
test produced an actual transcript, observed speech metrics and a complete
report, and returned the realtime worker to idle afterward.

Actual browser check: default public demo script (3 sentences) produced one
editable summary group in 27.58 seconds with Qwen3.5-9B Q4_K_M. The summary
server exited after generation. A subsequent real WebSocket audio smoke test
loaded Q8 on Vulkan0, completed its transcript/report, and released the worker.
This single demo timing is a functional smoke result, not a performance benchmark.
