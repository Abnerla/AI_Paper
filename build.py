# -*- coding: utf-8 -*-
"""
纸研社 跨平台构建脚本

用法:
    python build.py                    # 自动检测当前平台并构建
    python build.py --installer        # 同时生成安装程序
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

# 确保 CI 环境下中文输出不报错
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

APP_NAME = '纸研社'
SPEC_FILE = '纸研社.spec'
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, 'dist')
BUILD_DIR = os.path.join(PROJECT_DIR, 'build')
VERSION_PATTERN = re.compile(r'^v?(?P<version>\d+\.\d+\.\d+)$')


def read_command_output(command):
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_DIR,
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
        )
    except Exception:
        return ''
    return completed.stdout.strip()


def normalize_version(value):
    if not value:
        return None

    candidate = value.strip()
    if candidate.startswith('refs/tags/'):
        candidate = candidate[len('refs/tags/'):]

    match = VERSION_PATTERN.fullmatch(candidate)
    if not match:
        return None

    version = match.group('version')
    return version, f'v{version}'


def resolve_version():
    candidates = [
        os.environ.get('BUILD_VERSION'),
        os.environ.get('GITHUB_REF_NAME'),
    ]

    point_tags = read_command_output(['git', 'tag', '--points-at', 'HEAD'])
    if point_tags:
        candidates.extend(line.strip() for line in point_tags.splitlines() if line.strip())

    latest_tag = read_command_output(['git', 'describe', '--tags', '--abbrev=0'])
    if latest_tag:
        candidates.append(latest_tag)

    for candidate in candidates:
        normalized = normalize_version(candidate)
        if normalized:
            return normalized

    return '0.0.0', 'v0.0.0'


APP_VERSION, APP_VERSION_TAG = resolve_version()


def detect_platform():
    if sys.platform == 'win32':
        return 'windows'
    elif sys.platform == 'darwin':
        return 'macos'
    else:
        return 'linux'


def run_pyinstaller():
    """使用跨平台 spec 调用 PyInstaller。"""
    env = os.environ.copy()
    env['APP_VERSION'] = APP_VERSION
    env['APP_VERSION_TAG'] = APP_VERSION_TAG
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--clean',
        '--noconfirm',
        '--distpath', DIST_DIR,
        '--workpath', BUILD_DIR,
        SPEC_FILE,
    ]
    print(f'[build] Running: {" ".join(cmd)}')
    subprocess.check_call(cmd, cwd=PROJECT_DIR, env=env)
    print(f'[build] PyInstaller finished. Output in {DIST_DIR}')


def create_dmg():
    """生成 macOS 的 .dmg 安装程序。"""
    app_path = os.path.join(DIST_DIR, f'{APP_NAME}.app')
    dmg_path = os.path.join(DIST_DIR, f'{APP_NAME}_{APP_VERSION_TAG}.dmg')

    if not os.path.isdir(app_path):
        raise FileNotFoundError(f'[build] Missing app bundle: {app_path}')

    if os.path.exists(dmg_path):
        os.remove(dmg_path)

    cmd = [
        'hdiutil', 'create',
        '-volname', APP_NAME,
        '-srcfolder', app_path,
        '-ov',
        '-format', 'UDZO',
        dmg_path,
    ]
    print(f'[build] Creating DMG: {dmg_path}')
    subprocess.check_call(cmd)
    print(f'[build] DMG created: {dmg_path}')


def create_appimage():
    """生成 Linux 的 AppImage 安装程序。"""
    exe_path = os.path.join(DIST_DIR, APP_NAME)
    if not os.path.isfile(exe_path):
        raise FileNotFoundError(f'[build] Missing Linux executable: {exe_path}')

    appimage_tool = shutil.which('appimagetool')
    if not appimage_tool:
        raise FileNotFoundError('[build] Missing dependency: appimagetool')

    appdir = os.path.join(BUILD_DIR, f'{APP_NAME}.AppDir')
    if os.path.isdir(appdir):
        shutil.rmtree(appdir)
    os.makedirs(os.path.join(appdir, 'usr', 'bin'), exist_ok=True)

    shutil.copy2(exe_path, os.path.join(appdir, 'usr', 'bin', APP_NAME))

    icon_src = os.path.join(PROJECT_DIR, 'logo.png')
    if os.path.exists(icon_src):
        shutil.copy2(icon_src, os.path.join(appdir, f'{APP_NAME}.png'))

    desktop_content = f"""[Desktop Entry]
Name={APP_NAME}
Exec={APP_NAME}
Icon={APP_NAME}
Type=Application
Categories=Office;Education;
"""
    with open(os.path.join(appdir, f'{APP_NAME}.desktop'), 'w', encoding='utf-8') as f:
        f.write(desktop_content)

    apprun_content = """#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/""" + APP_NAME + """ "$@"
"""
    apprun_path = os.path.join(appdir, 'AppRun')
    with open(apprun_path, 'w', encoding='utf-8') as f:
        f.write(apprun_content)
    os.chmod(apprun_path, 0o755)

    output_path = os.path.join(DIST_DIR, f'{APP_NAME}-{APP_VERSION_TAG}.AppImage')
    cmd = [appimage_tool, appdir, output_path]
    print(f'[build] Creating AppImage: {output_path}')
    subprocess.check_call(cmd)
    print(f'[build] AppImage created: {output_path}')


def create_inno_setup_installer():
    """使用 Inno Setup 生成 Windows 安装程序。"""
    iss_path = os.path.join(PROJECT_DIR, 'installers', 'windows_setup.iss')
    if not os.path.isfile(iss_path):
        raise FileNotFoundError('[build] Missing installer script: installers/windows_setup.iss')

    iscc = None
    for candidate in [
        shutil.which('ISCC'),
        r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        r'C:\Program Files\Inno Setup 6\ISCC.exe',
    ]:
        if candidate and os.path.isfile(candidate):
            iscc = candidate
            break

    if not iscc:
        raise FileNotFoundError('[build] Missing dependency: Inno Setup (ISCC)')

    cmd = [iscc, f'/DMyAppVersion={APP_VERSION}', iss_path]
    print(f'[build] Creating Windows installer with Inno Setup')
    subprocess.check_call(cmd)
    print('[build] Windows installer created')


def main():
    parser = argparse.ArgumentParser(description=f'{APP_NAME} cross-platform build script')
    parser.add_argument('--installer', action='store_true', help='Also create platform installer')
    parser.add_argument('--clean', action='store_true', help='Clean build/dist directories first')
    args = parser.parse_args()

    platform = detect_platform()
    print(f'[build] Platform: {platform}')
    print(f'[build] App: {APP_NAME} {APP_VERSION_TAG}')

    if args.clean:
        for d in [DIST_DIR, BUILD_DIR]:
            if os.path.isdir(d):
                print(f'[build] Cleaning {d}')
                shutil.rmtree(d)

    run_pyinstaller()

    if args.installer:
        if platform == 'windows':
            create_inno_setup_installer()
        elif platform == 'macos':
            create_dmg()
        elif platform == 'linux':
            create_appimage()

    print(f'[build] Done! Output in {DIST_DIR}')


if __name__ == '__main__':
    main()
