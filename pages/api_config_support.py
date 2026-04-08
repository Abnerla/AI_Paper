# -*- coding: utf-8 -*-
"""
Shared preset and form helpers for the API config page.
"""

FORM_KEY = '__current__'

PRESET_OPTIONS = [
    ('custom', '自定义', {'website': '', 'base_url': '', 'model': '', 'api_format': 'OpenAI'}),
    ('openrouter', 'OpenRouter', {'website': 'https://openrouter.ai', 'base_url': 'https://openrouter.ai/api/v1', 'model': 'openai/gpt-4o-mini', 'api_format': 'OpenAI'}),
    ('openai', 'OpenAI', {'website': 'https://openai.com', 'base_url': 'https://api.openai.com/v1', 'model': 'gpt-4o', 'api_format': 'OpenAI'}),
    ('claude', 'Claude', {'website': 'https://anthropic.com', 'base_url': 'https://api.anthropic.com', 'model': 'claude-opus-4-6', 'api_format': 'Claude'}),
    ('deepseek', 'DeepSeek', {'website': 'https://platform.deepseek.com', 'base_url': 'https://api.deepseek.com/v1', 'model': 'deepseek-chat', 'api_format': 'OpenAI'}),
    ('doubao', '豆包', {'website': 'https://www.volcengine.com/product/doubao', 'base_url': 'https://ark.cn-beijing.volces.com/api/v3', 'model': 'doubao-pro-4k', 'api_format': 'OpenAI'}),
    ('zhipu', '智谱', {'website': 'https://open.bigmodel.cn', 'base_url': 'https://open.bigmodel.cn/api/paas/v4', 'model': 'glm-4-plus', 'api_format': 'OpenAI'}),
    ('tongyi', '通义', {'website': 'https://dashscope.aliyun.com', 'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'model': 'qwen-plus', 'api_format': 'OpenAI'}),
    ('baidu', '文心一言', {'website': 'https://cloud.baidu.com', 'base_url': 'https://qianfan.baidubce.com/v2', 'model': 'ernie-4.5-8k', 'api_format': 'OpenAI'}),
    ('spark', '讯飞星火', {'website': 'https://xinghuo.xfyun.cn', 'base_url': 'https://spark-api-open.xf-yun.com/v1', 'model': 'generalv3.5', 'api_format': 'OpenAI'}),
    ('minimax', 'MiniMax', {'website': 'https://platform.minimaxi.com', 'base_url': 'https://api.minimaxi.chat/v1', 'model': 'MiniMax-Text-01', 'api_format': 'OpenAI'}),
    ('moonshot', 'Moonshot', {'website': 'https://platform.moonshot.cn', 'base_url': 'https://api.moonshot.cn/v1', 'model': 'moonshot-v1-8k', 'api_format': 'OpenAI'}),
    ('yi', '零一万物', {'website': 'https://platform.lingyiwanwu.com', 'base_url': 'https://api.lingyiwanwu.com/v1', 'model': 'yi-large', 'api_format': 'OpenAI'}),
    ('siliconflow', 'SiliconFlow', {'website': 'https://siliconflow.cn', 'base_url': 'https://api.siliconflow.cn/v1', 'model': 'deepseek-ai/DeepSeek-V3', 'api_format': 'OpenAI'}),
    ('baichuan', '百川', {'website': 'https://platform.baichuan-ai.com', 'base_url': 'https://api.baichuan-ai.com/v1', 'model': 'Baichuan4', 'api_format': 'OpenAI'}),
    ('hunyuan', '混元', {'website': 'https://cloud.tencent.com/product/hunyuan', 'base_url': 'https://api.hunyuan.cloud.tencent.com/v1', 'model': 'hunyuan-turbo', 'api_format': 'OpenAI'}),
    ('sensenova', '商汤日日新', {'website': 'https://platform.sensenova.cn', 'base_url': 'https://api.sensenova.cn/compatible-mode/v1', 'model': 'SenseChat-5', 'api_format': 'OpenAI'}),
    ('stepfun', '阶跃星辰', {'website': 'https://platform.stepfun.com', 'base_url': 'https://api.stepfun.com/v1', 'model': 'step-2-16k', 'api_format': 'OpenAI'}),
    ('lingyi', '零一万物2', {'website': 'https://platform.lingyiwanwu.com', 'base_url': 'https://api.lingyiwanwu.com/v1', 'model': 'yi-lightning', 'api_format': 'OpenAI'}),
    ('360ai', '360智脑', {'website': 'https://ai.360.com', 'base_url': 'https://api.360.cn/v1', 'model': '360gpt2-pro', 'api_format': 'OpenAI'}),
    ('tiangong', '天工', {'website': 'https://model.tiangong.cn', 'base_url': 'https://sky-api.singularity-ai.com/saas/api/v4', 'model': 'tiangong-pro', 'api_format': 'OpenAI'}),
    ('hailuo', '海螺 AI', {'website': 'https://hailuoai.com', 'base_url': 'https://api.minimaxi.chat/v1', 'model': 'MiniMax-Text-01', 'api_format': 'OpenAI'}),
    ('jimeng', '即梦 AI', {'website': 'https://jimeng.jianying.com', 'base_url': 'https://api.jimeng.jianying.com/v1', 'model': 'jimeng-2.1', 'api_format': 'OpenAI'}),
]

PRESET_MAP = {
    preset_id: {'label': label, 'defaults': defaults}
    for preset_id, label, defaults in PRESET_OPTIONS
}


def build_base_form_template(provider_type='custom'):
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
        'api_key': '',
        'secret_key': '',
        'app_id': '',
        'api_secret': '',
    }


def merge_with_preset_defaults(cfg, provider_type):
    provider_type = provider_type if provider_type in PRESET_MAP else 'custom'
    merged = build_base_form_template(provider_type)
    merged.update(cfg or {})
    merged['provider_type'] = provider_type

    preset_defaults = PRESET_MAP.get(provider_type, {}).get('defaults', {})
    for field in ('website', 'base_url', 'model', 'api_format'):
        if not str(merged.get(field, '') or '').strip() and preset_defaults.get(field):
            merged[field] = preset_defaults[field]
    return merged
