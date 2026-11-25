import { useEffect, useState } from 'react';
import { AiravataStill, AiravataVideo } from './AiravataMedia';
import './flyby.css';

type Phase = 'idle' | 'loading' | 'playing' | 'still';

export function AiravataFlyby() {
  const [phase, setPhase] = useState<Phase>('idle');
  const [stalled, setStalled] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (phase === 'idle') return;
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    function stopWithEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') setPhase('idle');
    }
    function showStillOnReduce(event: MediaQueryListEvent) {
      if (event.matches) setPhase('still');
    }
    window.addEventListener('keydown', stopWithEscape);
    reduceMotion.addEventListener('change', showStillOnReduce);
    return () => {
      window.removeEventListener('keydown', stopWithEscape);
      reduceMotion.removeEventListener('change', showStillOnReduce);
    };
  }, [phase]);

  useEffect(() => {
    if (phase !== 'loading') return;
    const timeout = window.setTimeout(() => setPhase('still'), 10000);
    return () => window.clearTimeout(timeout);
  }, [phase]);

  function toggleFlyby() {
    setMessage('');
    setStalled(false);
    if (phase !== 'idle') setPhase('idle');
    else setPhase(window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'still' : 'loading');
  }

  const buttonLabel = phase === 'loading' ? 'Cancel flyby'
    : phase === 'playing' ? 'Stop flyby'
    : phase === 'still' ? 'Close flyby'
    : 'Airavata flyby';

  return <>
    <button type="button" className="secondary flyby-trigger"
      aria-expanded={phase !== 'idle'} aria-controls={phase === 'idle' ? undefined : 'airavata-visual'}
      onClick={toggleFlyby}>
      <span aria-hidden="true">{phase === 'idle' ? '▷' : '×'}</span>{buttonLabel}
    </button>
    {message && <span role="status" className="sr-only">{message}</span>}
    {phase !== 'idle' && <div className="flyby-sky" id="airavata-visual" data-phase={phase} data-visual>
      {phase === 'still'
        ? <AiravataStill className="flyby-still" alt="Airavata gliding with ivory wings"
            onError={() => { setPhase('idle'); setMessage('Airavata artwork is temporarily unavailable.'); }} />
        : <div className="flyby-path" aria-hidden="true" style={{ animationPlayState: stalled ? 'paused' : undefined }}>
            <AiravataVideo className="flyby-creature"
              onPlaying={() => { setStalled(false); setPhase('playing'); }}
              onWaiting={() => setStalled(true)}
              onEnded={() => setPhase('idle')}
              onUnavailable={() => setPhase('still')} />
          </div>}
    </div>}
  </>;
}
