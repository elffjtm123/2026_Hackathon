import { PracticePage } from "./features/practice/PracticePage";
import { useCallback, useEffect, useRef, useState } from "react";
import { ExperimentPage } from "./features/stt-experiments/ExperimentPage";
import { ModelThemesPage } from './features/model-themes/ModelThemesPage';
import { modelThemes, themeFromHash } from './features/model-themes/modelThemes';
import { PulseExperimentPage } from './features/pulse/PulseExperimentPage';

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
  const theme = hash === '#pulse-experiment' ? modelThemes[0] : themeFromHash(hash);
  return <>{navigationWarning && <p className="error-banner" role="alert">{navigationWarning}</p>}
    {hash === '#pulse-pos-experiment' ? <PulseExperimentPage onActivityChange={activity} />
      : hash === '#stt-experiments' ? <ExperimentPage onActivityChange={activity} />
      : theme ? <PracticePage key={theme.id} theme={theme} onActivityChange={activity} />
      : !hash || hash === '#' || hash === '#models' ? <ModelThemesPage />
      : <main className="practice-shell"><h1>없는 모델 테마입니다.</h1><p>지원하는 테마를 선택해 주세요.</p><a href="#">테마 선택으로</a></main>}
  </>;
}
