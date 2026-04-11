# -*- coding: utf-8 -*-
"""
配置管理模块 - 本地加密存储模型服务密钥
"""

import copy
import json
import os
import random
import time
import urllib.parse
from datetime import datetime

from modules.provider_registry import (
    API_FORMAT_ANTHROPIC_MESSAGES,
    AUTH_VALUE_MODE_BEARER,
    AUTH_VALUE_MODE_RAW,
    PRESET_REGISTRY,
    get_protocol_default_auth,
    normalize_api_format,
    normalize_provider_type,
)
from modules.runtime_paths import (
    DATA_DIR_POINTER_FILE,
    persist_runtime_data_root,
    resolve_runtime_data_root,
)


LEGACY_PROVIDER_IDS = {
    'custom',
    'openrouter',
    'openai',
    'claude',
    'gemini',
    'newapi',
    'sub2api',
    'newapi_openai',
    'newapi_gemini',
    'sub2api_openai',
    'sub2api_gemini',
    'deepseek',
    'doubao',
    'zhipu',
    'tongyi',
    'baidu',
    'spark',
    'minimax',
    'moonshot',
    'yi',
    'siliconflow',
    'baichuan',
    'hunyuan',
    'sensenova',
    'stepfun',
    '360ai',
    'tiangong',
}

CONFIG_DIR_POINTER_FILE = DATA_DIR_POINTER_FILE


def _normalize_directory(path):
    return os.path.abspath(os.path.expanduser(str(path or '').strip()))


def _rewrite_legacy_openai_proxy_base_url(provider_hint, base_url):
    raw_provider_hint = str(provider_hint or '').strip().lower()
    raw_base_url = str(base_url or '').strip()
    if raw_provider_hint not in {'newapi_gemini', 'sub2api_gemini'} or not raw_base_url:
        return raw_base_url

    parts = urllib.parse.urlsplit(raw_base_url)
    path = parts.path.rstrip('/')
    if path.endswith('/v1beta'):
        path = f'{path[:-len("/v1beta")]}/v1'
    elif '/v1beta/' in path:
        path = path.replace('/v1beta/', '/v1/', 1)
    else:
        return raw_base_url
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def resolve_config_dir(data_dir):
    return resolve_runtime_data_root(_normalize_directory(data_dir))


def persist_config_dir(data_dir, config_dir):
    persist_runtime_data_root(_normalize_directory(data_dir), _normalize_directory(config_dir))


def resolve_model_display_name(cfg):
    record = dict(cfg or {})
    display_name = str(record.get('model_display_name', '') or '').strip()
    if display_name:
        return display_name
    return str(record.get('model', '') or '').strip()


class ConfigManager:
    """配置管理器，负责模型配置的加密保存和读取"""

    CONFIG_FILE = 'config.enc'
    _KEY = b'SmartPaperTool2024SecretKey12345'  # 32字节密钥

    def __init__(self, data_dir):
        self.base_data_dir = _normalize_directory(data_dir)
        self.base_app_dir = self.base_data_dir
        os.makedirs(self.base_data_dir, exist_ok=True)
        self.data_dir = resolve_config_dir(self.base_data_dir)
        self.app_dir = self.data_dir
        self.config_path = os.path.join(self.data_dir, self.CONFIG_FILE)
        self._data = self._load()

    def _xor_encrypt(self, data: bytes) -> bytes:
        """简单 XOR 加密（内置，不依赖第三方库）"""
        key = self._KEY
        result = bytearray()
        for i, b in enumerate(data):
            result.append(b ^ key[i % len(key)])
        return bytes(result)

    def _default_data(self) -> dict:
        return {
            'apis': {},
            'active_api': '',
            'prompt_center': {
                'seeded': False,
                'scenes': {},
            },
            'workspace_state': {},
            'settings': {
                'auto_save_history': True,
                'max_history': 100,
                'default_reference_style': 'GB/T 7714',
                'default_output_format': 'docx',
                'theme_mode': 'light',
                'startup_page': 'home',
                'show_home_stats': True,
                'enable_loading_animation': True,
                'launch_on_startup': False,
                'silent_startup': False,
                'minimize_to_tray_on_close': False,
                'ignored_update_version': '',
                'global_test_model': '',
                'global_test_prompt': 'Who are you?',
                'global_test_timeout_sec': 45,
                'global_test_degrade_ms': 6000,
                'global_test_max_retries': 2,
                'global_billing_multiplier': '',
                'global_billing_mode': 'request_model',
                'home_last_import_failure': None,
                'usage_pricing_rules': [],
            },
        }

    def _load(self) -> dict:
        """从文件加载配置"""
        default = self._default_data()
        if not os.path.exists(self.config_path):
            return default

        try:
            with open(self.config_path, 'rb') as f:
                encrypted = f.read()
            decrypted = self._xor_encrypt(encrypted)
            loaded = json.loads(decrypted.decode('utf-8'))
            self._deep_merge(default, loaded)
            return self._sanitize_loaded_data(default)
        except Exception:
            return default

    def _deep_merge(self, base: dict, override: dict):
        """将 override 的值合并到 base 中"""
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                self._deep_merge(base[k], v)
            else:
                base[k] = v

    def _normalize_api_record(self, api_id, config):
        cfg = dict(config or {})
        raw_provider_hint = str(cfg.get('provider_type') or api_id or '').strip().lower()
        provider_type = normalize_provider_type(raw_provider_hint)
        if not provider_type:
            provider_type = api_id.lower() if api_id in LEGACY_PROVIDER_IDS else 'custom'
        cfg['provider_type'] = provider_type

        name = cfg.get('name', '')
        cfg['name'] = name.strip() if isinstance(name, str) else str(name or '').strip()
        preset_definition = PRESET_REGISTRY.get(provider_type, PRESET_REGISTRY['custom'])
        default_api_format = normalize_api_format(preset_definition.get('api_format', ''))
        if provider_type != 'custom':
            cfg['api_format'] = default_api_format
        else:
            cfg['api_format'] = normalize_api_format(cfg.get('api_format', default_api_format))
        cfg.setdefault('remark', '')
        cfg.setdefault('website', '')
        cfg.setdefault('key', '')
        cfg['base_url'] = _rewrite_legacy_openai_proxy_base_url(raw_provider_hint, cfg.get('base_url', ''))
        default_auth = get_protocol_default_auth(cfg['api_format'])
        default_auth_field = preset_definition.get('auth_field', default_auth['auth_field'])
        default_auth_value_mode = preset_definition.get('auth_value_mode', default_auth['auth_value_mode'])
        existing_auth_field = str(cfg.get('auth_field', '') or '').strip()
        if provider_type != 'custom':
            cfg['auth_field'] = str(default_auth_field or '').strip() or default_auth['auth_field']
            cfg['auth_value_mode'] = str(default_auth_value_mode or '').strip().lower() or default_auth['auth_value_mode']
        else:
            cfg['auth_field'] = existing_auth_field or default_auth['auth_field']
            raw_auth_value_mode = str(cfg.get('auth_value_mode', '') or '').strip().lower()
            if raw_auth_value_mode not in {AUTH_VALUE_MODE_BEARER, AUTH_VALUE_MODE_RAW}:
                normalized_existing_field = cfg['auth_field'].lower()
                if normalized_existing_field in {'authorization', 'proxy-authorization'}:
                    raw_auth_value_mode = AUTH_VALUE_MODE_BEARER
                elif normalized_existing_field:
                    raw_auth_value_mode = AUTH_VALUE_MODE_RAW
                else:
                    raw_auth_value_mode = default_auth['auth_value_mode']
            cfg['auth_value_mode'] = raw_auth_value_mode
            if cfg['api_format'] == API_FORMAT_ANTHROPIC_MESSAGES:
                cfg['auth_field'] = default_auth['auth_field']
                cfg['auth_value_mode'] = default_auth['auth_value_mode']
        cfg.setdefault('model_mapping', '')
        cfg.setdefault('model', '')
        cfg.setdefault('model_display_name', '')
        cfg.setdefault('extra_json', '')
        cfg.setdefault('extra_headers', '')
        cfg.setdefault('temperature', '')
        cfg.setdefault('max_tokens', '')
        cfg.setdefault('timeout', '')
        cfg.setdefault('top_p', '')
        cfg.setdefault('presence_penalty', '')
        cfg.setdefault('frequency_penalty', '')
        cfg.setdefault('use_separate_test', False)
        cfg.setdefault('test_model', '')
        cfg.setdefault('test_prompt', '')
        cfg.setdefault('test_timeout', '')
        cfg.setdefault('test_degrade_ms', '')
        cfg.setdefault('test_max_retries', '')
        cfg.setdefault('use_separate_billing', False)
        cfg.setdefault('billing_multiplier', '')
        cfg.setdefault('billing_mode', '')
        cfg.setdefault('hide_ai_signature', False)
        cfg.setdefault('teammates_mode', False)
        cfg.setdefault('enable_tool_search', False)
        cfg.setdefault('high_intensity_thinking', False)
        cfg.setdefault('enable_user_agent_spoof', False)
        for legacy_key in ('api_key', 'secret_key', 'app_id', 'api_secret'):
            cfg.pop(legacy_key, None)
        return cfg

    def _record_has_credentials(self, cfg):
        for key in ('key',):
            value = cfg.get(key, '')
            if isinstance(value, str) and value.strip():
                return True
        return False

    def _is_legacy_placeholder_record(self, api_id, cfg):
        if api_id not in LEGACY_PROVIDER_IDS:
            return False
        return not self._record_has_credentials(cfg)

    def _sanitize_prompt_record(self, prompt):
        if not isinstance(prompt, dict):
            return None

        prompt_id = str(prompt.get('id', '') or '').strip()
        if not prompt_id:
            return None

        mode = str(prompt.get('mode', 'instruction') or 'instruction').strip().lower()
        if mode not in ('instruction', 'template'):
            mode = 'instruction'

        source = str(prompt.get('source', 'user') or 'user').strip().lower()
        if source not in ('system', 'user'):
            source = 'user'

        try:
            created_at = int(prompt.get('created_at', 0) or 0)
        except Exception:
            created_at = 0
        try:
            updated_at = int(prompt.get('updated_at', created_at) or created_at)
        except Exception:
            updated_at = created_at

        return {
            'id': prompt_id,
            'name': str(prompt.get('name', '') or '').strip(),
            'description': str(prompt.get('description', '') or '').strip(),
            'mode': mode,
            'content': str(prompt.get('content', '') or ''),
            'source': source,
            'created_at': created_at,
            'updated_at': updated_at,
        }

    def _sanitize_prompt_scene(self, scene):
        if not isinstance(scene, dict):
            return {'active_prompt_id': '', 'prompts': []}

        prompts = []
        seen = set()
        for prompt in scene.get('prompts', []):
            sanitized = self._sanitize_prompt_record(prompt)
            if not sanitized:
                continue
            prompt_id = sanitized['id']
            if prompt_id in seen:
                continue
            seen.add(prompt_id)
            prompts.append(sanitized)

        active_prompt_id = str(scene.get('active_prompt_id', '') or '').strip()
        if active_prompt_id not in seen:
            active_prompt_id = prompts[0]['id'] if prompts else ''

        return {
            'active_prompt_id': active_prompt_id,
            'prompts': prompts,
        }

    def _sanitize_prompt_center(self, prompt_center):
        if not isinstance(prompt_center, dict):
            prompt_center = {}

        scenes = {}
        raw_scenes = prompt_center.get('scenes', {})
        if isinstance(raw_scenes, dict):
            for scene_id, scene in raw_scenes.items():
                scene_key = str(scene_id or '').strip()
                if not scene_key:
                    continue
                scenes[scene_key] = self._sanitize_prompt_scene(scene)

        return {
            'seeded': bool(prompt_center.get('seeded', False)),
            'scenes': scenes,
        }

    def _sanitize_workspace_state(self, workspace_state):
        if not isinstance(workspace_state, dict):
            return {}

        cleaned = {}
        for page_id, state in workspace_state.items():
            key = str(page_id or '').strip()
            if not key:
                continue
            if isinstance(state, dict):
                cleaned[key] = copy.deepcopy(state)
        return cleaned

    def _sanitize_loaded_data(self, data):
        apis = data.get('apis', {})
        cleaned_apis = {}
        if isinstance(apis, dict):
            for api_id, cfg in apis.items():
                if not isinstance(cfg, dict):
                    continue
                normalized = self._normalize_api_record(api_id, cfg)
                if self._is_legacy_placeholder_record(api_id, normalized):
                    continue
                cleaned_apis[api_id] = normalized

        data['apis'] = cleaned_apis
        active_api = data.get('active_api', '')
        if active_api not in cleaned_apis:
            data['active_api'] = next(iter(cleaned_apis), '')
        data['prompt_center'] = self._sanitize_prompt_center(data.get('prompt_center', {}))
        data['workspace_state'] = self._sanitize_workspace_state(data.get('workspace_state', {}))
        return data

    def save(self):
        """保存配置到文件"""
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            self._data = self._sanitize_loaded_data(dict(self._data))
            data = json.dumps(self._data, ensure_ascii=False, indent=2)
            encrypted = self._xor_encrypt(data.encode('utf-8'))
            with open(self.config_path, 'wb') as f:
                f.write(encrypted)
            return True
        except Exception:
            return False

    def switch_config_directory(self, target_dir):
        target_dir = _normalize_directory(target_dir)
        if not target_dir:
            raise ValueError('配置目录不能为空。')

        os.makedirs(target_dir, exist_ok=True)
        previous_dir = self.data_dir
        previous_path = self.config_path

        self.data_dir = target_dir
        self.app_dir = target_dir
        self.config_path = os.path.join(target_dir, self.CONFIG_FILE)

        try:
            if not self.save():
                raise RuntimeError('新的配置目录写入失败。')
            persist_config_dir(self.base_data_dir, target_dir)
        except Exception:
            self.data_dir = previous_dir
            self.app_dir = previous_dir
            self.config_path = previous_path
            raise

        return self.config_path

    def get(self, *keys, default=None):
        """获取配置值，支持链式 key"""
        d = self._data
        for k in keys:
            if isinstance(d, dict) and k in d:
                d = d[k]
            else:
                return default
        return d

    def set(self, *keys, value=None):
        """设置配置值"""
        d = self._data
        for k in keys[:-1]:
            if k not in d:
                d[k] = {}
            d = d[k]
        d[keys[-1]] = value

    def get_saved_apis(self):
        return self._data.setdefault('apis', {})

    def iter_saved_apis(self):
        return self.get_saved_apis().items()

    def list_saved_apis(self):
        return list(self.iter_saved_apis())

    def get_api_config(self, api_name=None):
        """获取指定模型服务的配置"""
        if api_name is None:
            api_name = self._data.get('active_api', '')
        return dict(self.get_saved_apis().get(api_name, {}))

    def set_api_config(self, api_name, config: dict):
        """设置指定模型服务的配置"""
        if not api_name:
            return
        self.get_saved_apis()[api_name] = self._normalize_api_record(api_name, config)

    def delete_api_config(self, api_name):
        apis = self.get_saved_apis()
        if api_name in apis:
            del apis[api_name]
        if self._data.get('active_api', '') == api_name:
            self._data['active_api'] = next(iter(apis), '')

    def reorder_apis(self, ordered_ids):
        """按给定顺序重新排列 apis 字典。"""
        apis = self.get_saved_apis()
        new_apis = {k: apis[k] for k in ordered_ids if k in apis}
        for k, v in apis.items():
            if k not in new_apis:
                new_apis[k] = v
        self._data['apis'] = new_apis

    def find_api_id_by_name(self, name, exclude_api_id=None):
        target = (name or '').strip()
        if not target:
            return None
        for api_id, cfg in self.iter_saved_apis():
            if api_id == exclude_api_id:
                continue
            if (cfg.get('name', '') or '').strip() == target:
                return api_id
        return None

    def generate_api_id(self):
        apis = self.get_saved_apis()
        while True:
            api_id = f"api_{int(time.time() * 1000)}_{random.randint(10, 99)}"
            if api_id not in apis:
                return api_id

    def generate_prompt_id(self):
        scenes = self.get_all_prompt_scenes()
        existing = {
            prompt.get('id')
            for scene in scenes.values()
            for prompt in scene.get('prompts', [])
            if isinstance(prompt, dict)
        }
        while True:
            prompt_id = f"prompt_{int(time.time() * 1000)}_{random.randint(100, 999)}"
            if prompt_id not in existing:
                return prompt_id

    @property
    def active_api(self):
        return self._data.get('active_api', '')

    @active_api.setter
    def active_api(self, val):
        self._data['active_api'] = val if val in self.get_saved_apis() else ''

    def reset(self):
        """重置为默认配置"""
        if os.path.exists(self.config_path):
            os.remove(self.config_path)
        self._data = self._load()

    def get_setting(self, key, default=None):
        return self.get('settings', key, default=default)

    def set_setting(self, key, value):
        self.set('settings', key, value=value)

    def get_workspace_state(self, page_id, default=None):
        workspace_state = self._sanitize_workspace_state(self._data.get('workspace_state', {}))
        self._data['workspace_state'] = workspace_state
        page_key = str(page_id or '').strip()
        if not page_key:
            return copy.deepcopy(default)
        state = workspace_state.get(page_key, default)
        return copy.deepcopy(state)

    def set_workspace_state(self, page_id, state):
        page_key = str(page_id or '').strip()
        if not page_key:
            return
        workspace_state = self._sanitize_workspace_state(self._data.get('workspace_state', {}))
        if isinstance(state, dict):
            workspace_state[page_key] = copy.deepcopy(state)
        else:
            workspace_state.pop(page_key, None)
        self._data['workspace_state'] = workspace_state

    def get_global_billing_settings(self):
        """获取归一化后的全局计费配置"""
        raw_multiplier = (self.get_setting('global_billing_multiplier', '') or '').strip()
        try:
            multiplier = float(raw_multiplier) if raw_multiplier else 1.0
        except Exception:
            raw_multiplier = ''
            multiplier = 1.0

        if multiplier <= 0:
            raw_multiplier = ''
            multiplier = 1.0

        mode = self.get_setting('global_billing_mode', 'request_model')
        if mode not in ('request_model', 'response_model'):
            mode = 'request_model'

        return {
            'raw_multiplier': raw_multiplier,
            'multiplier': multiplier,
            'mode': mode,
        }

    def get_home_last_import_failure(self):
        payload = self.get_setting('home_last_import_failure', None)
        if not isinstance(payload, dict):
            return None
        page_id = str(payload.get('page_id', '') or '').strip()
        file_name = str(payload.get('file_name', '') or '').strip()
        error_message = str(payload.get('error_message', '') or '').strip()
        timestamp = str(payload.get('timestamp', '') or '').strip()
        if not any((page_id, file_name, error_message, timestamp)):
            return None
        return {
            'page_id': page_id,
            'file_name': file_name,
            'error_message': error_message,
            'timestamp': timestamp,
        }

    def set_home_last_import_failure(self, page_id, file_name, error_message, timestamp=''):
        payload = {
            'page_id': str(page_id or '').strip(),
            'file_name': str(file_name or '').strip(),
            'error_message': str(error_message or '').strip()[:240],
            'timestamp': str(timestamp or '').strip() or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        self.set_setting('home_last_import_failure', payload)

    def clear_home_last_import_failure(self):
        self.set_setting('home_last_import_failure', None)

    def get_usage_pricing_rules(self):
        from modules.usage_stats import normalize_pricing_rules

        return normalize_pricing_rules(self.get_setting('usage_pricing_rules', []))

    def set_usage_pricing_rules(self, rules):
        from modules.usage_stats import normalize_pricing_rules

        self.set_setting('usage_pricing_rules', normalize_pricing_rules(rules))

    def ensure_prompt_center_seeded(self, scene_payloads):
        prompt_center = self._sanitize_prompt_center(self._data.get('prompt_center', {}))
        if prompt_center.get('seeded'):
            self._data['prompt_center'] = prompt_center
            return False

        prompt_center['scenes'] = {
            scene_id: self._sanitize_prompt_scene(copy.deepcopy(scene))
            for scene_id, scene in (scene_payloads or {}).items()
        }
        prompt_center['seeded'] = True
        self._data['prompt_center'] = prompt_center
        return True

    def sync_prompt_scene_defaults(self, scene_payloads, scene_ids=None):
        prompt_center = self._sanitize_prompt_center(self._data.get('prompt_center', {}))
        scenes = prompt_center.setdefault('scenes', {})
        target_scene_ids = tuple(scene_ids or tuple((scene_payloads or {}).keys()))
        changed = False

        for scene_id in target_scene_ids:
            default_scene = (scene_payloads or {}).get(scene_id)
            if not isinstance(default_scene, dict):
                continue

            sanitized_default_scene = self._sanitize_prompt_scene(copy.deepcopy(default_scene))
            default_prompts = sanitized_default_scene.get('prompts', [])
            if not default_prompts:
                continue

            default_system_prompt = copy.deepcopy(default_prompts[0])
            system_prompt_id = default_system_prompt.get('id', '')
            if not system_prompt_id:
                continue

            current_scene = self._sanitize_prompt_scene(scenes.get(scene_id, {}))
            current_prompts = current_scene.get('prompts', [])
            merged_prompts = []
            replaced_system_prompt = False

            for prompt in current_prompts:
                if prompt.get('id') != system_prompt_id:
                    merged_prompts.append(copy.deepcopy(prompt))
                    continue

                replaced_system_prompt = True
                synced_system_prompt = copy.deepcopy(default_system_prompt)
                synced_system_prompt['created_at'] = prompt.get('created_at', synced_system_prompt.get('created_at', 0))
                synced_system_prompt['updated_at'] = prompt.get('updated_at', synced_system_prompt.get('updated_at', 0))
                merged_prompts.append(synced_system_prompt)
                if synced_system_prompt != prompt:
                    changed = True

            if not replaced_system_prompt:
                merged_prompts.insert(0, default_system_prompt)
                changed = True

            active_prompt_id = current_scene.get('active_prompt_id', '')
            prompt_ids = {prompt.get('id') for prompt in merged_prompts if isinstance(prompt, dict)}
            if active_prompt_id not in prompt_ids:
                fallback_active_id = sanitized_default_scene.get('active_prompt_id', system_prompt_id)
                if active_prompt_id != fallback_active_id:
                    changed = True
                active_prompt_id = fallback_active_id

            synced_scene = self._sanitize_prompt_scene(
                {
                    'active_prompt_id': active_prompt_id,
                    'prompts': merged_prompts,
                }
            )
            if synced_scene != current_scene:
                changed = True
            scenes[scene_id] = synced_scene

        prompt_center['scenes'] = scenes
        self._data['prompt_center'] = prompt_center
        return changed

    def get_all_prompt_scenes(self):
        prompt_center = self._sanitize_prompt_center(self._data.get('prompt_center', {}))
        self._data['prompt_center'] = prompt_center
        return copy.deepcopy(prompt_center.get('scenes', {}))

    def get_prompt_scene(self, scene_id):
        prompt_center = self._sanitize_prompt_center(self._data.get('prompt_center', {}))
        self._data['prompt_center'] = prompt_center
        scene = prompt_center.get('scenes', {}).get(scene_id, {'active_prompt_id': '', 'prompts': []})
        return copy.deepcopy(scene)

    def set_prompt_scene(self, scene_id, scene_data):
        prompt_center = self._sanitize_prompt_center(self._data.get('prompt_center', {}))
        prompt_center.setdefault('scenes', {})[scene_id] = self._sanitize_prompt_scene(scene_data)
        self._data['prompt_center'] = prompt_center

    def set_active_prompt(self, scene_id, prompt_id):
        scene = self.get_prompt_scene(scene_id)
        prompt_ids = {prompt.get('id') for prompt in scene.get('prompts', [])}
        if prompt_id not in prompt_ids:
            return
        scene['active_prompt_id'] = prompt_id
        self.set_prompt_scene(scene_id, scene)

    def delete_prompt(self, scene_id, prompt_id):
        scene = self.get_prompt_scene(scene_id)
        prompts = [prompt for prompt in scene.get('prompts', []) if prompt.get('id') != prompt_id]
        active_prompt_id = scene.get('active_prompt_id', '')
        if active_prompt_id == prompt_id:
            active_prompt_id = prompts[0]['id'] if prompts else ''
        self.set_prompt_scene(
            scene_id,
            {
                'active_prompt_id': active_prompt_id,
                'prompts': prompts,
            },
        )
