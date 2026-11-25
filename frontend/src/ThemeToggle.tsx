import { useCallback, useEffect, useRef, useState } from 'react';
import { playStorm } from './stormScene';
import './theme-transition.css';

const themeKey = 'scrutiny-theme';
const themeColor = { light: '#f7f7f5', dark: '#11151d' };
type Theme = keyof typeof themeColor;

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(
    () => document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light',
  );
  const [storm, setStorm] = useState(false);
  const stormCanvas = useRef<HTMLCanvasElement>(null);

  const applyTheme = useCallback((next: Theme) => {
    document.documentElement.dataset.theme = next;
    const color = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    if (color) color.content = themeColor[next];
    try {
      localStorage.setItem(themeKey, next);
    } catch {
      // The theme can still be used in a session without browser storage.
    }
    setTheme(next);
  }, []);

  const switchToDark = useCallback(() => applyTheme('dark'), [applyTheme]);
  const finish = useCallback(() => {
    switchToDark();
    setStorm(false);
  }, [switchToDark]);

  useEffect(() => {
    if (!storm || !stormCanvas.current) return;
    const stop = playStorm(stormCanvas.current, switchToDark, finish);
    if (!stop) {
      finish();
      return;
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') finish();
    }
    function onMotionChange(event: MediaQueryListEvent) {
      if (event.matches) finish();
    }
    function onVisibilityChange() {
      if (document.hidden) finish();
    }
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const deadline = window.setTimeout(finish, 2900);
    window.addEventListener('keydown', onKey);
    document.addEventListener('visibilitychange', onVisibilityChange);
    reducedMotion.addEventListener('change', onMotionChange);
    return () => {
      stop();
      window.clearTimeout(deadline);
      window.removeEventListener('keydown', onKey);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      reducedMotion.removeEventListener('change', onMotionChange);
    };
  }, [storm, switchToDark, finish]);

  function toggleTheme() {
    if (storm) finish();
    else if (theme === 'dark') applyTheme('light');
    else if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) switchToDark();
    else setStorm(true);
  }

  const nextAction = storm ? 'Skip dark mode animation'
    : theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';

  return <>
    <button type="button" className="secondary theme-toggle" aria-label={nextAction}
      title={nextAction} onClick={toggleTheme}>
      <span className="theme-icon" aria-hidden="true">{storm ? '»' : theme === 'dark' ? '☀' : '☾'}</span>
      <span className="theme-label">{storm ? 'Skip intro' : theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
    </button>
    {storm && <canvas className="theme-storm" aria-hidden="true" ref={stormCanvas}/>}
  </>;
}
