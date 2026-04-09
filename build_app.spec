# -*- mode: python ; coding: utf-8 -*-

import os
import sys

from PyInstaller.utils.hooks import collect_submodules


SPEC_DIR = os.path.abspath(SPECPATH)
sys.path.insert(0, SPEC_DIR)

ICON_FILE = os.path.join(SPEC_DIR, 'logo.ico')
if not os.path.exists(ICON_FILE):
    raise FileNotFoundError(f'Missing icon file: {ICON_FILE}')

RESOURCE_FILES = (
    ('logo.png', '.'),
    ('loading.gif', '.'),
    ('modules/prompt_defaults.json', 'modules'),
)

RESOURCE_DIRS = (
    ('png', 'png'),
    ('Management', 'Management'),
    ('Introduction', 'Introduction'),
)

PAGE_HIDDENIMPORTS = tuple(sorted(collect_submodules('pages')))
HIDDENIMPORTS = list(
    dict.fromkeys(
        [
            'docx',
            'docx.shared',
            'docx.enum.text',
            *PAGE_HIDDENIMPORTS,
        ]
    )
)


def _require_path(relative_path):
    absolute_path = os.path.join(SPEC_DIR, *relative_path.split('/'))
    if not os.path.exists(absolute_path):
        raise FileNotFoundError(f'Missing resource: {absolute_path}')
    return absolute_path


def _build_datas():
    datas = []

    for relative_path, target_dir in RESOURCE_FILES:
        datas.append((_require_path(relative_path), target_dir))

    for relative_dir, target_root in RESOURCE_DIRS:
        source_root = _require_path(relative_dir)
        for current_root, _dirnames, filenames in os.walk(source_root):
            relative_subdir = os.path.relpath(current_root, source_root)
            destination_dir = target_root if relative_subdir == '.' else os.path.join(target_root, relative_subdir)
            for filename in filenames:
                datas.append((os.path.join(current_root, filename), destination_dir))

    return datas


DATAS = _build_datas()


a = Analysis(
    ['main.py'],
    pathex=[SPEC_DIR],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDENIMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AI_paper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON_FILE,
)
