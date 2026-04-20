# -*- coding: utf-8 -*-
""" 为什么我配置模型以后，使用AI功能会直接失败,甚至不显示等待画面
Thin desktop entrypoint for 纸研社.
"""

from modules.report_importer_worker import maybe_run_from_argv


if __name__ == '__main__':
    if maybe_run_from_argv():
        raise SystemExit(0)
    from modules.app_shell import main
    main()
