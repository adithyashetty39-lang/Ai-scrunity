import { useEffect, useRef, useState } from 'react';
import { AiravataStill, AiravataVideo } from './AiravataMedia';
import './review-wait.css';

export type ReviewJobPhase = 'preparing' | 'queued' | 'running';
type VisualPhase = 'delayed' | 'loading' | 'playing' | 'still' | 'finished';

const statusCopy: Record<ReviewJobPhase, { title: string; detail: string }> = {
  preparing: { title: 'Preparing evaluation', detail: 'Saving the current draft before sending it to the review queue.' },
  queued: { title: 'Queued for evaluation', detail: 'The draft is saved. Evaluation will start when a review worker is available.' },
  running: { title: 'Evaluating questions', detail: 'Scrutiny is checking each question against the confirmed syllabus and verifying its recommendations.' },
};

export function ReviewWaitingPanel({ phase }: { phase: ReviewJobPhase }) {
  const [visual, setVisual] = useState<VisualPhase>('delayed');
  const [stalled, setStalled] = useState(false);
  const statusRef = useRef<HTMLDivElement>(null);
  const copy = statusCopy[phase];
  const videoActive = visual === 'playing' || visual === 'loading';

  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const delay = window.setTimeout(() => setVisual(preference.matches ? 'still' : 'loading'), 2000);
    function reduceMotion(event: MediaQueryListEvent) {
      if (event.matches) setVisual(current => current === 'loading' || current === 'playing' ? 'still' : current);
    }
    preference.addEventListener('change', reduceMotion);
    return () => {
      window.clearTimeout(delay);
      preference.removeEventListener('change', reduceMotion);
    };
  }, []);

  useEffect(() => {
    if (visual !== 'loading' && !(visual === 'playing' && stalled)) return;
    const timer = window.setTimeout(() => setVisual('still'), 8000);
    return () => window.clearTimeout(timer);
  }, [visual, stalled]);

  return <div className="review-wait">
    <div className="review-wait-copy">
      <div ref={statusRef} role="status" aria-atomic="true" tabIndex={-1}>
        <h3>{copy.title}</h3>
        <p>{copy.detail}</p>
      </div>
      {videoActive && <button type="button" className="secondary" onClick={() => {
        setVisual('still');
        statusRef.current?.focus({ preventScroll: true });
      }}>
        Skip animation
      </button>}
    </div>
    <div className="review-wait-art" aria-hidden="true" data-visual data-phase={visual}>
      <div className="review-sheet"/>
      {visual === 'still' && <AiravataStill className="review-wait-still" onError={() => setVisual('finished')}/>}
      {videoActive && <div className="review-wait-flight">
        <AiravataVideo className="review-wait-creature"
          onPlaying={() => { setStalled(false); setVisual('playing'); }}
          onWaiting={() => setStalled(true)}
          onEnded={() => setVisual('still')}
          onUnavailable={() => setVisual('still')}/>
      </div>}
    </div>
  </div>;
}
