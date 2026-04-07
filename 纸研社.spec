# -*- mode: python ; coding: utf-8 -*-

import os


SPEC_DIR = os.path.abspath(SPECPATH)
ICON_FILE = os.path.join(SPEC_DIR, 'logo.ico')
if not os.path.exists(ICON_FILE):
    raise FileNotFoundError(f'未找到图标文件: {ICON_FILE}')

RESOURCE_ITEMS = [
    ('logo.png', '.'),
    ('loading.gif', '.'),
    ('png', 'png'),
    ('Management', 'Management'),
    ('Introduction', 'Introduction'),
    ('modules', 'modules'),
    ('pages', 'pages'),
]

DATAS = []
for source, target in RESOURCE_ITEMS:
    source_path = os.path.join(SPEC_DIR, source)
    if not os.path.exists(source_path):
        raise FileNotFoundError(f'未找到打包资源: {source_path}')
    DATAS.append((source, target))


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=DATAS,
    hiddenimports=['docx', 'docx.shared', 'docx.enum.text'],
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
    name='纸研社',
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
