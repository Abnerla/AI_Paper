# -*- coding: utf-8 -*-
"""
Shared background task runner for Tk pages.
"""

import threading
import uuid


class TaskRunner:
    """Run background work and marshal callbacks back to the UI thread."""

    def __init__(self, scheduler, loading=None, set_status=None, thread_factory=None, log_callback=None):
        self.scheduler = scheduler
        self.loading = loading
        self.set_status = set_status
        self.thread_factory = thread_factory or threading.Thread
        self.log_callback = log_callback or self._resolve_log_callback(set_status)
        self._active_count = 0
        self._tasks = {}

    def run(
        self,
        *,
        work,
        on_success,
        on_error=None,
        on_start=None,
        loading_text='',
        status_text='',
        status_color=None,
    ):
        task_label = self._build_task_label(work, status_text=status_text, loading_text=loading_text)
        if callable(on_start):
            on_start()

        self._active_count += 1
        task_id = uuid.uuid4().hex
        self._tasks[task_id] = {'cancelled': False, 'label': task_label}

        try:
            if self.loading and loading_text:
                self.loading.show(loading_text)
                self.scheduler.update_idletasks()

            if self.set_status and status_text:
                self.set_status(status_text, status_color)
        except Exception:
            self._active_count = max(0, self._active_count - 1)
            raise

        self._log(f'[task_start] {task_label}')

        def worker():
            try:
                result = work()
            except Exception as exc:
                # 即使出错也稍微延迟隐藏，避免闪烁
                self.scheduler.after(100, lambda err=exc, tid=task_id: self._finish_error(err, on_error, task_label, tid))
                return

            # 成功时也稍微延迟隐藏，让用户看清“处理完成”等状态
            self.scheduler.after(100, lambda value=result, tid=task_id: self._finish_success(value, on_success, task_label, tid))

        thread = self.thread_factory(target=worker, daemon=True)
        self._tasks[task_id]['thread'] = thread
        thread.start()
        return task_id

    def cancel(self, task_id=None):
        """标记任务已取消。正在执行的网络请求无法强杀，但完成回调会被忽略。"""
        if task_id:
            task = self._tasks.get(task_id)
            if task:
                task['cancelled'] = True
                if not task.get('released'):
                    task['released'] = True
                    self._active_count = max(0, self._active_count - 1)
                    if self.loading and self._active_count <= 0:
                        self.loading.hide()
                self._log(f'[task_cancel_requested] {task.get("label", task_id)}', level='WARN')
                return True
            return False
        cancelled = False
        for task in self._tasks.values():
            task['cancelled'] = True
            if not task.get('released'):
                task['released'] = True
                self._active_count = max(0, self._active_count - 1)
            cancelled = True
        if cancelled:
            if self.loading and self._active_count <= 0:
                self.loading.hide()
            self._log('[task_cancel_requested] all', level='WARN')
        return cancelled

    def is_cancelled(self, task_id):
        return bool((self._tasks.get(task_id) or {}).get('cancelled'))

    def _finish_success(self, result, callback, task_label, task_id=None):
        task = self._tasks.pop(task_id, {}) if task_id else {}
        if not task.get('released'):
            self._active_count = max(0, self._active_count - 1)
            if self.loading and self._active_count <= 0:
                self.loading.hide()
        if task.get('cancelled'):
            self._log(f'[task_cancelled] {task_label}', level='WARN')
            return
        self._log(f'[task_success] {task_label}')
        if callable(callback):
            callback(result)

    def _finish_error(self, exc, callback, task_label, task_id=None):
        task = self._tasks.pop(task_id, {}) if task_id else {}
        if not task.get('released'):
            self._active_count = max(0, self._active_count - 1)
            if self.loading and self._active_count <= 0:
                self.loading.hide()
        if task.get('cancelled'):
            self._log(f'[task_cancelled] {task_label} | {exc}', level='WARN')
            return
        self._log(f'[task_error] {task_label} | {exc}', level='ERROR')
        if callable(callback):
            callback(exc)

    @staticmethod
    def _resolve_log_callback(set_status):
        owner = getattr(set_status, '__self__', None)
        callback = getattr(owner, '_write_app_log', None)
        return callback if callable(callback) else None

    @staticmethod
    def _build_task_label(work, *, status_text='', loading_text=''):
        for candidate in (status_text, loading_text):
            text = str(candidate or '').strip()
            if text:
                return text
        work_name = getattr(work, '__name__', '') or work.__class__.__name__
        return work_name or 'unnamed_task'

    def _log(self, message, level='INFO'):
        if callable(self.log_callback):
            self.log_callback(message, level=level)
