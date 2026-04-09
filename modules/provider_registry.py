# -*- coding: utf-8 -*-
"""
AI 服务商预设注册表。
"""

from __future__ import annotations


HANDLER_OPENAI = 'openai'
HANDLER_CLAUDE = 'claude'

MODEL_LIST_REMOTE = 'remote'
MODEL_LIST_STATIC = 'static'
MODEL_LIST_MANUAL = 'manual'

ANTHROPIC_VERSION = '2023-06-01'

DEFAULT_EXTRA_HEADERS_HINT = (
    '填写 JSON 对象，为当前请求追加自定义请求头；不会覆盖认证字段和 Content-Type。'
)

MANUAL_MODEL_LIST_MESSAGE = '当前模板不支持自动获取模型列表，请直接填写模型 ID。'

_PRESET_DEFINITIONS = (
    {
        'id': 'custom',
        'label': '自定义',
        'website': '',
        'docs_url': 'https://platform.openai.com/docs/api-reference/chat',
        'base_url': '',
        'model': '',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_REMOTE,
        'static_models': (),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': 'openrouter',
        'label': 'OpenRouter',
        'website': 'https://openrouter.ai',
        'docs_url': 'https://openrouter.ai/docs/quickstart',
        'base_url': 'https://openrouter.ai/api/v1',
        'model': 'openai/gpt-4o-mini',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_REMOTE,
        'static_models': (),
        'extra_headers_hint': (
            '填写 JSON 对象，为 OpenAI 兼容请求追加自定义请求头。'
            'OpenRouter 常见字段包括 HTTP-Referer、X-Title。'
            '示例：{"HTTP-Referer": "https://your-app.example", "X-Title": "纸研社"}'
        ),
        'credential_hint': '',
    },
    {
        'id': 'openai',
        'label': 'OpenAI',
        'website': 'https://openai.com',
        'docs_url': 'https://platform.openai.com/docs/api-reference/models/list',
        'base_url': 'https://api.openai.com/v1',
        'model': 'gpt-4o',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_REMOTE,
        'static_models': (),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': 'claude',
        'label': 'Claude',
        'website': 'https://anthropic.com',
        'docs_url': 'https://docs.anthropic.com/en/api/models-list',
        'base_url': 'https://api.anthropic.com',
        'model': 'claude-sonnet-4-6',
        'api_format': 'Claude',
        'handler_name': HANDLER_CLAUDE,
        'model_list_strategy': MODEL_LIST_REMOTE,
        'static_models': (),
        'extra_headers_hint': 'Claude 原生接口使用固定请求头，不需要在这里追加额外认证字段。',
        'credential_hint': '请填写 Anthropic Console 中生成的 API Key。',
    },
    {
        'id': 'deepseek',
        'label': 'DeepSeek',
        'website': 'https://platform.deepseek.com',
        'docs_url': 'https://api-docs.deepseek.com',
        'base_url': 'https://api.deepseek.com/v1',
        'model': 'deepseek-chat',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('deepseek-chat', 'deepseek-reasoner'),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': 'doubao',
        'label': '豆包',
        'website': 'https://www.volcengine.com/product/doubao',
        'docs_url': 'https://www.volcengine.com/docs/82379',
        'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
        'model': 'doubao-pro-4k',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('doubao-pro-4k',),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': 'zhipu',
        'label': '智谱',
        'website': 'https://open.bigmodel.cn',
        'docs_url': 'https://open.bigmodel.cn/dev/howuse/model',
        'base_url': 'https://open.bigmodel.cn/api/paas/v4',
        'model': 'glm-4-plus',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('glm-4-plus', 'glm-4-air', 'glm-4-flash'),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': 'tongyi',
        'label': '通义',
        'website': 'https://dashscope.aliyun.com',
        'docs_url': 'https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope',
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'model': 'qwen-plus',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('qwen-plus', 'qwen-turbo', 'qwen-max'),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': 'baidu',
        'label': '文心一言',
        'website': 'https://cloud.baidu.com',
        'docs_url': 'https://cloud.baidu.com/doc/qianfan/s/Hmh4suq26',
        'base_url': 'https://qianfan.baidubce.com/v2',
        'model': 'ernie-4.5-8k-preview',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('ernie-4.5-8k-preview',),
        'extra_headers_hint': (
            '填写 JSON 对象，为百度千帆兼容模式追加自定义请求头。'
            '如需补充应用级标识，请按官方文档填写对应请求头字段。'
        ),
        'credential_hint': '请填写百度千帆 V2 API Key；如需区分调用量和账单，可在额外请求头 JSON 中追加 appid。',
    },
    {
        'id': 'spark',
        'label': '讯飞星火',
        'website': 'https://xinghuo.xfyun.cn',
        'docs_url': 'https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html',
        'base_url': 'https://spark-api-open.xf-yun.com/v1',
        'model': '4.0Ultra',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('4.0Ultra', 'generalv3.5', 'max-32k', 'generalv3', 'pro-128k', 'lite'),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '请填写讯飞控制台对应模型版本生成的 APIPassword。',
    },
    {
        'id': 'minimax',
        'label': 'MiniMax',
        'website': 'https://platform.minimaxi.com',
        'docs_url': 'https://platform.minimaxi.com/document',
        'base_url': 'https://api.minimaxi.chat/v1',
        'model': 'MiniMax-Text-01',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('MiniMax-Text-01',),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': 'moonshot',
        'label': 'Moonshot',
        'website': 'https://platform.moonshot.cn',
        'docs_url': 'https://platform.moonshot.cn/docs',
        'base_url': 'https://api.moonshot.cn/v1',
        'model': 'moonshot-v1-8k',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k'),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': 'yi',
        'label': '零一万物',
        'website': 'https://platform.lingyiwanwu.com',
        'docs_url': 'https://platform.lingyiwanwu.com/docs',
        'base_url': 'https://api.lingyiwanwu.com/v1',
        'model': 'yi-large',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('yi-large', 'yi-lightning'),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': 'siliconflow',
        'label': 'SiliconFlow',
        'website': 'https://siliconflow.cn',
        'docs_url': 'https://docs.siliconflow.cn',
        'base_url': 'https://api.siliconflow.cn/v1',
        'model': 'deepseek-ai/DeepSeek-V3',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('deepseek-ai/DeepSeek-V3', 'deepseek-ai/DeepSeek-R1'),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': 'baichuan',
        'label': '百川',
        'website': 'https://platform.baichuan-ai.com',
        'docs_url': 'https://platform.baichuan-ai.com/docs',
        'base_url': 'https://api.baichuan-ai.com/v1',
        'model': 'Baichuan4',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('Baichuan4',),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': 'hunyuan',
        'label': '混元',
        'website': 'https://cloud.tencent.com/product/hunyuan',
        'docs_url': 'https://cloud.tencent.com/document/product/1729',
        'base_url': 'https://api.hunyuan.cloud.tencent.com/v1',
        'model': 'hunyuan-turbo',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('hunyuan-turbo',),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': 'sensenova',
        'label': '商汤日日新',
        'website': 'https://platform.sensenova.cn',
        'docs_url': 'https://platform.sensenova.cn/document',
        'base_url': 'https://api.sensenova.cn/compatible-mode/v1',
        'model': 'SenseChat-5',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('SenseChat-5',),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': 'stepfun',
        'label': '阶跃星辰',
        'website': 'https://platform.stepfun.com',
        'docs_url': 'https://platform.stepfun.com/docs',
        'base_url': 'https://api.stepfun.com/v1',
        'model': 'step-2-16k',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('step-2-16k',),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': '360ai',
        'label': '360 智脑',
        'website': 'https://ai.360.com',
        'docs_url': 'https://ai.360.com/platform/docs',
        'base_url': 'https://api.360.cn/v1',
        'model': '360gpt2-pro',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('360gpt2-pro',),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
    {
        'id': 'tiangong',
        'label': '天工',
        'website': 'https://model.tiangong.cn',
        'docs_url': 'https://model.tiangong.cn/docs',
        'base_url': 'https://sky-api.singularity-ai.com/saas/api/v4',
        'model': 'tiangong-pro',
        'api_format': 'OpenAI',
        'handler_name': HANDLER_OPENAI,
        'model_list_strategy': MODEL_LIST_STATIC,
        'static_models': ('tiangong-pro',),
        'extra_headers_hint': DEFAULT_EXTRA_HEADERS_HINT,
        'credential_hint': '',
    },
)

PRESET_REGISTRY = {
    item['id']: dict(item)
    for item in _PRESET_DEFINITIONS
}

PRESET_OPTIONS = [
    (
        item['id'],
        item['label'],
        {
            'website': item['website'],
            'base_url': item['base_url'],
            'model': item['model'],
            'api_format': item['api_format'],
        },
    )
    for item in _PRESET_DEFINITIONS
]

PRESET_MAP = {
    item['id']: {
        'label': item['label'],
        'defaults': {
            'website': item['website'],
            'base_url': item['base_url'],
            'model': item['model'],
            'api_format': item['api_format'],
        },
        'docs_url': item['docs_url'],
        'handler_name': item['handler_name'],
        'model_list_strategy': item['model_list_strategy'],
        'static_models': list(item['static_models']),
        'extra_headers_hint': item['extra_headers_hint'],
        'credential_hint': item['credential_hint'],
    }
    for item in _PRESET_DEFINITIONS
}


def normalize_provider_type(provider_type):
    value = str(provider_type or '').strip().lower()
    return value if value in PRESET_REGISTRY else 'custom'


def get_preset_definition(provider_type):
    return dict(PRESET_REGISTRY[normalize_provider_type(provider_type)])


def list_preset_definitions():
    return [dict(item) for item in _PRESET_DEFINITIONS]


def resolve_handler_name(provider_type, api_format='OpenAI'):
    normalized_provider = normalize_provider_type(provider_type)
    normalized_format = str(api_format or '').strip().lower()
    if normalized_provider == 'custom':
        if normalized_format == 'claude':
            return HANDLER_CLAUDE
        return HANDLER_OPENAI
    return PRESET_REGISTRY[normalized_provider]['handler_name']


def resolve_model_list_strategy(provider_type, api_format='OpenAI'):
    normalized_provider = normalize_provider_type(provider_type)
    if normalized_provider == 'custom':
        return MODEL_LIST_REMOTE
    return PRESET_REGISTRY[normalized_provider]['model_list_strategy']


def get_static_models(provider_type):
    return list(get_preset_definition(provider_type).get('static_models', ()))


def get_extra_headers_hint(provider_type):
    preset = get_preset_definition(provider_type)
    return preset.get('extra_headers_hint') or DEFAULT_EXTRA_HEADERS_HINT


def get_credential_hint(provider_type):
    preset = get_preset_definition(provider_type)
    return preset.get('credential_hint') or ''


def get_model_list_manual_message(provider_type):
    strategy = resolve_model_list_strategy(provider_type)
    if strategy == MODEL_LIST_MANUAL:
        return MANUAL_MODEL_LIST_MESSAGE
    return ''
