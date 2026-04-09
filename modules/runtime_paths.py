from __future__ import annotations

import os
import sys
from dataclasses import dataclass


APP_DATA_DIR_NAME = '\u7eb8\u7814\u793e'
LOGS_DIR_NAME = 'logs'
TEMP_DIR_NAME = 'temp'


def _normalize_path(path):
    return os.path.abspath(os.path.expanduser(str(path or '.')))


def _project_root():
    return _normalize_path(os.path.join(os.path.dirname(__file__), os.pardir))


def _resolve_resource_root():
    if getattr(sys, 'frozen', False):
        return _normalize_path(getattr(sys, '_MEIPASS', '') or os.path.dirname(sys.executable))
    return _project_root()


def _resolve_app_root():
    if getattr(sys, 'frozen', False):
        return _normalize_path(os.path.dirname(sys.executable))
    return _project_root()


def _resolve_data_root():
    if not getattr(sys, 'frozen', False):
        return _project_root()

    if sys.platform == 'win32':
        local_appdata = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA')
        if local_appdata:
            return _normalize_path(os.path.join(local_appdata, APP_DATA_DIR_NAME))
    elif sys.platform == 'darwin':
        support_dir = os.path.expanduser('~/Library/Application Support')
        if os.path.isdir(support_dir):
            return _normalize_path(os.path.join(support_dir, APP_DATA_DIR_NAME))
    else:
        xdg_data = os.environ.get('XDG_DATA_HOME') or os.path.expanduser('~/.local/share')
        return _normalize_path(os.path.join(xdg_data, APP_DATA_DIR_NAME))

    return _normalize_path(os.path.join(_resolve_app_root(), 'user_data'))


def _join_path(base_path, *parts):
    tokens = [base_path]
    for part in parts:
        text = str(part or '').strip()
        if not text:
            continue
        tokens.append(text)
    return _normalize_path(os.path.join(*tokens))


@dataclass(frozen=True)
class RuntimePaths:
    resource_root: str
    app_root: str
    data_root: str
    logs_dir: str
    temp_dir: str

    def resolve_resource(self, *parts):
        return _join_path(self.resource_root, *parts)

    def resolve_data(self, *parts):
        return _join_path(self.data_root, *parts)


def build_runtime_paths():
    resource_root = _resolve_resource_root()
    app_root = _resolve_app_root()
    data_root = _resolve_data_root()
    return RuntimePaths(
        resource_root=resource_root,
        app_root=app_root,
        data_root=data_root,
        logs_dir=_join_path(data_root, LOGS_DIR_NAME),
        temp_dir=_join_path(data_root, TEMP_DIR_NAME),
    )


_RUNTIME_PATHS = None


def get_runtime_paths():
    global _RUNTIME_PATHS
    if _RUNTIME_PATHS is None:
        _RUNTIME_PATHS = build_runtime_paths()
    return _RUNTIME_PATHS


def resolve_resource_path(*parts):
    return get_runtime_paths().resolve_resource(*parts)


def resolve_data_path(*parts):
    return get_runtime_paths().resolve_data(*parts)
