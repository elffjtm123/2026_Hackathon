import type { FeedbackState } from "../feedbackState";
import {directionLabels, gazeLabel, speechPaceLabels} from '../feedbackState';
import type { ConnectionStatus } from "../types";

type FeedbackPanelProps = {
  connectionStatus: ConnectionStatus;
  feedback: FeedbackState;
  socketError: string | null;
};

const statusLabels: Record<ConnectionStatus, string> = {
  idle: "대기",
  connecting: "연결 중",
  connected: "백엔드",
  disconnected: "연결 끊김",
  error: "오류",
};

export function FeedbackPanel({
  connectionStatus,
  feedback,
  socketError,
}: FeedbackPanelProps) {
  return (
    <section className="side-panel" aria-label="최신 피드백">
      <div className="panel-header">
        <h2>최신 피드백</h2>
        <span className={`status-pill status-pill--${connectionStatus}`}>
          {statusLabels[connectionStatus]}
        </span>
      </div>

      {socketError ? <p className="error-text">{socketError}</p> : null}

      {feedback.gaze || feedback.speech || feedback.gazeStale ? (
        <div className="feedback-detail">
          <div>
            <span className="label">시선 상태</span>
            <strong>{gazeLabel(feedback)}</strong>
            <p>{feedback.gaze?.gaze?.message}</p>
          </div>
          <div>
            <span className="label">얼굴 방향</span>
            <strong>{directionLabels[feedback.gaze?.gaze?.headDirection ?? 'unknown']}</strong>
            <small>좌우는 사용자 몸 기준입니다. 프리뷰는 거울처럼 표시됩니다.</small>
            {feedback.gaze?.gaze ? <details><summary>관찰 진단</summary>
              <p>품질 플래그: {feedback.gaze.gaze.qualityFlags?.join(', ') || '없음'}</p>
              <p>얼굴 각도: yaw {feedback.gaze.gaze.headPose.yaw?.toFixed(1) ?? '미측정'}° / pitch {feedback.gaze.gaze.headPose.pitch?.toFixed(1) ?? '미측정'}°</p>
              <p>시선 각도: yaw {feedback.gaze.gaze.gazeAngles?.yaw?.toFixed(1) ?? '미측정'}° / pitch {feedback.gaze.gaze.gazeAngles?.pitch?.toFixed(1) ?? '미측정'}°</p>
            </details> : null}
          </div>
          <div>
            <span className="label">발화 속도</span>
            <strong>{speechPaceLabels[feedback.speech?.speech?.pace ?? 'unknown']}</strong>
            <p>{feedback.speech?.speech?.message}</p>
          </div>
          {feedback.speech?.filler ? <div>
            <span className="label">받아쓰기에서 검출된 습관어</span>
            <strong>{feedback.speech.filler.status === 'disabled' ? '비활성' : feedback.speech.filler.totalCount === null ? '분석 없음' : `${feedback.speech.filler.totalCount}회`}</strong>
            <p>{feedback.speech.filler.totalCount === null ? '인식된 발화가 있어야 집계할 수 있습니다.' : Object.entries(feedback.speech.filler.counts ?? {})
              .map(([word,count]) => `${word} ${count}회`).join(', ') || '검출 없음'}</p>
            <small>음성 인식에서 생략된 습관어는 집계되지 않을 수 있습니다.</small>
          </div> : null}
          {feedback.speech?.transcript ? (
            <div>
              <span className="label">인식된 음성</span>
              <p>{feedback.speech.transcript}</p>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="muted-text">세션을 시작하면 피드백이 표시됩니다.</p>
      )}
    </section>
  );
}
