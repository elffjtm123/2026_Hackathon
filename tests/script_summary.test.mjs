import assert from 'node:assert/strict';
import test from 'node:test';
import * as tools from '../src/features/practice/scriptTools.ts';
import * as protocol from '../src/lib/realtimeProtocol.ts';

test('미로드·준비 중인 모델을 준비 완료로 표시하지 않는다', () => {
  assert.equal(typeof protocol.modelStatusLabel, 'function');
  const module = {provider:'qwen3_asr', model:'Qwen ASR',device:null,reason:null};
  assert.equal(protocol.modelStatusLabel({...module,status:'idle'}), '미로드');
  assert.equal(protocol.modelStatusLabel({...module,status:'loading'}), '준비 중');
  assert.equal(protocol.modelStatusLabel({...module,status:'ready'}), '준비 완료');
  assert.equal(protocol.modelStatusLabel({...module,status:'unavailable'}), '사용 불가');
});

test('요약 응답을 원문 문장 번호로 매핑하고 수정 전 대본 결과는 거부한다', () => {
  assert.equal(typeof tools.summaryHints, 'function');
  const result = {normalized_script:'같은 문장. 같은 문장.',groups:[
    {start_sentence:0,end_sentence:1,original:'같은 문장. 같은 문장.',hint:'묶음 요약',error:null},
  ]};
  assert.deepEqual(tools.summaryHints('같은 문장.\n같은 문장.', result), {0:'묶음 요약',1:'묶음 요약'});
  assert.throws(() => tools.summaryHints('수정한 대본.', result));
  assert.throws(() => tools.summaryHints('같은 문장. 같은 문장.', {
    ...result, groups: [result.groups[0], result.groups[0]],
  }));
});

test('묶음은 모든 원문을 순서대로 한 번만 포함해야 한다', () => {
  const script = '하나. 둘. 셋.';
  const group = {start_sentence:0,end_sentence:2,original:script,hint:'전체 설명',error:null};
  const result = {normalized_script:script,groups:[group]};
  for (const change of [{start_sentence:1},{end_sentence:1},{end_sentence:3},
    {start_sentence:false},{original:'변조'},{hint:''},{hint:null,error:null}]) {
    assert.throws(() => tools.summaryHints(script,{...result,groups:[{...group,...change}]}));
  }
  assert.deepEqual(tools.summaryHints(script,{...result,groups:[{...group,hint:null,error:'생성 실패'}]}),{});
});

test('일부 재요약 실패가 있으면 기존 수동 요약을 덮어쓰지 않는다', () => {
  const script='하나. 둘.';
  const current=[{start_sentence:0,end_sentence:1,original:script,hint:'직접 수정한 힌트',error:null}];
  const result={normalized_script:script,groups:[{...current[0],hint:null,error:'생성 실패'}]};
  assert.throws(()=>tools.replacementSummaryGroups(script,result,current),/기존 요약/);
  assert.equal(current[0].hint,'직접 수정한 힌트');
  assert.deepEqual(tools.replacementSummaryGroups(script,result,tools.manualSummaryGroups(script)),result.groups);
});
