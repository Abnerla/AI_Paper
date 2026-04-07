# -*- coding: utf-8 -*-
"""
API客户端模块 - 支持多个AI服务商
"""

import json
import re
import time
import urllib.request
import urllib.error
import urllib.parse
import threading
import uuid
from datetime import datetime
from typing import Callable, Optional

from modules.usage_stats import (
    UsageEvent,
    UsageStatsStore,
    calculate_total_cost,
    extract_claude_usage,
    extract_openai_usage,
    extract_tongyi_usage,
    find_pricing_rule,
    resolve_event_billing,
)


class APIClient:
    """统一的AI API客户端"""

    def __init__(self, config_mgr, log_callback=None):
        self.config = config_mgr
        self.log_callback = log_callback
        app_dir = getattr(config_mgr, 'app_dir', '') or '.'
        self.usage_store = UsageStatsStore(app_dir, config_mgr=config_mgr)

    def set_log_callback(self, log_callback):
        self.log_callback = log_callback

    def _get_active(self):
        return self.config.active_api

    def _get_config(self, api_name, cfg=None):
        if cfg is not None:
            return dict(cfg)
        return dict(self.config.get_api_config(api_name) or {})

    def _resolve_handler_name(self, api_name, cfg):
        api_format = (cfg.get('api_format', '') or '').strip().lower()
        provider_type = (cfg.get('provider_type', '') or '').strip().lower()
        api_name_hint = (api_name or '').strip().lower()
        provider_hint = provider_type or api_name_hint

        if api_format == 'claude':
            return 'claude'
        if api_format == 'baidu':
            return 'baidu'
        if api_format in ('openai', 'custom'):
            if provider_hint == 'claude':
                return 'claude'
            if provider_hint == 'baidu' and cfg.get('api_key') and cfg.get('secret_key'):
                return 'baidu'
            if provider_hint == 'spark' and cfg.get('app_id') and cfg.get('api_key') and cfg.get('api_secret'):
                return 'spark'
            if provider_hint == 'tongyi' and not cfg.get('base_url'):
                return 'tongyi'
            return 'openai'

        if provider_hint == 'claude':
            return 'claude'
        if provider_hint == 'baidu' and cfg.get('api_key') and cfg.get('secret_key'):
            return 'baidu'
        if provider_hint == 'spark' and cfg.get('app_id') and cfg.get('api_key') and cfg.get('api_secret'):
            return 'spark'
        if provider_hint == 'tongyi' and not cfg.get('base_url'):
            return 'tongyi'
        return 'openai'

    @staticmethod
    def _coerce_positive_float(value, default=None):
        try:
            number = float(value)
        except Exception:
            return default
        if number <= 0:
            return default
        return number

    def _resolve_request_timeout(self, cfg, request_timeout, *, default=60.0):
        explicit_timeout = self._coerce_positive_float(request_timeout)
        if explicit_timeout is not None:
            return explicit_timeout

        configured_timeout = None
        if isinstance(cfg, dict):
            configured_timeout = self._coerce_positive_float(cfg.get('timeout', ''))
        if configured_timeout is not None:
            return configured_timeout
        return max(float(default or 60.0), 1.0)

    @staticmethod
    def _normalize_auth_field(field_name):
        value = str(field_name or '').strip()
        return value or 'Authorization'

    @staticmethod
    def _build_bearer_headers(key, *, auth_field='Authorization', include_content_type=True):
        headers = {}
        if include_content_type:
            headers['Content-Type'] = 'application/json'
        headers[str(auth_field or 'Authorization')] = f'Bearer {key}'
        return headers

    @staticmethod
    def _resolve_openai_compat_urls(base_url):
        normalized_base_url = str(base_url or 'https://api.openai.com/v1').strip() or 'https://api.openai.com/v1'
        parts = urllib.parse.urlsplit(normalized_base_url)
        path = parts.path.rstrip('/')
        chat_suffix = '/chat/completions'

        if path.endswith(chat_suffix):
            root_path = path[:-len(chat_suffix)] or ''
            chat_path = path
        else:
            root_path = path
            chat_path = f'{root_path}{chat_suffix}' if root_path else chat_suffix

        models_path = f'{root_path}/models' if root_path else '/models'
        root_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, root_path, '', ''))
        chat_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, chat_path, '', ''))
        models_url = urllib.parse.urlunsplit((parts.scheme, parts.netloc, models_path, '', ''))
        return {
            'root_url': root_url or normalized_base_url.rstrip('/'),
            'chat_completions_url': chat_url,
            'models_url': models_url,
        }

    @staticmethod
    def _parse_model_mapping(raw_mapping):
        mapping = {}
        text = str(raw_mapping or '').strip()
        if not text:
            return mapping

        for item in re.split(r'[\r\n,;；，]+', text):
            entry = str(item or '').strip()
            if not entry:
                continue
            delimiter = ':' if ':' in entry else '=' if '=' in entry else ''
            if not delimiter:
                continue
            source, target = entry.split(delimiter, 1)
            source = source.strip()
            target = target.strip()
            if source and target:
                mapping[source] = target
        return mapping

    def _apply_model_mapping(self, model_name, cfg):
        current_model = str(model_name or '').strip()
        if not current_model:
            return current_model, False

        mappings = self._parse_model_mapping((cfg or {}).get('model_mapping', ''))
        if not mappings:
            return current_model, False

        if current_model in mappings:
            return mappings[current_model], True

        lowered = current_model.lower()
        for source, target in mappings.items():
            if source.lower() == lowered:
                return target, True
        return current_model, False

    def _resolve_request_model_name(self, provider_name, cfg):
        model_name = str((cfg or {}).get('model', '') or '').strip() or 'unknown'
        if provider_name != 'openai':
            return model_name
        mapped_model, _mapping_hit = self._apply_model_mapping(model_name, cfg)
        return mapped_model or model_name

    @staticmethod
    def _load_extra_json_payload(cfg):
        raw = str((cfg or {}).get('extra_json', '') or '').strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f'高级请求体 JSON 格式错误: {exc}') from exc
        if not isinstance(payload, dict):
            raise ValueError('高级请求体 JSON 必须是 JSON 对象')
        return payload

    @staticmethod
    def _merge_openai_extra_json(base_payload, extra_payload):
        merged = dict(base_payload or {})
        ignored_keys = []
        protected_keys = {
            'model',
            'messages',
            'system',
            'temperature',
            'max_tokens',
            'prompt',
            'input',
        }
        for key, value in dict(extra_payload or {}).items():
            if key in protected_keys or key in merged:
                ignored_keys.append(str(key))
                continue
            merged[key] = value
        return merged, sorted(set(ignored_keys))

    def _prepare_openai_compat_request(self, prompt, system, cfg, temperature, max_tokens):
        key = str((cfg or {}).get('key', '') or '').strip()
        if not key:
            raise ValueError('OpenAI API Key未配置')

        urls = self._resolve_openai_compat_urls((cfg or {}).get('base_url', 'https://api.openai.com/v1'))
        configured_model = str((cfg or {}).get('model', '') or '').strip() or 'gpt-4o'
        request_model, mapping_hit = self._apply_model_mapping(configured_model, cfg)
        auth_field = self._normalize_auth_field((cfg or {}).get('auth_field', 'Authorization'))

        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})

        payload = {
            'model': request_model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
        }
        extra_json_payload = self._load_extra_json_payload(cfg)
        payload, ignored_keys = self._merge_openai_extra_json(payload, extra_json_payload)
        headers = self._build_bearer_headers(key, auth_field=auth_field, include_content_type=True)

        return {
            'url': urls['chat_completions_url'],
            'models_url': urls['models_url'],
            'root_url': urls['root_url'],
            'payload': payload,
            'headers': headers,
            'request_model': request_model,
            'auth_field': auth_field,
            'model_mapping_hit': mapping_hit,
            'extra_json_keys': sorted(extra_json_payload.keys()),
            'ignored_extra_json_keys': ignored_keys,
        }

    def call(
        self,
        prompt: str,
        system: str = '',
        api_name: str = None,
        on_complete: Callable[[str], None] = None,
        on_error: Callable[[str], None] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        cfg: dict = None,
        usage_context: dict = None,
    ):
        """调用AI API（异步，通过回调返回结果）"""
        if api_name is None:
            api_name = self._get_active()

        def _run():
            try:
                result = self._call_sync(
                    prompt,
                    system,
                    api_name,
                    temperature,
                    max_tokens,
                    cfg=cfg,
                    usage_context=usage_context,
                )
                if on_complete:
                    on_complete(result)
            except Exception as e:
                if on_error:
                    on_error(str(e))

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t

    def call_sync(
        self,
        prompt: str,
        system: str = '',
        api_name: str = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        request_timeout: float = None,
        model_override: str = None,
        cfg: dict = None,
        usage_context: dict = None,
    ) -> str:
        """同步调用AI API"""
        if api_name is None:
            api_name = self._get_active()
        return self._call_sync(
            prompt,
            system,
            api_name,
            temperature,
            max_tokens,
            request_timeout=request_timeout,
            model_override=model_override,
            cfg=cfg,
            usage_context=usage_context,
        )

    def call_json_sync(
        self,
        prompt: str,
        system: str = '',
        api_name: str = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        request_timeout: float = None,
        model_override: str = None,
        cfg: dict = None,
        schema_name: str = '',
        usage_context: dict = None,
    ):
        """同步调用 AI 并解析 JSON。"""
        schema_hint = f'，schema={schema_name}' if schema_name else ''
        enforced_prompt = (
            f'{prompt}\n\n'
            f'输出要求：请严格只返回可解析的 JSON，不要输出 Markdown 代码块、额外解释或前后缀文本{schema_hint}。'
        )
        raw = self.call_sync(
            enforced_prompt,
            system=system,
            api_name=api_name,
            temperature=temperature,
            max_tokens=max_tokens,
            request_timeout=request_timeout,
            model_override=model_override,
            cfg=cfg,
            usage_context=usage_context,
        )
        payload = self._extract_json_payload(raw)
        try:
            return json.loads(payload)
        except Exception as exc:
            raise ValueError(f'AI 未返回有效 JSON: {exc}') from exc

    def _call_sync(
        self,
        prompt,
        system,
        api_name,
        temperature,
        max_tokens,
        request_timeout=None,
        model_override=None,
        cfg=None,
        usage_context=None,
    ):
        handlers = {
            'openai': self._call_openai_compat,
            'claude': self._call_claude,
            'baidu': self._call_baidu,
            'tongyi': self._call_tongyi,
            'spark': self._call_spark,
        }
        cfg = self._get_config(api_name, cfg=cfg)
        handler = handlers.get(self._resolve_handler_name(api_name, cfg))
        if not handler:
            raise ValueError(f'不支持的API: {api_name}')
        if model_override:
            cfg['model'] = model_override
        provider_name = self._resolve_handler_name(api_name, cfg)
        model_name = self._resolve_request_model_name(provider_name, cfg)
        timeout_value = self._resolve_request_timeout(cfg, request_timeout)
        started_at = time.perf_counter()
        request_id = uuid.uuid4().hex
        self._log(
            '[api_request] '
            f'api={api_name or "active"} '
            f'provider={provider_name} '
            f'model={model_name} '
            f'prompt_len={len(prompt or "")} '
            f'system_len={len(system or "")} '
            f'max_tokens={max_tokens} '
            f'temperature={temperature} '
            f'timeout={timeout_value}'
        )
        try:
            response_payload = handler(prompt, system, cfg, temperature, max_tokens, request_timeout=timeout_value)
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            self._log(
                '[api_error] '
                f'api={api_name or "active"} '
                f'provider={provider_name} '
                f'model={model_name} '
                f'elapsed_ms={elapsed_ms} '
                f'error={exc}',
                level='ERROR',
            )
            self._record_usage_event(
                request_id=request_id,
                usage_context=usage_context,
                api_name=api_name,
                provider_name=provider_name,
                request_model=model_name,
                response_model='',
                cfg=cfg,
                duration_ms=elapsed_ms,
                usage={},
                status='error',
                error_message=str(exc),
            )
            raise
        result_text = str(response_payload.get('text', '') or '')
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        self._log(
            '[api_response] '
            f'api={api_name or "active"} '
            f'provider={provider_name} '
            f'model={model_name} '
            f'elapsed_ms={elapsed_ms} '
            f'result_len={len(result_text)}'
        )
        self._record_usage_event(
            request_id=request_id,
            usage_context=usage_context,
            api_name=api_name,
            provider_name=provider_name,
            request_model=model_name,
            response_model=response_payload.get('response_model', ''),
            cfg=cfg,
            duration_ms=elapsed_ms,
            usage=response_payload.get('usage', {}) or {},
            status='success',
            error_message='',
        )
        return result_text

    def _http_post(self, url, data: dict, headers: dict, timeout=60) -> dict:
        """发送HTTP POST请求"""
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(url, data=body, headers=headers, method='POST')
        safe_url = self._sanitize_url_for_log(url)
        started_at = time.perf_counter()
        self._log(f'[http_post] url={safe_url} timeout={timeout} body_bytes={len(body)}')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode('utf-8')
                self._log(
                    '[http_response] '
                    f'url={safe_url} status={getattr(resp, "status", "unknown")} '
                    f'elapsed_ms={int((time.perf_counter() - started_at) * 1000)} '
                    f'body_chars={len(raw)}'
                )
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='replace')
            self._log(
                '[http_error] '
                f'url={safe_url} status={e.code} '
                f'elapsed_ms={int((time.perf_counter() - started_at) * 1000)} '
                f'error={err_body[:240]}',
                level='ERROR',
            )
            raise RuntimeError(f'HTTP {e.code}: {err_body}')
        except urllib.error.URLError as e:
            self._log(
                '[http_error] '
                f'url={safe_url} '
                f'elapsed_ms={int((time.perf_counter() - started_at) * 1000)} '
                f'error={e.reason}',
                level='ERROR',
            )
            raise RuntimeError(f'网络错误: {e.reason}')

    def _call_openai_compat(self, prompt, system, cfg, temperature, max_tokens, request_timeout=None):
        """调用OpenAI兼容接口（包括自定义base_url）"""
        prepared = self._prepare_openai_compat_request(prompt, system, cfg, temperature, max_tokens)
        self._log(
            '[openai_compat] '
            f'endpoint={self._sanitize_url_for_log(prepared["url"])} '
            f'auth_field={prepared["auth_field"]} '
            f'model={prepared["request_model"]} '
            f'model_mapping_hit={prepared["model_mapping_hit"]} '
            f'extra_json_keys={",".join(prepared["extra_json_keys"]) or "-"} '
            f'ignored_extra_json_keys={",".join(prepared["ignored_extra_json_keys"]) or "-"} '
            f'timeout={request_timeout}'
        )
        resp = self._http_post(
            prepared['url'],
            prepared['payload'],
            prepared['headers'],
            timeout=request_timeout,
        )
        return {
            'text': resp['choices'][0]['message']['content'],
            'response_model': str(resp.get('model', '') or prepared['request_model']),
            'request_model': prepared['request_model'],
            'usage': extract_openai_usage(resp),
        }

    def _call_claude(self, prompt, system, cfg, temperature, max_tokens, request_timeout=None):
        """调用Anthropic Claude API"""
        key = cfg.get('key', '')
        if not key:
            raise ValueError('Claude API Key未配置')
        base_url = cfg.get('base_url', 'https://api.anthropic.com').rstrip('/')
        model = cfg.get('model', 'claude-opus-4-6')
        url = f'{base_url}/v1/messages'
        data = {
            'model': model,
            'max_tokens': max_tokens,
            'messages': [{'role': 'user', 'content': prompt}],
        }
        if system:
            data['system'] = system
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': key,
            'anthropic-version': '2023-06-01',
        }
        resp = self._http_post(url, data, headers, timeout=request_timeout or 60)
        return {
            'text': resp['content'][0]['text'],
            'response_model': str(resp.get('model', '') or model),
            'usage': extract_claude_usage(resp),
        }

    def _call_baidu(self, prompt, system, cfg, temperature, max_tokens, request_timeout=None):
        """调用百度文心API"""
        api_key = cfg.get('api_key', '')
        secret_key = cfg.get('secret_key', '')
        if not api_key or not secret_key:
            raise ValueError('百度文心 API Key或Secret Key未配置')
        # 获取access_token
        token_url = f'https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={api_key}&client_secret={secret_key}'
        req = urllib.request.Request(token_url)
        with urllib.request.urlopen(req, timeout=request_timeout or 30) as resp:
            token_data = json.loads(resp.read().decode('utf-8'))
        access_token = token_data.get('access_token', '')
        if not access_token:
            raise RuntimeError('获取百度access_token失败')

        model = cfg.get('model', 'ERNIE-4.0-8K')
        model_map = {
            'ERNIE-4.0-8K': 'ernie-4.0-8k',
            'ERNIE-3.5-8K': 'ernie-3.5-8k',
            'ERNIE-Speed': 'ernie-speed-128k',
        }
        endpoint = model_map.get(model, 'ernie-4.0-8k')
        url = f'https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/{endpoint}?access_token={access_token}'
        messages = []
        if system:
            messages.append({'role': 'user', 'content': system})
            messages.append({'role': 'assistant', 'content': '好的，我明白了。'})
        messages.append({'role': 'user', 'content': prompt})
        data = {'messages': messages, 'temperature': max(0.01, min(temperature, 1.0))}
        headers = {'Content-Type': 'application/json'}
        resp = self._http_post(url, data, headers, timeout=request_timeout or 60)
        return {
            'text': resp.get('result', ''),
            'response_model': str(resp.get('model', '') or model),
            'usage': {},
        }

    def _call_tongyi(self, prompt, system, cfg, temperature, max_tokens, request_timeout=None):
        """调用阿里通义千问API"""
        key = cfg.get('key', '')
        if not key:
            raise ValueError('千问 API Key未配置')
        model = cfg.get('model', 'qwen-max')
        url = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation'
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})
        data = {
            'model': model,
            'input': {'messages': messages},
            'parameters': {
                'temperature': temperature,
                'max_tokens': max_tokens,
                'result_format': 'message',
            }
        }
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {key}',
        }
        resp = self._http_post(url, data, headers, timeout=request_timeout or 60)
        return {
            'text': resp['output']['choices'][0]['message']['content'],
            'response_model': str(resp.get('model', '') or resp.get('output', {}).get('model', '') or model),
            'usage': extract_tongyi_usage(resp),
        }

    def _call_spark(self, prompt, system, cfg, temperature, max_tokens, request_timeout=None):
        """调用讯飞星火API（HTTP版）"""
        app_id = cfg.get('app_id', '')
        api_key = cfg.get('api_key', '')
        api_secret = cfg.get('api_secret', '')
        if not all([app_id, api_key, api_secret]):
            raise ValueError('讯飞星火配置不完整（需要app_id、api_key、api_secret）')
        model = cfg.get('model', 'generalv3.5')
        # 使用HTTP API
        import hmac, hashlib, time, base64
        host = 'spark-api.xf-yun.com'
        path = f'/v3.5/chat'
        if model == 'generalv2':
            path = '/v2.1/chat'
        elif model == 'general':
            path = '/v1.1/chat'
        url = f'https://{host}{path}'
        # 构造鉴权
        date = time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime())
        sign_str = f'host: {host}\ndate: {date}\nPOST {path} HTTP/1.1'
        sign = base64.b64encode(
            hmac.new(api_secret.encode(), sign_str.encode(), digestmod=hashlib.sha256).digest()
        ).decode()
        auth = base64.b64encode(
            f'api_key="{api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{sign}"'.encode()
        ).decode()
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        messages.append({'role': 'user', 'content': prompt})
        data = {
            'header': {'app_id': app_id},
            'parameter': {'chat': {'domain': model, 'temperature': temperature, 'max_tokens': max_tokens}},
            'payload': {'message': {'text': messages}}
        }
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'auth="{auth}"',
            'Date': date,
            'Host': host,
        }
        resp = self._http_post(url, data, headers, timeout=request_timeout or 60)
        text = resp.get('payload', {}).get('choices', {}).get('text', [{}])
        return {
            'text': ''.join(t.get('content', '') for t in text),
            'response_model': str(resp.get('model', '') or model),
            'usage': {},
        }

    @staticmethod
    def _sanitize_url_for_log(url):
        parts = urllib.parse.urlsplit(str(url or ''))
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, '', ''))

    def _record_usage_event(
        self,
        *,
        request_id,
        usage_context,
        api_name,
        provider_name,
        request_model,
        response_model,
        cfg,
        duration_ms,
        usage,
        status,
        error_message,
    ):
        if not getattr(self, 'usage_store', None):
            return
        try:
            billing = resolve_event_billing(self.config, api_name, cfg, response_model=str(response_model or ''))
            pricing_rule = find_pricing_rule(self.config, provider_name, billing['billed_model'])
            total_cost = calculate_total_cost(usage, pricing_rule, billing['billing_multiplier'])
            context = dict(usage_context or {})
            event = UsageEvent(
                request_id=str(request_id or '').strip(),
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                page_id=str(context.get('page_id', '') or '').strip(),
                scene_id=str(context.get('scene_id', '') or '').strip(),
                action=str(context.get('action', '') or '').strip(),
                api_id=str(api_name or self._get_active() or '').strip(),
                provider=str(provider_name or '').strip(),
                request_model=str(request_model or '').strip(),
                response_model=str(response_model or '').strip(),
                status=str(status or 'success').strip(),
                duration_ms=int(duration_ms or 0),
                first_token_ms=0,
                input_tokens=int(usage.get('input_tokens', 0) or 0),
                output_tokens=int(usage.get('output_tokens', 0) or 0),
                cache_create_tokens=int(usage.get('cache_create_tokens', 0) or 0),
                cache_hit_tokens=int(usage.get('cache_hit_tokens', 0) or 0),
                billing_multiplier=float(billing['billing_multiplier']),
                billing_mode=str(billing['billing_mode']),
                total_cost=total_cost,
                error_message=str(error_message or '').strip(),
            )
            self.usage_store.append_event(event)
        except Exception as exc:
            self._log(f'[usage_event_error] {exc}', level='WARN')

    def _log(self, message, level='INFO'):
        if callable(self.log_callback):
            self.log_callback(message, level=level)

    def fetch_models(self, api_name: str, cfg: dict = None) -> list:
        """获取指定服务商的模型列表，返回模型id字符串列表"""
        cfg = self._get_config(api_name, cfg=cfg)
        key = str(cfg.get('key', '') or '').strip()
        base_url = str(cfg.get('base_url', '') or '').strip()
        if not key or not base_url:
            raise ValueError('请先填写 API Key 和请求地址')
        provider_name = self._resolve_handler_name(api_name, cfg)
        if provider_name == 'openai':
            url = self._resolve_openai_compat_urls(base_url)['models_url']
        else:
            url = f'{base_url.rstrip("/")}/models'
        headers = self._build_bearer_headers(
            key,
            auth_field=self._normalize_auth_field(cfg.get('auth_field', 'Authorization')),
            include_content_type=True,
        )
        req = urllib.request.Request(url, headers=headers, method='GET')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='replace')
            raise RuntimeError(f'HTTP {e.code}: {err_body}')
        except urllib.error.URLError as e:
            raise RuntimeError(f'网络错误: {e.reason}')
        # 兼容 {"data": [{"id":...}]} 和 {"models": [{"name":...}]} 两种格式
        items = data.get('data') or data.get('models') or []
        result = []
        for item in items:
            mid = item.get('id') or item.get('name') or ''
            if mid:
                result.append(mid)
        return sorted(result)

    def test_connection(
        self,
        api_name: str,
        prompt: str = '请只回复 ok',
        model_override: str = None,
        timeout: float = 45,
        degrade_threshold_ms: int = None,
        max_retries: int = 0,
        cfg: dict = None,
    ) -> tuple:
        """测试API连接，返回(成功, 消息)"""
        last_error = None
        attempts = max(1, int(max_retries) + 1)
        request_timeout = max(float(timeout or 45), 1.0)

        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                result = self._call_sync(
                    prompt,
                    '你是测速助手，只回复最短结果。',
                    api_name,
                    0.0,
                    16,
                    request_timeout=request_timeout,
                    model_override=(model_override or '').strip() or None,
                    cfg=cfg,
                )
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                response_preview = (result or '').strip().replace('\n', ' ')
                response_preview = response_preview[:80] or '已收到空响应'

                if degrade_threshold_ms and elapsed_ms > int(degrade_threshold_ms):
                    return True, (
                        f'连接成功，但耗时 {elapsed_ms}ms，已超过降级阈值 {int(degrade_threshold_ms)}ms。'
                        f' 响应预览：{response_preview}'
                    )

                retry_note = f'，第 {attempt} 次尝试成功' if attempt > 1 else ''
                return True, f'连接成功，耗时 {elapsed_ms}ms{retry_note}。响应预览：{response_preview}'
            except Exception as exc:
                last_error = str(exc)

        return False, f'连接失败，已尝试 {attempts} 次。最后一次错误：{last_error}'

    @staticmethod
    def _extract_json_payload(text: str) -> str:
        content = str(text or '').strip()
        if not content:
            raise ValueError('AI 返回为空')

        fence_match = re.match(r'^```(?:json)?\s*(.*?)\s*```$', content, flags=re.IGNORECASE | re.DOTALL)
        if fence_match:
            content = fence_match.group(1).strip()

        candidates = []
        for opener, closer in (('{', '}'), ('[', ']')):
            start = content.find(opener)
            end = content.rfind(closer)
            if start >= 0 and end > start:
                candidate = content[start:end + 1].strip()
                if candidate:
                    candidates.append((start, candidate))
        if candidates:
            candidates.sort(key=lambda item: item[0])
            return candidates[0][1]
        return content
