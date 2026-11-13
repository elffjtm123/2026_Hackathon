import {useEffect,useMemo,useRef,useState} from 'react';
import type {PracticeSummary} from '../../lib/realtimeProtocol';
import {analyzeAffect,coachingFor,type SessionSignals} from './analysis';
import './affect.css';

export function SessionInsights({summary,signals}: {summary:PracticeSummary;signals:SessionSignals}){
  const dialog=useRef<HTMLDialogElement>(null);
  const analysis=useMemo(()=>analyzeAffect(signals,summary.deliveryMetrics),[signals,summary.deliveryMetrics]);
  const coaching=useMemo(()=>coachingFor(summary),[summary]);
  const [selected,setSelected]=useState<number|null>(null);
  const point=selected===null?null:analysis.points[selected];
  const position=point?.status==='estimated'?{valence:point.valence!,arousal:point.arousal!}:selected===null?analysis.overall:null;
  const plotScale=position?105/Math.max(1,Math.hypot(position.valence,position.arousal)):105;
  useEffect(()=>{dialog.current?.showModal();return()=>dialog.current?.close();},[summary.sessionId]);
  const download=()=>{
    const url=URL.createObjectURL(new Blob([JSON.stringify({schema:'session-insights.v1',sessionId:summary.sessionId,
      method:'Experimental personal-baseline rules, not a validated emotion classifier',analysis,coaching,
      delivery:summary.deliveryMetrics},null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='presentation-session-insights.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  return <section className="session-insights" aria-label="종합 상태와 최종 피드백">
    <header><div><p className="eyebrow">SESSION INSIGHTS · EXPERIMENT</p><h2>종합 상태와 최종 피드백</h2></div>
      <button className="primary-button" onClick={()=>dialog.current?.showModal()}>최종 피드백 다시 보기</button></header>
    <div className="affect-layout"><div className="affect-chart">
      <svg viewBox="0 0 360 330" role="img" aria-label="쾌·불쾌와 각성도 원형 모형 · 실험적 추정">
        <circle cx="180" cy="160" r="115" fill="#eaf2f7"/>
        <path d="M180 160V45A115 115 0 0 1 295 160Z" fill="#dcefe8"/>
        <path d="M180 160H65A115 115 0 0 1 180 45Z" fill="#f7e6df"/>
        <path d="M180 160V275A115 115 0 0 1 65 160Z" fill="#eee9f4"/>
        <path d="M180 160H295A115 115 0 0 1 180 275Z" fill="#e0eff0"/>
        <path d="M45 160H315M180 25V295" stroke="#6a7e88" strokeWidth="1.5"/>
        <text x="180" y="17" textAnchor="middle">높은 각성</text><text x="180" y="317" textAnchor="middle">낮은 각성</text>
        <text x="15" y="151">불쾌</text><text x="314" y="151">쾌</text>
        <text x="108" y="103" textAnchor="middle">긴장·불편</text><text x="251" y="103" textAnchor="middle">활기·기대</text>
        <text x="108" y="225" textAnchor="middle">저활성·불편</text><text x="251" y="225" textAnchor="middle">차분·편안</text>
        {position?<g><circle cx={180+position.valence*plotScale} cy={160-position.arousal*plotScale} r="15" fill="#2b697b22"/>
          <circle cx={180+position.valence*plotScale} cy={160-position.arousal*plotScale} r="6" fill="#245c70" stroke="white" strokeWidth="2"/></g>
          :<text x="180" y="166" textAnchor="middle" className="affect-chart-empty">판단 보류</text>}
      </svg>
    </div><div className="affect-explanation"><h3>{point?.label??analysis.dominant}</h3>
      <p>세 신호가 겹치는 10초 구간으로 비교합니다. 유효 기준 구간 {analysis.baselineCount}/3개 · 분류 구간 {analysis.estimatedCount}개</p>
      {position&&<p>쾌·불쾌 축 {position.valence.toFixed(2)} · 상대 각성 축 {position.arousal.toFixed(2)}</p>}
      {!analysis.estimatedCount&&<p>표정·새 맥박값·음성 특징이 함께 있는 완전한 10초 구간 3개를 기준으로 모은 뒤, 이후 구간을 비교해야 합니다.</p>}
      <p className="affect-note">실험용 규칙 추정입니다. 본인의 실제 감정과 다를 수 있으며, 확률·진단·면접 점수가 아닙니다. 초기 기준도 안정 상태가 확인된 값은 아닙니다.</p>
      <details><summary>판단 기준과 사용한 근거</summary><ul>
        <li>쾌·불쾌: 입꼬리 올림·내림과 눈썹 내림 계수로 만든 표정 단서입니다.</li>
        <li>각성: 개인 기준 대비 맥박 변화 45%, 음높이·조음 속도·음량 변화 45%, 눈 크게 뜸 변화 10%를 결합합니다.</li>
        <li>맥박 15 BPM·음높이 4반음·속도 25%·음량 6 dB를 변화 척도로 사용합니다. 모두 검증 전의 조정 가능한 초기값입니다.</li>
        <li>자동 음량 조절이 꺼졌다고 확인된 경우에만 음량을 결합합니다. 이전 맥박값·잠정값과 누락 구간은 제외합니다.</li>
        <li>시선 이탈과 습관어는 발표 피드백에 쓰고 감정을 결정하는 입력으로 사용하지 않습니다.</li>
      </ul><a href="https://doi.org/10.1037/h0077714" target="_blank" rel="noreferrer">Russell의 원형 감정 모형</a>
        <p>원형 모형은 표시 틀입니다. 위 수식·가중치가 논문에서 검증된 분류기는 아닙니다.</p></details>
    </div></div>
    {analysis.points.length>0&&<details><summary>구간별 상태와 측정 부족 이유</summary><div className="affect-table"><table><thead><tr><th>구간</th><th>상태</th><th>표정 관찰</th><th>새 맥박</th><th>음높이</th><th>부족한 근거</th></tr></thead>
      <tbody>{analysis.points.map((p,i)=><tr key={i}><td><button className="affect-time" onClick={()=>setSelected(i)}>{(p.startMs/1000).toFixed(0)}–{(p.endMs/1000).toFixed(0)}초</button></td>
        <td>{p.label}</td><td>{Math.round(p.evidence.faceCoverage*100)}%</td><td>{p.evidence.pulseBpm===null?'—':p.evidence.pulseBpm.toFixed(0)+' BPM'} ({p.evidence.pulseCount}개)</td>
        <td>{p.evidence.f0?.toFixed(0)??'—'} Hz</td><td>{p.missing.join(' · ')||'세 신호 확인'}</td></tr>)}</tbody></table></div>
      <button className="secondary-button" onClick={()=>setSelected(null)}>전체 분류 구간 평균 보기</button></details>}
    <button className="secondary-button" onClick={download}>종합 결과 JSON 내려받기</button>
    <dialog ref={dialog} className="coaching-dialog" aria-label="세션 종료 최종 피드백">
      <header><div><p className="eyebrow">YOUR NEXT PRACTICE</p><h2>이번 연습의 최종 피드백</h2></div><button className="secondary-button" autoFocus onClick={()=>dialog.current?.close()}>닫기</button></header>
      <p>종합 상태: <strong>{analysis.dominant}</strong> <small>· 실험적 추정 · 분류 {analysis.estimatedCount}구간</small></p>
      <p className="coaching-intro">시선·속도·습관어의 실제 분석 결과를 기준으로 다음 연습에서 바꿀 행동을 정리했습니다.</p>
      {coaching.strengths.length>0&&<div className="coaching-strength"><h3>잘된 점</h3><ul>{coaching.strengths.map(v=><li key={v}>{v}</li>)}</ul></div>}
      {coaching.improvements.length>0&&<div><h3>확인할 점</h3><ul>{coaching.improvements.map(v=><li key={v}>{v}</li>)}</ul></div>}
      <div className="coaching-next"><h3>다음 연습 목표</h3><ol>{coaching.nextPractice.map(v=><li key={v}>{v}</li>)}</ol></div>
      <p className="affect-note">속도 범위와 시선 비율 기준은 서비스의 초기 설정입니다. 감정 추정은 발표 평가나 사람의 능력 판정에 반영하지 않습니다.</p>
      <button className="primary-button" onClick={()=>dialog.current?.close()}>구간별 결과 확인하기</button>
    </dialog>
  </section>;
}
