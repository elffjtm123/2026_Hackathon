import { PracticePage } from "./features/practice/PracticePage";
import { useCallback, useEffect, useRef, useState } from "react";
import { ExperimentPage } from "./features/stt-experiments/ExperimentPage";
import { ModelThemesPage } from './features/model-themes/ModelThemesPage';
import { PulseExperimentPage } from './features/pulse/PulseExperimentPage';
import { routeFromHash, themesHash } from './routes';

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
        setNavigationWarning('진행 중인 연습·녹음·실험을 종료한 뒤 테마를 변경해 주세요.');
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
      : route.page === 'stt-experiments' ? <ExperimentPage onActivityChange={activity} />
      : route.page === 'practice' ? <PracticePage key={route.theme.id} theme={route.theme} onActivityChange={activity} />
      : route.page === 'themes' ? <ModelThemesPage />
      : <main className="practice-shell"><h1>없는 모델 테마입니다.</h1><p>지원하는 테마를 선택해 주세요.</p><a href={themesHash}>테마 선택으로</a></main>}
  </>;
}
