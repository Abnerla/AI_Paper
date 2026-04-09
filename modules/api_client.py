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

from modules.provider_registry import (
    ANTHROPIC_VERSION,
    HANDLER_CLAUDE,
    HANDLER_GEMINI,
    HANDLER_OPENAI,
    MODEL_LIST_MANUAL,
    MODEL_LIST_REMOTE,
    MODEL_LIST_STATIC,
    get_preset_definition,
    get_model_list_manual_message,
    get_static_models,
    normalize_provider_type,
    resolve_handler_name as resolve_provider_handler_name,
    resolve_model_list_strategy,
)
from modules.usage_stats import (
    UsageEvent,
    UsageStatsStore,
    calculate_total_cost,
    extract_claude_usage,
    extract_gemini_usage,
    extract_openai_usage,
    find_pricing_rule,
    resolve_event_billing,
)


class APIClient:
    """统一的AI API客户端"""

    def __init__(self, config_mgr, log_callback=None):
        self.config = config_mgr
        self.log_callback = log_callback
        data_dir = getattr(config_mgr, 'data_dir', '') or getattr(config_mgr, 'app_dir', '') or '.'
        self.usage_store = UsageStatsStore(data_dir, config_mgr=config_mgr)

    def set_log_callback(self, log_callback):
        self.log_callback = log_callback

    def _get_active(self):
        return self.config.active_api

    def _get_config(self, api_name, cfg=None):
        if cfg is not None:
            return dict(cfg)
        return dict(self.config.get_api_config(api_name) or {})

    def _resolve_handler_name(self, api_name, cfg):
        provider_type = normalize_provider_type(cfg.get('provider_type') or api_name)
        return resolve_provider_handler_name(provider_type, cfg.get('api_format', 'OpenAI'))

    def _resolve_model_list_strategy(self, api_name, cfg):
        provider_type = normalize_provider_type(cfg.get('provider_type') or api_name)
        return resolve_model_list_strategy(provider_type, cfg.get('api_format', 'OpenAI'))

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
    def _build_key_headers(key, *, auth_field, include_content_type=True, use_bearer=False):
        headers = {}
        if include_content_type:
            headers['Content-Type'] = 'application/json'
        if use_bearer:
            headers[str(auth_field or 'Authorization')] = f'Bearer {key}'
        else:
            headers[str(auth_field or 'x-goog-api-key')] = str(key)
        return headers

    @staticmethod
    def _should_use_bearer_auth(auth_field):
        return str(auth_field or '').strip().lower() in {'authorization', 'proxy-authorization'}

    @staticmethod
    def _coerce_float(value, default=None):
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _coerce_positive_int(value, default=None):
        try:
            number = int(value)
        except Exception:
            return default
        if number <= 0:
            return default
        return number

    @staticmethod
    def _load_extra_headers_payload(cfg):
        raw = str((cfg or {}).get('extra_headers', '') or '').strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f'额外请求头 JSON 格式错误: {exc}') from exc
        if not isinstance(payload, dict):
            raise ValueError('额外请求头 JSON 必须是 JSON 对象')

        normalized = {}
        for key, value in payload.items():
            header_name = str(key or '').strip()
            if not header_name:
                raise ValueError('额外请求头 JSON 不能包含空的请求头名称')
            if isinstance(value, (dict, list)):
                raise ValueError(f'额外请求头 {header_name} 的值必须是字符串、数字或布尔值')
            normalized[header_name] = '' if value is None else str(value)
        return normalized

    @staticmethod
    def _merge_extra_headers(base_headers, extra_headers, *, protected_fields=None):
        merged = dict(base_headers or {})
        existing = {
            str(key).strip().lower()
            for key in merged
            if str(key).strip()
        }
        protected = {
            str(key).strip().lower()
            for key in (protected_fields or [])
            if str(key).strip()
        }
        added_keys = []
        ignored_keys = []

        for key, value in dict(extra_headers or {}).items():
            header_name = str(key or '').strip()
            if not header_name:
                ignored_keys.append(str(key))
                continue
            header_name_lower = header_name.lower()
            if header_name_lower in protected or header_name_lower in existing:
                ignored_keys.append(header_name)
                continue
            merged[header_name] = str(value)
            existing.add(header_name_lower)
            added_keys.append(header_name)
        return merged, sorted(set(added_keys)), sorted(set(ignored_keys))

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
    def _resolve_claude_urls(base_url):
        normalized_base_url = str(base_url or 'https://api.anthropic.com').strip() or 'https://api.anthropic.com'
        parts = urllib.parse.urlsplit(normalized_base_url)
        path = parts.path.rstrip('/')
        if path.endswith('/v1/messages'):
            api_root_path = path[:-len('/messages')]
        elif path.endswith('/v1/models'):
            api_root_path = path[:-len('/models')]
        elif path.endswith('/v1'):
            api_root_path = path
        else:
            api_root_path = f'{path}/v1' if path else '/v1'

        messages_path = f'{api_root_path}/messages'
        models_path = f'{api_root_path}/models'
        return {
            'root_url': urllib.parse.urlunsplit((parts.scheme, parts.netloc, api_root_path, '', '')),
            'messages_url': urllib.parse.urlunsplit((parts.scheme, parts.netloc, messages_path, '', '')),
            'models_url': urllib.parse.urlunsplit((parts.scheme, parts.netloc, models_path, '', '')),
        }

    @staticmethod
    def _normalize_gemini_model_name(model_name):
        value = str(model_name or '').strip()
        if value.startswith('models/'):
            return value.split('/', 1)[1].strip()
        return value

    @classmethod
    def _resolve_gemini_urls(cls, base_url, model_name=''):
        normalized_base_url = (
            str(base_url or 'https://generativelanguage.googleapis.com/v1beta').strip()
            or 'https://generativelanguage.googleapis.com/v1beta'
        )
        parts = urllib.parse.urlsplit(normalized_base_url)
        path = parts.path.rstrip('/')
        root_path = path

        if ':generateContent' in path and '/models/' in path:
            root_path = path.split('/models/', 1)[0]
        elif path.endswith('/models'):
            root_path = path[:-len('/models')]
        elif '/models/' in path:
            root_path = path.split('/models/', 1)[0]

        if not root_path.endswith('/v1beta') and not root_path.endswith('/v1'):
            root_path = f'{root_path}/v1beta' if root_path else '/v1beta'

        models_path = f'{root_path}/models'
        request_model = cls._normalize_gemini_model_name(model_name)
        encoded_model = urllib.parse.quote(request_model, safe='-._~')
        generate_content_path = f'{models_path}/{encoded_model}:generateContent' if encoded_model else ''
        return {
            'root_url': urllib.parse.urlunsplit((parts.scheme, parts.netloc, root_path, '', '')),
            'models_url': urllib.parse.urlunsplit((parts.scheme, parts.netloc, models_path, '', '')),
            'generate_content_url': urllib.parse.urlunsplit(
                (parts.scheme, parts.netloc, generate_content_path, '', '')
            ) if generate_content_path else '',
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
        if provider_name not in {HANDLER_OPENAI, HANDLER_GEMINI}:
            return model_name
        mapped_model, _mapping_hit = self._apply_model_mapping(model_name, cfg)
        if provider_name == HANDLER_GEMINI:
            return self._normalize_gemini_model_name(mapped_model or model_name)
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
        removed_keys = []
        protected_keys = {
            'model',
            'messages',
            'system',
            'prompt',
            'input',
        }
        for key, value in dict(extra_payload or {}).items():
            if key in protected_keys:
                ignored_keys.append(str(key))
                continue
            if value is None:
                if key in merged:
                    merged.pop(key, None)
                    removed_keys.append(str(key))
                continue
            merged[key] = value

        if 'max_completion_tokens' in extra_payload and 'max_tokens' in merged and 'max_tokens' not in extra_payload:
            merged.pop('max_tokens', None)
            removed_keys.append('max_tokens')

        return merged, sorted(set(ignored_keys)), sorted(set(removed_keys))

    @staticmethod
    def _merge_gemini_extra_json(base_payload, extra_payload):
        merged = dict(base_payload or {})
        ignored_keys = []
        removed_keys = []
        protected_keys = {
            'contents',
            'systemInstruction',
            'model',
        }
        for key, value in dict(extra_payload or {}).items():
            if key in protected_keys:
                ignored_keys.append(str(key))
                continue
            if value is None:
                if key in merged:
                    merged.pop(key, None)
                    removed_keys.append(str(key))
                continue
            merged[key] = value
        return merged, sorted(set(ignored_keys)), sorted(set(removed_keys))

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
        payload, ignored_keys, removed_keys = self._merge_openai_extra_json(payload, extra_json_payload)
        extra_headers_payload = self._load_extra_headers_payload(cfg)
        headers = self._build_bearer_headers(key, auth_field=auth_field, include_content_type=True)
        headers, extra_header_keys, ignored_extra_header_keys = self._merge_extra_headers(
            headers,
            extra_headers_payload,
            protected_fields={'Authorization', auth_field, 'Content-Type'},
        )

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
            'removed_extra_json_keys': removed_keys,
            'extra_header_keys': extra_header_keys,
            'ignored_extra_header_keys': ignored_extra_header_keys,
        }

    def _build_gemini_headers(self, cfg):
        key = str((cfg or {}).get('key', '') or '').strip()
        if not key:
            raise ValueError('Gemini API Key未配置')

        raw_auth_field = str((cfg or {}).get('auth_field', '') or '').strip()
        auth_field = raw_auth_field or 'x-goog-api-key'
        use_bearer = self._should_use_bearer_auth(auth_field)
        headers = self._build_key_headers(
            key,
            auth_field=auth_field,
            include_content_type=True,
            use_bearer=use_bearer,
        )
        extra_headers_payload = self._load_extra_headers_payload(cfg)
        headers, extra_header_keys, ignored_extra_header_keys = self._merge_extra_headers(
            headers,
            extra_headers_payload,
            protected_fields={'Content-Type', auth_field},
        )
        return {
            'headers': headers,
            'auth_field': auth_field,
            'use_bearer': use_bearer,
            'extra_header_keys': extra_header_keys,
            'ignored_extra_header_keys': ignored_extra_header_keys,
        }

    def _prepare_gemini_request(self, prompt, system, cfg, temperature, max_tokens):
        key = str((cfg or {}).get('key', '') or '').strip()
        if not key:
            raise ValueError('Gemini API Key未配置')

        configured_model = (
            str((cfg or {}).get('model', '') or '').strip()
            or get_preset_definition('gemini').get('model', 'gemini-2.5-flash')
        )
        request_model, mapping_hit = self._apply_model_mapping(configured_model, cfg)
        request_model = self._normalize_gemini_model_name(request_model or configured_model)
        urls = self._resolve_gemini_urls(
            (cfg or {}).get('base_url', 'https://generativelanguage.googleapis.com/v1beta'),
            request_model,
        )
        if not urls['generate_content_url']:
            raise ValueError('Gemini 请求地址无效')

        generation_config = {
            'temperature': temperature,
            'maxOutputTokens': max_tokens,
        }
        top_p = self._coerce_float((cfg or {}).get('top_p', ''), default=None)
        if top_p is not None:
            generation_config['topP'] = top_p
        presence_penalty = self._coerce_float((cfg or {}).get('presence_penalty', ''), default=None)
        if presence_penalty is not None:
            generation_config['presencePenalty'] = presence_penalty
        frequency_penalty = self._coerce_float((cfg or {}).get('frequency_penalty', ''), default=None)
        if frequency_penalty is not None:
            generation_config['frequencyPenalty'] = frequency_penalty

        payload = {
            'contents': [
                {
                    'role': 'user',
                    'parts': [{'text': prompt}],
                }
            ],
            'generationConfig': generation_config,
        }
        if system:
            payload['systemInstruction'] = {
                'role': 'system',
                'parts': [{'text': system}],
            }

        extra_json_payload = self._load_extra_json_payload(cfg)
        payload, ignored_keys, removed_keys = self._merge_gemini_extra_json(payload, extra_json_payload)
        header_bundle = self._build_gemini_headers(cfg)

        return {
            'url': urls['generate_content_url'],
            'models_url': urls['models_url'],
            'root_url': urls['root_url'],
            'payload': payload,
            'headers': header_bundle['headers'],
            'auth_field': header_bundle['auth_field'],
            'use_bearer': header_bundle['use_bearer'],
            'request_model': request_model,
            'model_mapping_hit': mapping_hit,
            'extra_json_keys': sorted(extra_json_payload.keys()),
            'ignored_extra_json_keys': ignored_keys,
            'removed_extra_json_keys': removed_keys,
            'extra_header_keys': header_bundle['extra_header_keys'],
            'ignored_extra_header_keys': header_bundle['ignored_extra_header_keys'],
        }

    @staticmethod
    def _extract_gemini_text_from_part(part):
        if isinstance(part, str):
            return part
        if not isinstance(part, dict):
            return ''
        text = part.get('text')
        if isinstance(text, str):
            return text
        return ''

    @classmethod
    def _extract_gemini_response_text(cls, payload):
        resp = dict(payload or {})
        candidates = resp.get('candidates') if isinstance(resp.get('candidates'), list) else []
        fragments = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get('content')
            if not isinstance(content, dict):
                continue
            parts = content.get('parts') if isinstance(content.get('parts'), list) else []
            for part in parts:
                fragment = cls._extract_gemini_text_from_part(part)
                if fragment:
                    fragments.append(fragment)

        text = '\n'.join(fragment for fragment in fragments if fragment).strip()
        prompt_feedback = resp.get('promptFeedback') if isinstance(resp.get('promptFeedback'), dict) else {}
        block_reason = str(prompt_feedback.get('blockReason', '') or '').strip()
        finish_reasons = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            finish_reason = str(candidate.get('finishReason', '') or '').strip()
            if finish_reason:
                finish_reasons.append(finish_reason)

        return {
            'text': text,
            'text_source': 'candidates.content.parts.text' if text else 'empty',
            'content_kind': 'gemini_parts' if text else 'empty',
            'has_choices': bool(candidates),
            'has_output_text': bool(text),
            'block_reason': block_reason,
            'finish_reasons': sorted(set(finish_reasons)),
        }

    @staticmethod
    def _extract_openai_text_from_content_item(item):
        if isinstance(item, str):
            return item
        if not isinstance(item, dict):
            return ''

        text_value = item.get('text')
        if isinstance(text_value, str):
            return text_value
        if isinstance(text_value, dict):
            nested_text = text_value.get('value') or text_value.get('text') or ''
            if isinstance(nested_text, str):
                return nested_text

        output_text = item.get('output_text')
        if isinstance(output_text, str):
            return output_text
        if isinstance(output_text, dict):
            nested_output_text = output_text.get('value') or output_text.get('text') or ''
            if isinstance(nested_output_text, str):
                return nested_output_text

        content_value = item.get('content')
        if isinstance(content_value, str):
            return content_value
        return ''

    @classmethod
    def _extract_openai_text_from_content(cls, content):
        if isinstance(content, str):
            return content, 'string'
        if isinstance(content, list):
            fragments = []
            for item in content:
                fragment = cls._extract_openai_text_from_content_item(item)
                if fragment:
                    fragments.append(fragment)
            return '\n'.join(fragment for fragment in fragments if fragment), 'array'
        if isinstance(content, dict):
            fragment = cls._extract_openai_text_from_content_item(content)
            if fragment:
                return fragment, 'object'
        return '', 'empty'

    @classmethod
    def _extract_openai_text_from_output_items(cls, output_items):
        if not isinstance(output_items, list):
            return ''

        fragments = []
        for item in output_items:
            if not isinstance(item, dict):
                continue
            content = item.get('content')
            fragment, _content_kind = cls._extract_openai_text_from_content(content)
            if fragment:
                fragments.append(fragment)
                continue
            fallback_fragment = cls._extract_openai_text_from_content_item(item)
            if fallback_fragment:
                fragments.append(fallback_fragment)
        return '\n'.join(fragment for fragment in fragments if fragment)

    @classmethod
    def _extract_openai_response_text(cls, payload):
        resp = dict(payload or {})
        has_choices = isinstance(resp.get('choices'), list) and bool(resp.get('choices'))
        has_output_text = bool(str(resp.get('output_text', '') or '').strip())
        has_output_items = isinstance(resp.get('output'), list) and bool(resp.get('output'))

        choices = resp.get('choices') if isinstance(resp.get('choices'), list) else []
        if choices:
            first_choice = choices[0] if isinstance(choices[0], dict) else {}
            message = first_choice.get('message') if isinstance(first_choice.get('message'), dict) else {}
            message_content = message.get('content')
            text, content_kind = cls._extract_openai_text_from_content(message_content)
            if text:
                return {
                    'text': text,
                    'text_source': 'choices.message.content',
                    'content_kind': content_kind,
                    'has_choices': has_choices,
                    'has_output_text': has_output_text,
                }

            choice_text = first_choice.get('text')
            if isinstance(choice_text, str) and choice_text:
                return {
                    'text': choice_text,
                    'text_source': 'choices.text',
                    'content_kind': 'legacy_text',
                    'has_choices': has_choices,
                    'has_output_text': has_output_text,
                }

        output_text = resp.get('output_text')
        if isinstance(output_text, str) and output_text:
            return {
                'text': output_text,
                'text_source': 'output_text',
                'content_kind': 'responses_output_text',
                'has_choices': has_choices,
                'has_output_text': has_output_text,
            }

        output_items_text = cls._extract_openai_text_from_output_items(resp.get('output'))
        if output_items_text:
            return {
                'text': output_items_text,
                'text_source': 'output.content',
                'content_kind': 'responses_output_array',
                'has_choices': has_choices,
                'has_output_text': has_output_text or has_output_items,
            }

        return {
            'text': '',
            'text_source': 'empty',
            'content_kind': 'empty',
            'has_choices': has_choices,
            'has_output_text': has_output_text or has_output_items,
        }

    def _build_claude_headers(self, cfg):
        key = str((cfg or {}).get('key', '') or '').strip()
        if not key:
            raise ValueError('Claude API Key未配置')
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': key,
            'anthropic-version': ANTHROPIC_VERSION,
        }
        extra_headers_payload = self._load_extra_headers_payload(cfg)
        headers, _added_keys, _ignored_keys = self._merge_extra_headers(
            headers,
            extra_headers_payload,
            protected_fields={'x-api-key', 'anthropic-version', 'Content-Type'},
        )
        return headers

    @staticmethod
    def _merge_model_candidates(model_ids, current_model=''):
        merged = []
        seen = set()
        current = str(current_model or '').strip()
        for model_id in ([current] if current else []) + list(model_ids or []):
            value = str(model_id or '').strip()
            if not value:
                continue
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            merged.append(value)
        return merged

    @staticmethod
    def _extract_model_ids(payload):
        items = payload.get('data') or payload.get('models') or []
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            model_id = item.get('id') or item.get('name') or ''
            if model_id:
                result.append(model_id)
        return sorted(result)

    @classmethod
    def _extract_gemini_model_ids(cls, payload):
        items = payload.get('models') or payload.get('data') or []
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            supported_methods = item.get('supportedGenerationMethods')
            if isinstance(supported_methods, list) and supported_methods:
                normalized_methods = {str(method or '').strip() for method in supported_methods}
                if 'generateContent' not in normalized_methods:
                    continue
            model_id = item.get('id') or item.get('name') or ''
            model_id = cls._normalize_gemini_model_name(model_id)
            if model_id:
                result.append(model_id)
        return sorted(set(result), key=lambda item: item.lower())

    def _fetch_remote_models(self, provider_name, cfg, *, timeout=15):
        key = str(cfg.get('key', '') or '').strip()
        base_url = str(cfg.get('base_url', '') or '').strip()
        if not key or not base_url:
            raise ValueError('请先填写 API Key 和请求地址')

        if provider_name == HANDLER_OPENAI:
            auth_field = self._normalize_auth_field(cfg.get('auth_field', 'Authorization'))
            url = self._resolve_openai_compat_urls(base_url)['models_url']
            headers = self._build_bearer_headers(
                key,
                auth_field=auth_field,
                include_content_type=True,
            )
            extra_headers_payload = self._load_extra_headers_payload(cfg)
            headers, extra_header_keys, ignored_extra_header_keys = self._merge_extra_headers(
                headers,
                extra_headers_payload,
                protected_fields={'Authorization', auth_field, 'Content-Type'},
            )
            extractor = self._extract_model_ids
        elif provider_name == HANDLER_CLAUDE:
            auth_field = 'x-api-key'
            url = self._resolve_claude_urls(base_url)['models_url']
            headers = self._build_claude_headers(cfg)
            extra_header_keys = []
            ignored_extra_header_keys = []
            extractor = self._extract_model_ids
        elif provider_name == HANDLER_GEMINI:
            header_bundle = self._build_gemini_headers(cfg)
            auth_field = header_bundle['auth_field']
            url = self._resolve_gemini_urls(base_url)['models_url']
            headers = header_bundle['headers']
            extra_header_keys = header_bundle['extra_header_keys']
            ignored_extra_header_keys = header_bundle['ignored_extra_header_keys']
            extractor = self._extract_gemini_model_ids
        else:
            raise ValueError(f'不支持的模型列表处理器: {provider_name}')

        self._log(
            '[fetch_models_remote] '
            f'provider={provider_name} '
            f'endpoint={self._sanitize_url_for_log(url)} '
            f'auth_field={auth_field} '
            f'extra_header_keys={",".join(extra_header_keys) or "-"} '
            f'ignored_extra_header_keys={",".join(ignored_extra_header_keys) or "-"}'
        )
        payload = self._http_get_json(url, headers=headers, timeout=timeout)
        return extractor(payload)

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
            HANDLER_OPENAI: self._call_openai_compat,
            HANDLER_CLAUDE: self._call_claude,
            HANDLER_GEMINI: self._call_gemini,
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
        result_preview = result_text.strip().replace('\n', ' ')[:80]
        self._log(
            '[api_response] '
            f'api={api_name or "active"} '
            f'provider={provider_name} '
            f'model={model_name} '
            f'elapsed_ms={elapsed_ms} '
            f'result_len={len(result_text)} '
            f'text_source={response_payload.get("text_source", "-")} '
            f'content_kind={response_payload.get("content_kind", "-")} '
            f'result_preview_len={len(result_preview)} '
            f'has_choices={int(bool(response_payload.get("has_choices", False)))} '
            f'has_output_text={int(bool(response_payload.get("has_output_text", False)))}'
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

    def _http_get_json(self, url, headers: dict, timeout=15) -> dict:
        """发送 HTTP GET 请求并解析 JSON。"""
        req = urllib.request.Request(url, headers=headers, method='GET')
        safe_url = self._sanitize_url_for_log(url)
        started_at = time.perf_counter()
        self._log(f'[http_get] url={safe_url} timeout={timeout}')
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
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode('utf-8', errors='replace')
            self._log(
                '[http_error] '
                f'url={safe_url} status={exc.code} '
                f'elapsed_ms={int((time.perf_counter() - started_at) * 1000)} '
                f'error={err_body[:240]}',
                level='ERROR',
            )
            raise RuntimeError(f'HTTP {exc.code}: {err_body}')
        except urllib.error.URLError as exc:
            self._log(
                '[http_error] '
                f'url={safe_url} '
                f'elapsed_ms={int((time.perf_counter() - started_at) * 1000)} '
                f'error={exc.reason}',
                level='ERROR',
            )
            raise RuntimeError(f'网络错误: {exc.reason}')

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
            f'removed_extra_json_keys={",".join(prepared["removed_extra_json_keys"]) or "-"} '
            f'extra_header_keys={",".join(prepared["extra_header_keys"]) or "-"} '
            f'ignored_extra_header_keys={",".join(prepared["ignored_extra_header_keys"]) or "-"} '
            f'timeout={request_timeout}'
        )
        resp = self._http_post(
            prepared['url'],
            prepared['payload'],
            prepared['headers'],
            timeout=request_timeout,
        )
        extracted = self._extract_openai_response_text(resp)
        return {
            'text': extracted['text'],
            'text_source': extracted['text_source'],
            'content_kind': extracted['content_kind'],
            'has_choices': extracted['has_choices'],
            'has_output_text': extracted['has_output_text'],
            'response_model': str(resp.get('model', '') or prepared['request_model']),
            'request_model': prepared['request_model'],
            'usage': extract_openai_usage(resp),
        }

    def _call_claude(self, prompt, system, cfg, temperature, max_tokens, request_timeout=None):
        """调用Anthropic Claude API"""
        urls = self._resolve_claude_urls(cfg.get('base_url', 'https://api.anthropic.com'))
        model = cfg.get('model', get_preset_definition('claude').get('model', 'claude-sonnet-4-6'))
        data = {
            'model': model,
            'max_tokens': max_tokens,
            'messages': [{'role': 'user', 'content': prompt}],
        }
        if system:
            data['system'] = system
        headers = self._build_claude_headers(cfg)
        resp = self._http_post(urls['messages_url'], data, headers, timeout=request_timeout or 60)
        return {
            'text': resp['content'][0]['text'],
            'response_model': str(resp.get('model', '') or model),
            'usage': extract_claude_usage(resp),
        }

    def _call_gemini(self, prompt, system, cfg, temperature, max_tokens, request_timeout=None):
        """调用 Gemini 原生 API。"""
        prepared = self._prepare_gemini_request(prompt, system, cfg, temperature, max_tokens)
        self._log(
            '[gemini] '
            f'endpoint={self._sanitize_url_for_log(prepared["url"])} '
            f'auth_field={prepared["auth_field"]} '
            f'use_bearer={int(prepared["use_bearer"])} '
            f'model={prepared["request_model"]} '
            f'model_mapping_hit={prepared["model_mapping_hit"]} '
            f'extra_json_keys={",".join(prepared["extra_json_keys"]) or "-"} '
            f'ignored_extra_json_keys={",".join(prepared["ignored_extra_json_keys"]) or "-"} '
            f'removed_extra_json_keys={",".join(prepared["removed_extra_json_keys"]) or "-"} '
            f'extra_header_keys={",".join(prepared["extra_header_keys"]) or "-"} '
            f'ignored_extra_header_keys={",".join(prepared["ignored_extra_header_keys"]) or "-"} '
            f'timeout={request_timeout}'
        )
        resp = self._http_post(
            prepared['url'],
            prepared['payload'],
            prepared['headers'],
            timeout=request_timeout,
        )
        extracted = self._extract_gemini_response_text(resp)
        if not extracted['text']:
            finish_reasons = ','.join(extracted['finish_reasons']) or '-'
            block_reason = extracted['block_reason'] or '-'
            raise RuntimeError(
                f'Gemini 未返回可显示文本，block_reason={block_reason}，finish_reason={finish_reasons}'
            )
        return {
            'text': extracted['text'],
            'text_source': extracted['text_source'],
            'content_kind': extracted['content_kind'],
            'has_choices': extracted['has_choices'],
            'has_output_text': extracted['has_output_text'],
            'response_model': str(resp.get('modelVersion', '') or resp.get('model', '') or prepared['request_model']),
            'request_model': prepared['request_model'],
            'usage': extract_gemini_usage(resp),
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
        provider_type = normalize_provider_type(cfg.get('provider_type') or api_name)
        strategy = self._resolve_model_list_strategy(api_name, cfg)
        current_model = str(cfg.get('model', '') or '').strip()
        provider_name = self._resolve_handler_name(api_name, cfg)

        if strategy == MODEL_LIST_STATIC:
            static_models = get_static_models(provider_type)
            key = str(cfg.get('key', '') or '').strip()
            base_url = str(cfg.get('base_url', '') or '').strip()
            if key and base_url:
                try:
                    models = self._fetch_remote_models(provider_name, cfg, timeout=15)
                    return self._merge_model_candidates(models, current_model)
                except RuntimeError as exc:
                    error_text = str(exc)
                    if not (error_text.startswith('HTTP 404') or error_text.startswith('HTTP 405')):
                        raise
                    self._log(
                        '[fetch_models_static_fallback] '
                        f'provider={provider_type} '
                        f'reason={error_text}',
                        level='WARN',
                    )
            models = self._merge_model_candidates(static_models, current_model)
            self._log(
                '[fetch_models_static] '
                f'provider={provider_type} '
                f'models={",".join(models) or "-"}'
            )
            return models

        if strategy == MODEL_LIST_MANUAL:
            if current_model:
                return [current_model]
            raise ValueError(get_model_list_manual_message(provider_type))

        result = self._fetch_remote_models(provider_name, cfg, timeout=15)
        return self._merge_model_candidates(result, current_model)

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
                normalized_result = (result or '').strip()
                if not normalized_result:
                    last_error = '连接建立但未返回可显示文本，请检查模型类型或响应格式。'
                    continue

                response_preview = normalized_result.replace('\n', ' ')
                response_preview = response_preview[:80]

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
