// 图表编辑器前端控制器（P3.A）
// - 加载 block 数据
// - 优先用本地 mermaid（如有 ./mermaid/mermaid.esm.min.mjs），否则降级 CDN，再不行降为占位
// - drawio 视图按钮预留，离线包就位后启用

const KIND_OPTIONS = [
  ['flowchart', '流程图 flowchart'],
  ['sequence', '时序图 sequence'],
  ['classDiagram', '类图 classDiagram'],
  ['stateDiagram', '状态图 stateDiagram'],
  ['erDiagram', 'ER 图 erDiagram'],
  ['mindmap', '思维导图 mindmap'],
  ['gantt', '甘特图 gantt'],
  ['journey', '用户旅程 journey'],
  ['pie', '饼图 pie'],
  ['quadrant', '象限图 quadrant'],
  ['timeline', '时间线 timeline'],
  ['c4', 'C4 架构图 c4'],
  ['freeform', '自由形式 freeform'],
];

const $ = (id) => document.getElementById(id);
const $caption = $('caption');
const $kind = $('kind');
const $mermaid = $('mermaid');
const $preview = $('preview');
const $status = $('status');
const $parseInfo = $('parseInfo');
const $btnSave = $('btnSave');
const $btnCancel = $('btnCancel');
const $btnDrawio = $('btnDrawio');
const $drawioFrame = $('drawioFrame');
const $rightPaneTitle = $('rightPaneTitle');
const $body = document.querySelector('.body');
const DRAWIO_URL = 'drawio/index.html?embed=1&proto=json&lang=zh&splash=0&noSaveBtn=1&libraries=1&offline=1&local=1&stealth=1&gapi=0&db=0&od=0&tr=0&gh=0&gl=0&ms365=0&picker=0';

let currentBlock = null;
let mermaidApi = null;
let renderTimer = null;
let dirty = false;
let drawioReady = false;
let drawioAvailable = false;
let drawioActive = false;     // 当前是否切到 drawio 视图
let drawioCurrentXml = '';
let pendingExport = null;     // {resolve, reject} 缩略图 export 请求
let exportRequest = null;     // 导出模式请求

function setStatus(text) {
  $status.textContent = text || '';
}

function buildKindOptions() {
  for (const [value, label] of KIND_OPTIONS) {
    const opt = document.createElement('option');
    opt.value = value; opt.textContent = label;
    $kind.appendChild(opt);
  }
}

async function loadMermaid() {
  // 1) 本地 UMD（mermaid/mermaid.min.js 已通过 <script> 挂载到 window.mermaid）
  if (window.mermaid) {
    setStatus('已加载本地 mermaid');
    return window.mermaid;
  }
  // 2) CDN 兜底（动态注入 <script>）
  try {
    await new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js';
      s.onload = resolve; s.onerror = reject;
      document.head.appendChild(s);
    });
    if (window.mermaid) {
      setStatus('已加载 mermaid (CDN)');
      return window.mermaid;
    }
  } catch (_) { /* fallthrough */ }
  setStatus('mermaid 不可用，仅展示文本');
  return null;
}

async function initMermaid() {
  const m = await loadMermaid();
  if (!m) return null;
  m.initialize({ startOnLoad: false, securityLevel: 'strict', theme: 'default' });
  return m;
}

function scheduleRender() {
  if (renderTimer) clearTimeout(renderTimer);
  renderTimer = setTimeout(renderPreview, 300);
}

async function renderPreview() {
  const text = $mermaid.value.trim();
  if (!text) {
    $preview.innerHTML = '<div class="placeholder">请输入 Mermaid 源代码</div>';
    $parseInfo.textContent = '';
    return;
  }
  if (!mermaidApi) {
    $preview.innerHTML = '<div class="placeholder">mermaid 未就绪</div>';
    return;
  }
  try {
    const id = 'mmd_' + Date.now();
    const { svg } = await mermaidApi.render(id, text);
    $preview.innerHTML = svg;
    $parseInfo.textContent = '解析成功';
  } catch (exc) {
    const msg = (exc && exc.message) ? exc.message : String(exc);
    $preview.innerHTML = '<div class="error">' + escapeHtml(msg) + '</div>';
    $parseInfo.textContent = '语法错误，无法渲染';
  }
}

function escapeHtml(text) {
  return String(text || '').replace(/[&<>"']/g, (ch) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}

async function getThumbnailDataUri() {
  const svg = $preview.querySelector('svg');
  if (!svg) return '';
  try {
    const xml = new XMLSerializer().serializeToString(svg);
    const blob = new Blob([xml], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const img = await new Promise((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = reject;
      i.src = url;
    });
    const canvas = document.createElement('canvas');
    const targetW = 480;
    const ratio = (img.height || 1) / (img.width || 1);
    canvas.width = targetW; canvas.height = Math.round(targetW * ratio) || 300;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    URL.revokeObjectURL(url);
    return canvas.toDataURL('image/png');
  } catch (_) {
    return '';
  }
}

async function loadInitial() {
  const api = window.pywebview && window.pywebview.api;
  if (!api) {
    setStatus('JS Bridge 未就绪');
    return;
  }
  const payload = await api.load_diagram();
  const block = (payload && payload.block) || {};
  const mode = (payload && payload.mode) || 'edit';
  currentBlock = block;
  $caption.value = block.caption || '';
  setKind(block.diagram_kind || 'flowchart');
  $mermaid.value = block.mermaid || '';
  drawioCurrentXml = block.mxgraph_xml || '';

  const caps = (payload && payload.capabilities) || {};
  drawioAvailable = !!caps.drawio;
  if (mode === 'export') {
    exportRequest = {
      format: (payload && payload.export_format) || 'png',
      started: false,
    };
  }
  if (drawioAvailable) {
    $btnDrawio.disabled = false;
    $btnDrawio.title = '在 Mermaid 与 draw.io 视图之间切换';
  } else {
    $btnDrawio.title = 'drawio 离线包未就位，仍可使用 mermaid 视图';
  }

  await renderPreview();
  if (exportRequest && drawioAvailable) {
    await switchToDrawio();
  } else if (drawioAvailable && drawioCurrentXml && !$mermaid.value.trim()) {
    await switchToDrawio();
  }
}

function setKind(kind) {
  for (const opt of $kind.options) {
    if (opt.value === kind) { $kind.value = kind; return; }
  }
  $kind.value = 'flowchart';
}

function markDirty() { dirty = true; }

async function saveAndClose() {
  const api = window.pywebview && window.pywebview.api;
  if (!api) return;
  $btnSave.disabled = true;
  setStatus('保存中...');
  let thumb = '';
  const payload = {
    caption: $caption.value.trim(),
    diagram_kind: $kind.value,
    mermaid: $mermaid.value,
    authoring_format: drawioActive || drawioCurrentXml ? 'drawio' : 'mermaid',
  };
  if (drawioActive || drawioCurrentXml) {
    payload.mxgraph_xml = drawioCurrentXml || '';
    if (drawioActive) {
      try { thumb = await exportDrawioThumbnail(); } catch (_) { thumb = ''; }
    }
  } else {
    try { thumb = await getThumbnailDataUri(); } catch (_) { thumb = ''; }
  }
  if (thumb) payload.thumbnail_b64 = thumb;
  try {
    const result = await api.save_diagram(payload);
    if (result && result.ok) {
      setStatus('已保存');
      await api.close_window();
    } else {
      setStatus('保存失败：' + ((result && result.error) || '未知错误'));
      $btnSave.disabled = false;
    }
  } catch (exc) {
    setStatus('保存异常：' + (exc.message || exc));
    $btnSave.disabled = false;
  }
}

async function cancelEdit() {
  const api = window.pywebview && window.pywebview.api;
  if (dirty) {
    if (!window.confirm('当前修改尚未保存，确定要关闭吗？')) return;
  }
  if (api) await api.close_window();
}

function bindEvents() {
  $mermaid.addEventListener('input', () => { markDirty(); scheduleRender(); });
  $caption.addEventListener('input', markDirty);
  $kind.addEventListener('change', markDirty);
  $btnSave.addEventListener('click', saveAndClose);
  $btnCancel.addEventListener('click', cancelEdit);
  $btnDrawio.addEventListener('click', toggleDrawioView);
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); saveAndClose(); }
    if (e.key === 'Escape') { e.preventDefault(); cancelEdit(); }
  });
  window.addEventListener('message', handleDrawioMessage);
}

async function toggleDrawioView() {
  if (!drawioAvailable) {
    window.alert('drawio 离线包未就位。请把 drawio 解压到 Management/web_assets/drawio/ 后重启程序。');
    return;
  }
  if (!drawioActive) {
    await switchToDrawio();
  } else {
    await switchToMermaid();
  }
}

async function switchToDrawio() {
  // 先把当前 mermaid 转换为 mxgraph XML（让 Python 端做转换）
  const api = window.pywebview && window.pywebview.api;
  let xml = drawioCurrentXml;
  if (!xml && api && api.mermaid_to_mxgraph) {
    try {
      const text = $mermaid.value || '';
      const res = await api.mermaid_to_mxgraph(text);
      if (res && res.ok) xml = res.xml || '';
    } catch (_) { /* ignore */ }
  }
  drawioCurrentXml = xml || drawioCurrentXml;

  // 加载 drawio iframe（embed 模式）
  if ($drawioFrame.src === 'about:blank' || $drawioFrame.src.endsWith('about:blank')) {
    $drawioFrame.src = DRAWIO_URL;
  }
  $preview.classList.add('hidden');
  $drawioFrame.classList.remove('hidden');
  $body.classList.add('drawio-mode');
  $rightPaneTitle.textContent = 'draw.io 视图';
  $btnDrawio.textContent = 'Mermaid';
  drawioActive = true;
  setStatus('draw.io 视图');
}

async function switchToMermaid() {
  $preview.classList.remove('hidden');
  $drawioFrame.classList.add('hidden');
  $body.classList.remove('drawio-mode');
  $rightPaneTitle.textContent = '实时预览';
  $btnDrawio.textContent = 'draw.io 视图';
  drawioActive = false;
  setStatus('mermaid 视图');
  await renderPreview();
}

function handleDrawioMessage(event) {
  // drawio embed 协议发来的 JSON 消息
  let msg = event.data;
  if (typeof msg === 'string') {
    try { msg = JSON.parse(msg); } catch (_) { return; }
  }
  if (!msg || typeof msg !== 'object') return;
  const evt = msg.event;
  if (evt === 'init') {
    // drawio 就绪，推入当前 XML
    drawioReady = true;
    drawioCurrentXml = sanitizeMxgraphForDrawio(drawioCurrentXml || _emptyMxgraph());
    sendToDrawio({ action: 'load', xml: drawioCurrentXml, autosave: 1 });
    if (exportRequest && !exportRequest.started) {
      exportRequest.started = true;
      setTimeout(runExportRequest, 600);
    }
  } else if (evt === 'autosave' || evt === 'save') {
    if (msg.xml) {
      drawioCurrentXml = msg.xml;
      markDirty();
    }
  } else if (evt === 'export' && msg.data) {
    if (pendingExport) {
      pendingExport.resolve(msg.data);
      pendingExport = null;
    }
  }
}

function sendToDrawio(payload) {
  if (!$drawioFrame.contentWindow) return;
  try {
    $drawioFrame.contentWindow.postMessage(JSON.stringify(payload), '*');
  } catch (_) { /* ignore */ }
}

function _emptyMxgraph() {
  return '<mxGraphModel dx="1024" dy="768" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1024" pageHeight="768" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>';
}

function sanitizeMxgraphForDrawio(xml) {
  const fallback = _emptyMxgraph();
  const text = String(xml || '').trim();
  if (!text) return fallback;
  try {
    const doc = new DOMParser().parseFromString(text, 'text/xml');
    if (doc.querySelector('parsererror')) return fallback;
    const model = doc.documentElement && doc.documentElement.tagName === 'mxGraphModel'
      ? doc.documentElement
      : doc.querySelector('mxGraphModel');
    if (!model) return fallback;
    let root = model.querySelector('root');
    if (!root) {
      root = doc.createElement('root');
      model.appendChild(root);
    }
    ensureRootCell(doc, root, '0', null);
    ensureRootCell(doc, root, '1', '0');

    const cells = directChildrenByTag(root, 'mxCell');
    const ids = new Set(cells.map((cell) => cell.getAttribute('id')).filter(Boolean));
    let vertexIndex = 0;

    for (const cell of cells) {
      const id = cell.getAttribute('id');
      if (!id) {
        root.removeChild(cell);
        continue;
      }
      if (id === '0' || id === '1') continue;

      const isVertex = cell.getAttribute('vertex') === '1';
      const isEdge = cell.getAttribute('edge') === '1';
      if (isVertex) {
        ensureVertexGeometry(doc, cell, vertexIndex++);
      } else if (isEdge) {
        const source = cell.getAttribute('source');
        const target = cell.getAttribute('target');
        if (!source || !target || !ids.has(source) || !ids.has(target)) {
          root.removeChild(cell);
          continue;
        }
        ensureEdgeGeometry(doc, cell);
      }
    }
    return new XMLSerializer().serializeToString(model);
  } catch (_) {
    return fallback;
  }
}

function ensureRootCell(doc, root, id, parent) {
  let cell = directChildrenByTag(root, 'mxCell').find((item) => item.getAttribute('id') === id);
  if (!cell) {
    cell = doc.createElement('mxCell');
    cell.setAttribute('id', id);
    root.insertBefore(cell, root.firstChild);
  }
  if (parent) cell.setAttribute('parent', parent);
}

function ensureVertexGeometry(doc, cell, index) {
  let geometry = directChildrenByTag(cell, 'mxGeometry')[0];
  if (!geometry) {
    geometry = doc.createElement('mxGeometry');
    cell.appendChild(geometry);
  }
  geometry.setAttribute('as', 'geometry');
  const defaults = {
    x: 80 + (index % 4) * 180,
    y: 80 + Math.floor(index / 4) * 120,
    width: 120,
    height: 60,
  };
  for (const [key, value] of Object.entries(defaults)) {
    const current = geometry.getAttribute(key);
    if (current === null || current === '' || Number.isNaN(Number(current))) {
      geometry.setAttribute(key, String(value));
    }
  }
}

function ensureEdgeGeometry(doc, cell) {
  let geometry = directChildrenByTag(cell, 'mxGeometry')[0];
  if (!geometry) {
    geometry = doc.createElement('mxGeometry');
    cell.appendChild(geometry);
  }
  geometry.setAttribute('relative', '1');
  geometry.setAttribute('as', 'geometry');
  for (const point of Array.from(geometry.querySelectorAll('mxPoint'))) {
    const x = point.getAttribute('x');
    const y = point.getAttribute('y');
    if (x === null || y === null || Number.isNaN(Number(x)) || Number.isNaN(Number(y))) {
      point.parentNode.removeChild(point);
    }
  }
}

function directChildrenByTag(parent, tagName) {
  return Array.from(parent.childNodes || []).filter((node) => node.nodeType === 1 && node.tagName === tagName);
}

async function exportDrawioThumbnail() {
  if (!drawioActive || !drawioReady) return '';
  return await exportDrawioData('xmlpng', 5000);
}

async function exportDrawioData(format, timeoutMs) {
  if (!drawioActive || !drawioReady) return '';
  const promise = new Promise((resolve, reject) => {
    pendingExport = { resolve, reject };
    setTimeout(() => {
      if (pendingExport) {
        pendingExport = null;
        reject(new Error('drawio export timeout'));
      }
    }, timeoutMs || 8000);
  });
  sendToDrawio({ action: 'export', format: format || 'png', spinKey: 'export' });
  try { return await promise; } catch (_) { return ''; }
}

async function runExportRequest() {
  const api = window.pywebview && window.pywebview.api;
  if (!api || !exportRequest) return;
  setStatus('正在导出 draw.io 原生图像...');
  const target = exportRequest.format || 'png';
  const drawioFormat = target === 'drawio.svg' ? 'xmlsvg' : target;
  const data = await exportDrawioData(drawioFormat, 12000);
  if (!data) {
    setStatus('draw.io 原生导出失败');
    await api.close_window();
    return;
  }
  const result = await api.save_export({
    format: target,
    data,
    mime_type: target === 'png' ? 'image/png' : 'image/svg+xml',
  });
  if (result && result.ok) {
    setStatus('导出完成');
  } else {
    setStatus('导出保存失败：' + ((result && result.error) || '未知错误'));
  }
  await api.close_window();
}

(async function bootstrap() {
  buildKindOptions();
  bindEvents();
  // pywebview 把 api 注入到 window.pywebview 后才会触发 pywebviewready；做兼容轮询
  if (window.pywebview && window.pywebview.api) {
    mermaidApi = await initMermaid();
    await loadInitial();
  } else {
    window.addEventListener('pywebviewready', async () => {
      mermaidApi = await initMermaid();
      await loadInitial();
    });
  }
})();
