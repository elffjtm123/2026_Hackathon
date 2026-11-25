import { useCallback, useEffect, useRef, useState } from 'react';
import { InterviewApiError, requestPlan, uploadDocuments } from './api.ts';
import { DOCUMENT_KINDS, MAX_JOB_CHARS, buildPlanRequest, canStartInterview, classifyFile, documentStatus, moveQuestion,
  selectedIds, startPayload, toggleQuestion, type DocumentTexts } from './planSelection.ts';
import { excludeCommonIds } from './storage.ts';
import type { DocumentKind, InterviewPlan, PlanProgress } from './types.ts';

export type KindState = {busy: boolean; fileName: string | null; note: string; error: string | null};
const emptyKind: KindState = {busy: false, fileName: null, note: '', error: null};

// Preparation of one interview: documents (held in this screen's memory only), the job, the plan
// the server made, and the user's choice and order of its questions.
export function useInterviewSetup() {
  const [texts, setTexts] = useState<DocumentTexts>({});
  const [kinds, setKinds] = useState<Record<DocumentKind, KindState>>(
    () => Object.fromEntries(DOCUMENT_KINDS.map(({kind}) => [kind, emptyKind])) as Record<DocumentKind, KindState>);
  const [job, setJob] = useState('');
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState<PlanProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<InterviewPlan | null>(null);
  const [order, setOrder] = useState<string[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  const patchKind = useCallback((kind: DocumentKind, patch: Partial<KindState>) =>
    setKinds(current => ({...current, [kind]: {...current[kind], ...patch}})), []);

  const changeText = useCallback((kind: DocumentKind, text: string) => setTexts(current => ({...current, [kind]: text})), []);
  const changeJob = useCallback((value: string) => setJob(value.slice(0, MAX_JOB_CHARS)), []);

  // HWP/HWPX and other formats are refused here, so they never reach the server.
  const upload = useCallback(async (kind: DocumentKind, file: File) => {
    const verdict = classifyFile(file.name);
    if (!verdict.ok) { patchKind(kind, {error: verdict.message, note: '', fileName: null}); return; }
    patchKind(kind, {busy: true, error: null, note: '', fileName: file.name});
    try {
      const [document] = await uploadDocuments([{kind, file}]);
      changeText(kind, document.text);
      patchKind(kind, {busy: false, note: documentStatus(document.warnings)});
    } catch (reason) {
      patchKind(kind, {busy: false, fileName: null, error: reason instanceof Error ? reason.message : '파일을 읽지 못했습니다.'});
    }
  }, [changeText, patchKind]);

  const generate = useCallback(async () => {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setGenerating(true); setError(null); setProgress(null);
    try {
      const result = await requestPlan(buildPlanRequest(texts, job, excludeCommonIds()),
        {signal: controller.signal, onProgress: p => { if (!controller.signal.aborted) setProgress(p); }});
      if (controller.signal.aborted) return;
      setPlan(result);
      setOrder(result.questions.map(q => q.id));
      setSelected(result.questions.map(q => q.id));
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof InterviewApiError || reason instanceof Error
        ? reason.message : '질문을 만들지 못했습니다. 다시 시도하세요.');
    } finally {
      if (request.current === controller) request.current = null;
      setGenerating(false);
    }
  }, [texts, job]);

  const cancelGenerate = useCallback(() => { request.current?.abort(); request.current = null; setGenerating(false); setProgress(null); }, []);
  const move = useCallback((id: string, direction: -1 | 1) => setOrder(current => moveQuestion(current, id, direction)), []);
  const toggle = useCallback((id: string) => setSelected(current => toggleQuestion(current, id)), []);
  // A plan serves one session; after it ran, the next interview starts from a fresh plan.
  const resetPlan = useCallback(() => { setPlan(null); setOrder([]); setSelected([]); setError(null); }, []);

  const chosen = selectedIds(order, selected);
  const start = plan && canStartInterview(order, selected) ? startPayload(plan, order, selected) : null;
  return {texts, kinds, job, generating, progress, error, plan, order, selected, chosen, start,
    changeText, changeJob, upload, generate, cancelGenerate, move, toggle, resetPlan};
}
