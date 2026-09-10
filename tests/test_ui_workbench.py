"""模块化工作台的结构、真实 API 接线与脚本语法看门。"""

from __future__ import annotations

import shutil
import subprocess
import threading
import urllib.request
import re
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


UI_PATH = Path(__file__).resolve().parents[1] / "ui" / "index.html"
CYTOSCAPE_PATH = UI_PATH.parent / "vendor" / "cytoscape.min.js"
LUCIDE_PATH = UI_PATH.parent / "vendor" / "lucide.min.js"
OPEN_PROPS_EASINGS_PATH = UI_PATH.parent / "vendor" / "open-props-easings.min.css"
OPEN_PROPS_SHADOW_PATH = UI_PATH.parent / "vendor" / "open-props-shadow.min.css"
STYLE_PATH = UI_PATH.parent / "styles" / "app.css"
APP_JS_PATH = UI_PATH.parent / "js" / "app.js"
MEMORY_JS_PATH = UI_PATH.parent / "js" / "components" / "project-memory.js"
EVIDENCE_JS_PATH = UI_PATH.parent / "js" / "components" / "evidence.js"
AUTOSAVE_JS_PATH = UI_PATH.parent / "js" / "components" / "autosave.js"
JS_PATHS = (MEMORY_JS_PATH, EVIDENCE_JS_PATH, AUTOSAVE_JS_PATH, APP_JS_PATH)


def _ui_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in (UI_PATH, STYLE_PATH, *JS_PATHS)
    )


def _js_source() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in JS_PATHS
    )


class _IdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(str(values["id"]))


def test_ui_has_no_duplicate_static_ids():
    parser = _IdParser()
    parser.feed(UI_PATH.read_text(encoding="utf-8"))
    duplicates = sorted({value for value in parser.ids if parser.ids.count(value) > 1})
    assert duplicates == []


def test_ui_uses_deep_thesis_brand():
    html = UI_PATH.read_text(encoding="utf-8")
    assert "<title>Deep Thesis — 论文全流程智能体</title>" in html
    assert "thesis-agent-dsh" not in html
    assert "论文写作 Agent" not in html


def test_outline_result_exposes_accessible_section_contract_summary():
    source = APP_JS_PATH.read_text(encoding="utf-8")
    assert 'class="section-contract-summary"' in source
    assert "<summary>查看 " in source
    assert "section_contract" in source
    assert "contract_hash" in source


def test_project_memory_academic_foundation_controls_are_wired():
    html = UI_PATH.read_text(encoding="utf-8")
    memory = MEMORY_JS_PATH.read_text(encoding="utf-8")
    for field_id in (
        "memory-scope-boundaries",
        "memory-forbidden-claims",
        "memory-unresolved-claims",
        "memory-max-rounds",
        "memory-plateau-rounds",
        "memory-min-improvement",
    ):
        assert f'id="{field_id}"' in html
        assert field_id in memory
    for payload_key in (
        "scope_boundaries",
        "forbidden_claims",
        "unresolved_claims",
        "stopping_policy",
        "max_revision_rounds",
        "min_score_improvement",
    ):
        assert payload_key in memory
    assert "invalidStoppingField" in memory
    assert "checkValidity()" in memory
    assert "STOPPING_POLICY_FIELDS" in memory
    assert "validationBound" in memory
    assert 'id="memory-stopping-help"' in html


def test_cytoscape_is_vendored_locally():
    assert CYTOSCAPE_PATH.is_file()
    assert CYTOSCAPE_PATH.stat().st_size > 300_000


def test_visual_dependencies_are_vendored_and_declared():
    assert LUCIDE_PATH.is_file()
    assert LUCIDE_PATH.stat().st_size > 300_000
    assert "lucide v0.469.0 - ISC" in LUCIDE_PATH.read_text(
        encoding="utf-8", errors="ignore"
    )[:500]
    for path in (OPEN_PROPS_EASINGS_PATH, OPEN_PROPS_SHADOW_PATH):
        assert path.is_file()
        assert path.stat().st_size > 1_000
    notices = (UI_PATH.parents[1] / "THIRD_PARTY_NOTICES.md").read_text(
        encoding="utf-8"
    )
    assert "Lucide 0.469.0" in notices
    assert "Open Props" in notices


def test_ui_assets_are_split_and_referenced_locally():
    html = UI_PATH.read_text(encoding="utf-8")
    style_sources = [
        './vendor/open-props-shadow.min.css',
        './vendor/open-props-easings.min.css',
        './styles/app.css',
    ]
    style_positions = [html.index(f'<link rel="stylesheet" href="{source}">')
                       for source in style_sources]
    assert style_positions == sorted(style_positions)
    script_sources = [
        './vendor/cytoscape.min.js',
        './vendor/lucide.min.js',
        './js/components/project-memory.js',
        './js/components/evidence.js',
        './js/components/autosave.js',
        './js/app.js',
    ]
    positions = [html.index(f'<script src="{source}"></script>') for source in script_sources]
    assert positions == sorted(positions)
    assert "<style>" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html)
    for source in (*style_sources, *script_sources):
        target = (UI_PATH.parent / source.removeprefix('./')).resolve()
        assert target.is_relative_to(UI_PATH.parent.resolve())
        assert target.is_file()
    assert "function loadProjectMemoryPanel" not in APP_JS_PATH.read_text(encoding="utf-8")
    assert "window.ThesisProjectMemory.loadPanel" in APP_JS_PATH.read_text(encoding="utf-8")
    assert "window.ThesisProjectMemory = Object.freeze" in MEMORY_JS_PATH.read_text(encoding="utf-8")
    assert "function loadEvidencePanel" not in APP_JS_PATH.read_text(encoding="utf-8")
    assert "function apiTaskSources" not in APP_JS_PATH.read_text(encoding="utf-8")
    assert "function apiEvidenceAudit" not in APP_JS_PATH.read_text(encoding="utf-8")
    assert "window.ThesisEvidence.loadPanel" in APP_JS_PATH.read_text(encoding="utf-8")
    assert "window.ThesisEvidence = Object.freeze" in EVIDENCE_JS_PATH.read_text(encoding="utf-8")
    assert "function loadEvidencePanel" in EVIDENCE_JS_PATH.read_text(encoding="utf-8")
    assert "window.ThesisAutosave = Object.freeze" in AUTOSAVE_JS_PATH.read_text(encoding="utf-8")
    assert "registerDraftSurface" in AUTOSAVE_JS_PATH.read_text(encoding="utf-8")


def test_split_ui_assets_are_served_with_expected_content_types():
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

    handler = lambda *args, **kwargs: QuietHandler(  # noqa: E731
        *args, directory=str(UI_PATH.parent), **kwargs
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        expected = {
            "/": {"text/html"},
            "/styles/app.css": {"text/css"},
            "/js/app.js": {"text/javascript", "application/javascript"},
            "/js/components/project-memory.js": {"text/javascript", "application/javascript"},
            "/js/components/evidence.js": {"text/javascript", "application/javascript"},
            "/js/components/autosave.js": {"text/javascript", "application/javascript"},
            "/vendor/cytoscape.min.js": {"text/javascript", "application/javascript"},
            "/vendor/lucide.min.js": {"text/javascript", "application/javascript"},
            "/vendor/open-props-easings.min.css": {"text/css"},
            "/vendor/open-props-shadow.min.css": {"text/css"},
        }
        for path, content_types in expected.items():
            with urllib.request.urlopen(base + path, timeout=5) as response:
                assert response.status == 200
                assert response.headers.get_content_type() in content_types
                assert response.read(32)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_trust_workbench_is_wired_to_real_endpoints_and_accessible_states():
    html = UI_PATH.read_text(encoding="utf-8")
    javascript = _js_source()
    for fragment in (
        'role="tablist" aria-label="项目工作台"',
        'role="status" aria-live="polite"',
        'id="protocol-form"',
        'id="argument-claim-rows"',
        'id="academic-foundation-list"',
        'id="research-file-input"',
        'id="login-form"',
        'id="session-search"',
        'for="session-search"',
        'id="session-search-status"',
        'id="inference-form"',
        'id="inference-api-key" type="password" autocomplete="off"',
        'id="wb-tab-memory"',
        'id="memory-form"',
        'aria-describedby="memory-help memory-error"',
        './vendor/cytoscape.min.js',
    ):
        assert fragment in html
    for fragment in (
        '/writing/sections/${draftId}/revise',
        '/jobs/${jobId}/cancel',
        '/jobs/${jobId}/retry',
        '/evidence-audit',
        '/academic-foundation',
        '/research/argument-maps',
        '/research/protocols',
        '/research/runs/${runId}/transition',
        '/template/mapping',
        'data-section-action="compare"',
        'computeLineDiff',
        'AbortController',
        'showAccessibleDialog',
        '/api/v1/auth/login',
        '/api/v1/auth/audit',
        'aria-current="true"',
        'bindSessionSearch',
        'resolveSessionSelection',
        'filterSessions',
        'apiSelectCandidate',
        'apiCurateLiterature',
        'epistemic_intent',
        'apiReopenStage',
        'const form = event.currentTarget',
        'Math.min(pollDelay * 1.6, 5000)',
        'data-action="generate-all-sections"',
        'relevance_score',
        'literature-relevance',
        '/api/v1/console/provider/deepseek',
        'applyDeepSeekConfigView',
        'syncDeepSeekPresetCapabilities',
        '/api/v1/console/tasks/${taskId}/memory',
        'loadProjectMemoryPanel',
        'window.ThesisTrustUI = Object.freeze',
        'trust-assessment',
        'done-limited',
        "s.state === 'done-limited' ? 'triangle-alert'",
        "'aria-hidden': 'true'",
        "icon.removeAttribute('data-lucide')",
        '结构/题录通过不代表正文证据通过',
    ):
        assert fragment in javascript
    source = _ui_source()
    assert "localStorage.setItem('inference-api-key'" not in source
    assert 'OpenAI / Anthropic' not in source


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js 未安装")
def test_external_javascript_parses():
    for path in JS_PATHS:
        completed = subprocess.run(
            [shutil.which("node") or "node", "--check", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert completed.returncode == 0, f"{path.name}: {completed.stderr}"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js 未安装")
def test_session_selection_and_search_helpers():
    script = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('function resolveSessionSelection');
const end = source.indexOf('function formatI18n');
if (start < 0 || end <= start) throw new Error('session helpers not found');
const helpers = source.slice(start, end);
const run = new Function('DEGREE_LABEL', `${helpers}
  const items = [
    { task_id: 'one', title: 'AI 写作 🤖', subject_field: 'Natural Language', degree: 'MASTER', current_ring_no: 3 },
    { task_id: 'two', title: '教育评价', subject_field: '教育学', degree: 'PHD', current_ring_no: 5 },
  ];
  if (resolveSessionSelection(items, 'two').task_id !== 'two') throw new Error('selection was not retained');
  if (resolveSessionSelection(items, 'missing').task_id !== 'one') throw new Error('stale selection did not fall back');
  if (resolveSessionSelection([], 'missing') !== null) throw new Error('empty selection must be null');
  if (filterSessions(items, '  ai  ')[0].task_id !== 'one') throw new Error('case/space search failed');
  if (filterSessions(items, '博士')[0].task_id !== 'two') throw new Error('degree search failed');
  if (filterSessions(items, '🤖')[0].task_id !== 'one') throw new Error('emoji search failed');
  if (filterSessions(items, '完全不存在').length !== 0) throw new Error('no-match search failed');
`);
run({ BACHELOR: '本科', MASTER: '硕士', PHD: '博士' });
"""
    completed = subprocess.run(
        [shutil.which("node") or "node", "-e", script, str(APP_JS_PATH)],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr


# ---------------------------------------------------------------------
# 跨天断点续作：前端初始化与工作区状态流的真实执行验证
# ---------------------------------------------------------------------
_JS_HARNESS_TEMPLATE = r"""
const fs = require('fs');
const path = require('path');
const appSource = fs.readFileSync(process.argv[2], 'utf8');

function slice(startMarker, endMarker) {
  const start = appSource.indexOf(startMarker);
  if (start < 0) throw new Error('缺少起始锚点: ' + startMarker);
  const end = appSource.indexOf(endMarker, start);
  if (end < 0) throw new Error('缺少结束锚点: ' + endMarker);
  return appSource.slice(start, end);
}

const blocks = [
  slice('const WORKSPACE_TABS = new Set(', 'function sessionItemHtml'),
  slice('function resolveSessionSelection', 'function normalizeSessionSearch'),
  slice('async function loadSessions(options = {}) {', 'let sessionDetailRequest'),
  slice('async function submitNewSession', 'function bindNewSessionModal'),
  slice('async function apiListSessions', 'async function apiSessionProgress'),
].join('\n');

const preamble = `
const state = {
  timers: [], saves: [], gets: [], posts: [], detailCalls: [], activeTabs: [],
  toasts: [], sessionRenders: 0, cleared: 0, focused: null, announcements: [],
};
state.workspaceResponse = { code: 0, data: { workspace: null, resume: null } };
state.listResponse = { code: 0, data: [] };
state.createResponse = { code: 0, data: { task_id: '' } };
state.saveResponse = { code: 0 };
state.resumeResponse = { code: 0, data: null };
state.server = null;
state.serverMode = false;
state.gatePosts = false;
state.gateWaiters = [];
state.fetches = [];

const elements = new Map();
class FakeDetails {}
global.HTMLDetailsElement = FakeDetails;
function element(id) {
  if (!elements.has(id)) {
    const value = {
      id, hidden: false, disabled: false, textContent: '', value: '',
      dataset: {}, open: false, _handlers: {},
      classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
      focus() { state.focused = id; },
      removeAttribute() {}, setAttribute() {},
      addEventListener(name, fn) { this._handlers[name] = fn; },
      querySelector() { return null; }, querySelectorAll() { return []; },
      scrollIntoView() {}, closest() { return null; },
    };
    if (['memory-builder', 'protocol-builder', 'argument-builder', 'template-mapping-panel'].includes(id)) {
      Object.setPrototypeOf(value, FakeDetails.prototype);
    }
    elements.set(id, value);
  }
  return elements.get(id);
}
global.document = {
  getElementById: (id) => element(id),
  querySelector: () => null,
  querySelectorAll: () => [],
};
const windowListeners = {};
global.window = { addEventListener: (name, fn) => { windowListeners[name] = fn; } };

async function flushTimers() {
  for (let round = 0; round < 5 && state.timers.length; round += 1) {
    const pending = state.timers;
    state.timers = [];
    for (const timer of pending) await timer.fn();
  }
}
global.setTimeout = (fn, ms) => { state.timers.push({ fn, ms }); return state.timers.length; };
global.clearTimeout = () => { state.timers = []; };
global.requestAnimationFrame = (fn) => { fn(); return 1; };

let sessionCache = [];
let currentSession = null;
let currentSessionTitle = '';
let currentKnowledgeSession = '';
let sessionListRequest = 0;
const API_BASE = 'http://127.0.0.1:8000';
const RING_NAMES = { 1: '选题', 2: '开题评审', 3: '文献调研', 6: '撰写', 10: '定稿' };

function toast(message) { state.toasts.push(message); }
function showAccessibleDialog() {}
function hideAccessibleDialog() {}
async function renderSessionList() { state.sessionRenders += 1; }
async function loadSessionDetail(taskId) { state.detailCalls.push(taskId); }
async function clearSessionContext() { state.cleared += 1; }
function activateWorkbenchTab(target) {
  state.activeTabs.push(target);
  scheduleWorkspaceSave({
    active_tab: target,
    last_task_id: currentSession || workspaceState.last_task_id || '',
  });
}
async function apiGet(target) {
  state.gets.push(target);
  if (target.includes('/console/workspace')) {
    if (state.serverMode) return serverGetWorkspace();
    return state.workspaceResponse;
  }
  if (target.includes('/resume')) return state.resumeResponse;
  return state.listResponse;
}
async function apiPost(target, body) {
  state.posts.push({ target, body });
  if (target.includes('/console/workspace')) {
    // 可控在途：gatePosts 打开时请求挂起，由测试决定完成顺序。
    if (state.gatePosts) {
      await new Promise(resolve => { state.gateWaiters.push(resolve); });
    }
    const result = state.serverMode ? serverPutWorkspace(body) : state.saveResponse;
    state.saves.push(body);
    return result;
  }
  if (target === '/api/v1/console/tasks') return state.createResponse;
  return { code: -1, msg: '未预期的写入请求' };
}
// 迷你工作区服务端：实现与后端一致的 revision CAS，用于乱序请求验证。
function serverGetWorkspace() {
  if (!state.server) return { code: 0, data: { workspace: null, resume: null } };
  return { code: 0, data: { workspace: { ...state.server }, resume: null } };
}
function serverPutWorkspace(payload) {
  const incoming = Number(payload && payload.revision) || 0;
  const current = state.server;
  if (current) {
    if (incoming < current.revision) {
      return {
        code: 400003,
        msg: '服务端revision ' + current.revision + '，请求 ' + incoming + ' 更旧',
        data: { conflict: true, current_revision: current.revision, incoming_revision: incoming },
      };
    }
    if (incoming === current.revision) {
      const strip = value => {
        const copy = { ...value };
        delete copy.revision;
        delete copy.updated_at;
        return copy;
      };
      if (JSON.stringify(strip(current)) === JSON.stringify(strip(payload))) {
        return { code: 0, data: current };
      }
      return {
        code: 400003,
        msg: '服务端revision ' + current.revision + ' 内容已变化',
        data: { conflict: true, current_revision: current.revision, incoming_revision: incoming },
      };
    }
  }
  state.server = { ...payload };
  return { code: 0, data: state.server };
}
function releasePostAt(index) {
  const resolve = state.gateWaiters.splice(index, 1)[0];
  if (resolve) resolve();
}
function releaseAllPosts() {
  state.gateWaiters.splice(0, state.gateWaiters.length).forEach(resolve => resolve());
}
// pagehide 的 keepalive 走原生 fetch，必须接入同一服务端与网关才能验证乱序。
global.fetch = async (target, options = {}) => {
  const body = options && options.body ? JSON.parse(options.body) : {};
  state.fetches.push({ target, body });
  state.posts.push({ target, body });
  if (state.gatePosts) {
    await new Promise(resolve => { state.gateWaiters.push(resolve); });
  }
  const result = serverPutWorkspace(body);
  state.saves.push(body);
  return { ok: true, status: 200, json: async () => result };
};
async function settle() {
  for (let round = 0; round < 8; round += 1) {
    await new Promise(resolve => setImmediate(resolve));
  }
}
function lastSave() { return state.saves[state.saves.length - 1] || null; }
function assert(condition, message) { if (!condition) throw new Error(message); }
`;

const epilogue = `
async function main() {
__BODY__
}
main().then(() => process.exit(0)).catch(error => {
  console.error(error && error.stack ? error.stack : String(error));
  process.exit(1);
});
`;

const body = preamble + '\n' + blocks + '\n' + epilogue;
new Function('require', body)(require);
"""


def _run_workspace_harness(test_body: str) -> None:
    """在 Node 中真实执行工作区状态机，而不是只检查函数文本是否存在。"""
    import subprocess
    import tempfile

    script = _JS_HARNESS_TEMPLATE.replace("__BODY__", test_body)
    with tempfile.TemporaryDirectory() as tmp:
        script_path = Path(tmp) / "workspace-harness.js"
        script_path.write_text(script, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(script_path), str(APP_JS_PATH)],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert completed.returncode == 0, completed.stderr


def test_init_app_reads_server_workspace_before_session_list():
    """启动顺序：先读服务端工作区，再加载任务列表，且页签由服务端决定。"""
    source = APP_JS_PATH.read_text(encoding="utf-8")
    start = source.index("async function initApp()")
    end = source.index("// 新建对话按钮（.new-chat-btn 或 sidebar 新建）")
    init_head = source[start:end]

    assert "pauseWorkspacePersistence()" in init_head
    assert init_head.index("loadWorkspaceState()") < init_head.index(
        "loadSessionsWithWorkspaceFallback("
    )
    assert "preferredTaskId: restoredWorkspace.last_task_id" in init_head
    assert "forceDetail: true" in init_head

    tail_start = source.index("// 使用服务端保存的页签")
    tail = source[tail_start:]
    assert "activateWorkbenchTab(restoredTab)" in tail
    # HTML 里的默认选中项不得再覆盖服务端恢复页签。
    assert ".kb-tab.active" not in tail
    assert "continueButton.addEventListener('click', continueLastThesis)" in tail
    assert tail.index("activateWorkbenchTab(restoredTab)") < tail.index(
        "workspacePersistenceReady = true"
    )


def test_workspace_saves_are_skipped_until_recovery_completes():
    _run_workspace_harness(r"""
  assert(workspacePersistenceReady === false, '恢复完成前持久化开关必须为关闭');
  scheduleWorkspaceSave({ last_task_id: 'T1', active_tab: 'memory' });
  await flushTimers();
  assert(state.saves.length === 0, '恢复完成前的保存必须被跳过');

  // 恢复链路成功后才允许写回服务端。
  workspaceServerLoaded = true;
  sessionListLoaded = true;
  updateWorkspaceTrust();
  workspacePersistenceReady = true;
  scheduleWorkspaceSave({ last_task_id: 'T1', active_tab: 'memory' });
  scheduleWorkspaceSave({ last_task_id: 'T1', active_tab: 'evidence' });
  await flushTimers();
  assert(state.saves.length === 1, '防抖应合并为 1 次保存，实际 ' + state.saves.length);
  assert(lastSave().active_tab === 'evidence', '必须发送最新快照');
  assert(lastSave().last_task_id === 'T1', '任务指针必须一起保存');
""")


def test_init_reconnects_active_jobs_after_reload():
    """初始化后必须重新订阅活动作业，避免刷新后丢失轮询。"""
    source = APP_JS_PATH.read_text(encoding="utf-8")
    assert "async function resumeActiveJobs(taskId)" in source
    assert "['PENDING', 'RUNNING', 'CANCEL_REQUESTED'].includes(job.status)" in source
    assert "void resumeActiveJobs(currentSession)" in source
    assert "inner.dataset.historyBuilt = '';" in source
    init_tail = source[source.index("workspacePersistenceReady = true"):]
    assert "void resumeActiveJobs(currentSession)" in init_tail


def test_degraded_recovery_never_writes_back_to_server():
    """断网导致的降级本地状态绝不能覆盖服务端恢复位置。"""
    _run_workspace_harness(r"""
  state.workspaceResponse = { code: -1, msg: '无法连接后端' };
  state.listResponse = { code: -1, msg: '无法连接后端' };
  await loadWorkspaceState();
  await loadSessions();
  assert(workspaceRecoveryTrusted === false, '恢复未成功时必须拒绝写回');

  workspacePersistenceReady = true;
  scheduleWorkspaceSave({ last_task_id: '', active_tab: 'evidence' });
  await flushTimers();
  flushWorkspaceSaveOnExit();
  assert(state.saves.length === 0,
    '降级状态绝不能写回服务端，否则一次断网就会清空恢复位置');
  assert(state.posts.length === 0, '降级状态不得发出任何写入请求');
""")


def test_list_recovery_reloads_server_pointer():
    """列表恢复成功后必须重新读取服务端指针，而不是停留在断网时的默认值。"""
    _run_workspace_harness(r"""
  state.workspaceResponse = { code: -1, msg: '无法连接后端' };
  state.listResponse = { code: -1, msg: '无法连接后端' };
  await loadWorkspaceState();
  await loadSessions();
  assert(workspaceState.last_task_id === '', '断网时应使用安全本地默认值');

  state.workspaceResponse = {
    code: 0,
    data: {
      workspace: {
        last_task_id: 'T-SERVER', active_tab: 'jobs',
        expanded_items: [], editor_anchor: '',
      },
      resume: null,
    },
  };
  state.listResponse = { code: 0, data: [{ task_id: 'T-SERVER', title: '服务端任务' }] };
  await loadSessionsWithWorkspaceFallback();

  assert(workspaceState.last_task_id === 'T-SERVER', '列表恢复后必须重新读取服务端指针');
  assert(currentSession === 'T-SERVER', '必须按服务端指针重新选择任务');
  assert(workspaceRecoveryTrusted === true, '恢复成功后应重新允许写回');
""")


def test_list_request_failure_keeps_valid_resume_pointer():
    _run_workspace_harness(r"""
  assert(await apiListSessions() !== null, '成功但为空应返回数组');
  state.listResponse = { code: -1, msg: '无法连接后端' };
  assert(await apiListSessions() === null, '请求失败必须返回 null，不能伪装成空列表');

  currentSession = 'T-RESTORED';
  sessionCache = [{ task_id: 'T-RESTORED', title: '上次论文' }];
  const failed = await loadSessions();
  assert(failed.ok === false, '列表失败必须标记为未成功');
  assert(failed.items === null, '失败不得返回空数组');
  assert(currentSession === 'T-RESTORED', '断网不得清空已有恢复指针');
  assert(state.cleared === 0, '断网不得清空工作区上下文');

  state.listResponse = { code: 0, data: [] };
  const empty = await loadSessions();
  assert(empty.ok === true, '请求成功但为空必须标记为成功');
  assert(empty.selected === null, '确实为空时不应选中任何任务');
  assert(currentSession === null, '只有请求明确成功且为空时才能清空指针');
""")


def test_selecting_and_creating_task_persists_correct_pointer():
    _run_workspace_harness(r"""
  sessionCache = [
    { task_id: 'T-OLD', title: '旧论文' },
    { task_id: 'T-NEW', title: '新论文' },
  ];
  workspaceServerLoaded = true;
  sessionListLoaded = true;
  updateWorkspaceTrust();
  workspacePersistenceReady = true;
  workspaceState = { last_task_id: 'T-OLD', active_tab: 'jobs', expanded_items: ['job-1'], editor_anchor: 'section-1' };

  await selectSession('T-NEW');
  await flushTimers();
  assert(currentSession === 'T-NEW', '必须切换到被选中的任务');
  assert(lastSave().last_task_id === 'T-NEW', '选择任务必须保存新指针');
  assert(lastSave().expanded_items.length === 0, '切换任务必须清空上一任务的展开项');
  assert(lastSave().editor_anchor === '', '切换任务必须清空上一任务的编辑锚点');

  state.saves.length = 0;
  element('ns-title-input').value = ' 新建的论文 ';
  element('ns-degree').value = 'MASTER';
  element('ns-subject').value = '信息管理';
  state.createResponse = { code: 0, data: { task_id: 'T-CREATED' } };
  state.listResponse = { code: 0, data: [
    { task_id: 'T-NEW', title: '新论文' },
    { task_id: 'T-CREATED', title: '新建的论文' },
  ] };
  await submitNewSession();
  await flushTimers();
  assert(currentSession === 'T-CREATED', '创建后必须锁定新任务，不能跳回旧任务');
  assert(lastSave().last_task_id === 'T-CREATED', '创建后必须保存新任务指针');
""")


def test_continue_action_only_navigates_and_focuses():
    _run_workspace_harness(r"""
  sessionCache = [{ task_id: 'T1', title: '论文一' }];
  workspaceServerLoaded = true;
  sessionListLoaded = true;
  updateWorkspaceTrust();
  workspacePersistenceReady = true;
  state.saves.length = 0;
  state.posts.length = 0;

  renderResumeBanner({
    task_id: 'T1', title: '论文一', current_ring_no: 1, complete_percent: 0,
    pending_approvals: [], active_jobs: [], consistency_issues: [],
    next_safe_action: { type: 'EXECUTE_RING', label: '执行环1', ring_no: 1 },
  });
  assert(element('resume-banner').hidden === false, '横幅必须真实可见');
  assert(element('resume-continue').dataset.taskId === 'T1', '继续按钮必须绑定任务');

  await continueLastThesis();
  assert(state.detailCalls.includes('T1'), '继续必须加载任务详情');
  assert(element('resume-banner').hidden === true, '继续后必须隐藏横幅');
  assert(state.focused === 'run-cur-ring', 'EXECUTE_RING 必须聚焦执行按钮');
  assert(state.posts.every(item => item.target.includes('/console/workspace')),
    '继续动作只能写工作区，不得触发环执行或审批');

  // MONITOR_JOB必须聚焦不会随作业卡重绘而消失的稳定按钮。
  state.focused = null;
  renderResumeBanner({
    task_id: 'T1', title: '论文一', current_ring_no: 1, complete_percent: 0,
    pending_approvals: [],
    active_jobs: [{ job_id: 'J1', status: 'RUNNING' }],
    next_safe_action: { type: 'MONITOR_JOB', label: '查看后台作业', job_id: 'J1' },
  });
  await continueLastThesis();
  assert(state.focused === 'jobs-refresh',
    'MONITOR_JOB必须聚焦稳定的刷新按钮，避免列表重绘后焦点掉回body');

  state.focused = null;
  renderResumeBanner({
    task_id: 'T1', title: '论文一', current_ring_no: 5, complete_percent: 40,
    pending_approvals: [], active_jobs: [],
    autosaved_drafts: [{ draft_key: 'research-protocol:new', status: 'ACTIVE' }],
    next_safe_action: {
      type: 'RESUME_DRAFT', label: '继续编辑未提交草稿',
      draft_key: 'research-protocol:new', object_type: 'RESEARCH_PROTOCOL_FORM',
    },
  });
  await continueLastThesis();
  assert(state.activeTabs.includes('research'), '研究协议草稿必须打开研究页签');
  assert(state.focused === 'protocol-title', '研究协议草稿必须聚焦稳定的标题输入');
  assert(element('protocol-builder').open === true, '草稿恢复必须展开对应表单');

  // 被阻断的恢复不得把焦点带向执行按钮。
  state.focused = null;
  state.saves.length = 0;
  renderResumeBanner({
    task_id: 'T1', title: '论文一', current_ring_no: 6, complete_percent: 50,
    pending_approvals: [], active_jobs: [], consistency_issues: ['outbox:unprojected'],
    next_safe_action: { type: 'REPAIR_REQUIRED', label: '修复产物投影', ring_no: 6 },
  });
  await continueLastThesis();
  assert(state.focused === null, 'REPAIR_REQUIRED 不得聚焦任何执行入口');
  assert(String(element('resume-live').textContent).includes('恢复被阻断'),
    '阻断状态必须如实播报');
""")


def test_identity_switch_discards_stale_saves_and_banner():
    _run_workspace_harness(r"""
  workspacePersistenceReady = true;
  workspaceState = { last_task_id: 'T-OLD-USER', active_tab: 'writing', expanded_items: [], editor_anchor: '' };
  renderResumeBanner({
    task_id: 'T-OLD-USER', title: '旧用户论文', current_ring_no: 1,
    complete_percent: 0, pending_approvals: [], active_jobs: [],
    next_safe_action: { type: 'EXECUTE_RING', label: '执行环1', ring_no: 1 },
  });
  assert(element('resume-banner').hidden === false, '旧用户横幅应可见');

  // 旧身份已排队但尚未发出的保存请求，切换身份后不得再落到服务端。
  scheduleWorkspaceSave({ last_task_id: 'T-OLD-USER' });
  state.workspaceResponse = { code: 0, data: { workspace: null, resume: null } };
  state.listResponse = { code: 0, data: [] };
  await switchWorkspaceIdentity();
  await flushTimers();

  assert(element('resume-banner').hidden === true, '切换身份后不得残留旧用户横幅');
  assert(workspaceState.last_task_id === '', '切换身份后必须清空旧工作区指针');
  assert(state.saves.every(item => item.last_task_id !== 'T-OLD-USER'),
    '旧身份的延迟保存不得在新身份下发出');
""")


def test_workspace_snapshot_rejects_unknown_tabs_and_oversized_fields():
    _run_workspace_harness(r"""
  const normalized = normalizeWorkspaceState({
    last_task_id: 'T1', active_tab: 'not-a-tab',
    expanded_items: [1, 'ok'], editor_anchor: 'x',
  });
  assert(normalized.active_tab === 'refs', '非法页签必须回退到安全默认值');
  assert(normalized.expanded_items.length === 1, '非字符串展开项必须被过滤');

  workspaceState = { last_task_id: 'T1', active_tab: 'memory', expanded_items: [], editor_anchor: '' };
  const snapshot = workspaceSnapshot();
  assert(Object.keys(snapshot).sort().join(',') === 'active_tab,editor_anchor,expanded_items,last_task_id',
    '快照字段必须与后端契约一致');
""")


def test_expanded_items_are_collected_and_restored_from_stable_details_ids():
    _run_workspace_harness(r"""
  workspaceState = {
    last_task_id: 'T1',
    active_tab: 'memory',
    expanded_items: ['memory-builder', 'protocol-builder'],
    editor_anchor: '',
  };
  bindWorkspaceExpandedItems();
  applyWorkspaceExpandedItems();
  assert(element('memory-builder').open === true, '记忆表单应按工作区状态展开');
  assert(element('protocol-builder').open === true, '研究协议应按工作区状态展开');
  assert(element('argument-builder').open === false, '未保存的表单不应被展开');

  element('protocol-builder').open = false;
  element('argument-builder').open = true;
  element('argument-builder')._handlers.toggle();
  assert(workspaceState.expanded_items.includes('argument-builder'),
    '展开操作必须写入稳定ID');
  assert(!workspaceState.expanded_items.includes('protocol-builder'),
    '关闭操作必须从工作区状态移除');
""")


def _bootstrap_trusted_workspace(generation=True):
    """在 harness 中建立“恢复已完成、允许写回”的前置状态。"""
    return r"""
  workspaceServerLoaded = true;
  sessionListLoaded = true;
  updateWorkspaceTrust();
  workspacePersistenceReady = true;
"""


def test_inflight_save_of_old_identity_cannot_block_new_identity():
    """B01：用户A请求在途时切换身份，B的首次保存必须立即发出且不被A回包污染。"""
    _run_workspace_harness(_bootstrap_trusted_workspace(generation=True) + r"""
  state.serverMode = true;
  state.server = { last_task_id: 'T-A', active_tab: 'refs', expanded_items: [], editor_anchor: '', revision: 5 };
  workspaceState = { last_task_id: 'T-A', active_tab: 'refs', expanded_items: [], editor_anchor: '' };
  workspaceRevision = 5;
  workspaceSaveGeneration = newWorkspaceSaveGeneration();
  const generationA = workspaceSaveGeneration;

  // 1. 用户A的保存请求保持在途。
  state.gatePosts = true;
  scheduleWorkspaceSave({ active_tab: 'writing' });
  await flushTimers();
  assert(generationA.inFlight === true, 'A 的请求必须处于在途状态');
  assert(state.gateWaiters.length === 1, 'A 的请求应被网关挂起');

  // 2. 身份切换 -> 创建 B 世代。
  pauseWorkspacePersistence();
  assert(workspaceSaveGeneration !== generationA, '身份切换必须创建新的保存世代');
  assert(workspaceRevision === 6, '身份切换不得回退 A 已预留的 revision');
  workspaceServerLoaded = true;
  sessionListLoaded = true;
  updateWorkspaceTrust();
  workspacePersistenceReady = true;
  workspaceState = { last_task_id: 'T-B', active_tab: 'refs', expanded_items: [], editor_anchor: '' };
  const generationB = workspaceSaveGeneration;

  // 3-4. B 只做一次操作，不制造第二次。
  scheduleWorkspaceSave({ active_tab: 'memory' });
  await flushTimers();

  // 5. B 的 POST 必须真的发出，且带 B 的最新快照。
  const memoryPosts = state.posts.filter(item => item.body.active_tab === 'memory');
  assert(memoryPosts.length === 1, 'B 的首次保存不得被 A 的在途请求阻塞，实际 '
    + memoryPosts.length);
  assert(memoryPosts[0].body.last_task_id === 'T-B', '必须携带 B 的任务指针');
  assert(memoryPosts[0].body.revision === 7, 'B 必须使用高于 A 在途请求的 revision');
  assert(generationB.inFlight === true, 'B 世代自己的 inFlight 必须独立生效');

  // 6. A 的请求现在才返回（服务端按 revision 拒绝旧快照）。
  releaseAllPosts();
  await settle();

  // 7. A 的回包不得改变 B 的队列、播报或保存状态。
  assert(state.server.active_tab === 'memory', '服务端必须保留 B 的最新位置');
  assert(state.server.revision === 7, '服务端 revision 必须是 B 的 7');
  assert(state.gateWaiters.length === 0, '所有请求都应已返回');
  assert(String(element('resume-live').textContent).indexOf('另一页面') === -1,
    '旧世代的冲突回包不得污染新身份的播报');
  assert(generationB.queued === false, 'B 世代不得被 A 的回包重新排队');
""")


def test_out_of_order_pagehide_cannot_rollback_newer_snapshot():
    """B02：S1 在途、S2 通过 pagehide 发出；S2 先完成、S1 后完成，服务端必须保留 S2。"""
    _run_workspace_harness(_bootstrap_trusted_workspace() + r"""
  state.serverMode = true;
  state.server = { last_task_id: '', active_tab: 'refs', expanded_items: [], editor_anchor: '', revision: 0 };
  workspaceState = { last_task_id: '', active_tab: 'refs', expanded_items: [], editor_anchor: '' };
  workspaceRevision = 0;
  workspaceSaveGeneration = newWorkspaceSaveGeneration();

  // S1：普通防抖保存进入在途（revision 1）。
  state.gatePosts = true;
  scheduleWorkspaceSave({ active_tab: 'writing' });
  await flushTimers();
  assert(state.posts.length === 1, 'S1 应已发出');
  assert(state.posts[0].body.revision === 1, 'S1 应使用 revision 1');

  // S2：用户又切换页签，页面关闭时 keepalive 发出（revision 2）。
  scheduleWorkspaceSave({ active_tab: 'jobs' });
  flushWorkspaceSaveOnExit();
  assert(state.posts.length === 2, 'S2 应已通过 pagehide 发出');
  assert(state.posts[1].body.revision === 2, 'S2 必须使用比 S1 更高的 revision');

  // S2 先落库，S1 因网络延迟后落库。
  releasePostAt(1);
  await settle();
  releasePostAt(0);
  await settle();

  assert(state.server.active_tab === 'jobs', '乱序完成后服务端必须保留较新的 S2');
  assert(state.server.revision === 2, '服务端 revision 不得倒退');

  // S1 被拒绝后客户端以服务端为准重读，且不得循环 POST。
  assert(state.posts.length === 2, '冲突处理不得触发新的写入请求');
  assert(state.serverMode === true, '服务端状态未被客户端强行覆盖');
""")


def test_rapid_tab_changes_send_only_latest_content_and_highest_revision():
    _run_workspace_harness(_bootstrap_trusted_workspace() + r"""
  state.serverMode = true;
  state.server = { last_task_id: '', active_tab: 'refs', expanded_items: [], editor_anchor: '', revision: 3 };
  workspaceState = { last_task_id: '', active_tab: 'refs', expanded_items: [], editor_anchor: '' };
  workspaceRevision = 3;
  workspaceSaveGeneration = newWorkspaceSaveGeneration();

  scheduleWorkspaceSave({ active_tab: 'writing' });
  scheduleWorkspaceSave({ active_tab: 'research' });
  scheduleWorkspaceSave({ active_tab: 'notes' });
  await flushTimers();

  assert(state.posts.length === 1, '连续快速变化必须被防抖合并为一次保存，实际 '
    + state.posts.length);
  assert(lastSave().active_tab === 'notes', '必须只发送最新内容');
  assert(lastSave().revision === 4, '必须使用最高 revision');
  assert(state.server.revision === 4, '服务端 revision 必须递增到 4');
  assert(state.server.active_tab === 'notes', '服务端必须保留最新页签');
""")


def test_initial_recovery_does_not_inflate_revision():
    _run_workspace_harness(r"""
  state.serverMode = true;
  state.server = { last_task_id: 'T-SERVER', active_tab: 'jobs', expanded_items: [], editor_anchor: '', revision: 7 };
  state.listResponse = { code: 0, data: [{ task_id: 'T-SERVER', title: '服务端任务' }] };
  const revisionBefore = state.server.revision;

  // 复现 initApp 的恢复序列：读取工作区 -> 加载列表 -> 激活服务端页签。
  pauseWorkspacePersistence();
  await loadWorkspaceState();
  currentSession = workspaceState.last_task_id || null;
  await loadSessionsWithWorkspaceFallback({
    preferredTaskId: workspaceState.last_task_id,
    forceDetail: true,
  });
  activateWorkbenchTab(workspaceState.active_tab || 'refs');
  // 关键：页签激活的防抖定时器在持久化开启之后才会触发，
  // 必须证明那一刻也不会伪造一次用户修改。
  workspacePersistenceReady = true;
  await flushTimers();
  await settle();

  assert(state.posts.length === 0, '初始化恢复不得向服务端写入，实际 '
    + state.posts.length);
  assert(state.server.revision === revisionBefore, '初始化恢复不得伪造 revision 增长');
  assert(currentSession === 'T-SERVER', '必须恢复服务端指针');
  assert(workspaceRevision === 7, '客户端必须从服务端 revision 继续');
""")


def test_workspace_conflict_rereads_server_without_posting_loop():
    _run_workspace_harness(_bootstrap_trusted_workspace() + r"""
  // 另一页面已经推进到 revision 10，本页仍停留在 revision 9。
  state.serverMode = true;
  state.server = { last_task_id: 'T-OTHER', active_tab: 'graph', expanded_items: [], editor_anchor: '', revision: 10 };
  workspaceState = { last_task_id: 'T-OTHER', active_tab: 'graph', expanded_items: [], editor_anchor: '' };
  workspaceRevision = 9;
  workspaceSaveGeneration = newWorkspaceSaveGeneration();

  scheduleWorkspaceSave({ active_tab: 'writing' });
  const staleGeneration = workspaceSaveGeneration;
  staleGeneration.lastSnapshot = { last_task_id: 'T-OTHER', active_tab: 'refs', expanded_items: [], editor_anchor: '' };
  await runWorkspaceSave();
  await settle();

  assert(state.server.active_tab === 'graph', '冲突不得覆盖服务端已保存状态');
  assert(state.server.revision === 10, '同版本不同内容不得递增服务端 revision');
  assert(String(element('resume-live').textContent).indexOf('另一页面') !== -1,
    '冲突必须通过稳定 aria-live 区域提示');
  assert(workspaceState.active_tab === 'graph', '冲突后必须以服务端状态为准');
  assert(workspaceRevision === 10, '冲突后客户端必须采纳服务端 revision');
  assert(state.posts.length === 1, '冲突后不得循环重发 POST');
""")


def test_resume_banner_refreshes_when_active_job_set_changes():
    """B03：取消 PENDING 作业后，横幅必须立即更新为准确下一动作。"""
    _run_workspace_harness(_bootstrap_trusted_workspace() + r"""
  state.serverMode = true;
  state.server = { last_task_id: 'T1', active_tab: 'jobs', expanded_items: [], editor_anchor: '', revision: 1 };
  sessionCache = [{ task_id: 'T1', title: '论文一' }];
  currentSession = 'T1';

  renderResumeBanner({
    task_id: 'T1', title: '论文一', current_ring_no: 1, complete_percent: 0,
    pending_approvals: [], recoverable_jobs: [],
    active_jobs: [{ job_id: 'J1', status: 'RUNNING', operation: 'ring.execute' }],
    next_safe_action: { type: 'MONITOR_JOB', label: '继续查看正在运行的后台作业', job_id: 'J1' },
  });
  assert(element('resume-banner').hidden === false, '横幅应可见');
  assert(String(element('resume-summary').textContent).indexOf('运行中作业 1') !== -1,
    '取消前应显示运行中作业 1');

  // 作业已取消，但后端摘要已经变成 EXECUTE_RING。
  state.resumeResponse = {
    code: 0,
    data: {
      task_id: 'T1', title: '论文一', current_ring_no: 1, complete_percent: 0,
      pending_approvals: [], active_jobs: [],
      recoverable_jobs: [{ job_id: 'J1', status: 'CANCELLED', operation: 'ring.execute' }],
      next_safe_action: { type: 'EXECUTE_RING', label: '继续执行环1', ring_no: 1 },
    },
  };
  syncResumeBannerWithJobs([{ job_id: 'J1', status: 'CANCELLED', operation: 'ring.execute' }]);
  await settle();

  assert(String(element('resume-summary').textContent).indexOf('运行中作业 0') !== -1,
    '取消后横幅不得继续显示运行中作业 1');
  assert(String(element('resume-next').textContent).indexOf('继续执行环1') !== -1,
    '取消后横幅必须显示准确的下一动作');

  // 活动集合未变化时不得触发无意义刷新。
  state.posts.length = 0;
  const summaryBefore = element('resume-summary').textContent;
  syncResumeBannerWithJobs([]);
  await settle();
  assert(element('resume-summary').textContent === summaryBefore,
    '活动集合未变化时不得刷新横幅');
""")


def test_resume_banner_hides_when_accurate_summary_unavailable():
    _run_workspace_harness(_bootstrap_trusted_workspace() + r"""
  sessionCache = [{ task_id: 'T1', title: '论文一' }];
  currentSession = 'T1';
  renderResumeBanner({
    task_id: 'T1', title: '论文一', current_ring_no: 1, complete_percent: 0,
    pending_approvals: [], active_jobs: [], recoverable_jobs: [],
    next_safe_action: { type: 'EXECUTE_RING', label: '继续执行环1', ring_no: 1 },
  });
  assert(element('resume-banner').hidden === false, '横幅应可见');

  // 拿不到与当前任务一致的准确摘要时必须隐藏，绝不继续展示旧摘要。
  state.resumeResponse = { code: -1, msg: '无法连接后端' };
  await refreshVisibleResumeSummary();
  assert(element('resume-banner').hidden === true, '刷新失败必须隐藏横幅而不是展示旧摘要');
""")
