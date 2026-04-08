# -*- coding: utf-8 -*-
"""
模型配置页使用的预设与表单辅助函数。
"""

from modules.provider_registry import PRESET_MAP, PRESET_OPTIONS, normalize_provider_type


FORM_KEY = '__current__'


def build_base_form_template(provider_type='custom'):
    provider_type = normalize_provider_type(provider_type)
    return {
        'name': '',
        'remark': '',
        'website': '',
        'key': '',
        'base_url': '',
        'api_format': 'OpenAI',
        'auth_field': 'Authorization',
        'model_mapping': '',
        'model': '',
        'provider_type': provider_type,
        'hide_ai_signature': False,
        'teammates_mode': False,
        'enable_tool_search': False,
        'high_intensity_thinking': False,
        'extra_json': '',
        'extra_headers': '',
        'temperature': '',
        'max_tokens': '',
        'timeout': '',
        'top_p': '',
        'presence_penalty': '',
        'frequency_penalty': '',
        'use_separate_test': False,
        'test_model': '',
        'test_prompt': '',
        'test_timeout': '',
        'test_degrade_ms': '',
        'test_max_retries': '',
        'use_separate_billing': False,
        'billing_multiplier': '',
        'billing_mode': '',
    }


def merge_with_preset_defaults(cfg, provider_type):
    provider_type = normalize_provider_type(provider_type)
    merged = build_base_form_template(provider_type)
    merged.update(cfg or {})
    merged['provider_type'] = provider_type

    preset_defaults = PRESET_MAP.get(provider_type, {}).get('defaults', {})
    for field in ('website', 'base_url', 'api_format'):
        if not str(merged.get(field, '') or '').strip() and preset_defaults.get(field):
            merged[field] = preset_defaults[field]
    return merged
