#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验纸研社技能仓库元数据和发布包。"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SKILLS_SRC = ROOT / 'skills_src'
SKILLS_DIR = ROOT / 'skills'
INDEX_PATH = ROOT / 'skills_index.json'

REQUIRED_INDEX_FIELDS = (
    'id',
    'name',
    'version',
    'description',
    'min_app_version',
    'download_url',
)
REQUIRED_MANIFEST_FIELDS = (
    'id',
    'name',
    'version',
    'description',
    'min_app_version',
    'entry',
)


def _load_json(path: Path):
    try:
        with path.open('r', encoding='utf-8') as handle:
            return json.load(handle)
    except Exception as exc:
        raise ValueError(f'{path}: JSON 读取失败：{exc}') from exc


def _non_empty(data, field):
    return str((data or {}).get(field, '') or '').strip()


def _validate_required(data, fields, label, errors):
    for field in fields:
        if not _non_empty(data, field):
            errors.append(f'{label}: 缺少必填字段 {field}')


def _validate_manifest(manifest, label, errors):
    if not isinstance(manifest, dict):
        errors.append(f'{label}: skill.json 必须是对象')
        return
    _validate_required(manifest, REQUIRED_MANIFEST_FIELDS, label, errors)
    entry = manifest.get('entry')
    if not isinstance(entry, dict):
        errors.append(f'{label}: entry 必须是对象')
    else:
        if not _non_empty(entry, 'module'):
            errors.append(f'{label}: entry.module 不能为空')
        if not _non_empty(entry, 'class'):
            errors.append(f'{label}: entry.class 不能为空')


def _validate_source_dirs(errors):
    if not SKILLS_SRC.is_dir():
        errors.append(f'{SKILLS_SRC}: 目录不存在')
        return {}
    manifests = {}
    for skill_dir in sorted(path for path in SKILLS_SRC.iterdir() if path.is_dir()):
        manifest_path = skill_dir / 'skill.json'
        if not manifest_path.is_file():
            errors.append(f'{skill_dir}: 缺少 skill.json')
            continue
        try:
            manifest = _load_json(manifest_path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        _validate_manifest(manifest, str(manifest_path), errors)
        skill_id = _non_empty(manifest, 'id')
        if skill_id:
            manifests[skill_id] = manifest
    return manifests


def _validate_index(source_manifests, errors):
    if not INDEX_PATH.is_file():
        errors.append(f'{INDEX_PATH}: 文件不存在')
        return {}
    try:
        payload = _load_json(INDEX_PATH)
    except ValueError as exc:
        errors.append(str(exc))
        return {}
    items = payload.get('skills')
    if not isinstance(items, list):
        errors.append(f'{INDEX_PATH}: skills 必须是数组')
        return {}

    indexed = {}
    seen = set()
    for index, item in enumerate(items):
        label = f'{INDEX_PATH}: skills[{index}]'
        if not isinstance(item, dict):
            errors.append(f'{label}: 条目必须是对象')
            continue
        _validate_required(item, REQUIRED_INDEX_FIELDS, label, errors)
        skill_id = _non_empty(item, 'id')
        if not skill_id:
            continue
        if skill_id in seen:
            errors.append(f'{label}: 重复 id {skill_id}')
        seen.add(skill_id)
        indexed[skill_id] = item
        manifest = source_manifests.get(skill_id)
        if manifest:
            for field in ('name', 'version', 'description', 'min_app_version'):
                if _non_empty(item, field) != _non_empty(manifest, field):
                    errors.append(f'{label}: {field} 与 skills_src/{skill_id}/skill.json 不一致')
    return indexed


def _validate_zip_packages(source_manifests, indexed, errors):
    if not SKILLS_DIR.is_dir():
        errors.append(f'{SKILLS_DIR}: 目录不存在')
        return
    for skill_id, manifest in sorted(source_manifests.items()):
        zip_path = SKILLS_DIR / f'{skill_id}.zip'
        if skill_id in indexed and not zip_path.is_file():
            errors.append(f'{zip_path}: 索引已发布但 ZIP 不存在')
            continue
        if not zip_path.is_file():
            continue
        try:
            with zipfile.ZipFile(zip_path) as archive:
                skill_json_paths = [name for name in archive.namelist() if name.endswith('/skill.json') or name == 'skill.json']
                if len(skill_json_paths) != 1:
                    errors.append(f'{zip_path}: 应包含且仅包含一个 skill.json')
                    continue
                package_manifest = json.loads(archive.read(skill_json_paths[0]).decode('utf-8'))
        except Exception as exc:
            errors.append(f'{zip_path}: ZIP 读取失败：{exc}')
            continue
        _validate_manifest(package_manifest, str(zip_path), errors)
        if _non_empty(package_manifest, 'id') != skill_id:
            errors.append(f'{zip_path}: skill.json id 与文件名不一致')
        for field in ('name', 'version', 'description', 'min_app_version'):
            if _non_empty(package_manifest, field) != _non_empty(manifest, field):
                errors.append(f'{zip_path}: {field} 与源码 skill.json 不一致')


def main():
    errors = []
    source_manifests = _validate_source_dirs(errors)
    indexed = _validate_index(source_manifests, errors)
    _validate_zip_packages(source_manifests, indexed, errors)

    if errors:
        print('技能仓库校验失败：')
        for error in errors:
            print(f'- {error}')
        return 1
    print(f'技能仓库校验通过：{len(source_manifests)} 个源码技能，{len(indexed)} 个索引技能。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
