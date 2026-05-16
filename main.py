# -*- coding: utf-8 -*-
"""
纸研社 启动程序
"""

import sys
import traceback

from modules.report_importer_worker import maybe_run_from_argv
from pages.diagram_editor_window import maybe_run_from_argv as maybe_run_diagram_webview_from_argv


if __name__ == '__main__':
    try:
        if maybe_run_from_argv():
            raise SystemExit(0)
        if maybe_run_diagram_webview_from_argv():
            raise SystemExit(0)
        from modules.app_shell import main
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                '启动错误',
                '程序启动时发生异常，请查看日志或联系开发者。\n\n'
                f'{traceback.format_exc()[:500]}',
            )
            root.destroy()
        except Exception:
            pass
        sys.exit(1)
