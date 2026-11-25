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
test('대본 옆 요약 버튼과 아래 문장별 수정 결과가 표시된다', async () => {
  const {PresentationSetup} = await server.ssrLoadModule('/src/features/practice/components/PresentationSetup.tsx');
  const props = {script:'서비스를 소개합니다. 원본은 저장하지 않습니다.',
    timeLimitSeconds:60,disabled:false,onScriptChange(){},onTimeLimitChange(){},
    groups:[{start_sentence:0,end_sentence:1,original:'서비스를 소개합니다. 원본은 저장하지 않습니다.',hint:'서비스 소개 · 원본 미저장',error:null}],onHintChange(){},
    onSummarize(){},isSummarizing:false,summaryError:null,summaryProgress:null,summarySeconds:1.2};
  const markup = renderToStaticMarkup(createElement(PresentationSetup, props));
  assert.match(markup, /요약 시작|다시 요약/);
  assert.ok(markup.indexOf('id="presentation-script"') < markup.indexOf('서비스 소개'));
  assert.match(markup, /AI 초안/);
  assert.match(markup, /원본 미저장/);
  assert.match(markup, /<details[^>]*open=""/);
  assert.match(markup, /<summary[^>]*>.*묶음 요약본/);
  assert.match(markup, /1~2번 문장/);
  assert.equal((markup.match(/묶음 요약 힌트/g)??[]).length,1);
  const pending = renderToStaticMarkup(createElement(PresentationSetup, {...props,isSummarizing:true,
    summaryProgress:{stage:'generating',completed_sentences:1,total_sentences:2,failed_sentences:0}}));
  assert.doesNotMatch(pending, /Qwen3.5-9B/);
  assert.match(pending, /원문 2문장 중 1문장 처리/);
  assert.match(pending, /<progress[^>]*max="2"[^>]*value="1"/);
  assert.match(pending, /<button[^>]*disabled=""[^>]*>요약 중/);
  const {SessionControls} = await server.ssrLoadModule('/src/features/practice/components/SessionControls.tsx');
  const controls = renderToStaticMarkup(createElement(SessionControls, {mode:'presentation',
    isRunning:false,isStarting:false,isStopping:false,elapsedSeconds:0,
    onModeChange(){},onStart(){},onEnd(){},startBlocked:true}));
  assert.match(controls, /<button[^>]*class="primary-button"[^>]*disabled=""/);
});
after(async () => {
  await server.close();
  await rm(cacheDir, { recursive: true, force: true });
});

test('요약 진행 스트림은 잘린 UTF-8과 여러 프레임을 처리하고 완료 전 중단을 거부한다', async () => {
  const {readSummaryStream} = await server.ssrLoadModule('/src/features/practice/scriptSummary.ts');
  const script='문제입니다. 해결했습니다.';
  const result={normalized_script:script,model:'Qwen3.5-9B Q4_K_M',elapsed_seconds:1,
    groups:[{start_sentence:0,end_sentence:1,original:script,hint:'문제 해결',error:null}]};
  const progress={stage:'generating',completed_sentences:1,total_sentences:2,failed_sentences:0};
  const events=[{event:'progress',data:progress},{event:'complete',data:result}];
  const encoded=new TextEncoder().encode(events.map(e=>JSON.stringify(e)+'\n').join(''));
  const chunks=new ReadableStream({start(controller){
    for(let i=0;i<encoded.length;i+=3) controller.enqueue(encoded.slice(i,i+3));
    controller.close();
  }});
  const seen=[];
  const headers={'Content-Type':'application/x-ndjson'};
  assert.deepEqual(await readSummaryStream(new Response(chunks,{headers}),script,p=>seen.push(p)),result);
  assert.deepEqual(seen,[progress]);
  await assert.rejects(readSummaryStream(new Response(JSON.stringify(events[0])+'\n',{headers}),script,()=>{}),/완료 전에/);
  for(const change of [{completed_sentences:3},{failed_sentences:2},{total_sentences:3},{stage:'unknown'}]) {
    await assert.rejects(readSummaryStream(new Response(JSON.stringify({event:'progress',data:{...progress,...change}})+'\n',{headers}),script,()=>{}),/진행 정보/);
  }
  await assert.rejects(readSummaryStream(new Response(JSON.stringify({event:'error',data:{message:'모델 실패'}})+'\n',{headers}),script,()=>{}),/모델 실패/);
});

test('묶음 안의 모든 문장에서는 같은 발표 힌트를 유지한다', async () => {
  const {groupHints} = await server.ssrLoadModule('/src/features/practice/scriptTools.ts');
  const {KaraokeGuide} = await server.ssrLoadModule('/src/features/practice/components/KaraokeGuide.tsx');
  const sentenceHints=groupHints([{start_sentence:0,end_sentence:1,hint:'문제 → 해결'}]);
  for (const current_sentence_index of [0,1]) {
    const markup=renderToStaticMarkup(createElement(KaraokeGuide,{script:'문제입니다. 해결했습니다.',
      timeLimitSeconds:60,elapsedSeconds:0,karaokeEnabled:true,keywordHintEnabled:true,sentenceHints,
      progress:{current_sentence_index,current_token_index:current_sentence_index,progress_ratio:0.5}}));
    assert.match(markup,/문제 → 해결/);
  }
});

test('발표 가이드는 시간만으로 진행하지 않고 수동 문장 힌트를 표시한다', async () => {
  const {KaraokeGuide} = await server.ssrLoadModule('/src/features/practice/components/KaraokeGuide.tsx');
  const props = {script:'기능을 설명합니다. 원본을 저장하지 않습니다.',timeLimitSeconds:60,
    elapsedSeconds:55,karaokeEnabled:true,keywordHintEnabled:false};
  const waiting = renderToStaticMarkup(createElement(KaraokeGuide, props));
  assert.match(waiting, /기능을/);
  assert.match(waiting, /대본을 읽으면/);
  assert.match(waiting, /실제 진행 0%/);
  const firstHint = renderToStaticMarkup(createElement(KaraokeGuide, {...props,
    keywordHintEnabled:true,sentenceHints:{0:'첫 설명 힌트'}}));
  assert.match(firstHint,/첫 설명 힌트/);
  const unmatched = renderToStaticMarkup(createElement(KaraokeGuide, {...props,
    progress:{current_token_index:null,current_sentence_index:null,progress_ratio:0,alignment_status:'uncertain'}}));
  assert.match(unmatched,/대본과 일치하는 발화를 찾지 못했습니다/);
  const progress = {current_token_index:4,current_sentence_index:1,progress_ratio:1,
    expected_progress_ratio:1,alignment_status:'matched',pace_status:'on_time'};
  const final = renderToStaticMarkup(createElement(KaraokeGuide, {...props,progress}));
  assert.match(final, /않습니다\./);
  const memo = renderToStaticMarkup(createElement(KaraokeGuide, {...props,progress,
    keywordHintEnabled:true,sentenceHints:{1:'부정: 원본 영상·음성 저장 안 함'}}));
  assert.match(memo, /부정: 원본 영상·음성 저장 안 함/);
  const unset = renderToStaticMarkup(createElement(KaraokeGuide, {...props,progress,keywordHintEnabled:true}));
  assert.match(unset, /힌트 미설정/);
});

test("면접에서도 머리글의 종료 버튼이 발표와 같은 자리에 있다", async () => {
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
  const actions = markup => markup.match(/<div class="control-actions">.*?<\/div>/s)[0];
  const interview = renderToStaticMarkup(createElement(SessionControls, { ...props, mode: "interview" }));
  const presentation = renderToStaticMarkup(createElement(SessionControls, { ...props, mode: "presentation" }));
  assert.equal(actions(interview), actions(presentation));
  assert.match(interview, /<button[^>]*class="secondary-button"[^>]*>종료<\/button>/);
  const idle = renderToStaticMarkup(createElement(SessionControls, { ...props, mode: "interview", isRunning: false, startDisabled: true }));
  assert.match(idle, /<button[^>]*class="primary-button"[^>]*disabled=""[^>]*>시작/);
  assert.doesNotMatch(idle.match(/<div class="mode-tabs".*?<\/div>/s)[0], /disabled=""/, "a missing plan does not lock the mode tabs");
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
  assert.doesNotMatch(live, />면접 종료<\/button>/, "ending is the header button");
  assert.doesNotMatch(live, /발음 명료도|대본 일치도|미측정/);

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
  assert.match(report, /질문별 결과/);
  assert.match(report, /tabindex="-1"[^>]*>면접 연습 결과<\/h2>/);
  assert.doesNotMatch(report, /<video/);
});

const liveProps = {
  stream: null, feedback: { gaze: null, speech: null, pronunciation: null }, connectionStatus: "connected",
  socketError: null, isRunning: true, isStopping: false, summary: null,
};
const runState = (patch) => ({
  status: "asking", question: { id: "q1", round: 1, index: 2, total: 5, text: "자기소개를 해 주세요", readingMs: 8000, answerLimitMs: 120000 },
  textVisible: true, readingStartedAt: 1000, answerElapsedMs: 0, answerRunningSince: null, replayAvailable: true,
  replayPending: false, advanceReason: null, breakStage: null, followUpCount: null, suspended: false, breaks: [], ...patch,
});
const renderLive = async (run, now = 4000) => {
  const { InterviewContent } = await server.ssrLoadModule("/src/features/practice/components/InterviewContent.tsx");
  return renderToStaticMarkup(createElement(InterviewContent, { ...liveProps, run, now, onReplay() {} }));
};

test("질문은 읽는 시간에만 보이고, 가려진 뒤에는 남은 답변 시간과 질문 수만 보인다", async () => {
  const reading = await renderLive(runState({}));
  assert.match(reading, /자기소개를 해 주세요/);
  assert.match(reading, /질문 2 \/ 5/);
  assert.match(reading, /읽는 시간 5초/);
  assert.match(reading, /<button[^>]*disabled=""[^>]*>질문 다시 보기/, "no replay while the text is on screen");

  const hidden = await renderLive(runState({ textVisible: false, answerRunningSince: 9000 }), 39000);
  assert.doesNotMatch(hidden, /자기소개를 해 주세요/);
  assert.match(hidden, /1:30/);
  assert.match(hidden, /남은 질문<\/dt><dd>3개/);
  assert.doesNotMatch(hidden, /<button[^>]*disabled=""[^>]*>질문 다시 보기/);
  assert.match(hidden, /질문 다시 보기 \(1회\)/);

  const used = await renderLive(runState({ textVisible: false, answerRunningSince: 9000, replayAvailable: false }), 39000);
  assert.match(used, /<button[^>]*disabled=""[^>]*>질문 다시 보기를 사용했습니다/);
});

test("넘어갈 때 짧은 전환 문구와 라운드 휴식 단계 문구가 보인다", async () => {
  assert.match(await renderLive(runState({ status: "advancing", textVisible: false, advanceReason: "silence" })), /다음 질문입니다/);
  const stages = { suspending: /잠시 면접을 멈춥니다/, generating: /추가 질문을 만들고/, resuming: /다시 시작할 준비/, skipped: /추가 질문 없이/ };
  for (const [stage, text] of Object.entries(stages)) {
    const html = await renderLive(runState({ status: "break", question: null, textVisible: false, breakStage: stage, suspended: stage !== "skipped" }));
    assert.match(html, text);
    assert.doesNotMatch(html, /자기소개를 해 주세요/);
  }
  const suspended = await renderLive(runState({ status: "break", question: null, textVisible: false, breakStage: "generating", suspended: true }));
  assert.match(suspended, /휴식 중/);
  assert.match(await renderLive(runState({ status: "finished", question: null, textVisible: false })), /면접이 끝났습니다/);
});

const plan = {
  interview_id: "iv1", warnings: ["document_questions_failed"],
  questions: [
    { id: "q1", kind: "common", subtype: "s", text: "자기소개를 해 주세요", intent: "", source_quote: null, rubric_items: [], parent_id: null, bank_id: "b1", round: 1 },
    { id: "q2", kind: "document", subtype: "s", text: "프로젝트에서 맡은 역할은 무엇이었나요", intent: "", source_quote: "결제 모듈을 단독으로 구현했습니다", rubric_items: [], parent_id: null, bank_id: null, round: 1 },
  ],
};
const kinds = Object.fromEntries(["cover_letter", "resume", "portfolio"].map(k => [k, { busy: false, fileName: null, note: "", error: null }]));
const baseSetup = (patch = {}) => ({
  texts: {}, kinds, job: "", generating: false, progress: null, error: null, plan: null, order: [], selected: [], chosen: [], start: null,
  changeText() {}, changeJob() {}, upload() {}, generate() {}, cancelGenerate() {}, move() {}, toggle() {}, resetPlan() {}, ...patch,
});
const renderSetup = async (setup, extra = {}) => {
  const { InterviewSetup } = await server.ssrLoadModule("/src/features/interview/InterviewSetup.tsx");
  return renderToStaticMarkup(createElement(InterviewSetup, { setup, disabled: false, onStart() {}, pastResults: [], onOpenResult() {}, onDeleteResult() {}, ...extra }));
};

test("준비 화면은 종류별 업로드, 글자 수 합계, 직무 입력을 보여 주고 HWP는 PDF 변환을 안내한다", async () => {
  const html = await renderSetup(baseSetup({ texts: { resume: "가".repeat(30001) }, job: "백엔드" }));
  for (const label of ["자기소개서", "이력서", "포트폴리오"]) assert.match(html, new RegExp(`<legend>${label}</legend>`));
  assert.match(html, /accept="\.pdf,\.docx,\.txt,\.hwp,\.hwpx"/);
  assert.match(html, /HWP\) 파일은 PDF로 저장/);
  assert.match(html, /30,001 \/ 30,000자/);
  assert.match(html, /한도를 넘었습니다/);
  assert.match(html, /<button[^>]*disabled=""[^>]*>질문 만들기/, "generating is blocked over the limit");
  assert.match(html, /<input id="interview-job"[^>]*maxLength="30"/);
  const warned = await renderSetup(baseSetup({ kinds: { ...kinds, portfolio: { ...kinds.portfolio, note: "파일에서 글자를 찾지 못했습니다. 직접 붙여넣어 주세요." } } }));
  assert.match(warned, /붙여넣어 주세요/);
  const hwp = await renderSetup(baseSetup({ kinds: { ...kinds, resume: { ...kinds.resume, error: "한글(HWP/HWPX) 파일은 올릴 수 없습니다. 한글에서 PDF로 저장" } } }));
  assert.match(hwp, /role="alert"[^>]*>한글\(HWP\/HWPX\)/);
});

test("질문 생성 중에는 진행 단계와 취소 버튼이 보인다", async () => {
  const html = await renderSetup(baseSetup({ generating: true, progress: { stage: "extracting", completed: 1, total: 4 } }));
  assert.match(html, /서류에서 질문 재료를 찾는 중 \(1\/4\)/);
  assert.match(html, />취소<\/button>/);
  assert.match(html, /<progress[^>]*max="4"[^>]*value="1"/);
});

test("질문 목록은 선택·순서 변경 버튼과 근거 문장, 서류 질문 실패 경고를 보여 준다", async () => {
  const setup = baseSetup({ plan, order: ["q1", "q2"], selected: ["q1", "q2"], chosen: ["q1", "q2"], start: { interview_id: "iv1", question_ids: ["q1", "q2"] } });
  const html = await renderSetup(setup);
  assert.match(html, /서류 기반 질문을 만들지 못해 공통 질문으로 채웠습니다/);
  assert.match(html, /결제 모듈을 단독으로 구현했습니다/);
  assert.equal((html.match(/type="checkbox"/g) ?? []).length, 2);
  assert.match(html, /<button[^>]*disabled=""[^>]*aria-label="1번 질문을 위로 옮기기"/, "the first question cannot move up");
  assert.match(html, /<button[^>]*aria-label="2번 질문을 위로 옮기기"/);
  assert.doesNotMatch(html, /<button[^>]*disabled=""[^>]*aria-label="2번 질문을 위로 옮기기"/);
  assert.match(html, /<button[^>]*disabled=""[^>]*aria-label="2번 질문을 아래로 옮기기"/);
  assert.match(html, /<button[^>]*class="primary-button"[^>]*>면접 시작/);
  const none = await renderSetup({ ...setup, selected: [], chosen: [], start: null });
  assert.match(none, /<button[^>]*disabled=""[^>]*>면접 시작/);
  assert.match(none, /질문을 하나 이상 선택하세요/);
});

test("지난 면접 결과 목록은 보기와 삭제 버튼을 가진다", async () => {
  const past = [{ interview_id: "old", date: "2026-11-20T09:00:00.000Z", questions: [], items: [], evaluation: null, evaluation_status: "failed", summary: null }];
  const html = await renderSetup(baseSetup(), { pastResults: past });
  assert.match(html, /지난 면접 결과/);
  assert.match(html, />보기<\/button>/);
  assert.match(html, /결과 삭제/);
  assert.match(html, /평가 없음/);
});

const reportItems = [
  { question_id: "q1", parent_id: null, round: 1, text: "자기소개를 해 주세요", transcript: "저는 백엔드 개발자입니다", advance_reason: "silence", replay_used: true },
  { question_id: "q2", parent_id: null, round: 1, text: "역할은 무엇이었나요", transcript: "", advance_reason: "no_response", replay_used: false },
  { question_id: "q3", parent_id: null, round: 1, text: "마지막으로 하고 싶은 말", transcript: "감사합니다", advance_reason: "silence", replay_used: false },
  { question_id: "f1", parent_id: "q1", round: 2, text: "본인이 직접 한 일은 무엇인가요", transcript: "제가 API를 설계했습니다", advance_reason: "silence", replay_used: false },
];
const grade = (n, source = "main") => ({ grade: n, evidence_quote: "백엔드 개발자", evidence_source: source, reason: "근거가 분명합니다", improvement: "수치를 덧붙이세요" });
const evaluationResult = {
  items: [
    { question_id: "q1", status: "evaluated", not_evaluable_reason: null, grades: { specificity: grade(3), learning: grade(2, "follow_up") },
      excluded_items: ["reasoning", "collaboration"], partial: true, score: 12.5, follow_up_ids: ["f1"] },
    { question_id: "q2", status: "not_evaluable", not_evaluable_reason: "no_response", grades: {}, excluded_items: [], partial: false, score: null, follow_up_ids: [] },
    { question_id: "q3", status: "not_scored", not_evaluable_reason: null, grades: {}, excluded_items: [], partial: false, score: null, follow_up_ids: [] },
  ],
  overall_score: 12.5, summary: { strengths: ["구체적인 역할 설명"], improvements: ["결과 수치"], next_goals: ["STAR 구조로 답하기"] },
  model: "m", elapsed_seconds: 30, warnings: ["summary_failed"],
};
const renderReport = async (evaluation, extra = {}) => {
  const { InterviewReport } = await server.ssrLoadModule("/src/features/interview/InterviewReport.tsx");
  return renderToStaticMarkup(createElement(InterviewReport, { items: reportItems, questions: [], evaluation, ...extra }, createElement("p", null, "음성·시선 결과 자리")));
};
const done = { status: "complete", progress: null, evaluation: evaluationResult, error: null };

test("결과 화면은 종합 피드백, 질문별 카드, 부분 평가 배지와 평가 불가 이유를 보여 준다", async () => {
  const html = await renderReport(done);
  assert.match(html, /전체 점수<\/span><strong>12\.5 \/ 20/);
  assert.match(html, /구체적인 역할 설명/);
  assert.match(html, /STAR 구조로 답하기/);
  assert.match(html, /종합 피드백을 만들지 못했습니다/);
  assert.match(html, /부분 평가 · 제외된 항목: 문제 해결과 판단 근거, 협업과 의사소통/);
  assert.match(html, /평가 불가 · 무응답/);
  assert.match(html, /마무리 질문 · 평가하지 않음/);
  assert.match(html, /경험·행동의 구체성/);
  assert.match(html, /3 \/ 4/);
  assert.match(html, /근거 \(본 답변\)/);
  assert.match(html, /근거 \(추가 답변\)/);
  assert.match(html, /인식 오류가 점수에 영향을 줄 수 있습니다/);
  assert.match(html, /음성·시선 결과 자리/);
  assert.match(html, /질문 다시 보기 사용/);
  assert.match(html, /인식된 답변이 없습니다/);
  // The follow-up answer sits inside its parent's card, not in a card of its own.
  const parent = html.indexOf("자기소개를 해 주세요</h3>");
  const next = html.indexOf("역할은 무엇이었나요</h3>");
  const follow = html.indexOf("제가 API를 설계했습니다");
  assert.ok(parent < follow && follow < next, "the follow-up is in the first card");
  assert.equal((html.match(/<article/g) ?? []).length, 3);
});

test("평가 중에는 진행과 중단 버튼이 보이고 받아쓰기는 먼저 보인다", async () => {
  const running = { status: "running", progress: { stage: "evaluating", index: 2, total: 3 }, evaluation: null, error: null };
  const html = await renderReport(running, { onCancelEvaluation() {} });
  assert.match(html, /질문별 답변을 평가하는 중 \(2\/3\)/);
  assert.match(html, /<progress[^>]*max="3"[^>]*value="1"/);
  assert.match(html, />평가 중단<\/button>/);
  assert.match(html, /저는 백엔드 개발자입니다/);
  assert.match(html, /평가 전/);
  assert.doesNotMatch(html, /전체 점수/);
});

test("평가가 실패하거나 중단돼도 받아쓰기와 음성·시선 결과는 남고 다시 평가할 수 있다", async () => {
  const failed = { status: "failed", progress: null, evaluation: null, error: "답변 평가에 실패했습니다. 다시 시도하세요." };
  const html = await renderReport(failed, { onRetryEvaluation() {} });
  assert.match(html, /답변 평가에 실패했습니다/);
  assert.match(html, />다시 평가<\/button>/);
  assert.match(html, /제가 API를 설계했습니다/);
  assert.match(html, /음성·시선 결과 자리/);
});

test("결과 화면의 새 면접 버튼은 평가 중에는 잠긴다", async () => {
  const { InterviewContent } = await server.ssrLoadModule("/src/features/practice/components/InterviewContent.tsx");
  const summary = { sessionId: "s1", durationSeconds: 60, gazeAwayRatio: null, pronunciationAccuracy: null, speechPaceWarningCount: null,
    averageSyllablesPerMinute: null, fillerWordCounts: null, transcript: "t", incomplete: false };
  const render = evaluation => renderToStaticMarkup(createElement(InterviewContent, { ...liveProps, isRunning: false, summary,
    reportItems, evaluation, onNewInterview() {} }));
  assert.match(render({ status: "running", progress: null, evaluation: null, error: null }), /<button[^>]*disabled=""[^>]*>새 면접 준비/);
  assert.doesNotMatch(render(done), /<button[^>]*disabled=""[^>]*>새 면접 준비/);
  assert.match(render(done), /질문별 결과/);
});

test("1초마다 바뀌는 카운트다운은 읽어 주는 영역 밖에 있다", async () => {
  const live = markup => markup.match(/<div aria-live="polite"[^>]*>(.*?)<\/div>(?=<dl|<p class="interview-question__status"|<button|<p class="interview-note"|<\/section>)/s)?.[1] ?? "";
  const hidden = await renderLive(runState({ textVisible: false, answerRunningSince: 9000 }), 39000);
  assert.match(live(hidden), /질문이 가려졌습니다/);
  assert.doesNotMatch(live(hidden), /남은 답변 시간|1:30|남은 질문/);
  assert.match(hidden, /남은 답변 시간/);
  const reading = await renderLive(runState({}));
  assert.match(live(reading), /자기소개를 해 주세요/);
  assert.doesNotMatch(live(reading), /읽는 시간/);
  assert.doesNotMatch(hidden + reading + await renderLive(runState({ status: "break", question: null, breakStage: "generating" })), /role="status"[^>]*>[^<]*<[^>]*role="status"/);
  const breakHtml = await renderLive(runState({ status: "break", question: null, textVisible: false, breakStage: "generating" }));
  assert.doesNotMatch(breakHtml.match(/<div aria-live="polite"[^>]*>.*?<\/div>/s)[0], /role="status"/);
});

test("면접 결과에는 발표 전용 항목이 없고 저장 안내가 면접에 맞다", async () => {
  const { InterviewContent } = await server.ssrLoadModule("/src/features/practice/components/InterviewContent.tsx");
  const { SessionSummary } = await server.ssrLoadModule("/src/features/practice/components/SessionSummary.tsx");
  const summary = { sessionId: "s1", durationSeconds: 60, gazeAwayRatio: 0.1, pronunciationAccuracy: null, speechPaceWarningCount: 0,
    averageSyllablesPerMinute: 250, fillerWordCounts: {}, transcript: "전체 받아쓰기 문장", incomplete: false,
    deliveryMetrics: { status: "observed", agc_on: false,
      report: { total_voiced_ms: 60000, sentences: [{ start_ms: 0, end_ms: 1, voiced_ms: 1000, sentence_index: 0 }], baseline: {}, bursts: [] },
      windows: { window_ms: 10000, baseline: {}, windows: [{ start_ms: 0, end_ms: 10000, voiced_ms: 8000, coverage: 0.8, speech_rate: 300 }] } } };
  const html = renderToStaticMarkup(createElement(InterviewContent, { ...liveProps, isRunning: false, summary, reportItems }));
  for (const gone of ["대본과 인식 결과 일치도", "실제 대본 진행률", "대본 일치도는 STT", "대본 문장별 특징", "새 리포트에는 저장하지 않습니다", "받아쓰기 결과", "전체 받아쓰기 문장"])
    assert.ok(!html.includes(gone), `${gone} must not show in interview mode`);
  assert.match(html, /이 브라우저에만 저장/);
  assert.match(html, /시간 구간별 특징/);
  const presentation = renderToStaticMarkup(createElement(SessionSummary, { summary }));
  for (const kept of ["대본과 인식 결과 일치도", "실제 대본 진행률", "받아쓰기 결과", "전체 받아쓰기 문장", "대본 문장별 특징", "새 리포트에는 저장하지 않습니다"])
    assert.ok(presentation.includes(kept), `${kept} stays in presentation mode`);
});

test("준비 화면은 파일 없음 문구를 한 번만 보이고, 잃어버린 계획 안내를 보여 준다", async () => {
  const empty = await renderSetup(baseSetup());
  assert.equal((empty.match(/선택한 파일 없음/g) ?? []).length, 0, "the native input already says it");
  const named = await renderSetup(baseSetup({ kinds: { ...kinds, resume: { ...kinds.resume, fileName: "이력서.pdf" } } }));
  assert.match(named, /이력서\.pdf/);
  const notice = await renderSetup(baseSetup(), { notice: "연결이 끊겨 면접이 중단되었습니다. 질문을 다시 만들어 주세요." });
  assert.match(notice, /role="alert"[^>]*>연결이 끊겨/);
});

test("준비 화면의 줄은 좁은 화면에서 줄어들 수 있게 minmax(0, 1fr)로 둔다", async () => {
  const { readFile } = await import("node:fs/promises");
  const css = await readFile(new URL("../src/features/interview/interview.css", import.meta.url), "utf8");
  assert.match(css, /\.interview-doc__file\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  assert.match(css, /\.interview-doc\s*{[^}]*min-inline-size:\s*0/);
  assert.match(css, /\.interview-doc__input\s*{[^}]*width:\s*100%/);
});

test("결과 화면의 열은 넓은 표 때문에 늘어나지 않는다", async () => {
  const { readFile } = await import("node:fs/promises");
  const css = await readFile(new URL("../src/features/interview/interview.css", import.meta.url), "utf8");
  assert.match(css, /\.interview-setup, \.interview-results\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  assert.match(css, /\.interview-report\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  assert.match(css, /\.interview-results \.summary-panel[^{]*{[^}]*min-width:\s*0/);
});
