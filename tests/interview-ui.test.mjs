import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const cacheDir = await mkdtemp(join(tmpdir(), "interview-ui-vite-"));
const server = await createServer({
  configFile: false,
  cacheDir,
  esbuild: { jsx: "automatic" },
  server: { middlewareMode: true, hmr: false, ws: false },
  optimizeDeps: { noDiscovery: true },
});
after(async () => {
  await server.close();
  await rm(cacheDir, { recursive: true, force: true });
});

test("면접 종료는 영상 옆에서만 할 수 있고 발표 종료 버튼은 유지된다", async () => {
  const { SessionControls } = await server.ssrLoadModule(
    "/src/features/practice/components/SessionControls.tsx"
  );
  const props = {
    isRunning: true,
    isStarting: false,
    isStopping: false,
    elapsedSeconds: 42,
    onModeChange() {},
    onStart() {},
    onEnd() {},
  };

  const interview = renderToStaticMarkup(
    createElement(SessionControls, { ...props, mode: "interview" })
  );
  const presentation = renderToStaticMarkup(
    createElement(SessionControls, { ...props, mode: "presentation" })
  );

  assert.doesNotMatch(interview, />종료<\/button>/);
  assert.match(presentation, />종료<\/button>/);
});

test("면접은 진행 화면과 실제 세션 결과 화면을 구분한다", async () => {
  const { InterviewContent } = await server.ssrLoadModule(
    "/src/features/practice/components/InterviewContent.tsx"
  );
  const props = {
    stream: null,
    feedback: { gaze: null, speech: null, pronunciation: null },
    connectionStatus: "idle",
    socketError: null,
    isRunning: true,
    isStopping: false,
    onEnd() {},
    summary: null,
  };

  const live = renderToStaticMarkup(createElement(InterviewContent, props));
  assert.match(live, /질문이 여기에 표시됩니다/);
  assert.match(live, /카메라 프리뷰/);
  assert.match(live, />면접 종료<\/button>/);

  const report = renderToStaticMarkup(
    createElement(InterviewContent, {
      ...props,
      isRunning: false,
      summary: {
        sessionId: "session-1",
        durationSeconds: 42,
        gazeAwayRatio: 0.25,
        pronunciationAccuracy: null,
        speechPaceWarningCount: 1,
        averageSyllablesPerMinute: 280,
        fillerWordCounts: { 음: 2 },
        transcript: "실제로 인식된 답변",
        incomplete: false,
      },
    })
  );
  assert.match(report, /실제로 인식된 답변/);
  assert.match(report, /질문별 결과/);
  assert.match(report, /tabindex="-1"[^>]*>면접 연습 결과<\/h2>/);
  assert.doesNotMatch(report, /<video/);
});
