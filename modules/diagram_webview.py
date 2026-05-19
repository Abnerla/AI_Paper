# -*- coding: utf-8 -*-
"""
图表 webview 子进程驱动（P3.A）。

设计要点：
- pywebview 必须在主线程运行 webview.start()，会与 tkinter mainloop 冲突
- 解决：把 webview 编辑器跑在独立 Python 子进程，用临时 JSON 文件做 IPC
- 子进程 stdout 输出 `RESULT:<json_path>` 表示用户点了保存
- 子进程退出码 0 = 保存，非 0 = 取消/失败
- 父进程读取临时文件得到新 block，再调 on_save 回写编辑器

只有当 pywebview 已安装、drawio 离线包存在、当前平台支持时才启用 webview 路径；
否则 dialog 仍走 P2 的 Tk 文本编辑器（保底体验）。
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import uuid

from modules.runtime_paths import resolve_resource_path

WEBVIEW_WORKER_FLAG = '--diagram-webview'


def is_pywebview_installed() -> bool:
    try:
        import webview  # noqa: F401
        return True
    except ImportError:
        return False


def is_platform_supported() -> bool:
    if sys.platform == 'win32':
        try:
            ver = sys.getwindowsversion()
            if ver.major < 10:
                return False
        except Exception:
            return False
    return True


def is_drawio_available() -> bool:
    """检查离线 drawio 启动资源是否完整。"""
    try:
        base_parts = ('Management', 'web_assets', 'drawio')
        required = [
            ('index.html',),
            ('js', 'bootstrap.js'),
            ('js', 'main.js'),
            ('js', 'PreConfig.js'),
            ('js', 'PostConfig.js'),
            ('js', 'shapes-14-6-5.min.js'),
            ('js', 'stencils.min.js'),
            ('js', 'extensions.min.js'),
            ('styles', 'grapheditor.css'),
        ]
        for parts in required:
            if not os.path.exists(resolve_resource_path(*base_parts, *parts)):
                return False

        app_bundle = resolve_resource_path(*base_parts, 'js', 'app.min.js')
        fallback_bundle = resolve_resource_path(*base_parts, 'js', 'integrate.min.js')
        return os.path.exists(app_bundle) or os.path.exists(fallback_bundle)
    except Exception:
        return False


def is_mermaid_available() -> bool:
    """检查 mermaid 离线包是否就位（优先 UMD min.js，回退 ESM）。"""
    try:
        umd = resolve_resource_path('Management', 'web_assets', 'mermaid', 'mermaid.min.js')
        if os.path.exists(umd):
            return True
        esm = resolve_resource_path('Management', 'web_assets', 'mermaid', 'mermaid.esm.min.mjs')
        return os.path.exists(esm)
    except Exception:
        return False


def is_webview_supported() -> bool:
    """整体可用性：平台 + 库 + host.html。"""
    if not is_platform_supported():
        return False
    if not is_pywebview_installed():
        return False
    try:
        host_path = resolve_resource_path('Management', 'web_assets', 'host.html')
        return os.path.exists(host_path)
    except Exception:
        return False


def webview_unavailable_reason() -> str:
    if not is_platform_supported():
        return 'webview 仅支持 Windows 10+/macOS/Linux；当前平台不支持。'
    if not is_pywebview_installed():
        return '未安装 pywebview，请执行 pip install pywebview 后重启程序。'
    try:
        host_path = resolve_resource_path('Management', 'web_assets', 'host.html')
        if not os.path.exists(host_path):
            return f'缺少 host.html 资源（{host_path}）。'
    except Exception as exc:
        return f'资源解析失败：{exc}'
    return ''


def open_diagram_in_webview(block: dict, *, timeout: float = 600.0) -> dict | None:
    """以子进程方式打开图表编辑窗，阻塞等待用户保存或关闭。

    返回值：保存返回新 block dict；取消或失败返回 None。
    """
    if not is_webview_supported():
        return None

    workdir = tempfile.mkdtemp(prefix='diagram_wv_')
    in_path = os.path.join(workdir, f'in_{uuid.uuid4().hex}.json')
    out_path = os.path.join(workdir, f'out_{uuid.uuid4().hex}.json')

    payload = {
        'block': block,
        'capabilities': {
            'drawio': is_drawio_available(),
            'mermaid': is_mermaid_available(),
        },
        'out_path': out_path,
    }
    with open(in_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False)

    cmd = _build_worker_command(in_path)
    try:
        completed = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            cwd=_project_cwd(),
        )
    except subprocess.TimeoutExpired:
        return None
    finally:
        # 异步清理输入文件，输出文件读完再清
        threading.Thread(target=_safe_remove, args=(in_path,), daemon=True).start()

    if completed.returncode != 0:
        _safe_remove(out_path)
        try:
            os.rmdir(workdir)
        except OSError:
            pass
        return None

    result = None
    if os.path.exists(out_path):
        try:
            with open(out_path, 'r', encoding='utf-8') as handle:
                result = json.load(handle)
        except (OSError, ValueError):
            result = None
    _safe_remove(out_path)
    try:
        os.rmdir(workdir)
    except OSError:
        pass
    return result if isinstance(result, dict) else None


def export_diagram_in_webview(block: dict, export_format: str, *, timeout: float = 45.0) -> dict | None:
    """使用 draw.io WebView 原生导出 PNG/SVG。

    返回 {'format': ..., 'data': ...}；环境不可用、用户关闭或导出失败时返回 None。
    """
    if not is_webview_supported() or not is_drawio_available():
        return None

    workdir = tempfile.mkdtemp(prefix='diagram_export_wv_')
    in_path = os.path.join(workdir, f'in_{uuid.uuid4().hex}.json')
    out_path = os.path.join(workdir, f'out_{uuid.uuid4().hex}.json')

    payload = {
        'mode': 'export',
        'export_format': str(export_format or '').strip(),
        'block': block,
        'capabilities': {
            'drawio': is_drawio_available(),
            'mermaid': is_mermaid_available(),
        },
        'out_path': out_path,
    }
    with open(in_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False)

    cmd = _build_worker_command(in_path)
    try:
        completed = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            cwd=_project_cwd(),
        )
    except subprocess.TimeoutExpired:
        return None
    finally:
        threading.Thread(target=_safe_remove, args=(in_path,), daemon=True).start()

    result = None
    if completed.returncode == 0 and os.path.exists(out_path):
        try:
            with open(out_path, 'r', encoding='utf-8') as handle:
                result = json.load(handle)
        except (OSError, ValueError):
            result = None
    _safe_remove(out_path)
    try:
        os.rmdir(workdir)
    except OSError:
        pass
    return result if isinstance(result, dict) else None


def _python_executable() -> str:
    return sys.executable


def _build_worker_command(in_path: str) -> list:
    """frozen 时复用 self exe；开发时用 sys.executable + main.py。"""
    if getattr(sys, 'frozen', False):
        return [sys.executable, WEBVIEW_WORKER_FLAG, in_path]
    main_script = os.path.join(_project_cwd(), 'main.py')
    return [sys.executable, main_script, WEBVIEW_WORKER_FLAG, in_path]


def _project_cwd() -> str:
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _safe_remove(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
