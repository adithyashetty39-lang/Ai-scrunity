"""Create a deployable checkout from an explicit allowlist, with an empty data store."""
import shutil
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED


root = Path(__file__).resolve().parent
destination = root / 'tmp' / 'hosted-source'
allowed = [Path(name) for name in ('Dockerfile','.dockerignore','railway.toml','backend/requirements.txt',
    'frontend/index.html','frontend/package.json','frontend/package-lock.json','frontend/tsconfig.json','frontend/vite.config.ts')]
for directory, extensions in (('backend/app',{'.py','.png'}), ('frontend/src',{'.ts','.tsx','.css','.svg','.png'})):
    allowed.extend(path.relative_to(root) for path in (root/directory).rglob('*')
                   if path.is_file() and path.suffix in extensions and not any(part.startswith('.') for part in path.relative_to(root).parts))
allowed.extend(Path('frontend/src/fonts') / name for name in (
    'instrument-sans.woff2', 'instrument-sans-OFL.txt', 'dm-mono.woff2', 'dm-mono-OFL.txt',
))
allowed.extend(Path('frontend/src/media') / name for name in (
    'airavata-flyby.webm', 'airavata-still.webp',
))


def main():
    destination.mkdir(parents=True,exist_ok=True)
    unexpected = {path.relative_to(destination) for path in destination.rglob('*') if path.is_file()}-set(allowed)
    if unexpected:
        raise SystemExit('The staging folder contains unexpected files. Use an empty staging directory before uploading.')
    archive = root/'tmp'/'scrutiny-hosted-source.zip'
    with ZipFile(archive,'w',ZIP_DEFLATED) as output:
        for relative in sorted(allowed):
            source = (root/relative).resolve(strict=True)
            if source != root/relative or not source.is_file():
                raise ValueError(f'Expected an ordinary source file: {relative}')
            target = destination/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.is_symlink() or not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError(f'Unsafe staging path: {relative}')
            shutil.copyfile(source,target)
            output.write(target,relative.as_posix())
    print(f'Packaged {len(allowed)} source files in {archive}')


if __name__ == '__main__':
    main()
