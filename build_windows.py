#!/usr/bin/env python3
"""Build native Windows x64 ZIP and per-user setup, bundling verified FFmpeg.

Run --prepare before source tests; otherwise pass --version X.Y.Z to build.
The downloaded archive is immutable and verified against its publisher's digest.
No build output is checked into the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / 'build' / 'windows'
FFMPEG_VERSION = '8.1.2'
FFMPEG_ARCHIVE = f'ffmpeg-{FFMPEG_VERSION}-essentials_build.zip'
FFMPEG_URL = f'https://github.com/GyanD/codexffmpeg/releases/download/{FFMPEG_VERSION}/{FFMPEG_ARCHIVE}'
# Published SHA-256: official GitHub release asset metadata `digest`.
FFMPEG_SHA256 = 'db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec'
FFMPEG_SOURCE = 'https://github.com/FFmpeg/FFmpeg/commit/38b88335f9'


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare_ffmpeg() -> Path:
    BUILD.mkdir(parents=True, exist_ok=True)
    archive = BUILD / FFMPEG_ARCHIVE
    if not archive.is_file() or digest(archive) != FFMPEG_SHA256:
        temporary = archive.with_suffix('.download')
        try:
            request = urllib.request.Request(FFMPEG_URL, headers={'User-Agent': 'Shenlujian-Windows-build'})
            with urllib.request.urlopen(request, timeout=120) as response, temporary.open('wb') as target:
                if not response.url.startswith('https://'):
                    raise RuntimeError('Refusing a non-HTTPS FFmpeg download')
                shutil.copyfileobj(response, target)
            if digest(temporary) != FFMPEG_SHA256:
                raise RuntimeError('FFmpeg SHA-256 mismatch; download was not used')
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    unpacked = BUILD / 'ffmpeg-download'
    if unpacked.exists():
        shutil.rmtree(unpacked)
    unpacked.mkdir()
    with zipfile.ZipFile(archive) as source:
        for entry in source.infolist():
            destination = (unpacked / entry.filename).resolve()
            if not destination.is_relative_to(unpacked.resolve()):
                raise RuntimeError('Unsafe path in FFmpeg archive')
        source.extractall(unpacked)
    candidates = list(unpacked.glob('*/bin/ffmpeg.exe'))
    if len(candidates) != 1:
        raise RuntimeError('Unexpected FFmpeg archive layout')
    upstream = candidates[0].parent.parent
    destination = BUILD / 'ffmpeg'
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(upstream, destination, ignore=shutil.ignore_patterns('ffplay.exe'))
    if not (destination / 'bin' / 'ffprobe.exe').is_file():
        raise RuntimeError('The archive did not contain ffprobe.exe')
    # Preserve publisher license, README and documentation alongside the binaries.
    (destination / 'FFMPEG-SOURCE.txt').write_text(
        f'FFmpeg {FFMPEG_VERSION}, Gyan essentials GPLv3 build\n'
        f'Binary: {FFMPEG_URL}\nSHA256: {FFMPEG_SHA256}\n'
        f'Publisher checksum metadata: https://api.github.com/repos/GyanD/codexffmpeg/releases/tags/{FFMPEG_VERSION}\n'
        f'Corresponding FFmpeg source: {FFMPEG_SOURCE}\n'
        'Build/distribution documentation: https://www.gyan.dev/ffmpeg/builds/\n'
        'Third-party build recipes and source references: https://github.com/GyanD/codexffmpeg\n'
        'License and configuration notices in this directory apply to FFmpeg.\n', encoding='utf-8')
    print(f'Verified FFmpeg {FFMPEG_VERSION}: {FFMPEG_SHA256}')
    return destination


def bundle_notices(payload: Path) -> None:
    shutil.copy2(ROOT / 'LICENSE', payload / 'LICENSE')
    notice_dir = payload / 'licenses'
    notice_dir.mkdir(exist_ok=True)
    for name in ('PyQt5', 'PyQt5-Qt5', 'PyQt5-sip', 'PyInstaller'):
        package = importlib.metadata.distribution(name)
        folder = notice_dir / name
        folder.mkdir(exist_ok=True)
        for item in package.files or ():
            if any(token in Path(item).name.upper() for token in ('LICENSE', 'COPYING', 'COPYRIGHT')):
                original = Path(package.locate_file(item))
                if original.is_file():
                    # Preserve enough relative structure to avoid repeated LICENSE names.
                    safe_name = str(item).replace('\\', '_').replace('/', '_')
                    shutil.copy2(original, folder / safe_name)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file():
        shutil.copy2(python_license, notice_dir / 'PYTHON-LICENSE.txt')
    (notice_dir / 'WINDOWS-THIRD-PARTY.txt').write_text(
        '神录剪 Windows distribution / third-party notices\n\n'
        'Application: GNU GPLv3; see ../LICENSE and ../source/.\n'
        'Python 3.11.9: Python Software Foundation license, https://www.python.org/downloads/release/python-3119/\n'
        'PyQt5 5.15.11 / PyQt5-sip 12.17.0: GPLv3, https://www.riverbankcomputing.com/software/pyqt/\n'
        'PyQt source: https://pypi.org/project/PyQt5/5.15.11/#files\n'
        'SIP source: https://pypi.org/project/PyQt5-sip/12.17.0/#files\n'
        'Qt 5.15.2 shared libraries: LGPLv3/GPLv3; replaceable DLLs in _internal/PyQt5/Qt5/.\n'
        'Qt source: https://download.qt.io/archive/qt/5.15/5.15.2/single/\n'
        'PyInstaller 6.22.0: GPLv2 with bootloader exception; https://github.com/pyinstaller/pyinstaller/tree/v6.22.0\n'
        'FFmpeg and bundled codec libraries: see ../ffmpeg/ license, README, doc and FFMPEG-SOURCE.txt.\n'
        'The FFmpeg build includes GPL components, including x264.\n', encoding='utf-8')
    # Include this exact application's source and build recipes in both packages.
    source = payload / 'source'
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    for relative in tracked:
        if not relative:
            continue
        original = ROOT / relative
        if original.is_file():
            target = source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)


def assert_payload(payload: Path) -> None:
    required = ['shenlujian.exe', 'ffmpeg/bin/ffmpeg.exe', 'ffmpeg/bin/ffprobe.exe',
                '_internal/PyQt5/Qt5/plugins/platforms/qwindows.dll',
                '_internal/PyQt5/Qt5/bin/Qt5Multimedia.dll']
    for relative in required:
        if not (payload / relative).is_file():
            raise RuntimeError(f'Windows payload is missing {relative}')
    backends = list((payload / '_internal/PyQt5/Qt5/plugins/mediaservice').glob('*.dll'))
    if not any(path.name in {'dsengine.dll', 'wmfengine.dll'} for path in backends):
        raise RuntimeError('Missing Windows Qt multimedia playback backend')
    if not list((payload / '_internal/PyQt5/Qt5/plugins/audio').glob('*.dll')):
        raise RuntimeError('Missing Windows Qt audio backend')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--version', default='1.2.0')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Build on Windows x64 (for example GitHub Actions windows-2022)')
    if not re.fullmatch(r'\d+\.\d+\.\d+', args.version):
        parser.error('--version must be X.Y.Z')
    ffmpeg = prepare_ffmpeg()
    if args.prepare:
        github_path = os.environ.get('GITHUB_PATH')
        if github_path:
            with open(github_path, 'a', encoding='utf-8') as stream:
                stream.write(str(ffmpeg / 'bin') + '\n')
        return
    from PyQt5.QtCore import QLibraryInfo
    plugins = Path(QLibraryInfo.location(QLibraryInfo.PluginsPath))
    command = [sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
               '--onedir', '--windowed', '--name', 'shenlujian',
               '--manifest', str(ROOT / 'scripts' / 'windows.manifest'),
               '--distpath', str(BUILD / 'dist'), '--workpath', str(BUILD / 'pyinstaller'),
               '--specpath', str(BUILD), '--paths', str(ROOT),
               '--add-data', f'{ROOT / "assets"}{os.pathsep}assets',
               '--hidden-import', 'PyQt5.QtMultimedia', '--hidden-import', 'PyQt5.QtMultimediaWidgets',
               '--hidden-import', 'scripts.windows_smoke',
               '--exclude-module', 'dbus', '--exclude-module', 'gi',
               '--exclude-module', 'matplotlib', '--exclude-module', 'numpy', '--exclude-module', 'PIL']
    # Qt hooks usually do this; explicit inclusion and assertions make omissions fail CI.
    for plugin_type in ('mediaservice', 'audio'):
        files = list((plugins / plugin_type).glob('*.dll'))
        if not files:
            raise RuntimeError(f'The Qt wheel has no {plugin_type} plugins')
        for path in files:
            command += ['--add-binary', f'{path}{os.pathsep}PyQt5/Qt5/plugins/{plugin_type}']
    command.append(str(ROOT / 'shenlujian.py'))
    subprocess.run(command, cwd=ROOT, check=True)
    payload = BUILD / 'dist' / 'shenlujian'
    shutil.copytree(ffmpeg, payload / 'ffmpeg', dirs_exist_ok=True)
    bundle_notices(payload)
    assert_payload(payload)
    (payload / 'WINDOWS-START.txt').write_text(
        '神录剪 Windows 10/11 x64\n\n'
        '双击 shenlujian.exe 启动。FFmpeg、ffprobe、Python、Qt 已包含，无需另行安装。\n'
        '便携版请先完整解压 ZIP；不要在压缩包内直接运行，也不要仅复制 EXE。\n'
        '快捷键：F9 开始录屏，F10 停止并保存，F11 全屏。\n'
        '编辑器支持导入视频/音乐、独立音轨预览和混音导出。\n'
        '录屏当前录制画面；系统声音和麦克风录制另行支持。\n'
        '使用音乐预览时，请在 Windows 设置中选择可用扬声器并取消静音。\n'
        '许可、第三方组件与源码见 LICENSE、licenses、ffmpeg 和 source。\n', encoding='utf-8')
    releases = ROOT / 'releases'
    releases.mkdir(exist_ok=True)
    archive = releases / f'shenlujian-{args.version}-windows-x64-portable.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as target:
        for path in sorted(payload.rglob('*')):
            if path.is_file():
                target.write(path, Path('shenlujian-windows-x64') / path.relative_to(payload))
    iscc = shutil.which('ISCC.exe')
    if not iscc:
        candidate = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Inno Setup 6' / 'ISCC.exe'
        if candidate.is_file():
            iscc = str(candidate)
    if not iscc:
        raise RuntimeError('Inno Setup 6 is required; it is preinstalled on windows-2022 runners')
    subprocess.run([iscc, f'/DAppVersion={args.version}', f'/DPayloadDir={payload}',
                    f'/DReleaseDir={releases}', str(ROOT / 'build_windows.iss')], check=True, cwd=ROOT)
    for path in sorted(releases.glob(f'shenlujian-{args.version}-windows-x64-*')):
        print(f'{path.name}  {path.stat().st_size} bytes  SHA256 {digest(path)}')


if __name__ == '__main__':
    main()
