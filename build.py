# -*- coding: utf-8 -*-
"""
纸研社 跨平台构建脚本

用法:
    python build.py                    # 自动检测当前平台并构建
    python build.py --installer        # 同时生成安装程序
"""

import argparse
import os
import shutil
import subprocess
import sys

APP_NAME = '纸研社'
APP_VERSION = 'v1.2.3'
SPEC_FILE = '纸研社.spec'
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, 'dist')
BUILD_DIR = os.path.join(PROJECT_DIR, 'build')


def detect_platform():
    if sys.platform == 'win32':
        return 'windows'
    elif sys.platform == 'darwin':
        return 'macos'
    else:
        return 'linux'


def run_pyinstaller():
    """Run PyInstaller with the cross-platform spec file."""
    cmd = [
        sys.executable, '-m', 'PyInstaller',
        '--clean',
        '--noconfirm',
        '--distpath', DIST_DIR,
        '--workpath', BUILD_DIR,
        SPEC_FILE,
    ]
    print(f'[build] Running: {" ".join(cmd)}')
    subprocess.check_call(cmd, cwd=PROJECT_DIR)
    print(f'[build] PyInstaller finished. Output in {DIST_DIR}')


def create_dmg():
    """Create a .dmg installer for macOS."""
    app_path = os.path.join(DIST_DIR, f'{APP_NAME}.app')
    dmg_path = os.path.join(DIST_DIR, f'{APP_NAME}_{APP_VERSION}.dmg')

    if not os.path.isdir(app_path):
        print(f'[build] Warning: {app_path} not found, skipping DMG creation')
        return

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
    """Create an AppImage for Linux (requires appimagetool on PATH)."""
    exe_path = os.path.join(DIST_DIR, APP_NAME)
    if not os.path.isfile(exe_path):
        print(f'[build] Warning: {exe_path} not found, skipping AppImage creation')
        return

    appimage_tool = shutil.which('appimagetool')
    if not appimage_tool:
        print('[build] Warning: appimagetool not found on PATH, skipping AppImage creation')
        return

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

    output_path = os.path.join(DIST_DIR, f'{APP_NAME}-{APP_VERSION}.AppImage')
    cmd = [appimage_tool, appdir, output_path]
    print(f'[build] Creating AppImage: {output_path}')
    subprocess.check_call(cmd)
    print(f'[build] AppImage created: {output_path}')


def create_inno_setup_installer():
    """Create a Windows installer using Inno Setup (if installed)."""
    iss_path = os.path.join(PROJECT_DIR, 'installers', 'windows_setup.iss')
    if not os.path.isfile(iss_path):
        print('[build] Warning: installers/windows_setup.iss not found, skipping installer')
        return

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
        print('[build] Warning: Inno Setup (ISCC) not found, skipping installer')
        return

    cmd = [iscc, iss_path]
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
    print(f'[build] App: {APP_NAME} {APP_VERSION}')

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
