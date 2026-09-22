import assert from "node:assert/strict";
import test from "node:test";

import * as scriptTools from "../src/features/practice/scriptTools.ts";
import * as socketTools from "../src/features/practice/hooks/useFeedbackSocket.ts";

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
