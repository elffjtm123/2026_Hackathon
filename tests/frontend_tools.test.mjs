import assert from "node:assert/strict";
import test from "node:test";

import * as scriptTools from "../src/features/practice/scriptTools.ts";
import * as socketTools from "../src/features/practice/hooks/useFeedbackSocket.ts";
import * as feedbackState from "../src/features/practice/feedbackState.ts";
import * as audioTools from "../src/features/practice/audioTools.ts";
import * as lifecycle from "../src/features/practice/sessionLifecycle.ts";
import * as mediaTools from "../src/features/practice/hooks/useUserMedia.ts";

test("받아쓰기 청크를 중복 없이 순서대로 누적한다", () => {
  assert.equal(typeof scriptTools.appendTranscript, "function");
  assert.equal(scriptTools.appendTranscript("", "  안녕하세요.  "), "안녕하세요.");
  assert.equal(
    scriptTools.appendTranscript("안녕하세요.", "저는 개발자입니다."),
    "안녕하세요. 저는 개발자입니다."
  );
  assert.equal(
    scriptTools.appendTranscript("안녕하세요.", "안녕하세요."),
    "안녕하세요."
  );
  assert.equal(
    scriptTools.appendTranscript("안녕하세요.", "안녕하세요. 저는 개발자입니다."),
    "안녕하세요. 저는 개발자입니다."
  );
  assert.equal(
    scriptTools.appendTranscript("안녕하세요. 저는", "저는 개발자입니다."),
    "안녕하세요. 저는 개발자입니다."
  );
});

test("주요 단어는 일반적인 서술어가 아니라 현재 문장의 핵심어를 고른다", () => {
  const sentence = ["실시간", "면접", "피드백은", "시선과", "발화", "속도를", "분석합니다."];
  const script =
    "실시간 면접 피드백은 시선과 발화 속도를 분석합니다. " +
    "실시간 시스템은 WebRTC로 영상을 전달합니다.";

  assert.equal(scriptTools.selectAttentionKeyword(sentence, script), "면접");
});

test("인사말과 일반적인 서술어는 주요 단어에서 제외한다", () => {
  const sentence = ["안녕하세요.", "오늘은", "실시간", "피드백", "서비스를", "소개하겠습니다."];
  const script =
    "안녕하세요. 오늘은 실시간 피드백 서비스를 소개하겠습니다. " +
    "이 서비스는 시선과 발화 속도를 분석합니다.";

  assert.equal(scriptTools.selectAttentionKeyword(sentence, script), "실시간");
});

test("session.end를 ping이 아닌 백엔드 종료 이벤트로 변환한다", () => {
  assert.deepEqual(
    socketTools.toBackendEvent({
      type: "session.end",
      sessionId: "session-1",
      timestamp: 1234,
    }),
    {
      event: "session.end",
      timestamp_ms: 1234,
      data: { sessionId: "session-1" },
    }
  );
});

test("발화 피드백이 마지막 시선 상태를 덮어쓰지 않는다", () => {
  const gaze = {
    type: "feedback",
    sessionId: "s",
    source: "gaze",
    timestamp: 1,
    severity: "warning",
    gaze: {
      status: "left",
      faceDetected: true,
      headPose: { yaw: -18, pitch: 0, roll: 0 },
      direction: "left",
      attentionState: "away",
      quality: 0.9,
      confidence: 0.88,
      calibrated: true,
      message: "왼쪽",
    },
  };
  const speech = {
    type: "feedback",
    sessionId: "s",
    source: "speech_rate",
    timestamp: 2,
    severity: "info",
    speech: { pace: "normal", message: "적절" },
    filler: { totalCount: 0, counts: {} },
  };
  const afterGaze = feedbackState.reduceFeedback(
    feedbackState.emptyFeedbackState,
    gaze
  );
  const afterSpeech = feedbackState.reduceFeedback(afterGaze, speech);
  assert.equal(afterSpeech.gaze?.gaze?.status, "left");
  assert.equal(afterSpeech.gaze?.gaze?.calibrated, true);
  assert.equal(afterSpeech.speech?.speech?.pace, "normal");
});

test("출처 없는 임의 피드백은 실제 분석 상태를 바꾸지 않는다", () => {
  const fake = {
    type: "feedback",
    sessionId: "s",
    timestamp: 1,
    severity: "warning",
    gaze: { status: "away" },
    speech: { pace: "fast" },
  };

  assert.deepEqual(
    feedbackState.reduceFeedback(feedbackState.emptyFeedbackState, fake),
    feedbackState.emptyFeedbackState
  );
});

test("48 kHz mono 입력을 16 kHz WAV로 변환한다", async () => {
  const input = Float32Array.from({ length: 48_000 }, (_, index) =>
    Math.sin(index / 20)
  );
  const output = audioTools.downsampleLinear(input, 48_000, 16_000);
  const wav = audioTools.encodePcm16Wav(output, 16_000);
  const view = new DataView(await wav.arrayBuffer());

  assert.equal(output.length, 16_000);
  assert.equal(view.getUint32(24, true), 16_000);
  assert.equal(view.getUint16(22, true), 1);
});

test("44.1 kHz 입력도 16 kHz 길이로 변환한다", () => {
  const output = audioTools.downsampleLinear(
    new Float32Array(44_100),
    44_100,
    16_000
  );
  assert.equal(output.length, 16_000);
});

test("종료 flush는 2초보다 짧은 마지막 샘플도 청크로 반환한다", () => {
  const input = new Float32Array(12_000);
  const { chunk, remainder } = audioTools.takeNextAudioChunk(
    input,
    96_000,
    12_000,
    true
  );

  assert.equal(chunk?.length, 12_000);
  assert.equal(remainder.length, 0);
});

test("세션 종료는 미디어 flush 후 완료 응답을 기다린다", async () => {
  const calls = [];
  const report = {
    transcript: "마지막 답변",
    gaze: { awayCount: 0, awayDurationMs: 0 },
    speech: { averageSyllablesPerMinute: 0 },
    filler: { counts: {} },
    incomplete: false,
  };

  const result = await lifecycle.completePracticeSession({
    flushMedia: async () => {
      calls.push("flush");
    },
    closeMedia: () => {
      calls.push("media");
    },
    requestCompletion: async () => {
      calls.push("complete");
      return report;
    },
    closeSocket: () => {
      calls.push("socket");
    },
  });

  assert.deepEqual(calls, ["flush", "media", "complete", "socket"]);
  assert.equal(result, report);
});

test("카메라 권한 거부를 사용자가 이해할 수 있게 알린다", () => {
  assert.equal(
    mediaTools.mediaErrorMessage(
      new DOMException("Permission denied", "NotAllowedError")
    ),
    "카메라와 마이크 권한이 필요합니다. 브라우저 설정에서 권한을 허용해 주세요."
  );
});
