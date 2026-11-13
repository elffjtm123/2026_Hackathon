import {deliveryForUser, type DeliveryMetrics, type DeliveryRow} from './metrics';

const fmt = (n: unknown, digits=1) => typeof n === 'number' && Number.isFinite(n) ? n.toFixed(digits) : '—';
const columns = [
  ['speech_rate','발화 속도','음절/분'], ['articulation_rate','조음 속도','음절/분'],
  ['f0_median_hz','음높이 F0','Hz'], ['f0_st','상대 음높이','반음'], ['loudness_rel_db','기준 대비 음량','dB'],
  ['pause_count','쉼','회'], ['longest_pause_ms','최장 쉼','ms'],
  ['sentence_end_pause_ms','다음 문장까지 쉼','ms'], ['disfluency_density','습관어·반복 밀도','회/유성 분'],
] as const;

function FeatureTable({rows, windows}: {rows: DeliveryRow[]; windows?: boolean}) {
  const visible = columns.filter(([key]) => rows.some(row => key in row));
  return <div className="delivery-table"><table><thead><tr><th>{windows ? '분석 구간' : '대본 문장'}</th>
    <th>유성 시간</th>{windows && <th>유성 비율</th>}
    {visible.map(([key,label,unit]) => <th key={key}>{label}{unit && <small>{unit}</small>}</th>)}</tr></thead>
    <tbody>{rows.map((row, index) => <tr key={index}><th scope="row">{windows
      ? `${fmt(row.start_ms == null ? null : row.start_ms/1000)}–${fmt(row.end_ms == null ? null : row.end_ms/1000)}초`
      : `${(row.sentence_index ?? index)+1}번`}</th>
      <td>{fmt(row.voiced_ms == null ? null : row.voiced_ms/1000)}초</td>
      {windows && <td>{fmt(row.coverage == null ? null : row.coverage*100,0)}%</td>}
      {visible.map(([key]) => <td key={key}>{fmt(row[key])}</td>)}
    </tr>)}</tbody></table></div>;
}

// User-facing view: PVQ, absolute loudness and spectral balance are withheld (deliveryForUser).
export function DeliveryReport({metrics: raw,sessionId}: {metrics?: DeliveryMetrics;sessionId:string}) {
  const metrics = deliveryForUser(raw);
  if (!metrics) return null;
  const windows=metrics.windows?.windows ?? [], sentences=metrics.report?.sentences ?? [];
  const last=windows.filter(row=>(row.voiced_ms??0)>=1000).at(-1);
  const download=()=>{
    const url=URL.createObjectURL(new Blob([JSON.stringify({schema:'voice-features.v1',sessionId,delivery_metrics:metrics},null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download='presentation-voice-features.json';link.click();
    window.setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  return <section className="delivery-report" aria-label="목소리 전달력 특징 결과">
    <header><div><p className="eyebrow">VOICE FEATURES · SESSION REPORT</p><h2>목소리 전달력 · 특징 추출 결과</h2></div>
      <span className="status-pill">{{observed:'특징 추출 완료',unavailable:'근거 부족 · 부분 결과',disabled:'비활성',failed:'분석 실패'}[metrics.status]}</span></header>
    {metrics.status==='disabled' ? <p>이번 연습에서 목소리 전달력 분석을 껐습니다.</p>
      : metrics.status==='failed' ? <p>음성 특징 추출이 완료되지 않았습니다. 다른 분석 결과와 구분해 확인해 주세요.</p>
      : <>
        <p>유성 발화 {fmt((metrics.report?.total_voiced_ms??0)/1000)}초 · 대본 문장 {sentences.length}개 · 시간 구간 {windows.length}개</p>
        {metrics.status==='unavailable' && <p className="delivery-note">전체 유성 발화가 60초 미만이거나 분석 근거가 부족합니다. 추출된 구간 특징만 표시합니다.</p>}
        {metrics.agc_on===true && <p className="delivery-note">마이크 자동 음량 조절이 켜져 있어 음량 변화는 표시하지 않습니다.</p>}
        {metrics.agc_on===null && <p className="delivery-meta">마이크 자동 음량 조절 적용 여부를 확인하지 못해 음량 변화는 표시하지 않습니다.</p>}
        {last && <><h3>마지막 유효 구간의 특징</h3><div className="delivery-cards">
          {[['음높이 F0',last.f0_median_hz,'Hz'],
            ...(metrics.agc_on===false ? [['기준 대비 음량',last.loudness_rel_db,'dB']] : []),
            ['발화 속도 · 쉼 포함',last.speech_rate,'음절/분'],['습관어·반복 밀도',last.disfluency_density,'회/유성 분']].map(([label,value,unit])=>
            <div key={String(label)}><span>{label}</span><strong>{fmt(value)} <small>{unit}</small></strong></div>)}
        </div></>}
        {windows.length>0 && <details open><summary>시간 구간별 특징 · 10초 비중첩</summary>
          <p className="delivery-meta">시간은 세션 시계 기준입니다. 시작·종료의 짧은 구간도 포함하며, 유성 발화 1초 미만인 구간의 음향 특징은 비워 둡니다.</p>
          <FeatureTable rows={windows} windows /></details>}
        {sentences.length>0 && <details><summary>대본 문장별 특징</summary><FeatureTable rows={sentences} />
          <p className="delivery-meta">문장 번호는 STT와 대본 정렬 결과에 연결됩니다. 면접처럼 대본이 없으면 같은 문장 번호로 집계될 수 있습니다.</p></details>}
        <button className="secondary-button" onClick={download} disabled={!sentences.length&&!windows.length}>음성 특징 JSON 내려받기</button>
      </>}
    <p className="delivery-meta">음높이·속도·쉼·습관어의 관측값입니다. 음량은 자동 음량 조절이 꺼진 경우에만 이번 연습 안의 상대 변화로 보여 줍니다. 개별 음성 지표는 검증된 전달력 등급이 아닙니다. 원본 음성은 이 결과에 포함하지 않습니다.</p>
  </section>;
}
