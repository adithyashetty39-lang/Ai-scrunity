"""Entrypoint for the single-instance hosted deployment."""
import os
from pathlib import Path

import uvicorn


def main():
    if len(os.environ.get('SCRUTINY_ACCESS_TOKEN','')) < 32:
        raise SystemExit('Set SCRUTINY_ACCESS_TOKEN to a randomly generated secret of at least 32 characters.')
    if not os.environ.get('SCRUTINY_AI_KEY') or not os.environ.get('SCRUTINY_AI_MODEL'):
        raise SystemExit('Set the hosted provider key and model as runtime environment variables.')
    volume = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH') or os.environ.get('SCRUTINY_DATA_DIR')
    if not volume or not Path(volume).is_dir():
        raise SystemExit('Mount a persistent volume and configure SCRUTINY_DATA_DIR to its path.')
    os.environ['SCRUTINY_DATA_DIR'] = volume
    uvicorn.run('app.main:app',host='0.0.0.0',port=int(os.environ.get('PORT','8010')),workers=1)


if __name__ == '__main__':
    main()
