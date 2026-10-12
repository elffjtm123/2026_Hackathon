import assert from 'node:assert/strict';
import test from 'node:test';
import * as tools from '../src/features/practice/scriptTools.ts';

test('요약 응답을 원문 문장 번호로 매핑하고 수정 전 대본 결과는 거부한다', () => {
  assert.equal(typeof tools.summaryHints, 'function');
  const result = {normalized_script:'같은 문장. 같은 문장.',sentences:[
    {sentence_index:0,original:'같은 문장.',hint:'첫 번째 요약',error:null},
    {sentence_index:1,original:'같은 문장.',hint:null,error:'생성 실패'},
  ]};
  assert.deepEqual(tools.summaryHints('같은 문장.\n같은 문장.', result), {0:'첫 번째 요약'});
  assert.throws(() => tools.summaryHints('수정한 대본.', result));
  assert.throws(() => tools.summaryHints('같은 문장. 같은 문장.', {
    ...result, sentences: [result.sentences[0], result.sentences[0]],
  }));
});
