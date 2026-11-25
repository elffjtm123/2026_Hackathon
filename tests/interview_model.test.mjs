import assert from 'node:assert/strict';
import test from 'node:test';
import {MAX_JOB_CHARS, MAX_TOTAL_CHARS, buildPlanRequest, canStartInterview, classifyFile, documentStatus, historyEntryFor,
  moveQuestion, planProgressLabel, planWarningText, selectedIds, startPayload, toggleQuestion, totalChars}
  from '../src/features/interview/planSelection.ts';
import {buildReportCards, evaluationProgressLabel, formatScore, gradeSourceLabel, itemBadge, notEvaluableText, rubricLabel}
  from '../src/features/interview/reportModel.ts';

test('PDF, DOCX and TXT are accepted; HWP and HWPX ask for a PDF conversion and are never uploaded', () => {
  assert.deepEqual(classifyFile('이력서.PDF'), {ok: true});
  assert.deepEqual(classifyFile('a.docx'), {ok: true});
  assert.deepEqual(classifyFile('a.txt'), {ok: true});
  for (const name of ['a.hwp', 'a.HWPX']) {
    const r = classifyFile(name);
    assert.equal(r.ok, false);
    assert.match(r.message, /PDF/);
    assert.match(r.message, /한글|HWP/i);
  }
  assert.equal(classifyFile('a.png').ok, false);
  assert.match(classifyFile('noext').message, /PDF|DOCX|TXT/);
});

test('the total character count and limit span all three documents', () => {
  const docs = {resume: 'a'.repeat(10000), cover_letter: 'b'.repeat(15000), portfolio: 'c'.repeat(5000)};
  assert.equal(totalChars(docs), 30000);
  assert.equal(MAX_TOTAL_CHARS, 30000);
  assert.equal(totalChars({...docs, portfolio: 'c'.repeat(5001)}) > MAX_TOTAL_CHARS, true);
  assert.equal(totalChars({}), 0);
});

test('document warnings tell the user to paste text when nothing or only part was read', () => {
  assert.match(documentStatus([{code: 'no_text', message: ''}]), /붙여넣/);
  assert.match(documentStatus([{code: 'truncated', message: ''}]), /잘렸|붙여넣/);
  assert.equal(documentStatus([]), '');
});

test('the plan request drops empty documents, trims the job and keeps the exclude ids as given', () => {
  const body = buildPlanRequest({resume: '  내용  ', cover_letter: '   ', portfolio: ''}, '  백엔드  ', ['a', 'b']);
  assert.deepEqual(body, {documents: [{kind: 'resume', text: '  내용  '}], job: '백엔드', exclude_common_ids: ['a', 'b']});
  assert.deepEqual(buildPlanRequest({}, '   ', []), {documents: [], job: null, exclude_common_ids: []});
  assert.equal(buildPlanRequest({}, 'x'.repeat(40), []).job.length, MAX_JOB_CHARS);
  assert.deepEqual(buildPlanRequest({cover_letter: 'c', resume: 'r'}, '', []).documents.map(d => d.kind), ['cover_letter', 'resume'],
    'a stable kind order, whatever order the keys were set in');
});

test('questions can be reordered with bounds, deselected, and at least one must stay selected', () => {
  const order = ['q1', 'q2', 'q3'];
  assert.deepEqual(moveQuestion(order, 'q2', -1), ['q2', 'q1', 'q3']);
  assert.deepEqual(moveQuestion(order, 'q1', -1), order);
  assert.deepEqual(moveQuestion(order, 'q3', 1), order);
  assert.deepEqual(moveQuestion(order, 'nope', 1), order);
  let selected = ['q1', 'q2', 'q3'];
  selected = toggleQuestion(selected, 'q2');
  assert.deepEqual(selectedIds(['q2', 'q1', 'q3'], selected), ['q1', 'q3'], 'order follows the list, not the click order');
  selected = toggleQuestion(selected, 'q2');
  assert.deepEqual(selectedIds(order, selected), ['q1', 'q2', 'q3']);
  assert.equal(canStartInterview(order, []), false);
  assert.equal(canStartInterview(order, ['q1']), true);
});

test('the start payload and the history entry carry the chosen questions only', () => {
  const plan = {interview_id: 'iv', warnings: [], questions: [
    {id: 'q1', kind: 'common', bank_id: 'b1'}, {id: 'q2', kind: 'document', bank_id: null}, {id: 'q3', kind: 'common', bank_id: 'b3'}]};
  assert.deepEqual(startPayload(plan, ['q3', 'q1', 'q2'], ['q3', 'q2']), {interview_id: 'iv', question_ids: ['q3', 'q2']});
  assert.deepEqual(historyEntryFor(plan, ['q1', 'q2'], '2026-11-25T00:00:00.000Z'),
    {interview_id: 'iv', date: '2026-11-25T00:00:00.000Z', common_bank_ids: ['b1']});
});

test('plan and evaluation progress and warnings are shown in Korean', () => {
  assert.match(planProgressLabel({stage: 'loading'}), /모델/);
  assert.match(planProgressLabel({stage: 'extracting', completed: 1, total: 4}), /1.*4/);
  assert.match(planProgressLabel({stage: 'generating'}), /질문/);
  assert.match(planProgressLabel({stage: 'cleaning'}), /정리/);
  assert.ok(planProgressLabel({stage: 'brand-new'}).length > 0);
  assert.match(planWarningText('document_questions_failed'), /공통 질문/);
  assert.match(planWarningText('few_materials'), /서류/);
  assert.match(evaluationProgressLabel({stage: 'evaluating', index: 2, total: 5}), /2.*5/);
  assert.match(evaluationProgressLabel({stage: 'summarizing'}), /종합/);
  assert.match(evaluationProgressLabel({stage: 'loading'}), /모델/);
});

const item = (id, extra = {}) => ({question_id: id, round: 1, parent_id: null, text: `질문 ${id}`, transcript: `답 ${id}`,
  advance_reason: 'silence', replay_used: false, ...extra});
const evalItem = (id, extra = {}) => ({question_id: id, status: 'evaluated', not_evaluable_reason: null, grades: {}, excluded_items: [],
  partial: false, score: 10, follow_up_ids: [], ...extra});

test('not evaluable reasons, rubric names and grade sources are in Korean', () => {
  assert.equal(notEvaluableText('no_response'), '무응답');
  assert.equal(notEvaluableText('too_short'), '답변이 너무 짧음');
  assert.equal(notEvaluableText('recognition_failed'), '인식 실패');
  assert.equal(rubricLabel('learning'), '결과와 학습');
  assert.equal(rubricLabel('collaboration'), '협업과 의사소통');
  assert.equal(rubricLabel('unknown_item'), 'unknown_item');
  assert.equal(gradeSourceLabel('main'), '본 답변');
  assert.equal(gradeSourceLabel('follow_up'), '추가 답변');
  assert.equal(formatScore(12.34), '12.3 / 20');
  assert.equal(formatScore(null), '점수 없음');
});

test('the badge of an item: evaluated, partial with excluded items, not evaluable, not scored, failed, none yet', () => {
  assert.deepEqual(itemBadge(evalItem('a')), {tone: 'ok', label: '평가 완료'});
  const partial = itemBadge(evalItem('a', {partial: true, excluded_items: ['learning', 'reasoning']}));
  assert.equal(partial.tone, 'partial');
  assert.match(partial.label, /부분 평가/);
  assert.match(partial.label, /결과와 학습/);
  assert.match(partial.label, /문제 해결과 판단 근거/);
  assert.match(itemBadge(evalItem('a', {status: 'not_evaluable', not_evaluable_reason: 'too_short', score: null})).label, /평가 불가.*답변이 너무 짧음/);
  assert.match(itemBadge(evalItem('a', {status: 'not_scored', score: null})).label, /마무리.*평가하지 않음/);
  assert.match(itemBadge(evalItem('a', {status: 'failed', score: null})).label, /평가 실패/);
  assert.deepEqual(itemBadge(undefined), {tone: 'pending', label: '평가 전'});
});

test('cards group follow-up questions inside the parent and attach the evaluation of the main question', () => {
  const items = [item('q1'), item('q2'), item('f1', {round: 2, parent_id: 'q1'}), item('orphan', {round: 2, parent_id: 'gone'})];
  const evaluation = {items: [evalItem('q1', {follow_up_ids: ['f1']}), evalItem('q2', {status: 'failed', score: null})],
    overall_score: 10, summary: {strengths: [], improvements: [], next_goals: []}, model: 'm', elapsed_seconds: 1, warnings: []};
  const questions = [{id: 'q1', kind: 'document', source_quote: '근거 문장'}];
  const cards = buildReportCards(items, questions, evaluation);
  assert.deepEqual(cards.map(c => c.id), ['q1', 'q2', 'orphan']);
  assert.deepEqual(cards[0].followUps.map(f => f.id), ['f1']);
  assert.equal(cards[0].sourceQuote, '근거 문장');
  assert.equal(cards[0].evaluation.status, 'evaluated');
  assert.equal(cards[1].evaluation.status, 'failed');
  assert.equal(cards[2].evaluation, undefined);
  assert.equal(buildReportCards(items, questions, null)[0].evaluation, undefined);
});
