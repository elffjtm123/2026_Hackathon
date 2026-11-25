import { InterviewReport } from './InterviewReport';
import { formatScore } from './reportModel';
import type { StoredResult } from './storage';
import './interview.css';

// A result kept in this browser: questions, transcripts and the evaluation (when it finished).
export function StoredResultView({ result, onBack, onDelete }: { result: StoredResult; onBack: () => void; onDelete: () => void }) {
  const evaluation = {
    status: result.evaluation ? 'complete' as const : 'failed' as const,
    progress: null, evaluation: result.evaluation,
    error: result.evaluation ? null : '이 면접은 평가 없이 저장되었습니다. 받아쓰기만 볼 수 있습니다.',
  };
  return (
    <section className="interview-report" aria-label="저장된 면접 결과">
      <header className="interview-report__intro">
        <h2>저장된 면접 결과</h2>
        <p>{new Date(result.date).toLocaleString('ko-KR')}{result.evaluation ? ` · 전체 ${formatScore(result.evaluation.overall_score)}` : ''}</p>
        <div className="interview-actions">
          <button type="button" className="secondary-button" onClick={onBack}>목록으로</button>
          <button type="button" className="secondary-button" onClick={onDelete}>이 결과 삭제</button>
        </div>
      </header>
      <InterviewReport items={result.items} questions={result.questions} evaluation={evaluation} />
    </section>
  );
}
