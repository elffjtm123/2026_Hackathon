import assert from 'node:assert/strict';
import test from 'node:test';
import {completionForUi, summaryForUi} from '../src/lib/realtimeProtocol.ts';

test('미분석을 0회·0속도로 바꾸지 않고 서버 집계를 전달한다', () => {
  const report = completionForUi({scoring_version:'v2',incomplete:false,
    summary:{duration_ms:2000},gaze_metrics:{away_ratio:0.25,coverage_ratio:0.8,status:'observed'},
    speech_rate_metrics:{status:'unavailable'},filler_word_counts:null,
    pronunciation_clarity_score:85,script_completion_ratio:0.5});
  assert.equal(report.speech.averageSyllablesPerMinute, null);
  assert.equal(report.filler.counts, null);
  assert.equal(report.gaze.awayRatio,0.25);
  assert.equal(report.gaze.coverageRatio,0.8);
  assert.equal(report.scriptCompletionRatio,0.5);
  assert.equal(report.pronunciationAccuracy,85);
  assert.equal(report.durationMs,2000);
});

test('보고서가 없으면 임의 결과를 계산하지 않고 미완료로 표시한다', () => {
  const summary = summaryForUi('s', null, 12, '임시 받아쓰기');
  assert.equal(summary.gazeAwayRatio,null);
  assert.equal(summary.fillerWordCounts,null);
  assert.equal(summary.speechPaceWarningCount,null);
  assert.equal(summary.pronunciationAccuracy,null);
  assert.equal(summary.incomplete,true);
  assert.equal(summary.transcript,'임시 받아쓰기');
});
