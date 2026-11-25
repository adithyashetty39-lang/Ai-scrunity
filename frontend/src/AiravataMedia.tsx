import type { SyntheticEvent } from 'react';

const videoSource = new URL('./media/airavata-flyby.webm', import.meta.url).href;
const stillSource = new URL('./media/airavata-still.webp', import.meta.url).href;

function canComposite(video: HTMLVideoElement) {
  // Some browsers decode VP9 without its alpha plane. The corner of every frame is transparent.
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1;
  const context = canvas.getContext('2d', { willReadFrequently: true });
  if (!context) return false;
  context.drawImage(video, 0, 0, 1, 1, 0, 0, 1, 1);
  return context.getImageData(0, 0, 1, 1).data[3] < 8;
}

type VideoProps = {
  className: string;
  onPlaying: () => void;
  onWaiting: () => void;
  onEnded: () => void;
  onUnavailable: () => void;
};

export function AiravataVideo({ className, onPlaying, onWaiting, onEnded, onUnavailable }: VideoProps) {
  async function prepare(event: SyntheticEvent<HTMLVideoElement>) {
    const video = event.currentTarget;
    try {
      if (!canComposite(video)) throw new Error('Transparent video unavailable');
      await video.play();
    } catch {
      if (video.isConnected) onUnavailable();
    }
  }
  return <video className={className} src={videoSource} width={696} height={360}
    muted playsInline disablePictureInPicture preload="auto"
    onLoadedData={prepare} onPlaying={onPlaying} onWaiting={onWaiting}
    onEnded={onEnded} onError={onUnavailable}/>;
}

export function AiravataStill({ className, alt = '', onError }: {
  className: string; alt?: string; onError: () => void;
}) {
  return <img className={className} src={stillSource} width={696} height={360} alt={alt} onError={onError}/>;
}
