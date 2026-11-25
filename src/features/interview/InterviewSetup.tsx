import { DOCUMENT_KINDS, MAX_JOB_CHARS, MAX_TOTAL_CHARS, planProgressLabel, planWarningText, totalChars } from './planSelection.ts';
import type { StoredResult } from './storage.ts';
import type { useInterviewSetup } from './useInterviewSetup.ts';
import { formatScore } from './reportModel.ts';
import './interview.css';

type Setup = ReturnType<typeof useInterviewSetup>;
type InterviewSetupProps = {
  setup: Setup;
  disabled: boolean;
  onStart: () => void;
  pastResults: StoredResult[];
  onOpenResult: (id: string) => void;
  onDeleteResult: (id: string) => void;
  // Why the questions are gone (a lost connection spent the plan).
  notice?: string | null;
};

const KIND_LABEL = {common: '공통', document: '서류 기반', follow_up: '추가'} as const;

export function InterviewSetup({ setup, disabled, onStart, pastResults, onOpenResult, onDeleteResult, notice = null }: InterviewSetupProps) {
  const total = totalChars(setup.texts);
  const overLimit = total > MAX_TOTAL_CHARS;
  const uploading = DOCUMENT_KINDS.some(({ kind }) => setup.kinds[kind].busy);
  const locked = disabled || setup.generating;
  return (
    <div className="interview-setup">
      <section className="interview-panel" aria-labelledby="interview-docs-title">
        <h2 id="interview-docs-title">면접 서류와 지원 직무</h2>
        {notice ? <p className="error-banner" role="alert">{notice}</p> : null}
        <p className="interview-note">
          자기소개서·이력서·포트폴리오를 올리면 그 내용으로 질문을 만듭니다. 서류 없이도 공통 질문으로 연습할 수 있습니다.
          서류 전문은 저장하지 않고 이 화면에만 남으며, 질문 생성에만 쓰고 버립니다. PDF·DOCX·TXT를 올릴 수 있고,
          한글(HWP) 파일은 PDF로 저장해서 올려 주세요.
        </p>
        {DOCUMENT_KINDS.map(({ kind, label }) => {
          const state = setup.kinds[kind];
          const text = setup.texts[kind] ?? '';
          const inputId = `interview-file-${kind}`;
          const areaId = `interview-text-${kind}`;
          return (
            <fieldset key={kind} className="interview-doc" disabled={locked}>
              <legend>{label}</legend>
              <div className="interview-doc__file">
                <label htmlFor={inputId} className="label">{label} 파일 (PDF, DOCX, TXT)</label>
                <input
                  id={inputId}
                  className="interview-doc__input"
                  type="file"
                  accept=".pdf,.docx,.txt,.hwp,.hwpx"
                  disabled={state.busy}
                  onChange={event => {
                    const file = event.target.files?.[0];
                    event.target.value = '';
                    if (file) void setup.upload(kind, file);
                  }}
                />
                {state.busy || state.fileName ? <span className="interview-doc__name" role="status">{state.busy ? '읽는 중' : state.fileName}</span> : null}
              </div>
              {state.error ? <p className="error-text" role="alert">{state.error}</p> : null}
              {state.note ? <p className="interview-warning" role="status">{state.note}</p> : null}
              <label htmlFor={areaId} className="label">{label} 내용 (직접 고치거나 붙여넣을 수 있습니다)</label>
              <textarea
                id={areaId}
                value={text}
                onChange={event => setup.changeText(kind, event.target.value)}
                rows={5}
              />
              <small className="interview-count">{text.length.toLocaleString()}자</small>
            </fieldset>
          );
        })}
        <p className={overLimit ? 'error-text' : 'interview-count'} role={overLimit ? 'alert' : undefined}>
          서류 글자 수 합계 {total.toLocaleString()} / {MAX_TOTAL_CHARS.toLocaleString()}자
          {overLimit ? ' · 한도를 넘었습니다. 내용을 줄여 주세요.' : ''}
        </p>
        <div className="interview-job">
          <label htmlFor="interview-job" className="label">지원 직무 (선택, {MAX_JOB_CHARS}자 이하)</label>
          <input
            id="interview-job"
            type="text"
            value={setup.job}
            maxLength={MAX_JOB_CHARS}
            disabled={locked}
            onChange={event => setup.changeJob(event.target.value)}
            placeholder="예: 백엔드 개발자"
          />
        </div>
        <div className="interview-actions">
          <button type="button" className="primary-button" onClick={() => void setup.generate()}
            disabled={locked || overLimit || uploading} aria-busy={setup.generating}>
            {setup.generating ? '질문 만드는 중' : setup.plan ? '질문 다시 만들기' : '질문 만들기'}
          </button>
          {setup.generating ? <button type="button" className="secondary-button" onClick={setup.cancelGenerate}>취소</button> : null}
        </div>
        {setup.generating ? (
          <div className="interview-progress" role="status" aria-live="polite">
            <progress aria-label="질문 생성 진행" max={setup.progress?.total || undefined}
              value={setup.progress?.total ? setup.progress.completed ?? 0 : undefined} />
            <span>{setup.progress ? planProgressLabel(setup.progress) : '질문 생성을 시작하는 중'}</span>
            <small>모델을 불러오는 데 시간이 걸릴 수 있습니다. 끝나면 모델을 정리한 뒤 면접을 시작할 수 있습니다.</small>
          </div>
        ) : null}
        {setup.error ? <p className="error-banner" role="alert">{setup.error}</p> : null}
      </section>

      {setup.plan ? (
        <section className="interview-panel" aria-labelledby="interview-questions-title">
          <h2 id="interview-questions-title">면접 질문 고르기</h2>
          {setup.plan.warnings.map(code => <p key={code} className="interview-warning" role="status">{planWarningText(code)}</p>)}
          <p className="interview-note">
            질문을 빼거나 순서를 바꿀 수 있습니다. 면접이 시작되면 질문은 화면에 잠깐만 보이고, 말을 시작하거나 읽는 시간이 끝나면 사라집니다.
            답이 끝났다고 판단하면 다음 질문으로 넘어갑니다.
          </p>
          <ol className="interview-questions">
            {setup.order.map((id, index) => {
              const question = setup.plan?.questions.find(q => q.id === id);
              if (!question) return null;
              const checked = setup.selected.includes(id);
              return (
                <li key={id} className={`interview-q${checked ? '' : ' is-off'}`}>
                  <label className="interview-q__check">
                    <input type="checkbox" checked={checked} disabled={disabled} onChange={() => setup.toggle(id)} />
                    <span className="interview-q__text">{question.text}</span>
                  </label>
                  <span className="interview-q__kind">{KIND_LABEL[question.kind]}</span>
                  {question.kind === 'document' && question.source_quote ? (
                    <blockquote className="interview-q__source"><span className="label">서류의 근거 문장</span>{question.source_quote}</blockquote>
                  ) : null}
                  <div className="interview-q__move">
                    <button type="button" className="secondary-button" disabled={disabled || index === 0}
                      aria-label={`${index + 1}번 질문을 위로 옮기기`} onClick={() => setup.move(id, -1)}>위로</button>
                    <button type="button" className="secondary-button" disabled={disabled || index === setup.order.length - 1}
                      aria-label={`${index + 1}번 질문을 아래로 옮기기`} onClick={() => setup.move(id, 1)}>아래로</button>
                  </div>
                </li>
              );
            })}
          </ol>
          <p className="interview-count">선택한 질문 {setup.chosen.length}개 / 전체 {setup.order.length}개</p>
          <div className="interview-actions">
            <button type="button" className="primary-button" onClick={onStart} disabled={disabled || setup.start === null}>면접 시작</button>
            {setup.start === null ? <span className="interview-note">질문을 하나 이상 선택하세요.</span> : null}
          </div>
        </section>
      ) : null}

      {pastResults.length > 0 ? (
        <section className="interview-panel" aria-labelledby="interview-past-title">
          <h2 id="interview-past-title">지난 면접 결과</h2>
          <p className="interview-note">이 브라우저에만 최근 10개까지 저장됩니다. 서류 전문은 저장하지 않습니다.</p>
          <ul className="interview-past">
            {pastResults.map(result => (
              <li key={result.interview_id}>
                <span>{new Date(result.date).toLocaleString('ko-KR')}</span>
                <span>{result.evaluation ? formatScore(result.evaluation.overall_score) : '평가 없음'}</span>
                <button type="button" className="secondary-button" onClick={() => onOpenResult(result.interview_id)}>보기</button>
                <button type="button" className="secondary-button" onClick={() => onDeleteResult(result.interview_id)}
                  aria-label={`${new Date(result.date).toLocaleString('ko-KR')} 결과 삭제`}>삭제</button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
