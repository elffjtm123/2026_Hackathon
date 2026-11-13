import { useEffect, useRef, useState } from 'react';
import { PulsePanel } from './PulsePanel';

export function PulseExperimentPage({onActivityChange}: {onActivityChange?: (busy: boolean) => void}) {
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState('');
  const [starting, setStarting] = useState(false);
  const owned = useRef<MediaStream | null>(null);
  const generation = useRef(0);
  const stop = () => {
    generation.current++; owned.current?.getTracks().forEach(t => t.stop()); owned.current = null;
    setStream(null); setStarting(false);
  };
  useEffect(() => {
    onActivityChange?.(!!stream || starting);
    return () => onActivityChange?.(false);
  }, [stream, starting, onActivityChange]);
  useEffect(() => () => { generation.current++; owned.current?.getTracks().forEach(t => t.stop()); }, []);
  const start = async () => {
    const attempt = ++generation.current;
    setStarting(true); setError('');
    try {
      const next = await navigator.mediaDevices.getUserMedia({video: {width: {ideal: 640}, height: {ideal: 480}, frameRate: {ideal: 30}}, audio: false});
      if (attempt !== generation.current) { next.getTracks().forEach(t => t.stop()); return; }
      owned.current = next; setStream(next);
    } catch { if (attempt === generation.current) setError('카메라를 시작하지 못했습니다. 권한과 장치 사용 상태를 확인해 주세요.'); }
    finally { if (attempt === generation.current) setStarting(false); }
  };
  return <main className="practice-shell pulse-experiment"><header className="practice-header"><div>
    <p className="eyebrow">REALTIME COACH · RESEARCH LAB</p><h1>POS 비교 실험실</h1></div>
    <a href="#practice/service_qwen" className="secondary-button theme-link">발표·면접으로</a></header>
    <p>학습 없는 POS 기준선의 비교용 화면입니다. 실제 발표 중 사전학습 EfficientPhys를 사용하려면 위 ‘발표·면접으로’를 누르세요.</p>
    <div className="pulse-actions"><button className="primary-button" disabled={starting || !!stream} onClick={() => void start()}>{starting ? '권한 대기 중…' : '카메라만 시작'}</button>
      <button className="secondary-button" disabled={!starting && !stream} onClick={stop}>카메라 종료</button></div>
    {error && <p role="alert" className="error-banner">{error}</p>}
    <PulsePanel stream={stream} showPreview />
  </main>;
}
