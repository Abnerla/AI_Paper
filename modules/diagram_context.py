# -*- coding: utf-8 -*-
"""
AI 图表资料输入工具。

只提取可直接传入文本模型的内容；图片文件仅记录为附件说明，不作为多模态输入。
"""

from __future__ import annotations

import html
import ipaddress
import base64
import mimetypes
import os
import re
import socket
import urllib.parse
import urllib.request
from html.parser import HTMLParser


MAX_REFERENCE_CHARS = 12000
MAX_REFERENCE_ITEMS = 5
MAX_URL_BYTES = 1024 * 1024
MAX_IMAGE_ATTACHMENT_BYTES = 2 * 1024 * 1024
TEXT_EXTENSIONS = {'.txt', '.md', '.markdown', '.json', '.csv', '.xml'}
PDF_EXTENSIONS = {'.pdf'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff'}


class DiagramReferenceError(ValueError):
    """图表资料读取失败。"""


def sanitize_reference_items(items, *, max_items=MAX_REFERENCE_ITEMS, max_chars=MAX_REFERENCE_CHARS):
    cleaned = []
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or '').strip()[:120]
        source = str(item.get('source') or '').strip()[:500]
        kind = str(item.get('kind') or 'text').strip()[:40]
        content = str(item.get('content') or '').strip()
        warning = str(item.get('warning') or '').strip()[:300]
        mime_type = str(item.get('mime_type') or '').strip()[:120]
        size_bytes = _safe_int(item.get('size_bytes'))
        if not any((title, source, content, warning)):
            continue
        record = {
            'title': title or source or '未命名资料',
            'source': source,
            'kind': kind or 'text',
            'content': content[:max_chars],
            'warning': warning,
            'truncated': bool(item.get('truncated')) or len(content) > max_chars,
        }
        if mime_type:
            record['mime_type'] = mime_type
        if size_bytes:
            record['size_bytes'] = size_bytes
        cleaned.append(record)
        if len(cleaned) >= max_items:
            break
    return cleaned


def read_reference_file(path, *, max_chars=MAX_REFERENCE_CHARS):
    full_path = os.path.abspath(os.path.expanduser(str(path or '').strip()))
    if not full_path or not os.path.exists(full_path):
        raise DiagramReferenceError('资料文件不存在。')
    if not os.path.isfile(full_path):
        raise DiagramReferenceError('只能导入文件，不能导入文件夹。')

    ext = os.path.splitext(full_path)[1].lower()
    title = os.path.basename(full_path)
    if ext in TEXT_EXTENSIONS:
        content = _read_text_file(full_path)
        return _build_reference(title, full_path, ext.lstrip('.') or 'text', content, max_chars=max_chars)
    if ext in PDF_EXTENSIONS:
        content = _read_pdf_text(full_path)
        return _build_reference(title, full_path, 'pdf', content, max_chars=max_chars)
    if ext in IMAGE_EXTENSIONS:
        try:
            size_bytes = os.path.getsize(full_path)
        except OSError:
            size_bytes = 0
        if size_bytes > MAX_IMAGE_ATTACHMENT_BYTES:
            limit_mb = MAX_IMAGE_ATTACHMENT_BYTES // (1024 * 1024)
            raise DiagramReferenceError(f'图片资料超过 {limit_mb}MB 限制。')
        mime_type = mimetypes.guess_type(full_path)[0] or _mime_type_for_image_ext(ext)
        return {
            'title': title,
            'source': full_path,
            'kind': 'image',
            'mime_type': mime_type,
            'size_bytes': size_bytes,
            'content': '',
            'warning': '图片文件已记录；支持多模态的模型会把该图片作为视觉输入。',
            'truncated': False,
        }
    supported = ', '.join(sorted(TEXT_EXTENSIONS | PDF_EXTENSIONS | IMAGE_EXTENSIONS))
    raise DiagramReferenceError(f'不支持的资料类型：{ext or "无扩展名"}。支持类型：{supported}')


def read_reference_url(url, *, max_chars=MAX_REFERENCE_CHARS, timeout=10, resolver=None):
    normalized = validate_reference_url(url, resolver=resolver)
    request = urllib.request.Request(
        normalized,
        headers={'User-Agent': 'AI-paper-diagram-reference/1.0'},
        method='GET',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_URL_BYTES + 1)
            content_type = response.headers.get('Content-Type', '')
    except Exception as exc:
        raise DiagramReferenceError(f'URL 读取失败：{exc}') from exc

    if len(raw) > MAX_URL_BYTES:
        raw = raw[:MAX_URL_BYTES]
    encoding = _detect_encoding(content_type)
    text = raw.decode(encoding, errors='replace')
    if 'html' in content_type.lower() or _looks_like_html(text):
        text = extract_html_text(text)
    title = urllib.parse.urlsplit(normalized).netloc or normalized
    return _build_reference(title, normalized, 'url', text, max_chars=max_chars)


def validate_reference_url(url, *, resolver=None):
    text = str(url or '').strip()
    if not text:
        raise DiagramReferenceError('URL 不能为空。')
    parts = urllib.parse.urlsplit(text)
    if parts.scheme not in {'http', 'https'}:
        raise DiagramReferenceError('URL 只支持 http 或 https。')
    host = parts.hostname
    if not host:
        raise DiagramReferenceError('URL 缺少主机名。')
    _assert_public_host(host, resolver=resolver)
    return urllib.parse.urlunsplit(parts)


def format_reference_context(items, *, max_chars=24000):
    cleaned = sanitize_reference_items(items)
    sections = []
    total = 0
    for index, item in enumerate(cleaned, start=1):
        content = str(item.get('content') or '').strip()
        warning = str(item.get('warning') or '').strip()
        if not content and not warning:
            continue
        body = content or warning
        head = f'资料 {index}：{item.get("title") or "未命名资料"}'
        if item.get('source'):
            head += f'\n来源：{item["source"]}'
        if item.get('warning'):
            head += f'\n说明：{item["warning"]}'
        chunk = f'{head}\n{body}'
        remaining = max_chars - total
        if remaining <= 0:
            break
        if len(chunk) > remaining:
            chunk = chunk[:remaining] + '\n……资料内容已截断。'
        sections.append(chunk)
        total += len(chunk)
    return '\n\n'.join(sections)


def build_image_attachments(items, *, max_items=MAX_REFERENCE_ITEMS, max_bytes=MAX_IMAGE_ATTACHMENT_BYTES):
    """把图片资料转换为 APIClient 可消费的轻量多模态附件。"""
    attachments = []
    for item in sanitize_reference_items(items):
        if item.get('kind') != 'image':
            continue
        source = str(item.get('source') or '').strip()
        if not source:
            continue
        try:
            full_path = os.path.abspath(os.path.expanduser(source))
            size_bytes = os.path.getsize(full_path)
        except OSError:
            continue
        if size_bytes <= 0 or size_bytes > max_bytes:
            continue
        ext = os.path.splitext(full_path)[1].lower()
        mime_type = str(item.get('mime_type') or '').strip() or mimetypes.guess_type(full_path)[0] or _mime_type_for_image_ext(ext)
        if not mime_type.startswith('image/'):
            continue
        try:
            with open(full_path, 'rb') as handle:
                raw = handle.read(max_bytes + 1)
        except OSError:
            continue
        if len(raw) > max_bytes:
            continue
        attachments.append({
            'type': 'image',
            'title': item.get('title') or os.path.basename(full_path),
            'source': full_path,
            'mime_type': mime_type,
            'data': base64.b64encode(raw).decode('ascii'),
            'size_bytes': len(raw),
        })
        if len(attachments) >= max_items:
            break
    return attachments


def _build_reference(title, source, kind, content, *, max_chars):
    text = str(content or '').strip()
    if not text:
        raise DiagramReferenceError('资料中没有可提取的文本。')
    return {
        'title': str(title or '').strip() or '未命名资料',
        'source': str(source or '').strip(),
        'kind': kind,
        'content': text[:max_chars],
        'warning': '',
        'truncated': len(text) > max_chars,
    }


def _read_text_file(path):
    raw = open(path, 'rb').read()
    for encoding in ('utf-8-sig', 'utf-8', 'gb18030'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def _read_pdf_text(path):
    try:
        import fitz
    except ImportError as exc:
        raise DiagramReferenceError('读取 PDF 需要 PyMuPDF。') from exc
    pages = []
    try:
        with fitz.open(path) as doc:
            for page in doc:
                pages.append(page.get_text('text') or '')
    except Exception as exc:
        raise DiagramReferenceError(f'PDF 读取失败：{exc}') from exc
    return '\n'.join(pages)


def _mime_type_for_image_ext(ext):
    return {
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.webp': 'image/webp',
        '.gif': 'image/gif',
        '.bmp': 'image/bmp',
        '.tif': 'image/tiff',
        '.tiff': 'image/tiff',
    }.get(str(ext or '').lower(), 'image/png')


def _safe_int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _assert_public_host(host, *, resolver=None):
    host_text = str(host or '').strip().strip('[]').lower()
    if host_text in {'localhost'} or host_text.endswith('.localhost'):
        raise DiagramReferenceError('URL 指向本机地址，已阻止。')

    addresses = []
    try:
        addresses.append(ipaddress.ip_address(host_text))
    except ValueError:
        resolver = resolver or socket.getaddrinfo
        try:
            infos = resolver(host_text, None)
        except OSError as exc:
            raise DiagramReferenceError(f'URL 主机解析失败：{exc}') from exc
        for info in infos:
            sockaddr = info[4]
            if sockaddr:
                try:
                    addresses.append(ipaddress.ip_address(sockaddr[0]))
                except ValueError:
                    continue

    if not addresses:
        raise DiagramReferenceError('URL 主机没有可用地址。')
    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise DiagramReferenceError('URL 指向本机、内网或保留地址，已阻止。')


def _detect_encoding(content_type):
    match = re.search(r'charset=([\w.-]+)', str(content_type or ''), re.I)
    return match.group(1) if match else 'utf-8'


def _looks_like_html(text):
    sample = str(text or '')[:500].lower()
    return '<html' in sample or '<body' in sample or '<!doctype html' in sample


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'noscript'}:
            self._skip = True

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'noscript'}:
            self._skip = False
        if tag in {'p', 'div', 'section', 'article', 'br', 'li', 'tr', 'h1', 'h2', 'h3'}:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self._skip:
            value = html.unescape(data or '').strip()
            if value:
                self.parts.append(value)

    def text(self):
        return re.sub(r'\n{3,}', '\n\n', re.sub(r'[ \t]{2,}', ' ', '\n'.join(self.parts))).strip()


def extract_html_text(text):
    parser = _TextExtractor()
    try:
        parser.feed(text or '')
        return parser.text()
    except Exception:
        return re.sub(r'<[^>]+>', ' ', text or '')
