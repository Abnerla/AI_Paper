# -*- coding: utf-8 -*-
"""
报告解析子进程入口。
"""

from __future__ import annotations

import json
import sys
import traceback

from modules.report_importer import ReportImportEngine


def _write_stdout_json(payload: dict):
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
    sys.stdout.buffer.flush()


def _write_stderr_line(message: str):
    sys.stderr.buffer.write((str(message or '') + '\n').encode('utf-8', errors='replace'))
    sys.stderr.buffer.flush()


def _stderr_logger(message, level='INFO'):
    _write_stderr_line(f'[{str(level or "INFO").upper()}] {message}')


def run_worker(payload: dict) -> dict:
    engine = ReportImportEngine(log_callback=_stderr_logger)
    session = engine.parse(
        str(payload.get('path', '') or ''),
        str(payload.get('page_kind', '') or ''),
        str(payload.get('original_text', '') or ''),
    )
    return {
        'ok': True,
        'session': session.to_dict(),
    }


def main(argv=None):
    del argv
    try:
        raw_payload = sys.stdin.read()
        payload = json.loads(raw_payload or '{}')
        if not isinstance(payload, dict):
            raise RuntimeError('子进程收到的解析参数无效')
        response = run_worker(payload)
        _write_stdout_json(response)
        return 0
    except Exception as exc:
        traceback_text = traceback.format_exc().strip()
        if traceback_text:
            _write_stderr_line(traceback_text)
        _write_stdout_json({'ok': False, 'error': str(exc)})
        return 1


def maybe_run_from_argv(argv=None) -> bool:
    args = list(sys.argv if argv is None else argv)
    if len(args) < 2 or args[1] != ReportImportEngine.WORKER_FLAG:
        return False
    raise SystemExit(main(args[2:]))


if __name__ == '__main__':
    raise SystemExit(main())
