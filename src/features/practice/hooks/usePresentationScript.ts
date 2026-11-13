import { useCallback, useEffect, useRef, useState } from 'react';
import type { PracticeMode } from '../types';
import { groupHints, manualSummaryGroups, replacementSummaryGroups, type ScriptSummaryGroup, type SummaryProgress } from '../scriptTools';
import { requestScriptSummary } from '../scriptSummary';
import { readSessionValue } from '../../model-themes/runHistory';

const defaultScript = "안녕하세요. 오늘은 실시간 발표 피드백 서비스의 핵심 기능을 소개하겠습니다. 이 서비스는 시선, 발화 속도, 대본 일치도를 확인해 발표자가 더 안정적으로 연습할 수 있도록 돕습니다.";

// Presentation script, time limit and AI summary groups, persisted in this tab's sessionStorage.
export function usePresentationScript(mode: PracticeMode) {
  const [script, setScript] = useState(() => readSessionValue('live-practice-script') ?? defaultScript);
  const [timeLimitSeconds, setTimeLimitSeconds] = useState(() => {
    const saved = Number(readSessionValue('live-practice-time'));
    return Number.isFinite(saved) && saved >= 30 && saved <= 1800 ? saved : 180;
  });
  useEffect(() => {
    try {
      sessionStorage.setItem('live-practice-script', script);
      sessionStorage.setItem('live-practice-time', String(timeLimitSeconds));
      sessionStorage.setItem('live-practice-mode', mode);
    } catch { /* Storage is optional. */ }
  }, [script, timeLimitSeconds, mode]);
  const [summaryGroups, setSummaryGroups] = useState<ScriptSummaryGroup[] | null>(null);
  const groups = summaryGroups ?? manualSummaryGroups(script);
  const sentenceHints = groupHints(groups);
  const [isSummarizing, setIsSummarizing] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [summaryProgress, setSummaryProgress] = useState<SummaryProgress | null>(null);
  const [summarySeconds, setSummarySeconds] = useState<number | null>(null);
  const summaryRequest = useRef<AbortController | null>(null);
  const scriptVersion = useRef(0);
  useEffect(() => () => summaryRequest.current?.abort(), []);

  const changeScript = (next: string) => {
    scriptVersion.current++;
    setScript(next); setSummaryGroups(null); setSummaryProgress(null);
    setSummaryError(null); setSummarySeconds(null);
  };
  const changeHint = (index: number, hint: string) => {
    setSummaryGroups(current => (current ?? manualSummaryGroups(script))
      .map((group, i) => i === index ? {...group, hint, error: null} : group));
  };
  const changeTimeLimit = useCallback((seconds: number) => {
    if (Number.isFinite(seconds)) setTimeLimitSeconds(Math.min(1800, Math.max(30, seconds)));
  }, []);
  const summarize = async () => {
    if (summaryRequest.current) return;
    if (Object.values(sentenceHints).some(hint => hint.trim())
        && !window.confirm('현재 요약을 새 AI 초안으로 바꿀까요? 직접 수정한 내용이 덮어써질 수 있습니다.')) return;
    const controller = new AbortController();
    const version = scriptVersion.current;
    summaryRequest.current = controller;
    setIsSummarizing(true); setSummaryError(null); setSummaryProgress(null);
    try {
      const result = await requestScriptSummary(script, controller.signal, progress => {
        if (!controller.signal.aborted && version === scriptVersion.current) setSummaryProgress(progress);
      });
      if (controller.signal.aborted || version !== scriptVersion.current) return;
      setSummaryGroups(replacementSummaryGroups(script, result, groups));
      setSummarySeconds(result.elapsed_seconds);
    } catch (error) {
      if (!controller.signal.aborted && version === scriptVersion.current)
        setSummaryError(error instanceof Error ? error.message : '요약하지 못했습니다. 다시 시도하세요.');
    } finally {
      if (summaryRequest.current === controller) {
        summaryRequest.current = null;
        if (!controller.signal.aborted) setIsSummarizing(false);
      }
    }
  };
  const isSummaryPending = useCallback(() => summaryRequest.current !== null, []);
  return { script, timeLimitSeconds, groups, sentenceHints, isSummarizing, summaryError, summaryProgress,
    summarySeconds, changeScript, changeHint, changeTimeLimit, summarize, isSummaryPending };
}
