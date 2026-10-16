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
  assert.match(pending, /Qwen3.5-9B Q4_K_M/);
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
