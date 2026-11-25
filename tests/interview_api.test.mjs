import assert from 'node:assert/strict';
import test from 'node:test';
import {InterviewApiError, cancelEvaluation, interviewErrorMessage, readInterviewStream,
  requestEvaluation, requestPlan, uploadDocuments} from '../src/features/interview/api.ts';

const ndjson = (events, chunk = 7) => {
  const bytes = new TextEncoder().encode(events.map(e => JSON.stringify(e) + '\n').join(''));
  return new Response(new ReadableStream({start(c) {
    for (let i = 0; i < bytes.length; i += chunk) c.enqueue(bytes.slice(i, i + chunk));
    c.close();
  }}), {headers: {'Content-Type': 'application/x-ndjson'}});
};
const jsonError = (status, code, message = 'x') => new Response(JSON.stringify({error: {code, message}}),
  {status, headers: {'Content-Type': 'application/json'}});
const evaluation = {items: [], overall_score: null, summary: {strengths: [], improvements: [], next_goals: []},
  model: 'm', elapsed_seconds: 1, warnings: []};

test('the NDJSON reader joins split UTF-8 and returns the complete data after the progress lines', async () => {
  const seen = [];
  const plan = {interview_id: 'a', questions: [], warnings: []};
  const out = await readInterviewStream(ndjson([{event: 'progress', data: {stage: '로딩', n: 1}},
    {event: 'progress', data: {stage: 'extracting', completed: 1, total: 2}},
    {event: 'complete', data: plan}], 3), {onProgress: p => seen.push(p)});
  assert.deepEqual(out, plan);
  assert.deepEqual(seen.map(p => p.stage), ['로딩', 'extracting']);
});

test('an error line becomes an InterviewApiError with the code and a Korean message', async () => {
  await assert.rejects(readInterviewStream(ndjson([{event: 'error', data: {code: 'INTERVIEW_MODEL_UNAVAILABLE', message: 'en'}}])),
    e => e instanceof InterviewApiError && e.code === 'INTERVIEW_MODEL_UNAVAILABLE' && /모델/.test(e.message));
});

test('a stream that ends without a complete line, or has bad lines, is rejected', async () => {
  await assert.rejects(readInterviewStream(ndjson([{event: 'progress', data: {stage: 'loading'}}])), /완료 전에/);
  await assert.rejects(readInterviewStream(new Response('not json\n', {headers: {'Content-Type': 'application/x-ndjson'}})), /응답/);
  await assert.rejects(readInterviewStream(ndjson([{event: 'weird', data: {}}])), /응답/);
  await assert.rejects(readInterviewStream(new Response('{}', {headers: {'Content-Type': 'text/html'}})), /응답/);
});

test('an HTTP error uses the code mapping, with the server text as the fallback for unknown codes', async () => {
  await assert.rejects(readInterviewStream(jsonError(409, 'PRACTICE_ACTIVE')), e => e.code === 'PRACTICE_ACTIVE' && e.status === 409 && /세션/.test(e.message));
  await assert.rejects(readInterviewStream(jsonError(500, 'SOMETHING_NEW', '서버 문장')), e => e.message === '서버 문장');
  await assert.rejects(readInterviewStream(new Response('oops', {status: 502})), /서버/);
  assert.match(interviewErrorMessage('INTERVIEW_DOCUMENT_TOO_LARGE'), /큽니다/);
  assert.match(interviewErrorMessage('INTERVIEW_NOT_READY'), /끝난 뒤/);
  assert.match(interviewErrorMessage('VALIDATION_ERROR'), /입력/);
  assert.ok(interviewErrorMessage(undefined).length > 0);
});

test('uploadDocuments sends files and kinds in the same order and returns the extracted texts', async () => {
  let call;
  const docs = [{kind: 'resume', text: '이력', warnings: []}, {kind: 'portfolio', text: '', warnings: [{code: 'no_text', message: 'm'}]}];
  const result = await uploadDocuments([{kind: 'resume', file: new File(['a'], 'a.pdf')}, {kind: 'portfolio', file: new File(['b'], 'b.docx')}],
    {fetch: async (url, init) => { call = {url: String(url), init}; return new Response(JSON.stringify(docs), {headers: {'Content-Type': 'application/json'}}); }});
  assert.match(call.url, /\/interview\/documents$/);
  assert.equal(call.init.method, 'POST');
  assert.equal(call.init.headers?.['Content-Type'], undefined, 'the browser sets the multipart boundary');
  assert.deepEqual(call.init.body.getAll('kinds'), ['resume', 'portfolio']);
  assert.deepEqual(call.init.body.getAll('files').map(f => f.name), ['a.pdf', 'b.docx']);
  assert.deepEqual(result, docs);
  await assert.rejects(uploadDocuments([{kind: 'resume', file: new File(['a'], 'a.pdf')}],
    {fetch: async () => jsonError(413, 'INTERVIEW_DOCUMENT_TOO_LARGE')}), e => e.code === 'INTERVIEW_DOCUMENT_TOO_LARGE');
  await assert.rejects(uploadDocuments([{kind: 'resume', file: new File(['a'], 'a.pdf')}],
    {fetch: async () => new Response(JSON.stringify({nope: 1}))}), /응답/);
});

test('requestPlan asks for NDJSON, sends the body and passes the abort signal', async () => {
  let call;
  const controller = new AbortController();
  const plan = {interview_id: 'iv', questions: [{id: 'q1', kind: 'common', subtype: 's', text: 't', intent: 'i', source_quote: null,
    rubric_items: ['a'], parent_id: null, bank_id: 'b1', round: 1}], warnings: ['document_questions_failed']};
  const out = await requestPlan({documents: [{kind: 'resume', text: '내용'}], job: '개발자', exclude_common_ids: ['x']},
    {signal: controller.signal, fetch: async (url, init) => { call = {url: String(url), init}; return ndjson([{event: 'complete', data: plan}]); }});
  assert.equal(call.init.method, 'POST');
  assert.equal(call.init.headers.Accept, 'application/x-ndjson');
  assert.equal(call.init.signal.aborted, false);
  assert.deepEqual(JSON.parse(call.init.body), {documents: [{kind: 'resume', text: '내용'}], job: '개발자', exclude_common_ids: ['x']});
  assert.deepEqual(out, plan);
  controller.abort();
  assert.equal(call.init.signal.aborted, true);
  await assert.rejects(requestPlan({documents: [], job: null, exclude_common_ids: []},
    {fetch: async () => ndjson([{event: 'complete', data: {questions: []}}])}), /응답/);
});

test('requestEvaluation reads progress and validates the evaluation; cancel sends DELETE', async () => {
  const calls = [];
  const seen = [];
  const fetchImpl = async (url, init) => { calls.push({url: String(url), init});
    return init.method === 'DELETE' ? new Response(null, {status: 204})
      : ndjson([{event: 'progress', data: {stage: 'evaluating', index: 1, total: 2}}, {event: 'complete', data: evaluation}]); };
  const out = await requestEvaluation('iv 1', {fetch: fetchImpl, onProgress: p => seen.push(p)});
  assert.match(calls[0].url, /\/interview\/iv%201\/evaluation$/);
  assert.equal(calls[0].init.headers.Accept, 'application/x-ndjson');
  assert.deepEqual(seen, [{stage: 'evaluating', index: 1, total: 2}]);
  assert.deepEqual(out, evaluation);
  await cancelEvaluation('iv 1', {fetch: fetchImpl});
  assert.equal(calls[1].init.method, 'DELETE');
  await assert.rejects(requestEvaluation('iv', {fetch: async () => ndjson([{event: 'complete', data: {items: 'x'}}])}), /응답/);
  await assert.rejects(requestEvaluation('iv', {fetch: async () => ndjson([{event: 'error', data: {code: 'INTERVIEW_EVALUATION_CANCELLED', message: 'c'}}])}),
    e => e.code === 'INTERVIEW_EVALUATION_CANCELLED');
});

test('a last line without a newline is still read, and invalid UTF-8 is a bad response', async () => {
  const raw = body => new Response(body, {headers: {'Content-Type': 'application/x-ndjson'}});
  const plan = {interview_id: 'a', questions: [], warnings: []};
  assert.deepEqual(await readInterviewStream(raw(JSON.stringify({event: 'complete', data: plan}))), plan);
  assert.deepEqual(await readInterviewStream(raw(JSON.stringify({event: 'progress', data: {stage: 'x'}}) + '\n' + JSON.stringify({event: 'complete', data: plan}))), plan);
  await assert.rejects(readInterviewStream(raw(new Uint8Array([0x7b, 0xff, 0xfe, 0x0a]))), e => e instanceof InterviewApiError && e.code === 'BAD_RESPONSE');
  await assert.rejects(readInterviewStream(raw(new Uint8Array([0xe3, 0x81]))), e => e instanceof InterviewApiError && e.code === 'BAD_RESPONSE',
    'a stream that stops inside a character');
});
