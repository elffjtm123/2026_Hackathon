import {useEffect,useMemo,useRef,useState} from 'react';
import type {PracticeSummary} from '../../lib/realtimeProtocol';
import {analyzeActivation,BASELINE_MIN_WINDOWS,BASELINE_START_MS,coachingFor,insightsExport,
  type ActivationAnalysis,type ActivationPoint,type SessionSignals} from './analysis';
import './affect.css';

const W=360,H=200,PAD=34,MID=H/2,AMP=70;
const seconds=(ms:number)=>(ms/1000).toFixed(0);

// One bar per 10 s window on one axis: voice activation relative to the speaker's own baseline.
function ActivationChart({analysis,selected,onSelect}:{analysis:ActivationAnalysis;selected:number|null;onSelect:(i:number)=>void}){
  const points=analysis.points,end=Math.max(1,...points.map(p=>p.endMs));
  const x=(ms:number)=>PAD+(W-PAD-8)*ms/end;
  return <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="구간별 목소리 활성도 · 본인 기준 대비 · 실험적 규칙">
    <rect x={x(BASELINE_START_MS)} y={MID-AMP} width={Math.max(0,x(end)-x(BASELINE_START_MS))} height={AMP*2} className="activation-baseline-zone"/>
    <text x={x(BASELINE_START_MS)+4} y={MID-AMP+12}>기준 산출 구간 (30초 이후)</text>
    <path d={`M${PAD} ${MID}H${W-8}`} className="activation-zero"/>
    <text x={PAD-4} y={MID+4} textAnchor="end">기준</text>
    <text x={PAD-4} y={MID-AMP+4} textAnchor="end">높음</text><text x={PAD-4} y={MID+AMP+4} textAnchor="end">낮음</text>
    {points.map((p,i)=>{
      const left=x(p.startMs)+1,width=Math.max(2,x(p.endMs)-x(p.startMs)-2);
      if(p.activation===null)return <g key={i} onClick={()=>onSelect(i)}><title>{`${seconds(p.startMs)}–${seconds(p.endMs)}초 · ${p.label}`}</title>
        <rect x={left} y={MID-AMP} width={width} height={AMP*2} fill="transparent"/><path d={`M${left} ${MID}h${width}`} className="activation-missing"/></g>;
      const h=Math.abs(p.activation)*AMP;
      return <g key={i} onClick={()=>onSelect(i)}><title>{`${seconds(p.startMs)}–${seconds(p.endMs)}초 · ${p.label} · ${p.activation.toFixed(2)}`}</title>
        <rect x={left} y={MID-AMP} width={width} height={AMP*2} fill="transparent"/>
        <rect x={left} y={p.activation>=0?MID-h:MID} width={width} height={Math.max(1,h)} rx="2"
          className={`activation-bar activation-bar--${p.level}${selected===i?' is-selected':''}`}/></g>;
    })}
    <text x={PAD} y={H-6}>0초</text><text x={W-8} y={H-6} textAnchor="end">{seconds(end)}초</text>
    {analysis.status==='not-enough-data'&&<text x={W/2} y={MID-8} textAnchor="middle" className="activation-empty">근거 부족 · 수치 표시 안 함</text>}
  </svg>;
}

// Separate chart and scale: rPPG is unvalidated and is never combined with the voice result.
function PulseReference({points}:{points:ActivationPoint[]}){
  const values=points.filter(p=>p.pulse.bpm!==null);
  if(!values.length)return <p className="affect-note">맥박 추정 추세: 이번 연습에서 유효한 추정값이 없습니다.</p>;
  const end=Math.max(1,...points.map(p=>p.endMs)),lo=Math.min(...values.map(p=>p.pulse.bpm!))-5,hi=Math.max(...values.map(p=>p.pulse.bpm!))+5;
  const x=(p:ActivationPoint)=>PAD+(W-PAD-8)*((p.startMs+p.endMs)/2)/end,y=(bpm:number)=>12+(76-12)*(hi-bpm)/(hi-lo);
  return <div className="pulse-reference"><h3>맥박 추정 추세 · 참고용·미검증</h3>
    <svg viewBox={`0 0 ${W} 96`} role="img" aria-label="구간별 맥박 추정값 · 참고용·미검증">
      <text x={PAD-4} y={16} textAnchor="end">{hi.toFixed(0)}</text><text x={PAD-4} y={80} textAnchor="end">{lo.toFixed(0)}</text>
      <path d={values.map((p,i)=>`${i?'L':'M'}${x(p)} ${y(p.pulse.bpm!)}`).join('')} className="pulse-reference-line"/>
      {values.map((p,i)=><circle key={i} cx={x(p)} cy={y(p.pulse.bpm!)} r="4" className="pulse-reference-dot">
        <title>{`${seconds(p.startMs)}–${seconds(p.endMs)}초 · ${p.pulse.bpm!.toFixed(0)} BPM (추정 ${p.pulse.count}개)`}</title></circle>)}
    </svg>
    <p className="affect-note">카메라 맥박 추정은 정확도가 검증되지 않았습니다. 목소리 활성도 계산에 쓰지 않고, 화면에서만 보여 주며 JSON 내려받기에도 넣지 않습니다.</p></div>;
}

export function SessionInsights({summary,signals}: {summary:PracticeSummary;signals:SessionSignals}){
  const dialog=useRef<HTMLDialogElement>(null);
  const analysis=useMemo(()=>analyzeActivation(signals,summary.deliveryMetrics),[signals,summary.deliveryMetrics]);
  const coaching=useMemo(()=>coachingFor(summary),[summary]);
  const [selected,setSelected]=useState<number|null>(null);
  const point=selected===null?null:analysis.points[selected];
  const enough=analysis.status==='ok';
  useEffect(()=>{const node=dialog.current;node?.showModal();return()=>node?.close();},[summary.sessionId]);
  const download=()=>{
    const url=URL.createObjectURL(new Blob([JSON.stringify(insightsExport(summary.sessionId,analysis,coaching,summary.deliveryMetrics),null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='presentation-session-insights.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  const percent=(v:number|null)=>v===null?'—':`${v>=0?'+':''}${Math.round(v*100)}%`;
  const signed=(v:number|null,unit:string)=>v===null?'—':`${v>=0?'+':''}${v.toFixed(1)} ${unit}`;
  return <section className="session-insights" aria-label="목소리 활성도와 최종 피드백">
    <header><div><p className="eyebrow">SESSION INSIGHTS · EXPERIMENT</p><h2>목소리 활성도와 최종 피드백</h2></div>
      <button className="primary-button" onClick={()=>dialog.current?.showModal()}>최종 피드백 다시 보기</button></header>
    <div className="affect-layout"><div className="affect-chart">
      <ActivationChart analysis={analysis} selected={selected} onSelect={setSelected}/>
    </div><div className="affect-explanation"><h3>{point?.label??analysis.label}</h3>
      {enough
        ? <p>시작 30초 이후의 유효 10초 구간 {analysis.baseline.windowCount}개를 본인 기준으로 삼고, 각 구간의 목소리를 그 기준과 비교했습니다. 비교 구간 {analysis.comparedCount}개</p>
        : <p>근거 부족: 시작 30초 이후에 음성이 충분한 10초 구간이 {BASELINE_MIN_WINDOWS}개 이상 있어야 본인 기준을 만들 수 있습니다. 이번 연습은 {analysis.baseline.windowCount}개라 수치를 표시하지 않습니다.</p>}
      {enough&&(point?point.activation!==null:true)&&<p>기준 대비 목소리 활성도 {(point?point.activation!:analysis.overall!).toFixed(2)} <small>(−1 낮음 · 0 기준 · +1 높음)</small></p>}
      <p className="affect-note">실험용 규칙이며 검증된 측정이 아닙니다. 목소리의 높낮이·속도·음량이 이번 연습의 본인 기준과 얼마나 다른지만 나타내며, 확률·진단·면접 점수가 아닙니다.</p>
      <details><summary>판단 기준과 사용한 근거</summary><ul>
        <li>본인 기준: 시작 30초 이후의 유효 구간 중앙값입니다. 초반 30초는 음높이가 평소보다 낮게 나오는 경향이 있어 기준에서 뺍니다.</li>
        <li>목소리 활성도: 음높이 변화 45%, 조음 속도 변화 35%, 음량 변화 20%를 결합하고, 눈 크게 뜸 변화를 10%만 더합니다.</li>
        <li>음높이 4반음·속도 25%·음량 6 dB를 변화 척도로 쓰고, ±0.2 이상이면 높음/낮음으로 표시합니다. 모두 검증 전의 조정 가능한 초기값입니다.</li>
        <li>자동 음량 조절이 꺼졌다고 확인된 경우에만 음량을 씁니다. 얼굴이 절반 이상 보이지 않은 구간은 눈 움직임을 빼고 목소리만 씁니다.</li>
        <li>맥박 추정값, 시선 이탈, 습관어는 목소리 활성도 계산에 쓰지 않습니다.</li>
      </ul></details>
    </div></div>
    <PulseReference points={analysis.points}/>
    {analysis.points.length>0&&<details><summary>구간별 결과와 측정 부족 이유</summary><div className="affect-table"><table><thead><tr><th>구간</th><th>결과</th><th>음높이 변화</th><th>속도 변화</th><th>음량 변화</th><th>표정 관찰</th><th>부족한 근거</th></tr></thead>
      <tbody>{analysis.points.map((p,i)=><tr key={i}><td><button className="affect-time" onClick={()=>setSelected(i)}>{seconds(p.startMs)}–{seconds(p.endMs)}초{p.inBaseline?' · 기준':''}</button></td>
        <td>{p.label}</td><td>{signed(p.evidence.f0Semitones,'반음')}</td><td>{percent(p.evidence.rateChange)}</td>
        <td>{signed(p.evidence.loudnessDb,'dB')}</td><td>{Math.round(p.evidence.faceCoverage*100)}%</td><td>{p.missing.join(' · ')||'—'}</td></tr>)}</tbody></table></div>
      <button className="secondary-button" onClick={()=>setSelected(null)}>전체 평균 보기</button></details>}
    <button className="secondary-button" onClick={download}>종합 결과 JSON 내려받기</button>
    <dialog ref={dialog} className="coaching-dialog" aria-label="세션 종료 최종 피드백">
      <header><div><p className="eyebrow">YOUR NEXT PRACTICE</p><h2>이번 연습의 최종 피드백</h2></div><button className="secondary-button" autoFocus onClick={()=>dialog.current?.close()}>닫기</button></header>
      <p>목소리 활성도: <strong>{analysis.label}</strong> <small>· 실험적 규칙 · 비교 {analysis.comparedCount}구간</small></p>
      <p className="coaching-intro">시선·속도·습관어의 실제 분석 결과를 기준으로 다음 연습에서 바꿀 행동을 정리했습니다.</p>
      {coaching.strengths.length>0&&<div className="coaching-strength"><h3>잘된 점</h3><ul>{coaching.strengths.map(v=><li key={v}>{v}</li>)}</ul></div>}
      {coaching.improvements.length>0&&<div><h3>확인할 점</h3><ul>{coaching.improvements.map(v=><li key={v}>{v}</li>)}</ul></div>}
      <div className="coaching-next"><h3>다음 연습 목표</h3><ol>{coaching.nextPractice.map(v=><li key={v}>{v}</li>)}</ol></div>
      <p className="affect-note">속도 범위와 시선 비율 기준은 서비스의 초기 설정입니다. 목소리 활성도는 발표 평가나 사람의 능력 판정에 반영하지 않습니다.</p>
      <button className="primary-button" onClick={()=>dialog.current?.close()}>구간별 결과 확인하기</button>
    </dialog>
  </section>;
}
