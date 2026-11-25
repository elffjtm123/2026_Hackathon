import { PracticePage } from "./features/practice/PracticePage";
import { useCallback, useEffect, useRef, useState } from "react";
import { PulseExperimentPage } from './features/pulse/PulseExperimentPage';
import { routeFromHash } from './routes';

export default function App() {
  const [hash, setHash] = useState(window.location.hash);
  const hashRef = useRef(hash);
  const busyRef = useRef(false);
  const [navigationWarning, setNavigationWarning] = useState('');
  const activity = useCallback((busy: boolean) => { busyRef.current = busy; }, []);
  useEffect(() => {
    const update = () => {
      if (busyRef.current) {
        window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}${hashRef.current}`);
        setNavigationWarning('진행 중인 연습·녹음을 종료한 뒤 화면을 이동해 주세요.');
        return;
      }
      hashRef.current = window.location.hash; setHash(window.location.hash); setNavigationWarning('');
    };
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  const route = routeFromHash(hash);
  return <>{navigationWarning && <p className="error-banner" role="alert">{navigationWarning}</p>}
    {route.page === 'pulse-pos-experiment' ? <PulseExperimentPage onActivityChange={activity} />
      : route.page === 'practice' ? <PracticePage onActivityChange={activity} />
      : <main className="practice-shell"><h1>없는 화면입니다.</h1><a href="#practice">연습 화면으로</a></main>}
  </>;
}
