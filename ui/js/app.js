/* ============================================================
   交互逻辑
   ============================================================ */

/* —— 主题切换（图片4右下角的圆形图标按钮） —— */
const themeBtn = document.getElementById('theme-toggle');
if (themeBtn) {
  themeBtn.addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme');
    const next = cur === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    toast(t('toast.theme'));
  });
}

/* ============================================================
   输入区下方控件：4 个下拉 + Ultracode 滑块 + 上下文卡片
   ============================================================ */

// 通用 dropdown 打开/关闭工具
function openDd(menuId, triggerEl, alignRight = false) {
  // 关闭其他
  document.querySelectorAll('.dd-menu.show').forEach(m => {
    if (m.id !== menuId) m.classList.remove('show');
  });
  // 同步关闭按钮 aria-expanded
  ['perm-bypass', 'perm-add', 'model-select'].forEach(id => {
    const b = document.getElementById(id);
    if (b) b.setAttribute('aria-expanded', 'false');
  });
  const menu = document.getElementById(menuId);
  if (!menu || !triggerEl) return;
  // 定位
  const rect = triggerEl.getBoundingClientRect();
  menu.classList.toggle('show');
  const open = menu.classList.contains('show');
  triggerEl.setAttribute('aria-expanded', String(open));
  if (!open) return;
  // 计算位置：上方弹出
  const menuRect = menu.getBoundingClientRect();
  let left = rect.left;
  let top = rect.top - menuRect.height - 6;
  // 右对齐：让菜单右边对齐 trigger 右边
  if (alignRight) {
    left = rect.right - menuRect.width;
  }
  // 边界保护
  if (left < 8) left = 8;
  if (left + menuRect.width > window.innerWidth - 8) left = window.innerWidth - menuRect.width - 8;
  if (top < 8) top = rect.bottom + 6; // 上面不够则下面弹
  menu.style.left = left + 'px';
  menu.style.top = top + 'px';
  menu.style.bottom = 'auto';
}
function closeAllDd() {
  document.querySelectorAll('.dd-menu.show').forEach(m => m.classList.remove('show'));
  ['perm-bypass', 'perm-add', 'model-select'].forEach(id => {
    const b = document.getElementById(id);
    if (b) b.setAttribute('aria-expanded', 'false');
  });
}

/* —— 模型选择 —— */
const modelSelect = document.getElementById('model-select');
const modelName = document.getElementById('model-name');
const modelCap = document.getElementById('model-cap');
let currentModel = { model: 'deepseek-v4-flash', cap: 'Tools' };

// 给每个DeepSeek模型 item 加上数字快捷键 1-3
document.querySelectorAll('#dd-model .dd-item').forEach((item, idx) => {
  const num = document.createElement('span');
  num.className = 'dd-kbd';
  num.textContent = String(idx + 1);
  item.appendChild(num);
  // 当前选中标记
  syncModelItemActive(item);
  item.addEventListener('click', async () => {
    const response = await apiSaveDeepSeekConfig({
      model: item.dataset.model,
      supports_tools: item.dataset.tools === 'true',
      supports_vision: item.dataset.vision === 'true',
    });
    if (response.code !== 0) {
      toast(response.msg || '切换DeepSeek模型失败');
      closeAllDd();
      return;
    }
    applyDeepSeekConfigView(response.data);
    // 同步选中态
    document.querySelectorAll('#dd-model .dd-item').forEach(syncModelItemActive);
    closeAllDd();
    toast(currentLang === 'zh-CN' ? `已切换到 ${currentModel.model}` : `Switched to ${currentModel.model}`);
  });
});
function syncModelItemActive(item) {
  const isActive = item.dataset.model === currentModel.model;
  item.classList.toggle('active', isActive);
  // 移除/添加 ✓
  const exist = item.querySelector('.dd-check');
  if (isActive && !exist) {
    const chk = document.createElement('span');
    chk.className = 'dd-check';
    chk.textContent = '✓';
    item.appendChild(chk);
  } else if (!isActive && exist) {
    exist.remove();
  }
}
modelSelect?.addEventListener('click', (e) => {
  e.stopPropagation();
  openDd('dd-model', modelSelect, true);
});

/* —— 模式（逐环确认）—— */
const permBypass = document.getElementById('perm-bypass');
const permLabel = document.getElementById('perm-label');
const MODE_LABELS = {
  'zh-CN': { manual: '手动', acceptEdits: '接受编辑', plan: '计划', bypass: '逐环确认' },
  'en-US': { manual: 'Manual', acceptEdits: 'Accept edits', plan: 'Plan', bypass: 'Per-ring confirm' },
};
let currentMode = 'bypass';
function applyMode(mode) {
  currentMode = mode;
  if (permLabel) permLabel.textContent = MODE_LABELS[currentLang][mode] || mode;
  // 逐环确认时显示对勾 + 品牌橙 chip 样式
  const checkSvg = permBypass?.querySelector('svg:first-child');
  if (checkSvg) checkSvg.style.display = mode === 'bypass' ? '' : 'none';
  // 同步选中态
  document.querySelectorAll('#dd-perm .dd-item').forEach(item => {
    const isActive = item.dataset.mode === mode;
    item.classList.toggle('active', isActive);
    const exist = item.querySelector('.dd-check');
    if (isActive && !exist) {
      const chk = document.createElement('span');
      chk.className = 'dd-check';
      chk.textContent = '✓';
      item.appendChild(chk);
    } else if (!isActive && exist) exist.remove();
  });
}
document.querySelectorAll('#dd-perm .dd-item').forEach(item => {
  syncPermActive(item);
  item.addEventListener('click', () => {
    applyMode(item.dataset.mode);
    closeAllDd();
  });
});
function syncPermActive(item) {
  const isActive = item.dataset.mode === currentMode;
  item.classList.toggle('active', isActive);
  const exist = item.querySelector('.dd-check');
  if (isActive && !exist) {
    const chk = document.createElement('span');
    chk.className = 'dd-check';
    chk.textContent = '✓';
    item.appendChild(chk);
  } else if (!isActive && exist) exist.remove();
}
permBypass?.addEventListener('click', (e) => {
  e.stopPropagation();
  openDd('dd-perm', permBypass, false);
});

/* —— + 号添加菜单 —— */
const permAdd = document.getElementById('perm-add');
document.querySelectorAll('#dd-add .dd-item').forEach(item => {
  item.addEventListener('click', () => {
    const action = item.dataset.add;
    const actionLabels = currentLang === 'zh-CN'
      ? { file: '添加文件或照片', folder: '添加文件夹', slash: '斜线命令', connector: '添加连接器', plugin: '插件' }
      : { file: 'Add file/photo', folder: 'Add folder', slash: 'Slash command', connector: 'Add connector', plugin: 'Plugin' };
    closeAllDd();
    toast(actionLabels[action] || action);
    // 斜线命令 → 在输入框插入 /
    if (action === 'slash' && prompt) {
      prompt.value = '/';
      prompt.dispatchEvent(new Event('input'));
      prompt.focus();
    }
  });
});
permAdd?.addEventListener('click', (e) => {
  e.stopPropagation();
  openDd('dd-add', permAdd, false);
});

/* —— 点击外部关闭所有 dd —— */
document.addEventListener('click', (e) => {
  if (!e.target.closest('.dd-menu') && !e.target.closest('#perm-bypass') && !e.target.closest('#perm-add') && !e.target.closest('#model-select')) {
    closeAllDd();
  }
});

/* ============================================================
   通用 Popover 工具（打开 / 关闭 / 智能定位）
   ============================================================ */
let activePopover = null;
let activePopoverTrigger = null;
function openPopover(popId, triggerEl, opts = {}) {
  // 关闭其他 popover
  document.querySelectorAll('.popover.show').forEach(p => { if (p.id !== popId) p.classList.remove('show'); });
  closeAllDd();
  const pop = document.getElementById(popId);
  if (!pop || !triggerEl) return;
  pop.classList.toggle('show');
  const open = pop.classList.contains('show');
  triggerEl.setAttribute('aria-expanded', String(open));
  if (typeof opts.onOpen === 'function') opts.onOpen(open);
  if (!open) {
    activePopover = null;
    activePopoverTrigger = null;
    return;
  }
  activePopover = pop;
  activePopoverTrigger = triggerEl;
  // 定位
  const rect = triggerEl.getBoundingClientRect();
  pop.classList.remove('below');
  pop.style.left = '';
  pop.style.right = '';
  pop.style.top = '';
  pop.style.bottom = '';
  pop.style.visibility = 'hidden';
  pop.style.display = 'block';
  const popRect = pop.getBoundingClientRect();
  pop.style.display = '';
  pop.style.visibility = '';
  // 默认：上方弹出，三角朝下
  let left = rect.left + rect.width / 2 - popRect.width / 2;
  let top = rect.top - popRect.height - 12;
  if (top < 8) {
    // 下方弹出，三角朝上
    pop.classList.add('below');
    top = rect.bottom + 10;
  }
  if (left < 8) left = 8;
  if (left + popRect.width > window.innerWidth - 8) left = window.innerWidth - popRect.width - 8;
  pop.style.left = left + 'px';
  pop.style.top = top + 'px';
  // 三角水平位置：默认 50%（已经在 ::before 中），如有需要可调整 left
}
function closeActivePopover() {
  if (activePopover) activePopover.classList.remove('show');
  if (activePopoverTrigger) activePopoverTrigger.setAttribute('aria-expanded', 'false');
  activePopover = null;
  activePopoverTrigger = null;
}

/* —— Ultracode 思考深度（点击 chip → 弹窗 + 拖动 thumb） —— */
const ucToggle = document.getElementById('ultracode-toggle');
const ucThumb = document.getElementById('uc-thumb');
const ucTrackBig = document.getElementById('uc-track-big');
const ucThumbBig = document.getElementById('uc-thumb-big');
const ucValueNum = document.getElementById('uc-value-num');
let ucValue = 65; // 0-100
const UC_MAX = 100;
const UC_MIN = 0;

function setUcValue(v, silent = false) {
  ucValue = Math.max(UC_MIN, Math.min(UC_MAX, v));
  const pct = (ucValue / UC_MAX) * 100;
  // 小 chip thumb：用于在输入区下方反映当前值
  if (ucThumb) ucThumb.style.left = `calc(${pct}% - 7px)`;
  // 大 popover thumb
  if (ucThumbBig) {
    ucThumbBig.style.left = `calc(${pct}% - 12px)`;
  }
  const fillBig = document.getElementById('uc-fill-big');
  if (fillBig) fillBig.style.width = pct + '%';
  const stops = document.querySelectorAll('.uc-track-big-stops span');
  stops.forEach((s, i) => {
    s.classList.toggle('on', ucValue >= (i / Math.max(1, stops.length - 1)) * 100);
  });
  // 激活态：> 0 时高亮
  const active = ucValue > 0;
  if (ucToggle) ucToggle.classList.toggle('active', active);
  if (ucTrackBig) ucTrackBig.classList.toggle('active', active);
  if (ucTrackBig) ucTrackBig.setAttribute('aria-valuenow', String(ucValue));
  if (ucValueNum) ucValueNum.textContent = ucValue;
  if (!silent) toast(`${t('uc.thumbMoved')} · ${ucValue}/100`);
}

ucToggle?.addEventListener('click', (e) => {
  e.stopPropagation();
  openPopover('pop-uc', ucToggle, { onOpen: (open) => { if (open) setUcValue(ucValue, true); } });
});

// 大滑块：拖动 + 点击
let ucDragging = false;
function ucTrackToValue(clientX) {
  const rect = ucTrackBig.getBoundingClientRect();
  const x = Math.max(0, Math.min(rect.width, clientX - rect.left));
  return Math.round((x / rect.width) * UC_MAX);
}
function startUcDrag(e) {
  ucDragging = true;
  e.preventDefault();
  const x = e.touches ? e.touches[0].clientX : e.clientX;
  setUcValue(ucTrackToValue(x), true);
}
function moveUcDrag(e) {
  if (!ucDragging) return;
  const x = e.touches ? e.touches[0].clientX : e.clientX;
  setUcValue(ucTrackToValue(x), true);
}
function endUcDrag(e) {
  if (!ucDragging) return;
  ucDragging = false;
  toast(`${t('uc.thumbMoved')} · ${ucValue}/100`);
}
if (ucTrackBig) {
  ucTrackBig.addEventListener('mousedown', startUcDrag);
  document.addEventListener('mousemove', moveUcDrag);
  document.addEventListener('mouseup', endUcDrag);
  ucTrackBig.addEventListener('touchstart', startUcDrag, { passive: false });
  document.addEventListener('touchmove', moveUcDrag, { passive: false });
  document.addEventListener('touchend', endUcDrag);
  // 键盘
  ucTrackBig.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft')  { e.preventDefault(); setUcValue(ucValue - 1); }
    if (e.key === 'ArrowRight') { e.preventDefault(); setUcValue(ucValue + 1); }
    if (e.key === 'Home')       { e.preventDefault(); setUcValue(UC_MIN); }
    if (e.key === 'End')        { e.preventDefault(); setUcValue(UC_MAX); }
  });
}
// 初始化
setUcValue(ucValue, true);

/* —— 上下文窗口卡片：点击 → 弹出详细 Popover —— */
const contextCard = document.getElementById('context-card');
contextCard?.addEventListener('click', () => openPopover('pop-ctx', contextCard));
contextCard?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openPopover('pop-ctx', contextCard); }
});
document.getElementById('ctx-pop-close')?.addEventListener('click', closeActivePopover);

/* —— 点击外部关闭所有 popover —— */
document.addEventListener('click', (e) => {
  if (!e.target.closest('.popover') &&
      !e.target.closest('#context-card') &&
      !e.target.closest('#ultracode-toggle')) {
    closeActivePopover();
  }
});
document.getElementById('context-card')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    e.currentTarget.click();
  }
});

/* —— 数字快捷键 1-3 切换DeepSeek模型 —— */
document.addEventListener('keydown', (e) => {
  if (document.activeElement.tagName === 'TEXTAREA' || document.activeElement.tagName === 'INPUT') return;
  if (modelSelect && !modelSelect.disabled && e.key >= '1' && e.key <= '3') {
    const items = document.querySelectorAll('#dd-model .dd-item');
    const idx = parseInt(e.key, 10) - 1;
    if (items[idx]) items[idx].click();
  }
});

/* —— 移除 footer 状态栏：旧 sb-status 引用安全 fallback —— */
const sbFallback = document.getElementById('sb-status');
if (sbFallback) sbFallback.remove();

/* —— 阶段进度条构建 —— */
const STAGES = [
  { name: '选题', state: 'todo', icon: 'crosshair' },
  { name: '开题', state: 'todo', icon: 'clipboard-check' },
  { name: '文献', state: 'todo', icon: 'book-open' },
  { name: '综述', state: 'todo', icon: 'layers' },
  { name: '大纲', state: 'todo', icon: 'list-tree' },
  { name: '撰写', state: 'todo', icon: 'pen-line' },
  { name: '润色', state: 'todo', icon: 'sparkles' },
  { name: '引用', state: 'todo', icon: 'quote' },
  { name: '排版', state: 'todo', icon: 'layout-template' },
  { name: '定稿', state: 'todo', icon: 'badge-check' },
];

function renderLucideIcons() {
  if (window.lucide && typeof window.lucide.createIcons === 'function') {
    try {
      window.lucide.createIcons({
        attrs: { 'aria-hidden': 'true', focusable: 'false' },
        nameAttr: 'data-lucide',
      });
      // Lucide按[data-lucide]扫描整页；移除已渲染SVG的扫描标记，
      // 后续新消息只处理新增图标，不反复替换旧节点。
      document.querySelectorAll('svg[data-lucide]').forEach((icon) => {
        icon.removeAttribute('data-lucide');
      });
    }
    catch { /* 图标渲染失败不阻塞业务 */ }
  }
}

const stageBar = document.getElementById('stage-bar');
function renderEmptyStages() {
  stageBar.innerHTML = '';
  STAGES.forEach((s, i) => {
    const node = document.createElement('div');
    node.className = 'stage-node';
    node.innerHTML = (
      `<div class="stage-dot"><i data-lucide="${s.icon}" class="stage-icon"></i></div>`
      + `<div class="stage-label">${s.name}</div>`
    );
    node.title = `${i+1}. ${s.name} · 未开始`;
    stageBar.appendChild(node);
    if (i < STAGES.length - 1) {
      const line = document.createElement('div');
      line.className = 'stage-line';
      stageBar.appendChild(line);
    }
  });
}
renderEmptyStages();
renderLucideIcons();

/* —— 工具卡展开 —— */
document.querySelectorAll('.tool-card-head').forEach(head => {
  head.addEventListener('click', () => {
    head.parentElement.classList.toggle('open');
  });
});

/* —— 知识库面板页签 —— */
document.querySelectorAll('.kb-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    activateWorkbenchTab(tab.dataset.tab);
  });
  tab.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...document.querySelectorAll('.kb-tab')];
    const index = tabs.indexOf(tab);
    const nextIndex = event.key === 'Home' ? 0
      : event.key === 'End' ? tabs.length - 1
      : event.key === 'ArrowRight' ? (index + 1) % tabs.length
      : (index - 1 + tabs.length) % tabs.length;
    tabs[nextIndex].focus();
    activateWorkbenchTab(tabs[nextIndex].dataset.tab);
  });
});

function activateWorkbenchTab(target) {
  document.querySelectorAll('.kb-tab').forEach(tab => {
    const active = tab.dataset.tab === target;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll('.kb-pane').forEach(pane => {
    const active = pane.dataset.pane === target;
    pane.classList.toggle('active', active);
    pane.hidden = !active;
  });
  const sid = currentKnowledgeSession || currentSession || 'default';
  let loading = Promise.resolve();
  if (target === 'refs') {
    if (currentSession) loading = Promise.resolve(loadKbPanel(sid));
    else {
      const empty = document.getElementById('kb-refs-empty');
      if (empty) empty.style.display = '';
    }
  }
  if (target === 'notes') loading = Promise.resolve(loadNotes(sid));
  if (target === 'graph') loading = Promise.resolve(renderGraph(sid));
  if (target === 'memory') loading = Promise.resolve(window.ThesisProjectMemory.loadPanel());
  if (target === 'evidence') loading = Promise.resolve(window.ThesisEvidence.loadPanel());
  if (target === 'research') loading = Promise.resolve(loadResearchPanel());
  if (target === 'writing') loading = Promise.resolve(loadSectionsPanel());
  if (target === 'jobs') loading = Promise.resolve(loadJobsPanel());
  scheduleWorkspaceSave({
    active_tab: target,
    last_task_id: currentSession || workspaceState.last_task_id || '',
  });
  return loading;
}

/* —— 折叠知识库面板 —— */
const workspace = document.getElementById('workspace');
const toggleKb = document.getElementById('toggle-kb');
const closeKb = document.getElementById('close-kb');
function toggleKbPanel() {
  const collapsed = workspace.classList.toggle('kb-collapsed');
  toggleKb.setAttribute('aria-expanded', String(!collapsed));
}
toggleKb.addEventListener('click', toggleKbPanel);
closeKb.addEventListener('click', toggleKbPanel);

/* —— 会话项切换 —— */
document.querySelectorAll('.session-item').forEach(item => {
  item.addEventListener('click', (e) => {
    if (e.target.closest('.session-delete')) return;
    document.querySelectorAll('.session-item').forEach(s => s.classList.remove('active'));
    item.classList.add('active');
    toast('已切换对话');
  });
});

/* —— 删除会话（模态） —— */
const delModal = document.getElementById('del-modal');
const delName = document.getElementById('del-name');
let pendingDelete = null;
document.querySelectorAll('.session-delete').forEach(btn => {
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    pendingDelete = btn.closest('.session-item');
    delName.textContent = pendingDelete.querySelector('.session-title').textContent;
    showAccessibleDialog(delModal, document.getElementById('del-cancel'));
  });
});
document.getElementById('del-cancel').addEventListener('click', () => {
  hideAccessibleDialog(delModal);
  pendingDelete = null;
});
document.getElementById('del-confirm').addEventListener('click', async () => {
  if (pendingDelete) {
    const taskId = pendingDelete.dataset.task;
    const r = await apiDeleteSession(taskId);
    if (r.code === 0) {
      if (currentSession === taskId) {
        window.ThesisAutosave?.resetAutosaveIdentity?.();
        currentSession = null;
        currentSessionTitle = '';
        currentKnowledgeSession = '';
      }
      workspaceState = { ...workspaceState, expanded_items: [], editor_anchor: '' };
      applyWorkspaceExpandedItems();
      hideResumeBanner();
      const result = await loadSessions();
      // 只有列表请求明确成功时，才把实际回退选中的任务写回；请求失败则保留服务端旧指针。
      if (result.ok) {
        scheduleWorkspaceSave({
          last_task_id: currentSession || '',
          active_tab: workspaceState.active_tab || 'refs',
          expanded_items: [],
          editor_anchor: '',
        });
      }
      toast(r.msg || '对话已删除');
    } else {
      toast('删除失败: ' + (r.msg || ''));
    }
  }
  hideAccessibleDialog(delModal);
  pendingDelete = null;
});
delModal.addEventListener('click', (e) => {
  if (e.target === delModal) {
    hideAccessibleDialog(delModal);
    pendingDelete = null;
  }
});

/* —— 确认闸门按钮 —— */
document.querySelectorAll('[data-gate]').forEach(btn => {
  btn.addEventListener('click', () => {
    btn.disabled = true;
    btn.innerHTML = '✓ 已确认';
    toast('已进入下一环节');
    // 进度条：将 current 推进到下一节点
    const cur = document.querySelector('.stage-node.current');
    if (cur) {
      cur.classList.remove('current');
      cur.classList.add('done');
      const doneDot = cur.querySelector('.stage-dot');
      if (doneDot) {
        doneDot.innerHTML = '<i data-lucide="check" class="stage-icon"></i>';
        renderLucideIcons();
      }
      // 前一条线
      const prevLine = cur.previousElementSibling;
      if (prevLine && prevLine.classList.contains('stage-line')) prevLine.classList.add('done');
      // 下一节点变 current
      let next = cur.nextElementSibling;
      while (next && !next.classList.contains('stage-node')) next = next.nextElementSibling;
      if (next) next.classList.add('current');
    }
    document.getElementById('sb-status')?.remove();
    // 同时把页签 active 进度指示更新
    const tabLabel = document.querySelector('.title-tab.active');
    if (tabLabel && tabLabel.dataset.progressLabel) tabLabel.textContent = tabLabel.dataset.progressLabel;
  });
});

/* —— 输入框 —— */
const prompt = document.getElementById('prompt');
const sendBtn = document.getElementById('send-btn');
prompt.addEventListener('input', () => {
  sendBtn.disabled = prompt.value.trim().length === 0;
  prompt.style.height = 'auto';
  prompt.style.height = Math.min(prompt.scrollHeight, 200) + 'px';
});
prompt.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && !sendBtn.disabled) {
    e.preventDefault();
    sendMessage();
  }
});
sendBtn.addEventListener('click', sendMessage);

async function sendMessage() {
  const v = prompt.value.trim();
  if (!v) return;
  const flow = document.getElementById('chat-flow');
  const inner = flow.querySelector('.chat-inner');
  const msg = document.createElement('div');
  msg.className = 'msg user';
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  msg.innerHTML = `<div class="bubble">${escapeHtml(v)}</div><div class="msg-meta"><span>${hh}:${mm}</span></div>`;
  // 插入到末尾（input-area 之前自动滚动）
  const gateBlocks = inner.querySelectorAll('.gate-block');
  if (gateBlocks.length) {
    inner.insertBefore(msg, gateBlocks[gateBlocks.length - 1]);
  } else {
    inner.appendChild(msg);
  }
  prompt.value = '';
  prompt.style.height = 'auto';
  sendBtn.disabled = true;
  flow.scrollTop = flow.scrollHeight;

  if (!currentSession) {
    appendAIMsg('<p>请先在左侧新建或选择一个论文任务。</p>', '需要任务');
    return;
  }

  const command = v.replace(/\s+/g, '');
  const progress = await apiSessionProgress(currentSession);
  if (!progress) {
    appendAIMsg('<p>无法读取当前任务状态，请确认后端服务是否可用。</p>', '连接失败');
    return;
  }

  if (/确认|接受|通过当前/.test(command)) {
    if (!progress.can_confirm) {
      appendAIMsg('<p>当前没有待确认产物。请先执行当前环节并等待自动验收。</p>', '无法确认');
      return;
    }
    if (progress.author_decision_ready === false) {
      appendAIMsg(`<p>${escapeHtml2(progress.author_decision_blocker || '请先完成当前阶段的作者决策。')}</p>`, '需要作者操作');
      return;
    }
    appendGateBlock(
      progress.current_ring_no,
      progress.author_decision_ready !== false,
      progress.author_decision_blocker || '',
    );
    const gateButton = inner.querySelector(`.gate-block[data-ring="${progress.current_ring_no}"] [data-gate]`);
    await confirmNextRing({ currentTarget: gateButton });
    return;
  }

  if (/进度|状态|做到哪/.test(command)) {
    appendAIMsg(
      `<p>当前是<strong>环${progress.current_ring_no}（${RING_NAMES[progress.current_ring_no] || ''}）</strong>，状态为 <code>${escapeHtml2(progress.phase_state)}</code>，总体完成 ${progress.complete_percent}%。</p>`,
      '任务进度'
    );
    return;
  }

  if (/执行|运行|开始|继续/.test(command)) {
    if (progress.can_confirm) {
      appendAIMsg('<p>当前产物正在等待确认。请检查产物后输入“确认当前产物”，或点击确认按钮。</p>', '等待确认');
      appendGateBlock(
        progress.current_ring_no,
        progress.author_decision_ready !== false,
        progress.author_decision_blocker || '',
      );
      return;
    }
    await runCurrentRing();
    return;
  }

  appendAIMsg(
    '<p>当前命令入口支持“执行当前环节”“查看进度”“确认当前产物”。开放式论文问答将在分节写作接口完成后接入。</p>',
    '可用命令'
  );
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

/* ============================================================
   消息流产物渲染（环执行结果 → 对话流追加消息卡）
   ============================================================ */
const RING_NAMES = {1:'选题',2:'开题评审',3:'文献调研',4:'综述评审',5:'大纲',6:'撰写',7:'润色',8:'引用校验',9:'排版',10:'定稿'};

function appendUserMsg(text) {
  const flow = document.getElementById('chat-flow');
  const inner = flow.querySelector('.chat-inner');
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  const msg = document.createElement('div');
  msg.className = 'msg user';
  msg.innerHTML = `<div class="bubble">${escapeHtml(text)}</div><div class="msg-meta"><span>${hh}:${mm}</span></div>`;
  inner.appendChild(msg);
  flow.scrollTop = flow.scrollHeight;
  return msg;
}

function appendAIMsg(html, metaText) {
  const flow = document.getElementById('chat-flow');
  const inner = flow.querySelector('.chat-inner');
  const msg = document.createElement('div');
  msg.className = 'msg ai';
  msg.innerHTML = `<div class="bubble">${html}</div>${metaText ? `<div class="msg-meta"><span>${metaText}</span></div>` : ''}`;
  inner.appendChild(msg);
  renderLucideIcons();
  flow.scrollTop = flow.scrollHeight;
  return msg;
}

function escapeHtml2(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

const TRUST_STATUS_LABELS = {
  PASSED: '已通过',
  PARTIAL: '部分完成',
  FAILED: '未通过',
  NOT_ASSESSED: '未评估',
  PENDING: '待作者复核',
  APPROVED: '作者已确认',
  REJECTED: '作者已驳回',
};

function trustStatusClass(status) {
  if (status === 'PASSED' || status === 'APPROVED') return 'ok';
  if (status === 'FAILED' || status === 'REJECTED') return 'bad';
  return 'warn';
}

function renderTrustAssessment(assessment, compact = false) {
  if (!assessment?.dimensions) {
    return '<section class="trust-assessment is-empty" aria-label="引用可信度分档"><div class="wb-card-meta">尚未生成环8分档核验结果。</div></section>';
  }
  const order = ['structure', 'metadata', 'evidence'];
  const dimensions = order.map(key => {
    const item = assessment.dimensions[key] || {};
    const status = item.status || 'NOT_ASSESSED';
    return `<div class="trust-dimension" data-trust-status="${escapeHtml2(status)}">
      <span class="trust-dimension-label">${escapeHtml2(item.label || key)}</span>
      <span class="wb-status ${trustStatusClass(status)}">${escapeHtml2(TRUST_STATUS_LABELS[status] || status)}</span>
      ${compact ? '' : `<span class="trust-dimension-summary">${escapeHtml2(item.summary || '')}</span>`}
    </div>`;
  }).join('');
  const review = assessment.author_review || {};
  const reviewStatus = review.status || 'PENDING';
  return `<section class="trust-assessment" aria-label="引用可信度分档">
    <div class="trust-assessment-head">最高可声明层级：<strong>${escapeHtml2(assessment.highest_tier_label || assessment.highest_tier || '未评估')}</strong></div>
    <div class="trust-dimensions">${dimensions}</div>
    <div class="trust-author-review"><span>${escapeHtml2(review.label || '作者复核')}</span><span class="wb-status ${trustStatusClass(reviewStatus)}">${escapeHtml2(TRUST_STATUS_LABELS[reviewStatus] || reviewStatus)}</span></div>
    ${assessment.warning ? `<p class="trust-warning"><i data-lucide="alert-triangle" class="icon-xs"></i> ${escapeHtml2(assessment.warning)}</p>` : ''}
  </section>`;
}

window.ThesisTrustUI = Object.freeze({
  renderAssessment: renderTrustAssessment,
});

// —— 环执行结果 → 消息卡 ——
function renderRingResult(ringNo, data) {
  const name = RING_NAMES[ringNo] || ('环' + ringNo);
  if (ringNo === 1) {
    // 选题：候选题目卡（可点选）
    const cands = (data && data.candidates) || [];
    const selectedIndex = Number.isInteger(data?.selected_candidate_index)
      ? data.selected_candidate_index : null;
    const rec = data && data.recommendation ? `<p style="color:var(--text-subtle);font-size:13px;">${escapeHtml2(data.recommendation)}</p>` : '';
    appendAIMsg(`<p><strong>环1 选题完成</strong>，请选择一个候选题目后再确认：</p>` +
      cands.map((c, i) => `<button class="cand-item" type="button" aria-pressed="false" data-candidate-index="${i}" data-title="${escapeHtml2(c.title)}" style="display:block;width:100%;text-align:start;margin:6px 0;padding:8px 10px;border:1px solid var(--border-divider);border-radius:8px;cursor:pointer;transition:border-color .15s,background .15s;"><span style="display:block"><strong>${i+1}. ${escapeHtml2(c.title)}</strong></span><span style="display:block;color:var(--text-subtle);font-size:13px;">创新点：${escapeHtml2(c.innovation)}</span></button>`).join('') + rec,
      `${name} · 已完成`);
    // 绑定点选
    document.querySelectorAll('.cand-item').forEach(el => {
      el.addEventListener('click', async () => {
        const buttons = [...document.querySelectorAll('.cand-item')];
        buttons.forEach(button => { button.disabled = true; });
        const response = await apiSelectCandidate(
          currentSession,
          Number(el.dataset.candidateIndex),
          el.dataset.title,
        );
        buttons.forEach(button => { button.disabled = false; });
        if (response.code !== 0) {
          toast(`题目选择保存失败：${response.msg}`);
          return;
        }
        document.querySelectorAll('.cand-item').forEach(x => x.style.borderColor = 'var(--border-divider)');
        document.querySelectorAll('.cand-item').forEach(x => {
          x.style.background = '';
          x.setAttribute('aria-pressed', 'false');
        });
        el.style.borderColor = 'var(--claude)';
        el.style.background = 'var(--claude-soft)';
        el.setAttribute('aria-pressed', 'true');
        setGateReady(1, true);
        toast('作者选择已保存：' + el.dataset.title);
        // 作者决定已改变，横幅必须从“作者决定”推进到“待确认”。
        await refreshVisibleResumeSummary();
      });
    });
    if (selectedIndex !== null) {
      const selected = document.querySelector(`.cand-item[data-candidate-index="${selectedIndex}"]`);
      if (selected) {
        selected.style.borderColor = 'var(--claude)';
        selected.style.background = 'var(--claude-soft)';
        selected.setAttribute('aria-pressed', 'true');
      }
    }
  } else if (ringNo === 3) {
    // 文献调研：文献卡（跳转下载真链接 + 真复制 GB/T 7714）
    const items = (data && (data.candidate_items || data.items || [])) || [];
    const curated = Boolean(data?.curated);
    const includedIndexes = new Set(data?.included_indexes || []);
    appendAIMsg(`<p><strong>环3 文献调研完成</strong>，检索到 <strong>${items.length}</strong> 篇候选文献。请取消低相关条目并保存筛选：</p>` +
      items.map((it, index) => {
        const url = it.urls && it.urls[0] ? it.urls[0] : '';
        const doiUrl = it.doi ? `https://doi.org/${encodeURIComponent(it.doi)}` : '';
        const href = url || doiUrl || '';
        const checked = !curated || includedIndexes.has(index);
        const relevance = Number(it.relevance_score || 0);
        const relevanceLabel = relevance > 0 ? `相关度 ${Math.round(relevance * 100)}%` : '相关度待评估';
        const relevanceTerms = (it.relevance_terms || []).slice(0, 4).join('、');
        return `<div class="ref-card" data-literature-card style="margin:8px 0;"><label class="file-choice"><input type="checkbox" class="ring3-include" data-literature-index="${index}" ${checked ? 'checked' : ''} ${curated ? 'disabled' : ''}> 纳入论文项目</label><div class="ref-head"><div class="ref-title">${escapeHtml2(it.title)}</div><span class="badge ${it.reliability || 'matched'}">${escapeHtml2(it.reliability || 'matched')}</span></div><div class="wb-card-meta literature-relevance">${escapeHtml2(relevanceLabel)}${relevanceTerms ? ` · 命中：${escapeHtml2(relevanceTerms)}` : ''}</div><div class="ref-citation">${escapeHtml2(it.gbt7714 || '')}</div><div class="ref-actions">${href ? `<a class="link-btn" href="${escapeHtml2(href)}" target="_blank" rel="noopener">跳转下载</a>` : ''}<button class="icon-btn" type="button" onclick="copyText(${JSON.stringify(escapeHtml2(it.gbt7714 || ''))})">复制 GB/T 7714</button>${curated ? '' : `<button class="icon-btn literature-move" type="button" data-literature-move="up" aria-label="上移文献：${escapeHtml2(it.title)}">上移</button><button class="icon-btn literature-move" type="button" data-literature-move="down" aria-label="下移文献：${escapeHtml2(it.title)}">下移</button>`}</div></div>`;
      }).join('') + `<div class="wb-card-actions"><button class="btn btn-primary btn-sm" type="button" id="save-literature-curation" ${curated ? 'disabled' : ''}>${curated ? `已保存：纳入 ${includedIndexes.size} 条` : '保存文献筛选并登记知识库'}</button></div><div id="literature-curation-error" class="wb-card-meta" role="alert" style="color:var(--error)"></div>`,
      `${name} · 已完成`);
    document.getElementById('save-literature-curation')?.addEventListener('click', async event => {
      const button = event.currentTarget;
      const included = [...document.querySelectorAll('.ring3-include:checked')]
        .map(input => Number(input.dataset.literatureIndex));
      const error = document.getElementById('literature-curation-error');
      if (!included.length) {
        error.textContent = '至少保留一条文献。';
        return;
      }
      button.disabled = true;
      error.textContent = '';
      const response = await apiCurateLiterature(currentSession, included);
      if (response.code !== 0) {
        button.disabled = false;
        error.textContent = response.msg;
        return;
      }
      document.querySelectorAll('.ring3-include').forEach(input => { input.disabled = true; });
      button.textContent = `已保存：纳入 ${response.data?.included_count || included.length} 条`;
      setGateReady(3, true);
      await loadKbPanel(currentKnowledgeSession || currentSession);
      toast(response.msg);
      await refreshVisibleResumeSummary();
    });
    document.querySelectorAll('.literature-move').forEach(button => {
      button.addEventListener('click', () => {
        const card = button.closest('[data-literature-card]');
        if (!card) return;
        if (button.dataset.literatureMove === 'up' && card.previousElementSibling?.matches('[data-literature-card]')) {
          card.parentElement.insertBefore(card, card.previousElementSibling);
        } else if (button.dataset.literatureMove === 'down' && card.nextElementSibling?.matches('[data-literature-card]')) {
          card.parentElement.insertBefore(card.nextElementSibling, card);
        }
      });
    });
    if (curated) setGateReady(3, true);
  } else if (ringNo === 2 || ringNo === 4) {
    // 评审卡（新颖度/综述评审）
    const level = (data && data.novelty_level) || '';
    const badgeColor = level === 'HIGH' ? 'var(--success)' : level === 'LOW' ? 'var(--error)' : 'var(--warning)';
    const similar = data && data.similar_count != null ? data.similar_count : (data.relevant_count ?? 0);
    const diff = data && data.differ_from_prior ? `<p style="margin:8px 0;"><strong>与前人不同：</strong>${escapeHtml2(data.differ_from_prior)}</p>` : '';
    const rec = data && data.recommendation ? `<p style="margin:8px 0;"><strong>建议：</strong>${escapeHtml2(data.recommendation)}</p>` : '';
    appendAIMsg(
      `<p><strong>环${ringNo} ${name} 完成</strong>&nbsp;<span class="badge" style="background:${badgeColor}1a;color:${badgeColor};border:1px solid ${badgeColor}33;">${escapeHtml2(level || data.verdict || '完成')}</span></p>` +
      `<p style="font-size:13px;color:var(--text-subtle);">相似研究：<strong>${similar}</strong> 条</p>${diff}${rec}`,
      `${name} · 已完成`);
  } else if (ringNo === 5) {
    // 大纲卡（章节树）
    const chapters = (data && data.chapters) || [];
    const levels = chapters.filter(c => c.level === 1);
    const contracted = chapters.filter(c => c.section_contract);
    const contractDetails = contracted.length
      ? `<details class="section-contract-summary"><summary>查看 ${contracted.length} 个分节写作合同</summary><ul>${contracted.map(ch => {
          const contract = ch.section_contract || {};
          const claims = (contract.allowed_claim_keys || []).join('、') || '仅结构性说明';
          const evidenceCount = (contract.required_evidence_ids || []).length;
          const resultRule = contract.requires_verified_results ? '必须使用已核验结果' : '无强制结果';
          return `<li><strong>${escapeHtml2(ch.number || '')} ${escapeHtml2(ch.title || '')}</strong><span>目标：${escapeHtml2(contract.purpose || '')}</span><span>允许论断：${escapeHtml2(claims)} · 必需证据 ${evidenceCount} 条 · ${escapeHtml2(resultRule)}</span></li>`;
        }).join('')}</ul><p>合同集 Hash：${escapeHtml2((data.contract_hash || '').slice(0, 12))}</p></details>`
      : '<p class="wb-card-meta">当前大纲没有可写作的叶子节点合同。</p>';
    appendAIMsg(`<p><strong>环5 大纲完成</strong>，共 <strong>${levels.length}</strong> 章：</p>` +
      levels.map(ch => `<p style="margin:5px 0;font-size:13px;"><i data-lucide="file-text" class="icon-xs" style="vertical-align:-2px"></i> ${escapeHtml2(ch.number || '')} ${escapeHtml2(ch.title)}</p>`).join('') +
      contractDetails,
      `${name} · 已完成`);
  } else if (ringNo === 6) {
    // 撰写卡
    const chapters = (data && data.chapters) || [];
    const words = data && data.total_words != null ? data.total_words : 0;
    appendAIMsg(`<p><strong>环6 撰写完成</strong>：<strong>${chapters.length}</strong> 章 · <strong>${words}</strong> 字</p>` +
      chapters.slice(0, 3).map(ch => `<p style="margin:4px 0;font-size:13px;color:var(--text-subtle);">${escapeHtml2(ch.chapter_title || '')}（${ch.word_count || 0} 字）</p>`).join(''),
      `${name} · 已完成`);
  } else if (ringNo === 7) {
    // 润色卡
    const words = data && data.total_words != null ? data.total_words : 0;
    const terms = (data && data.applied_terms) || [];
    appendAIMsg(`<p><strong>环7 润色完成</strong>（只改表达不改事实）：${words} 字</p>` +
      (terms.length ? `<p style="font-size:13px;color:var(--text-subtle);">术语统一：${terms.slice(0,3).map(t => escapeHtml2(t)).join('、')}</p>` : ''),
      `${name} · 已完成`);
  } else if (ringNo === 8) {
    // 引用检查卡：流程完成不等于正文证据通过。
    const total = data && data.total != null ? data.total : 0;
    const passed = data && data.passed != null ? data.passed : 0;
    const failed = data && data.failed != null ? data.failed : 0;
    const uncertain = data && data.uncertain != null ? data.uncertain : 0;
    const trust = data?.trust_assessment || {};
    appendAIMsg(`<p><strong>环8 引用检查完成</strong>：共 <strong>${total}</strong> 条</p>` +
      `<p style="font-size:13px;">题录命中 ${passed} · 待人工 ${uncertain} · 未命中/阻断项 ${failed}</p>` +
      renderTrustAssessment(trust) +
      (failed > 0 ? `<p style="font-size:12px;color:var(--error)">存在阻断项，请根据分档摘要回到文献或证据环节处理。</p>` : ''),
      `${name} · ${escapeHtml2(trust.highest_tier_label || '已完成检查')}`);
  } else if (ringNo === 9) {
    // 排版卡
    const compliant = data && data.compliant;
    const issues = (data && data.issues) || [];
    appendAIMsg(`<p><strong>环9 排版检查${compliant ? '通过' : '未通过'}</strong></p>` +
      (issues.length ? `<p style="font-size:13px;color:var(--warning);">${issues.slice(0,3).map(i => escapeHtml2(i.message || i)).join('<br>')}</p>` : `<p style="font-size:13px;color:var(--success);">版式合规（0 硬伤）</p>`),
      `${name} · ${compliant ? '通过' : '未通过'}`);
  } else if (ringNo === 10) {
    // 定稿卡（验收汇总）
    const rings = (data && data.rings) || [];
    const passCount = rings.filter(r => r.status === '通过').length;
    const missing = (data && data.materials_missing) || [];
    appendAIMsg(`<p><strong>环10 定稿汇总</strong>：${passCount}/9 环通过</p>` +
      (missing.length ? `<p style="font-size:13px;color:var(--warning);">待补材料：${missing.map(m => escapeHtml2(m)).join('、')}</p>` : `<p style="font-size:13px;color:var(--success);">材料齐备，可提交！</p>`),
      `${name} · ${missing.length ? '待补' : '通过'}`);
  } else {
    // 通用产物卡
    const text = data && (data.summary || data.msg || '');
    appendAIMsg(`<p><strong>环${ringNo} ${name} 完成</strong></p><p style="font-size:13px;color:var(--text-subtle);">${escapeHtml2(text)}</p>`, `${name} · 已完成`);
  }
}

// —— 追加"确认进入下一环"闸门 ——
function appendGateBlock(ringNo, ready = true, blocker = '') {
  const flow = document.getElementById('chat-flow');
  const inner = flow.querySelector('.chat-inner');
  if (inner.querySelector(`.gate-block[data-ring="${ringNo}"]`)) {
    setGateReady(ringNo, ready, blocker);
    return;
  }
  const gate = document.createElement('div');
  gate.className = 'gate-block';
  gate.dataset.ring = String(ringNo);
  const gateHint = ringNo === 8
    ? '引用分档检查已完成；请确认你理解当前最高可声明层级'
    : '已完成自动校验，待您确认后进入下一环';
  const gateLabel = ringNo === 8
    ? '「引用校验」流程已完成；结构/题录通过不代表正文证据通过'
    : `「${RING_NAMES[ringNo] || '环' + ringNo}」环节已通过自动验收`;
  gate.innerHTML = `<div class="gate-hint"><span class="gate-dot"></span>${gateHint}</div>
    <div class="gate-row"><span class="gate-label">${gateLabel}</span>
    <button class="btn btn-primary" data-gate data-ring="${ringNo}" ${ready ? '' : 'disabled'}>${ready ? (ringNo === 10 ? '确认完成论文' : '确认进入下一环') : escapeHtml2(blocker || '请先完成作者决策')}</button></div>`;
  inner.appendChild(gate);
  const btn = gate.querySelector('[data-gate]');
  if (!btn.dataset.bound) { btn.dataset.bound = '1'; btn.addEventListener('click', confirmNextRing); }
  flow.scrollTop = flow.scrollHeight;
}

function setGateReady(ringNo, ready, blocker = '') {
  const button = document.querySelector(`.gate-block[data-ring="${ringNo}"] [data-gate]`);
  if (!button) return;
  button.disabled = !ready;
  button.textContent = ready
    ? (ringNo === 10 ? '确认完成论文' : '确认进入下一环')
    : (blocker || '请先完成作者决策');
}

// —— 执行环 + 追加消息 ——
async function runRingShow(taskId, ringNo, path) {
  appendUserMsg(`执行环${ringNo}（${RING_NAMES[ringNo] || ''}）`);
  const r = await apiRunRing(taskId, path);
  if (r.code === 0) {
    renderRingResult(ringNo, r.data);
    // 追加"确认进入下一环"闸门（双重验证）
    appendGateBlock(
      ringNo,
      ![1, 3].includes(ringNo),
      ringNo === 1 ? '请先选择候选题目' : '请先完成文献筛选',
    );
    toast(r.msg || `环${ringNo} 完成`);
  } else {
    // 评审未通过：警告卡 + 回退/重新生成
    const fb = (r.data && r.data.fallbackTo) || (r.data && r.data.fallBackTo);
    appendAIMsg(`<div class="warn-card" style="margin:8px 0;"><div class="warn-title">环${ringNo} 评审未通过</div><div style="font-size:13px;">${escapeHtml2(r.msg || '')}</div><div class="warn-actions"><button class="btn btn-primary btn-sm" onclick="runCurrentRing()">重新生成</button>${fb ? `<button class="btn btn-secondary btn-sm" onclick="rollbackRing(${fb})">回退到环${fb}</button>` : ''}</div></div>`, '评审未通过');
  }
  await loadSessionDetail(taskId);
  await loadSessions();
  await refreshVisibleResumeSummary();
}

/* —— 从失败 Gate 安全回到契约允许的上游环节 —— */
async function rollbackRing(targetRingNo) {
  if (!currentSession) return;
  const r = await apiReopenStage(
    currentSession,
    targetRingNo,
    `作者从失败环节回到环${targetRingNo}修订`,
  );
  if (r.code !== 0) {
    toast('回退失败: ' + (r.msg || ''));
    return;
  }
  document.querySelectorAll('.gate-block').forEach(element => element.remove());
  toast(r.msg);
  await loadSessionDetail(currentSession);
  await loadSessions();
  await refreshVisibleResumeSummary();
  appendAIMsg(`<p><strong>已回到环${targetRingNo}</strong>（${RING_NAMES[targetRingNo] || ''}）。请完成修订后重新执行。</p>`, `恢复 · 环${targetRingNo}`);
}



/* —— Toast —— */
let toastTimer = null;
const toastEl = document.getElementById('toast');
function toast(text) {
  toastEl.textContent = text;
  toastEl.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toastEl.classList.remove('show'), 1800);
}

const dialogReturnFocus = new WeakMap();
function showAccessibleDialog(container, initialFocus) {
  if (!container) return;
  dialogReturnFocus.set(container, document.activeElement);
  container.classList.add('show');
  requestAnimationFrame(() => {
    const target = initialFocus || container.querySelector('input, textarea, select, button, [tabindex]:not([tabindex="-1"])');
    target?.focus();
  });
}
function hideAccessibleDialog(container) {
  if (!container) return;
  container.classList.remove('show');
  const trigger = dialogReturnFocus.get(container);
  if (trigger && document.contains(trigger)) trigger.focus();
  dialogReturnFocus.delete(container);
}
function visibleModalContainer() {
  return [...document.querySelectorAll('.modal-mask.show, .settings-overlay.show, .node-drawer.show')].at(-1) || null;
}
document.addEventListener('keydown', event => {
  const container = visibleModalContainer();
  if (!container || event.key !== 'Tab') return;
  const focusable = [...container.querySelectorAll('button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])')]
    .filter(element => element.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0], last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});

/* —— ESC 关闭模态 —— */
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (delModal.classList.contains('show')) {
      hideAccessibleDialog(delModal);
      pendingDelete = null;
    }
    const nsModal = document.getElementById('new-session-modal');
    if (nsModal && nsModal.classList.contains('show')) hideAccessibleDialog(nsModal);
  }
});

/* —— 新建对话由 initApp 统一绑定（handleNewSession） —— */

/* —— 复制文本到剪贴板（真复制，带回退） —— */
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('已复制到剪贴板');
  } catch (e) {
    // 非安全上下文（http://127.0.0.1 之外的本地文件）回退 execCommand
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); toast('已复制到剪贴板'); }
    catch (e2) { toast('复制失败，请手动复制'); }
    document.body.removeChild(ta);
  }
}

/* ============================================================
   i18n 国际化系统（中英双语）
   ============================================================ */
const I18N = {
  'zh-CN': {
    'user.name': 'Deep Thesis',
    'user.role': '论文工作台',
    'menu.gateway': '网关',
    'menu.settings': '设置',
    'menu.language': '语言',
    'menu.inference': '推理配置',
    'menu.changelog': '查看更新日志',
    'menu.about': '了解更多',
    'menu.logout': '注销',
    'settings.title': '设置',
    'settings.search': '搜索',
    'settings.section.account': '设置',
    'settings.section.desktop': '桌面应用',
    'settings.section.custom': '自定义',
    'settings.nav.general': '一般',
    'settings.nav.privacy': '隐私',
    'settings.nav.usage': '用量',
    'settings.nav.cc': 'Claude Code',
    'settings.nav.cowork': 'Cowork',
    'settings.nav.appGeneral': '一般',
    'settings.nav.dev': '开发者',
    'settings.nav.skills': '技能',
    'settings.nav.connectors': '连接器',
    'settings.nav.plugins': '插件',
    'settings.tab.basic.title': '一般',
    'settings.tab.basic.item1': '默认开启智能建议',
    'settings.tab.cc.title': 'Claude Code',
    'settings.tab.cc.appearance': '代码外观',
    'settings.tab.cc.appearanceLight': 'Claude 浅色',
    'settings.tab.cc.appearanceDark': 'Claude 深色',
    'settings.tab.cc.font': '代码字体',
    'settings.tab.cc.fontDesc': '为代码和终端设置自定义等宽字体。',
    'settings.tab.cc.fontPh': '例如 JetBrains Mono',
    'settings.tab.appearance.title': '外观',
    'settings.tab.appearance.contrast': '高对比度深色主题',
    'settings.tab.appearance.contrastDesc': '开启深色模式时使用更暗、接近黑色的背景。',
    'settings.tab.appearance.uiFont': '界面字体',
    'settings.tab.appearance.uiFontDesc': 'Claude Code 界面字体，包括菜单、侧边栏和聊天。',
    'settings.tab.appearance.tts': '转录文本大小',
    'settings.tab.appearance.ttsDesc': '转录呈现文本的大小。',
    'settings.tab.appearance.tts.s': '小',
    'settings.tab.appearance.tts.m': '中',
    'settings.tab.appearance.tts.l': '大',
    'inference.title': '推理配置',
    'inference.desc': '本阶段仅支持DeepSeek接口。配置只在当前后端进程内生效，重启后恢复.env设置。',
    'modal.ok': '好的',
    'modal.cancel': '取消',
    'toast.settings.open': '已打开设置（设置面板演示中）',
    'toast.changelog': '当前已是最新版本',
    'toast.lang.switched': '已切换到中文',
    'toast.lang.switchedEn': 'Switched to English',
    'toast.theme': '已切换主题',
    'toast.menu.placeholder': '功能开发中',
    'common.system': '系统',
    'newChat': '新建对话',
    'tasks.all': 'All tasks',
    'search.label': '搜索论文任务',
    'search.placeholder': '搜索对话 / 主题 / 文献…',
    'search.empty': '暂无论文任务',
    'search.noMatches': '没有匹配的论文任务',
    'search.count': '共 {total} 个论文任务',
    'search.countOne': '共 {total} 个论文任务',
    'search.countFiltered': '显示 {visible} 个，共 {total} 个论文任务',
    'search.countFilteredOne': '显示 {visible} 个，共 {total} 个论文任务',
    'input.bypass': '逐环确认',
    'input.placeholder': '输入命令：执行当前环节 / 查看进度 / 确认当前产物',
    'toast.bypass.on': '已切换：逐环确认',
    'toast.bypass.off': '已切换：自动运行',
    'ctx.label': '上下文窗口',
    'dd.model.head': '模型',
    'dd.model.visionExp': 'deepseek-v4-flash-vision-exp',
    'dd.model.visionExp1m': 'deepseek-v4-flash-vision-exp',
    'dd.model.flash': 'deepseek-v4-flash',
    'dd.model.flash1m': 'deepseek-v4-flash',
    'dd.model.pro': 'deepseek-v4-pro',
    'dd.model.pro1m': 'deepseek-v4-pro',
    'dd.model.pro2m': 'deepseek-v4-pro',
    'dd.perm.head': '模式',
    'dd.perm.manual': '手动',
    'dd.perm.acceptEdits': '接受编辑',
    'dd.perm.plan': '计划',
    'dd.perm.bypass': '绕过权限',
    'dd.add.file': '添加文件或照片',
    'dd.add.folder': '添加文件夹',
    'dd.add.slash': '斜线命令',
    'dd.add.connector': '添加连接器',
    'dd.add.plugin': '插件',
    'uc.thinkDepth': '思考深度',
    'uc.current': '当前强度',
    'uc.thumbMoved': '思考强度已调整',
    'ctx.legend.used': '已使用',
    'ctx.legend.free': '剩余',
    'ctx.detail.system': '系统提示',
    'ctx.detail.user': '用户消息',
    'ctx.detail.tools': '工具调用',
    'ctx.detail.output': '模型输出',
  },
  'en-US': {
    'user.name': 'Deep Thesis',
    'user.role': 'Thesis workspace',
    'menu.gateway': 'Gateway',
    'menu.settings': 'Settings',
    'menu.language': 'Language',
    'menu.inference': 'Inference config',
    'menu.changelog': 'View changelog',
    'menu.about': 'Learn more',
    'menu.logout': 'Log out',
    'settings.title': 'Settings',
    'settings.search': 'Search',
    'settings.section.account': 'Settings',
    'settings.section.desktop': 'Desktop app',
    'settings.section.custom': 'Customize',
    'settings.nav.general': 'General',
    'settings.nav.privacy': 'Privacy',
    'settings.nav.usage': 'Usage',
    'settings.nav.cc': 'Claude Code',
    'settings.nav.cowork': 'Cowork',
    'settings.nav.appGeneral': 'General',
    'settings.nav.dev': 'Developer',
    'settings.nav.skills': 'Skills',
    'settings.nav.connectors': 'Connectors',
    'settings.nav.plugins': 'Plugins',
    'settings.tab.basic.title': 'General',
    'settings.tab.basic.item1': 'Enable smart suggestions by default',
    'settings.tab.cc.title': 'Claude Code',
    'settings.tab.cc.appearance': 'Code appearance',
    'settings.tab.cc.appearanceLight': 'Claude light',
    'settings.tab.cc.appearanceDark': 'Claude dark',
    'settings.tab.cc.font': 'Code font',
    'settings.tab.cc.fontDesc': 'Set a custom monospace font for code and terminal.',
    'settings.tab.cc.fontPh': 'e.g. JetBrains Mono',
    'settings.tab.appearance.title': 'Appearance',
    'settings.tab.appearance.contrast': 'High-contrast dark theme',
    'settings.tab.appearance.contrastDesc': 'Use a darker, near-black background when dark mode is on.',
    'settings.tab.appearance.uiFont': 'Interface font',
    'settings.tab.appearance.uiFontDesc': 'Claude Code interface font — menus, sidebar, chat.',
    'settings.tab.appearance.tts': 'Transcript text size',
    'settings.tab.appearance.ttsDesc': 'Size of rendered transcript text.',
    'settings.tab.appearance.tts.s': 'S',
    'settings.tab.appearance.tts.m': 'M',
    'settings.tab.appearance.tts.l': 'L',
    'inference.title': 'Inference config',
    'inference.desc': 'This stage supports the DeepSeek API only. Runtime configuration resets to .env after restart.',
    'modal.ok': 'OK',
    'modal.cancel': 'Cancel',
    'toast.settings.open': 'Opened Settings (panel preview)',
    'toast.changelog': 'You are up to date',
    'toast.lang.switched': '已切换到中文',
    'toast.lang.switchedEn': 'Switched to English',
    'toast.theme': 'Theme switched',
    'toast.menu.placeholder': 'Coming soon',
    'common.system': 'System',
    'newChat': 'New chat',
    'tasks.all': 'All tasks',
    'search.label': 'Search paper tasks',
    'search.placeholder': 'Search chats / topics / papers…',
    'search.empty': 'No paper tasks yet',
    'search.noMatches': 'No matching paper tasks',
    'search.count': '{total} paper tasks',
    'search.countOne': '{total} paper task',
    'search.countFiltered': 'Showing {visible} of {total} paper tasks',
    'search.countFilteredOne': 'Showing {visible} of {total} paper task',
    'input.bypass': 'Per-ring confirm',
    'input.placeholder': 'Command: run current ring / show progress / confirm artifact',
    'toast.bypass.on': 'Switched: Per-ring confirm',
    'toast.bypass.off': 'Switched: Auto run',
    'ctx.label': 'Context window',
    'dd.model.head': 'Model',
    'dd.model.visionExp': 'deepseek-v4-flash-vision-exp',
    'dd.model.visionExp1m': 'deepseek-v4-flash-vision-exp',
    'dd.model.flash': 'deepseek-v4-flash',
    'dd.model.flash1m': 'deepseek-v4-flash',
    'dd.model.pro': 'deepseek-v4-pro',
    'dd.model.pro1m': 'deepseek-v4-pro',
    'dd.model.pro2m': 'deepseek-v4-pro',
    'dd.perm.head': 'Mode',
    'dd.perm.manual': 'Manual',
    'dd.perm.acceptEdits': 'Accept edits',
    'dd.perm.plan': 'Plan',
    'dd.perm.bypass': 'Bypass perms',
    'dd.add.file': 'Add file or photo',
    'dd.add.folder': 'Add folder',
    'dd.add.slash': 'Slash command',
    'dd.add.connector': 'Add connector',
    'dd.add.plugin': 'Plugins',
    'uc.thinkDepth': 'Reasoning depth',
    'uc.current': 'Current depth',
    'uc.thumbMoved': 'Reasoning depth adjusted',
    'ctx.legend.used': 'Used',
    'ctx.legend.free': 'Free',
    'ctx.detail.system': 'System',
    'ctx.detail.user': 'User',
    'ctx.detail.tools': 'Tool calls',
    'ctx.detail.output': 'Output',
  }
};

const LANG_KEY = 'thesis-agent-lang';
let currentLang = localStorage.getItem(LANG_KEY) || 'zh-CN';

function t(key) {
  return (I18N[currentLang] && I18N[currentLang][key]) || I18N['zh-CN'][key] || key;
}

function applyI18n() {
  document.documentElement.setAttribute('lang', currentLang === 'zh-CN' ? 'zh-CN' : 'en');
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    if (I18N[currentLang][key] !== undefined) el.textContent = I18N[currentLang][key];
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.dataset.i18nPlaceholder;
    if (I18N[currentLang][key] !== undefined) el.setAttribute('placeholder', I18N[currentLang][key]);
  });
  document.querySelectorAll('.lang-option').forEach(opt => {
    opt.classList.toggle('active', opt.dataset.lang === currentLang);
  });
  // 模式 chip 文案随当前模式 + 语言同步
  if (typeof currentMode !== 'undefined' && typeof applyMode === 'function') applyMode(currentMode);
  // 模型 chip 文本不随语言切换（模型名固定英文）
}

function switchLang(lang) {
  currentLang = lang;
  localStorage.setItem(LANG_KEY, lang);
  applyI18n();
  if (typeof renderSessionList === 'function') renderSessionList();
  // 重新渲染设置面板（如果打开）
  if (document.getElementById('settings-overlay').classList.contains('show')) {
    renderSettings();
  }
  closeFootMenu();
  toast(lang === 'zh-CN' ? t('toast.lang.switched') : t('toast.lang.switchedEn'));
}

/* ============================================================
   左下角弹出菜单
   ============================================================ */
const footTrigger = document.getElementById('foot-trigger');
const footMenu = document.getElementById('foot-menu');
const langSubmenu = document.getElementById('lang-submenu');

function closeFootMenu() {
  footMenu.classList.remove('show');
  footTrigger.classList.remove('open');
  footTrigger.setAttribute('aria-expanded', 'false');
  closeLangSubmenu();
}
function closeLangSubmenu() {
  langSubmenu.classList.remove('show');
}

footTrigger.addEventListener('click', (e) => {
  e.stopPropagation();
  const open = footMenu.classList.toggle('show');
  footTrigger.classList.toggle('open', open);
  footTrigger.setAttribute('aria-expanded', String(open));
  if (!open) closeLangSubmenu();
});

document.addEventListener('click', (e) => {
  if (!footMenu.contains(e.target) && !footTrigger.contains(e.target)) closeFootMenu();
  if (!langSubmenu.contains(e.target) && !e.target.closest('[data-action="language"]')) closeLangSubmenu();
});

footMenu.querySelectorAll('.menu-item').forEach(item => {
  item.addEventListener('click', (e) => {
    e.stopPropagation();
    const action = item.dataset.action;
    if (action === 'settings') { openSettings(); closeFootMenu(); }
    else if (action === 'language') {
      const rect = item.getBoundingClientRect();
      langSubmenu.style.left = (rect.right + 8) + 'px';
      langSubmenu.style.bottom = (window.innerHeight - rect.bottom) + 'px';
      langSubmenu.classList.toggle('show');
    }
    else if (action === 'inference') { openInferenceModal(); closeFootMenu(); }
    else if (action === 'changelog') { toast(t('toast.changelog')); closeFootMenu(); }
    else if (action === 'about') { toast(t('toast.menu.placeholder')); closeFootMenu(); }
    else if (action === 'logout') { logoutCurrentUser(); closeFootMenu(); }
  });
});

document.querySelectorAll('.lang-option').forEach(opt => {
  opt.addEventListener('click', (e) => {
    e.stopPropagation();
    switchLang(opt.dataset.lang);
  });
});

/* ============================================================
   设置面板（仿 Claude Code 桌面端）
   ============================================================ */
const SETTINGS_NAV = [
  { groupKey: 'settings.section.account',
    items: [
      { id: 'basic',    icon: 'gear',    label: 'settings.nav.general' },
      { id: 'privacy',  icon: 'shield',  label: 'settings.nav.privacy' },
      { id: 'usage',    icon: 'chart',   label: 'settings.nav.usage' },
      { id: 'cc',       icon: 'code',    label: 'settings.nav.cc', active: true },
      { id: 'cowork',   icon: 'users',   label: 'settings.nav.cowork' },
    ]
  },
  { groupKey: 'settings.section.desktop',
    items: [
      { id: 'appGeneral', icon: 'monitor',  label: 'settings.nav.appGeneral' },
      { id: 'dev',        icon: 'terminal', label: 'settings.nav.dev' },
    ]
  },
  { groupKey: 'settings.section.custom',
    items: [
      { id: 'skills',     icon: 'sparkles', label: 'settings.nav.skills' },
      { id: 'connectors', icon: 'plug',     label: 'settings.nav.connectors' },
      { id: 'plugins',    icon: 'puzzle',   label: 'settings.nav.plugins' },
    ]
  },
];

const ICON_PATHS = {
  gear:    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  shield:  '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  chart:   '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>',
  code:    '<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>',
  users:   '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
  terminal:'<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
  sparkles:'<path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z"/><path d="M19 14l.7 2.1L22 17l-2.3.9L19 20l-.7-2.1L16 17l2.3-.9z"/>',
  plug:    '<path d="M9 2v6"/><path d="M15 2v6"/><path d="M6 8h12v3a6 6 0 0 1-12 0z"/><path d="M12 17v5"/>',
  puzzle:  '<path d="M19 11h-1V8a2 2 0 0 0-2-2h-3V5a2 2 0 1 0-4 0v1H6a2 2 0 0 0-2 2v3h1a2 2 0 1 1 0 4H4v3a2 2 0 0 0 2 2h3v-1a2 2 0 1 1 4 0v1h3a2 2 0 0 0 2-2v-3h1a2 2 0 1 0 0-4z"/>'
};

function renderSettingsNav() {
  const nav = document.getElementById('settings-nav');
  nav.innerHTML = SETTINGS_NAV.map(group => `
    <div class="settings-nav-group-title">${t(group.groupKey)}</div>
    ${group.items.map(it => `
      <button class="settings-nav-item ${it.active ? 'active' : ''}" data-settings-nav="${it.id}">
        <svg class="ni-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">${ICON_PATHS[it.icon] || ''}</svg>
        <span>${t(it.label)}</span>
      </button>
    `).join('')}
  `).join('');
  nav.querySelectorAll('.settings-nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
      nav.querySelectorAll('.settings-nav-item').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderSettingsContent(btn.dataset.settingsNav);
    });
  });
}

const CODE_PREVIEW_LIGHT = `
<div class="cp-body cp-light">
  <div><span class="ln-num">1</span><span class="kw">function</span> <span class="fn">greet</span>(<span class="var">name</span>: <span class="kw">string</span>) {</div>
  <div><span class="ln-num">2</span><span class="brace-op">  <span style="color:#af00db">return</span> <span style="color:#c7254e">"Hello, "</span> + <span style="color:#1f1f1f">name</span>;</span></div>
  <div><span class="ln-num">3</span><span class="brace-mod">  <span style="color:#af00db">return</span> <span style="color:#c7254e">\`Hello, \${name}\`</span>;</span></div>
  <div><span class="ln-num">4</span>}</div>
</div>`;
const CODE_PREVIEW_DARK = `
<div class="cp-body cp-dark">
  <div><span class="ln-num">1</span><span class="kw">function</span> <span class="fn">greet</span>(<span class="var">name</span>: <span class="kw">string</span>) {</div>
  <div><span class="ln-num">2</span><span class="brace-op">  <span style="color:#c586c0">return</span> <span style="color:#ce9178">"Hello, "</span> + <span style="color:#d4d4d4">name</span>;</span></div>
  <div><span class="ln-num">3</span><span class="brace-mod">  <span style="color:#c586c0">return</span> <span style="color:#ce9178">\`Hello, \${name}\`</span>;</span></div>
  <div><span class="ln-num">4</span>}</div>
</div>`;

function renderSettingsContent(tab = 'cc') {
  const content = document.getElementById('settings-content');
  if (tab === 'cc') {
    content.innerHTML = `
      <h2 class="settings-section-title">${t('settings.tab.cc.title')}</h2>
      <div class="settings-sub">${t('settings.tab.cc.appearance')}</div>
      <div style="display:block; margin-bottom: 16px;">
        <div class="code-preview-pair">
          <div class="code-preview-card">
            <div class="cp-head">
              <div class="select" style="pointer-events:none; min-width: 180px;">
                <span>${t('settings.tab.cc.appearanceLight')}</span>
                <svg class="chev" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
              </div>
            </div>
            ${CODE_PREVIEW_LIGHT}
          </div>
          <div class="code-preview-card">
            <div class="cp-head">
              <div class="select" style="pointer-events:none; min-width: 180px;">
                <span>${t('settings.tab.cc.appearanceDark')}</span>
                <svg class="chev" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
              </div>
            </div>
            ${CODE_PREVIEW_DARK}
          </div>
        </div>
      </div>
      <div class="settings-row">
        <div>
          <div class="settings-row-label">${t('settings.tab.cc.font')}</div>
          <div class="settings-row-desc">${t('settings.tab.cc.fontDesc')}</div>
        </div>
        <div class="settings-row-control">
          <div class="input-line"><input placeholder="${t('settings.tab.cc.fontPh')}" /></div>
        </div>
      </div>
      <div class="settings-sub" style="margin-top: 24px;">${t('settings.tab.appearance.title')}</div>
      <div class="settings-row">
        <div>
          <div class="settings-row-label">${t('settings.tab.appearance.contrast')}</div>
          <div class="settings-row-desc">${t('settings.tab.appearance.contrastDesc')}</div>
        </div>
        <div class="settings-row-control"><div class="toggle" data-toggle="contrast"></div></div>
      </div>
      <div class="settings-row">
        <div>
          <div class="settings-row-label">${t('settings.tab.appearance.uiFont')}</div>
          <div class="settings-row-desc">${t('settings.tab.appearance.uiFontDesc')}</div>
        </div>
        <div class="settings-row-control">
          <div class="select" style="min-width: 200px;">
            <span>Anthropic Sans</span>
            <span style="font-size:11px; color: var(--text-subtle); margin: 0 4px;">${t('common.system')}</span>
            <svg class="chev" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
          </div>
        </div>
      </div>
      <div class="settings-row">
        <div>
          <div class="settings-row-label">${t('settings.tab.appearance.tts')}</div>
          <div class="settings-row-desc">${t('settings.tab.appearance.ttsDesc')}</div>
        </div>
        <div class="settings-row-control">
          <div class="segmented" data-tts>
            <button data-size="s">${t('settings.tab.appearance.tts.s')}</button>
            <button class="active" data-size="m">${t('settings.tab.appearance.tts.m')}</button>
            <button data-size="l">${t('settings.tab.appearance.tts.l')}</button>
          </div>
        </div>
      </div>
    `;
  } else if (tab === 'basic') {
    content.innerHTML = `
      <h2 class="settings-section-title">${t('settings.tab.basic.title')}</h2>
      <div class="settings-row">
        <div>
          <div class="settings-row-label">${t('settings.tab.basic.item1')}</div>
          <div class="settings-row-desc">${currentLang === 'zh-CN' ? '开启后，Agent 会主动建议下一步操作。' : 'When on, the agent proactively suggests next steps.'}</div>
        </div>
        <div class="settings-row-control"><div class="toggle on" data-toggle="suggest"></div></div>
      </div>
    `;
  } else {
    const labelMap = { privacy:'settings.nav.privacy', usage:'settings.nav.usage', cowork:'settings.nav.cowork',
                       appGeneral:'settings.nav.appGeneral', dev:'settings.nav.dev',
                       skills:'settings.nav.skills', connectors:'settings.nav.connectors', plugins:'settings.nav.plugins' };
    content.innerHTML = `
      <h2 class="settings-section-title">${t(labelMap[tab] || tab)}</h2>
      <div style="color: var(--text-inactive); font-size: var(--fs-small); padding: 12px 0;">${currentLang === 'zh-CN' ? '该分类下暂无配置项。' : 'No settings in this category yet.'}</div>
    `;
  }
  // 绑定交互
  content.querySelectorAll('.toggle').forEach(tg => {
    tg.addEventListener('click', () => tg.classList.toggle('on'));
  });
  content.querySelectorAll('.segmented button').forEach(b => {
    b.addEventListener('click', () => {
      b.parentElement.querySelectorAll('button').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
    });
  });
}

function renderSettings() {
  renderSettingsNav();
  const active = document.querySelector('.settings-nav-item.active');
  renderSettingsContent(active ? active.dataset.settingsNav : 'cc');
}

function openSettings() {
  const overlay = document.getElementById('settings-overlay');
  showAccessibleDialog(overlay, document.getElementById('settings-search-input'));
  renderSettings();
}
function closeSettings() {
  hideAccessibleDialog(document.getElementById('settings-overlay'));
}
document.getElementById('settings-close').addEventListener('click', closeSettings);
document.getElementById('title-settings')?.addEventListener('click', openSettings);
document.getElementById('settings-overlay').addEventListener('click', (e) => {
  if (e.target.id === 'settings-overlay') closeSettings();
});

document.getElementById('settings-search-input').addEventListener('input', (e) => {
  const q = e.target.value.trim().toLowerCase();
  document.querySelectorAll('.settings-nav-item').forEach(item => {
    item.style.display = (q === '' || item.textContent.toLowerCase().includes(q)) ? '' : 'none';
  });
});

/* ============================================================
   推理配置 Modal
   ============================================================ */
const inferenceModal = document.getElementById('inference-modal');
let deepSeekModelPresets = [];
function syncDeepSeekPresetCapabilities() {
  const model = document.getElementById('inference-model').value.trim();
  const preset = deepSeekModelPresets.find(item => item.model === model);
  if (!preset) return;
  document.getElementById('inference-tools').checked = Boolean(preset.tools);
  document.getElementById('inference-vision').checked = Boolean(preset.vision);
}
function applyDeepSeekConfigView(payload) {
  const config = payload?.config || {};
  document.getElementById('inference-model').value = config.model || '';
  document.getElementById('inference-base-url').value = config.base_url || 'https://api.deepseek.com';
  document.getElementById('inference-thinking').value = config.thinking_mode || 'disabled';
  document.getElementById('inference-reasoning').value = config.reasoning_effort || 'low';
  document.getElementById('inference-tools').checked = Boolean(config.capabilities?.tools);
  document.getElementById('inference-vision').checked = Boolean(config.capabilities?.vision);
  document.getElementById('inference-enabled').checked = Boolean(config.enabled);
  document.getElementById('inference-api-key').value = '';
  document.getElementById('inference-key-status').textContent = config.api_key_configured
    ? '当前进程已配置API Key；留空不会覆盖。'
    : '当前进程尚未配置API Key。';
  const options = document.getElementById('deepseek-model-options');
  deepSeekModelPresets = payload?.models || [];
  options.innerHTML = deepSeekModelPresets
    .map(item => `<option value="${escapeHtml2(item.model)}">${escapeHtml2(item.label || item.model)}</option>`)
    .join('');
  const capabilities = [];
  if (config.capabilities?.tools) capabilities.push('Tools');
  if (config.capabilities?.vision) capabilities.push('Vision');
  currentModel = {
    model: config.model || '未配置',
    cap: capabilities.join(' · '),
  };
  if (modelName) modelName.textContent = currentModel.model;
  if (modelCap) {
    modelCap.textContent = currentModel.cap;
    modelCap.style.display = currentModel.cap ? '' : 'none';
  }
  document.querySelectorAll('#dd-model .dd-item').forEach(syncModelItemActive);
}
document.getElementById('inference-model').addEventListener('change', syncDeepSeekPresetCapabilities);
async function openInferenceModal() {
  const error = document.getElementById('inference-error');
  error.textContent = '';
  showAccessibleDialog(inferenceModal, document.getElementById('inference-model'));
  const response = await apiDeepSeekConfig();
  if (response.code !== 0) {
    error.textContent = response.msg || '读取DeepSeek配置失败。';
    return;
  }
  applyDeepSeekConfigView(response.data);
}
function closeInferenceModal() { hideAccessibleDialog(inferenceModal); }
document.getElementById('inference-close').addEventListener('click', closeInferenceModal);
document.getElementById('inference-form').addEventListener('submit', async event => {
  event.preventDefault();
  const error = document.getElementById('inference-error');
  const save = document.getElementById('inference-save');
  const model = document.getElementById('inference-model').value.trim();
  const baseUrl = document.getElementById('inference-base-url').value.trim();
  if (!model || !baseUrl) {
    error.textContent = '请填写DeepSeek模型名和Base URL。';
    return;
  }
  save.disabled = true;
  error.textContent = '';
  const response = await apiSaveDeepSeekConfig({
    model,
    base_url: baseUrl,
    api_key: document.getElementById('inference-api-key').value,
    thinking_mode: document.getElementById('inference-thinking').value,
    reasoning_effort: document.getElementById('inference-reasoning').value,
    supports_tools: document.getElementById('inference-tools').checked,
    supports_vision: document.getElementById('inference-vision').checked,
    enabled: document.getElementById('inference-enabled').checked,
  });
  document.getElementById('inference-api-key').value = '';
  save.disabled = false;
  if (response.code !== 0) {
    error.textContent = response.msg || '保存DeepSeek配置失败。';
    return;
  }
  applyDeepSeekConfigView(response.data);
  toast(response.msg || 'DeepSeek配置已更新');
  closeInferenceModal();
});
inferenceModal.addEventListener('click', (e) => {
  if (e.target === inferenceModal) closeInferenceModal();
});

function showLoginModal() {
  const modal = document.getElementById('login-modal');
  if (!modal || modal.classList.contains('show')) return;
  showAccessibleDialog(modal, document.getElementById('login-username'));
}

async function submitLogin(event) {
  event.preventDefault();
  const username = document.getElementById('login-username').value.trim();
  const passwordInput = document.getElementById('login-password');
  const error = document.getElementById('login-error');
  const submit = document.getElementById('login-submit');
  if (!username || !passwordInput.value) {
    error.textContent = '请输入用户名和密码。';
    return;
  }
  submit.disabled = true;
  error.textContent = '';
  await window.ThesisAutosave?.flushAllDrafts?.();
  const response = await apiLogin(username, passwordInput.value);
  passwordInput.value = '';
  submit.disabled = false;
  if (response.code !== 0) {
    error.textContent = response.msg || '登录失败。';
    passwordInput.focus();
    return;
  }
  hideAccessibleDialog(document.getElementById('login-modal'));
  const name = document.querySelector('.menu-head-name');
  if (name) name.textContent = response.data?.username || username;
  toast('登录成功');
  // 丢弃旧身份的工作区状态与待发请求，重新读取新用户自己的恢复位置。
  await switchWorkspaceIdentity();
}

async function logoutCurrentUser() {
  await window.ThesisAutosave?.flushAllDrafts?.();
  const response = await apiLogout();
  if (response.code !== 0) { toast(response.msg || '退出失败'); return; }
  await switchWorkspaceIdentity();
  showLoginModal();
}

/* ============================================================
   全局快捷键 & 启动初始化
   ============================================================ */
document.addEventListener('keydown', (e) => {
  // Ctrl+, 打开设置
  if ((e.ctrlKey || e.metaKey) && e.key === ',' && document.activeElement.tagName !== 'TEXTAREA' && document.activeElement.tagName !== 'INPUT') {
    e.preventDefault();
    openSettings();
  }
  if (e.key === 'Escape') {
    closeSettings();
    closeInferenceModal();
    if (delModal.classList.contains('show')) {
      hideAccessibleDialog(delModal);
      pendingDelete = null;
    }
    closeFootMenu();
    if (typeof closeAllDd === 'function') closeAllDd();
    if (typeof closeActivePopover === 'function') closeActivePopover();
  }
});

/* ============================================================
   会话列表（对接后端 /api/v1/console/tasks）
   ============================================================ */
let currentSession = null;
let currentSessionTitle = '';
let currentKnowledgeSession = '';
let sessionCache = [];
let sessionListRequest = 0;
let sessionSearchTimer = null;
const WORKSPACE_TABS = new Set([
  'refs', 'memory', 'evidence', 'research', 'writing', 'jobs', 'notes', 'graph',
]);
const WORKSPACE_EXPANDABLE_IDS = [
  'memory-builder', 'protocol-builder', 'argument-builder', 'template-mapping-panel',
];
let workspaceState = defaultWorkspaceState();
let workspacePersistenceReady = false;
let workspaceSaveTimer = null;
let workspaceIdentityToken = 0;
let resumeSummaryCache = null;
// 服务端可验证的单调版本。每次真实位置变化在“发送时”递增，
// 乱序到达的旧 POST 会被服务端按 revision 拒绝，旧快照无法倒退覆盖新状态。
let workspaceRevision = 0;
// 每次身份切换创建新的保存世代：旧世代请求自然结束，但只修改旧世代自己的
// in-flight / queued / lastSnapshot，绝不会占用或复用新身份的保存状态。
let workspaceSaveGeneration = newWorkspaceSaveGeneration();
// 只有真正读到服务端工作区、且任务列表请求成功时，才允许把本地状态写回服务端。
// 否则一次断网就会让本地默认值覆盖并清空用户的恢复位置。
let workspaceServerLoaded = false;
let sessionListLoaded = false;
let workspaceRecoveryTrusted = false;

function newWorkspaceSaveGeneration() {
  workspaceIdentityToken += 1;
  return {
    token: workspaceIdentityToken,
    inFlight: false,
    queued: false,
    lastSnapshot: null,
  };
}

function adoptWorkspaceRevision(value) {
  // 客户端计数器只增不减：即使旧身份请求仍在途，新身份也不会复用同一个
  // revision，从而避免“同版本不同内容”把新用户的首次保存挤成冲突。
  const candidate = Number(value);
  if (Number.isFinite(candidate) && candidate > workspaceRevision) {
    workspaceRevision = candidate;
  }
}

function updateWorkspaceTrust() {
  workspaceRecoveryTrusted = workspaceServerLoaded && sessionListLoaded;
}

function defaultWorkspaceState() {
  return {
    last_task_id: '', active_tab: 'refs', expanded_items: [], editor_anchor: '',
  };
}

function normalizeWorkspaceState(raw) {
  const source = raw && typeof raw === 'object' ? raw : {};
  return {
    last_task_id: typeof source.last_task_id === 'string' ? source.last_task_id : '',
    active_tab: WORKSPACE_TABS.has(source.active_tab) ? source.active_tab : 'refs',
    expanded_items: Array.isArray(source.expanded_items)
      ? source.expanded_items.filter(item => typeof item === 'string').slice(0, 30)
      : [],
    editor_anchor: typeof source.editor_anchor === 'string' ? source.editor_anchor : '',
  };
}

function workspaceSnapshot() {
  return normalizeWorkspaceState(workspaceState);
}

function applyWorkspaceExpandedItems() {
  const expanded = new Set(workspaceState.expanded_items || []);
  WORKSPACE_EXPANDABLE_IDS.forEach(id => {
    const element = document.getElementById(id);
    if (element instanceof HTMLDetailsElement) element.open = expanded.has(id);
  });
}

function bindWorkspaceExpandedItems() {
  WORKSPACE_EXPANDABLE_IDS.forEach(id => {
    const element = document.getElementById(id);
    if (!(element instanceof HTMLDetailsElement) || element.dataset.workspaceBound) return;
    element.dataset.workspaceBound = '1';
    element.addEventListener('toggle', () => {
      const items = WORKSPACE_EXPANDABLE_IDS.filter(itemId => (
        document.getElementById(itemId)?.open
      ));
      scheduleWorkspaceSave({ expanded_items: items });
    });
  });
}

function sameWorkspaceContent(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function announceWorkspace(message) {
  const live = document.getElementById('resume-live');
  if (live) live.textContent = message || '';
}

function scheduleWorkspaceSave(changes = {}) {
  workspaceState = normalizeWorkspaceState({ ...workspaceState, ...changes });
  if (!workspacePersistenceReady) return;
  clearTimeout(workspaceSaveTimer);
  workspaceSaveTimer = setTimeout(() => { runWorkspaceSave(); }, 300);
}

function isWorkspaceConflict(response) {
  return Boolean(response?.data?.conflict);
}

function handleWorkspaceSaveFailure(response) {
  if (isWorkspaceConflict(response)) {
    // 冲突只影响 UI 位置：以服务端为准重新读取，不自动用本地旧状态强行覆盖，
    // 也不自动重发，避免循环 POST。
    announceWorkspace('工作位置已在另一页面更新，请确认当前任务位置');
    loadWorkspaceState();
    return;
  }
  announceWorkspace(`工作位置保存失败：${response.msg || '未知错误'}`);
}

async function runWorkspaceSave() {
  // 捕获当前世代：即使身份随后切换，旧请求也只影响旧世代对象。
  const generation = workspaceSaveGeneration;
  if (generation.inFlight) { generation.queued = true; return; }
  if (!workspacePersistenceReady || !workspaceRecoveryTrusted) return;
  const content = workspaceSnapshot();
  if (generation.lastSnapshot && sameWorkspaceContent(generation.lastSnapshot, content)) {
    // 无真实变化不得伪造一次用户修改，也不得递增 revision。
    return;
  }
  generation.inFlight = true;
  // 在发送时同步预留 revision：跨世代或 pagehide 的并发请求不会撞到同一个
  // 版本号，从而避免“同版本不同内容”把较新的保存挤成冲突。
  const revision = workspaceRevision + 1;
  workspaceRevision = revision;
  try {
    const response = await apiSaveWorkspaceState({ ...content, revision });
    // 身份已切换时丢弃旧世代回包，绝不让旧用户的位置或错误提示影响新身份。
    if (generation !== workspaceSaveGeneration) return;
    if (response.code !== 0) { handleWorkspaceSaveFailure(response); return; }
    adoptWorkspaceRevision(response.data?.revision);
    generation.lastSnapshot = content;
  } catch (error) {
    if (generation !== workspaceSaveGeneration) return;
    announceWorkspace('工作位置保存失败：无法连接后端，正式论文状态不受影响');
  } finally {
    generation.inFlight = false;
    if (generation.queued && generation === workspaceSaveGeneration) {
      generation.queued = false;
      clearTimeout(workspaceSaveTimer);
      workspaceSaveTimer = setTimeout(() => { runWorkspaceSave(); }, 300);
    }
  }
}

function flushWorkspaceSaveOnExit() {
  // 恢复链路没有成功读到服务端状态时绝不回写，避免关闭页面时清空恢复位置。
  if (!workspacePersistenceReady || !workspaceRecoveryTrusted) return;
  const generation = workspaceSaveGeneration;
  const content = workspaceSnapshot();
  if (generation.lastSnapshot && sameWorkspaceContent(generation.lastSnapshot, content)) return;
  // keepalive 无法等待回包，这里同步占用更高 revision：
  // 仍在途的普通保存 revision 更低，注定被服务端拒绝，不会倒退覆盖本次快照。
  const revision = workspaceRevision + 1;
  workspaceRevision = revision;
  try {
    fetch(API_BASE + '/api/v1/console/workspace', {
      method: 'POST',
      keepalive: true,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...content, revision }),
    }).catch(() => {});
  } catch (_) {
    // 关闭前的末次保存失败不得影响正式论文状态。
  }
}
window.addEventListener('pagehide', flushWorkspaceSaveOnExit);

function pauseWorkspacePersistence() {
  clearTimeout(workspaceSaveTimer);
  workspaceSaveTimer = null;
  workspacePersistenceReady = false;
  // 注意：workspaceRevision 故意不归零。旧身份的请求可能仍在途并占用某个
  // revision，新身份必须从更高的值继续，否则会与之撞版本导致首次保存被拒。
  // 创建新世代：旧世代的 in-flight / queued 随旧世代一起失效，
  // 新身份的首次保存不会被旧身份仍在途的请求阻塞或吞掉。
  workspaceSaveGeneration = newWorkspaceSaveGeneration();
  workspaceServerLoaded = false;
  sessionListLoaded = false;
  workspaceRecoveryTrusted = false;
}

function clearWorkspaceForIdentity() {
  pauseWorkspacePersistence();
  workspaceState = defaultWorkspaceState();
  resumeSummaryCache = null;
  hideResumeBanner();
  announceWorkspace('');
}

function hideResumeBanner() {
  const banner = document.getElementById('resume-banner');
  if (banner) banner.hidden = true;
  resumeSummaryCache = null;
}

function renderResumeBanner(resume) {
  const banner = document.getElementById('resume-banner');
  const summary = document.getElementById('resume-summary');
  const next = document.getElementById('resume-next');
  const button = document.getElementById('resume-continue');
  if (!banner || !summary || !next || !button || !resume?.task_id) {
    hideResumeBanner();
    return;
  }
  resumeSummaryCache = resume;
  const pendingCount = (resume.pending_approvals || []).length;
  const activeJobCount = (resume.active_jobs || []).length;
  const draftCount = (resume.autosaved_drafts || []).length;
  summary.textContent = `${resume.title || '当前论文'} · 环${resume.current_ring_no} ${RING_NAMES[resume.current_ring_no] || ''} · 完成 ${resume.complete_percent || 0}% · 待审批 ${pendingCount} · 运行中作业 ${activeJobCount} · 未提交草稿 ${draftCount}`;
  next.textContent = `下一步：${resume.next_safe_action?.label || '查看当前任务'}`;
  button.dataset.taskId = resume.task_id;
  button.textContent = resume.next_safe_action?.type === 'REVIEW_DELIVERY'
    ? '查看交付结果'
    : resume.next_safe_action?.type === 'RESUME_DRAFT'
    ? '继续编辑草稿'
    : '继续写作';
  banner.hidden = false;
}

async function resolveResumeForSelected(selectedTaskId, cachedResume) {
  if (!selectedTaskId) return null;
  if (cachedResume && cachedResume.task_id === selectedTaskId) return cachedResume;
  const response = await apiTaskResume(selectedTaskId);
  return response?.code === 0 ? (response.data || null) : null;
}

function invalidateResumeSummary() {
  // 任何会改变 FSM、Artifact 审批、作者决定、分节或 Job 状态的成功操作，
  // 都必须先失效旧摘要，绝不能继续展示已知的过期数量与“唯一安全下一步”。
  resumeSummaryCache = null;
}

async function refreshVisibleResumeSummary() {
  const banner = document.getElementById('resume-banner');
  if (!banner || banner.hidden) { invalidateResumeSummary(); return; }
  if (!currentSession) { hideResumeBanner(); return; }
  const response = await apiTaskResume(currentSession);
  // 只有与当前任务一致的最新摘要才允许上屏；拿不到就隐藏，绝不展示旧摘要。
  if (response?.code === 0 && response.data?.task_id === currentSession) {
    renderResumeBanner(response.data);
    return;
  }
  hideResumeBanner();
}

function syncResumeBannerWithJobs(jobs) {
  const banner = document.getElementById('resume-banner');
  if (!banner || banner.hidden || !resumeSummaryCache) return;
  const ACTIVE_STATUSES = ['PENDING', 'RUNNING', 'CANCEL_REQUESTED'];
  const activeIds = (jobs || [])
    .filter(job => ACTIVE_STATUSES.includes(job.status))
    .map(job => job.job_id)
    .sort()
    .join(',');
  const cachedIds = (resumeSummaryCache.active_jobs || [])
    .map(job => job.job_id).sort().join(',');
  // Job 轮询发现活动作业集合变化时，立即重取摘要或隐藏横幅。
  if (activeIds !== cachedIds) refreshVisibleResumeSummary();
}

function findJobCard(jobId) {
  if (!jobId) return null;
  return Array.from(document.querySelectorAll('[data-job-id]'))
    .find(element => element.dataset.jobId === jobId) || null;
}

function resumeFocusTarget(resume) {
  const type = resume.next_safe_action?.type;
  const ringNo = resume.current_ring_no;
  if (type === 'CONFIRM_RING') {
    return document.querySelector(`.gate-block[data-ring="${ringNo}"] [data-gate]`)
      || document.querySelector('[data-gate]');
  }
  if (type === 'MONITOR_JOB') {
    const jobCard = findJobCard(resume.next_safe_action?.job_id);
    // 标题栏刷新按钮不会随作业列表异步重绘而被替换，键盘焦点更稳定。
    return document.getElementById('jobs-refresh')
      || jobCard?.querySelector('[data-job-action]');
  }
  if (type === 'COMPLETE_AUTHOR_DECISION') {
    if (ringNo === 1) return document.querySelector('.cand-item');
    if (ringNo === 3) {
      return document.getElementById('save-literature-curation')
        || document.querySelector('.ring3-include');
    }
    return document.getElementById('run-cur-ring');
  }
  if (type === 'RESUME_DRAFT') {
    const draftKey = resume.next_safe_action?.draft_key || '';
    const objectType = resume.next_safe_action?.object_type;
    if (objectType === 'SECTION_REVISION') {
      const surface = window.ThesisAutosave?.surfaces?.get(draftKey);
      const editor = surface?.editor;
      const area = editor?.closest('.section-edit-area');
      if (area) area.hidden = false;
      activeSectionDraftKey = draftKey;
      restoreEditorAnchor(draftKey, editor);
      return editor || document.getElementById('sections-refresh');
    }
    if (objectType === 'RESEARCH_PROTOCOL_FORM') {
      document.getElementById('protocol-builder').open = true;
      return document.getElementById('protocol-title');
    }
    if (objectType === 'ARGUMENT_MAP_FORM') {
      document.getElementById('argument-builder').open = true;
      return document.getElementById('argument-title');
    }
    document.getElementById('memory-builder').open = true;
    return document.getElementById('memory-questions');
  }
  if (type === 'RECOVER_STAGE') {
    const retry = document.querySelector('[data-job-id] [data-job-action="retry"]');
    return retry || document.getElementById('run-cur-ring');
  }
  if (type === 'REVIEW_DELIVERY') {
    const runButton = document.getElementById('run-cur-ring');
    return runButton && !runButton.disabled ? runButton : null;
  }
  if (type === 'REPAIR_REQUIRED') return null;
  return document.getElementById('run-cur-ring');
}

function resumeTargetTab(resume, fallbackTab) {
  // 只在目标确实位于后台作业面板时才切页签，避免无谓打断用户保存的页签。
  const type = resume.next_safe_action?.type;
  if (type === 'MONITOR_JOB') return 'jobs';
  if (type === 'RECOVER_STAGE' && (resume.recoverable_jobs || []).length) return 'jobs';
  if (type === 'RESUME_DRAFT') {
    if (resume.next_safe_action?.object_type === 'SECTION_REVISION') return 'writing';
    if (resume.next_safe_action?.object_type === 'PROJECT_MEMORY_FORM') return 'memory';
    return 'research';
  }
  return fallbackTab || 'refs';
}

async function continueLastThesis() {
  const resume = resumeSummaryCache;
  if (!resume?.task_id) return;
  const selected = sessionCache.find(item => item.task_id === resume.task_id);
  if (!selected) {
    hideResumeBanner();
    announceWorkspace('上次论文已不存在，已清除恢复入口。');
    return;
  }
  const type = resume.next_safe_action?.type;
  // 只导航与聚焦：切换任务、加载详情、打开对应页签。不执行环、不确认闸门、不调用模型。
  currentSession = selected.task_id;
  currentSessionTitle = selected.title || '';
  workspaceState = { ...workspaceState, expanded_items: [], editor_anchor: '' };
  applyWorkspaceExpandedItems();
  renderSessionList();
  await loadSessionDetail(currentSession);
  const targetTab = resumeTargetTab(resume, workspaceState.active_tab);
  await activateWorkbenchTab(targetTab);
  hideResumeBanner();
  scheduleWorkspaceSave({
    last_task_id: currentSession,
    active_tab: targetTab,
    expanded_items: [],
    editor_anchor: '',
  });
  if (type === 'REPAIR_REQUIRED') {
    const issues = (resume.consistency_issues || []).slice(0, 3).join('；');
    announceWorkspace(
      `恢复被阻断：${resume.next_safe_action?.label || '需要先修复一致性问题'}`
      + (issues ? `（${issues}）` : '') + '。已停止在恢复入口，不会继续推进。',
    );
    return;
  }
  if (type === 'REVIEW_DELIVERY') {
    announceWorkspace('论文十环已完成。完整交付下载视图仍在建设中，请在当前任务中查看各环已批准产物。');
  } else {
    announceWorkspace(`已恢复${resume.title || '上次论文'}，${resume.next_safe_action?.label || ''}`);
  }
  const target = resumeFocusTarget(resume);
  if (target) requestAnimationFrame(() => target.focus?.());
}

async function selectSession(taskId) {
  const selected = sessionCache.find(item => item.task_id === taskId);
  if (!selected) return;
  if (currentSession && currentSession !== selected.task_id) {
    await window.ThesisAutosave?.flushAllDrafts?.();
    window.ThesisAutosave?.resetAutosaveIdentity?.();
  }
  currentSession = selected.task_id;
  currentSessionTitle = selected.title || '';
  // 展开项和编辑锚点属于上一任务，切换任务时必须清空。
  workspaceState = { ...workspaceState, expanded_items: [], editor_anchor: '' };
  applyWorkspaceExpandedItems();
  renderSessionList();
  hideResumeBanner();
  await loadSessionDetail(currentSession);
  scheduleWorkspaceSave({
    last_task_id: currentSession,
    active_tab: workspaceState.active_tab || 'refs',
    expanded_items: [],
    editor_anchor: '',
  });
}

async function switchWorkspaceIdentity() {
  window.ThesisAutosave?.resetAutosaveIdentity?.();
  clearWorkspaceForIdentity();
  currentSession = null;
  currentSessionTitle = '';
  const restored = await loadWorkspaceState();
  applyWorkspaceExpandedItems();
  currentSession = restored.last_task_id || null;
  const result = await loadSessionsWithWorkspaceFallback({
    preferredTaskId: restored.last_task_id,
    forceDetail: true,
  });
  await activateWorkbenchTab(workspaceState.active_tab || 'refs');
  renderResumeBanner(await resolveResumeForSelected(currentSession, resumeSummaryCache));
  workspacePersistenceReady = true;
  return result;
}

async function loadWorkspaceState() {
  const response = await apiWorkspaceState();
  if (!response || !response.workspace) {
    // 读取失败时保留安全本地默认值，绝不向服务端写空值覆盖旧状态。
    // workspaceRevision 只增不减，避免读到失败后发出更低的版本被服务端拒绝。
    workspaceState = defaultWorkspaceState();
    resumeSummaryCache = null;
    workspaceServerLoaded = false;
    updateWorkspaceTrust();
    return workspaceState;
  }
  workspaceState = normalizeWorkspaceState(response.workspace);
  // 从服务端 revision 继续，客户端只发出比它更大的版本。
  adoptWorkspaceRevision(response.workspace?.revision);
  // 服务端当前内容就是这个世代的基线：初始化时激活默认页签属于“无变化重放”，
  // 不得伪造一次用户修改，也不得递增 revision。
  workspaceSaveGeneration.lastSnapshot = workspaceSnapshot();
  resumeSummaryCache = response.resume || null;
  workspaceServerLoaded = true;
  updateWorkspaceTrust();
  return workspaceState;
}

async function loadSessionsWithWorkspaceFallback(options = {}) {
  const result = await loadSessions(options);
  if (!result.ok) return result;
  // 工作区读取失败但列表随后成功时，重新读取服务端指针并据此重新选择。
  const pointer = workspaceState.last_task_id;
  if (
    workspaceServerLoaded && pointer
    && pointer !== currentSession
    && sessionCache.some(item => item.task_id === pointer)
  ) {
    return loadSessions({ preferredTaskId: pointer, forceDetail: true });
  }
  return result;
}

function sessionItemHtml(s, isActive = false) {
  const degree = DEGREE_LABEL[s.degree] || s.degree || '';
  const pct = s.complete_percent || 0;
  const ring = s.current_ring_no || 1;
  const doneText = pct >= 100 ? '已完成 · 100%' : `阶段 ${ring}/10 · ${pct}%`;
  const activeClass = isActive ? ' active' : '';
  const currentAttribute = isActive ? ' aria-current="true"' : '';
  return `
    <div class="session-item${activeClass}" data-task="${escapeHtml(s.task_id)}" role="listitem">
      <button class="session-main" type="button" aria-label="打开论文任务：${escapeHtml(s.title || '未命名')}"${currentAttribute}>
        <div class="session-row"><span class="session-title">${escapeHtml(s.title || '未命名')}</span></div>
        <div class="session-meta">
          <span class="session-degree">${escapeHtml(degree)}</span>
          <span class="session-progress-text">${escapeHtml(doneText)}</span>
        </div>
        <div class="session-progress-bar" aria-hidden="true"><div class="session-progress-fill" style="width:${pct}%${pct >= 100 ? '; background: var(--success)' : ''}"></div></div>
      </button>
      <button class="session-delete" type="button" title="删除对话" aria-label="删除论文任务：${escapeHtml(s.title || '未命名')}">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function resolveSessionSelection(items, selectedId) {
  return items.find(item => item.task_id === selectedId) || items[0] || null;
}

function normalizeSessionSearch(value) {
  return String(value || '').trim().toLocaleLowerCase();
}

function filterSessions(items, query) {
  const normalizedQuery = normalizeSessionSearch(query);
  if (!normalizedQuery) return items;
  return items.filter(item => [
    item.title,
    item.subject_field,
    item.degree,
    DEGREE_LABEL[item.degree],
    item.current_ring_no,
  ].some(value => normalizeSessionSearch(value).includes(normalizedQuery)));
}

function formatI18n(key, values = {}) {
  return Object.entries(values).reduce(
    (message, [name, value]) => message.replaceAll(`{${name}}`, String(value)),
    t(key),
  );
}

function updateSessionSearchStatus(visibleCount, totalCount, hasQuery) {
  const status = document.getElementById('session-search-status');
  if (!status) return;
  if (!totalCount) status.textContent = t('search.empty');
  else if (hasQuery) {
    const key = totalCount === 1 ? 'search.countFilteredOne' : 'search.countFiltered';
    status.textContent = formatI18n(key, { visible: visibleCount, total: totalCount });
  } else {
    const key = totalCount === 1 ? 'search.countOne' : 'search.count';
    status.textContent = formatI18n(key, { total: totalCount });
  }
}

function renderSessionList() {
  const box = document.getElementById('session-items');
  if (!box) return;
  const query = document.getElementById('session-search')?.value || '';
  const visibleItems = filterSessions(sessionCache, query);
  const hasQuery = Boolean(normalizeSessionSearch(query));
  if (visibleItems.length) {
    box.innerHTML = visibleItems.map(item => sessionItemHtml(item, item.task_id === currentSession)).join('');
  } else {
    const message = sessionCache.length ? t('search.noMatches') : t('search.empty');
    box.innerHTML = `<div class="no-sessions" role="listitem" style="padding:16px;color:var(--text-subtle);font-size:12px;">${escapeHtml(message)}</div>`;
  }
  updateSessionSearchStatus(visibleItems.length, sessionCache.length, hasQuery);

  box.querySelectorAll('.session-item').forEach(item => {
    const opener = item.querySelector('.session-main');
    opener.addEventListener('click', () => {
      selectSession(item.dataset.task);
    });
    const del = item.querySelector('.session-delete');
    if (del) del.addEventListener('click', (event) => {
      event.stopPropagation();
      pendingDelete = item;
      delName.textContent = item.querySelector('.session-title')?.textContent || '当前对话';
      const modal = document.getElementById('del-modal');
      if (modal) showAccessibleDialog(modal, document.getElementById('del-cancel'));
    });
  });
}

function bindSessionSearch() {
  const input = document.getElementById('session-search');
  if (!input || input.dataset.bound) return;
  input.dataset.bound = '1';
  input.addEventListener('input', () => {
    clearTimeout(sessionSearchTimer);
    sessionSearchTimer = setTimeout(renderSessionList, 150);
  });
  input.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || !input.value) return;
    event.preventDefault();
    clearTimeout(sessionSearchTimer);
    input.value = '';
    renderSessionList();
    input.focus();
  });
}

async function clearSessionContext() {
  window.ThesisAutosave?.resetAutosaveIdentity?.();
  currentSession = null;
  currentSessionTitle = '';
  currentKnowledgeSession = '';
  sessionDetailRequest += 1;
  renderEmptyStages();
  updateRunBtn(null);
  const kbHead = document.getElementById('kb-head-name');
  if (kbHead) kbHead.textContent = '知识库';
  const refsPane = document.querySelector('.kb-pane[data-pane="refs"]');
  refsPane?.querySelectorAll('.ref-item,.ref-kb-none').forEach(element => element.remove());
  const refCount = refsPane?.querySelector('.count');
  if (refCount) refCount.textContent = '0';
  const refsEmpty = document.getElementById('kb-refs-empty');
  if (refsEmpty) refsEmpty.style.display = '';
  const notesList = document.getElementById('notes-list');
  if (notesList) notesList.innerHTML = '<div style="padding:8px;font-size:12px;color:var(--text-subtle);">选择论文任务后查看笔记。</div>';
  if (cyGraph) { cyGraph.destroy(); cyGraph = null; }
  const graph = document.getElementById('kb-graph');
  if (graph) graph.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#888;font-size:12px;">选择论文任务后查看图谱。</div>';
  const graphCount = document.getElementById('graph-count');
  if (graphCount) graphCount.textContent = '0 节点';
  const inner = document.querySelector('#chat-flow .chat-inner');
  if (inner) {
    inner.removeAttribute('data-history-task');
    inner.removeAttribute('data-history-built');
    inner.innerHTML = `
      <div class="chat-empty">
        <span class="chat-empty-icon"><i data-lucide="graduation-cap"></i></span>
        <h2>开始你的论文之旅</h2>
        <p>从选题到定稿共十环：每环产物经自动验收后，由你确认再进入下一环。任务、产物与进度全程持久化，随时中断随时恢复。</p>
        <div class="chat-empty-actions">
          <button class="btn btn-primary" onclick="document.querySelector('.new-chat-btn')?.click()">新建论文任务</button>
        </div>
      </div>`;
    renderLucideIcons();
  }
  await loadActiveWorkbenchPane();
}

async function loadSessions(options = {}) {
  const requestId = ++sessionListRequest;
  const items = await apiListSessions();
  if (requestId !== sessionListRequest) {
    return { ok: false, items: null, selected: null };
  }
  if (items === null) {
    // 列表请求失败：保留现有列表和恢复指针，断网不能被当成“没有论文任务”。
    sessionListLoaded = false;
    updateWorkspaceTrust();
    announceWorkspace('论文任务列表加载失败，已保留上次恢复位置，可稍后重试。');
    return { ok: false, items: null, selected: null };
  }
  sessionListLoaded = true;
  if (!workspaceServerLoaded) {
    // 上次读取工作区失败，列表恢复后重新读取，避免用本地默认值覆盖服务端指针。
    await loadWorkspaceState();
  }
  updateWorkspaceTrust();
  sessionCache = items;
  const previousSession = currentSession;
  const selected = resolveSessionSelection(
    sessionCache, options.preferredTaskId || previousSession,
  );
  if (!selected) {
    currentSession = null;
    currentSessionTitle = '';
    renderSessionList();
    await clearSessionContext();
    return { ok: true, items, selected: null };
  }
  currentSession = selected.task_id;
  currentSessionTitle = selected.title || '';
  renderSessionList();
  // 首次恢复时即使前后 ID 相同，也必须加载一次详情。
  if (options.forceDetail || previousSession !== currentSession) {
    await loadSessionDetail(currentSession);
  }
  return { ok: true, items, selected };
}

let sessionDetailRequest = 0;
async function loadSessionDetail(taskId) {
  const requestId = ++sessionDetailRequest;
  const prog = await apiSessionProgress(taskId);
  if (requestId !== sessionDetailRequest || taskId !== currentSession) return;
  if (prog) { renderStagesFromProgress(prog); updateRunBtn(prog); }
  currentKnowledgeSession = prog?.session_id || taskId;
  await loadKbPanel(currentKnowledgeSession);
  if (requestId !== sessionDetailRequest || taskId !== currentSession) return;
  buildHistoryFromProgress(prog);
  await loadActiveWorkbenchPane();
}

// —— 根据进度重建消息历史（刷新后恢复已完成环）——
function buildHistoryFromProgress(prog) {
  if (!prog || !prog.rings) return;
  document.querySelectorAll('.cand-item').forEach(button => {
    button.disabled = prog.current_ring_no !== 1 || prog.phase_state !== 'WAITING_APPROVAL';
  });
  const flow = document.getElementById('chat-flow');
  const inner = flow.querySelector('.chat-inner');
  const finished = prog.rings.filter(r => r.state === 'PASSED');
  const summaryText = finished.length >= 10
    ? `论文任务：${prog.title || currentSessionTitle || '当前任务'}（10/10 环已完成）`
    : `论文任务：${prog.title || currentSessionTitle || '当前任务'}（已完成 ${finished.length}/10 环，当前环${prog.current_ring_no} ${RING_NAMES[prog.current_ring_no] || ''}）`;
  if (inner.dataset.historyTask !== prog.task_id) {
    inner.dataset.historyBuilt = '';
    inner.dataset.historyTask = prog.task_id;
    inner.replaceChildren();
  }
  // 同一任务已重建时仍确保待确认闸门存在。
  if (inner.dataset.historyBuilt === '1') {
    const summary = inner.querySelector('[data-progress-summary] .bubble');
    if (summary) summary.textContent = summaryText;
    if (prog.phase_state === 'WAITING_APPROVAL') appendGateBlock(
      prog.current_ring_no,
      prog.author_decision_ready !== false,
      prog.author_decision_blocker || '',
    );
    return;
  }
  inner.dataset.historyBuilt = '1';
  const summary = appendUserMsg(summaryText);
  summary.dataset.progressSummary = 'true';
  finished.forEach(r => {
    const name = RING_NAMES[r.ring_no] || ('环' + r.ring_no);
    const trust = r.ring_no === 8 ? prog.trust_assessments?.['8'] : null;
    const evidencePassed = trust?.highest_tier === 'EVIDENCE';
    const statusText = trust && !evidencePassed
      ? `<i data-lucide="alert-triangle" class="icon-xs" style="vertical-align:-2px"></i> 流程已确认 · ${escapeHtml2(trust.highest_tier_label || '证据未通过')}`
      : '✓ 已通过';
    const statusColor = trust && !evidencePassed ? 'var(--warning)' : 'var(--success)';
    appendAIMsg(`<p><strong>环${r.ring_no} ${name}</strong> <span style="color:${statusColor}">${statusText}</span></p>` +
      (trust ? renderTrustAssessment(trust, true) : '') +
      '<p style="font-size:12px;color:var(--text-subtle);">本环产物已确认。</p>',
      `${name} · ${trust && !evidencePassed ? '有限可信' : '已通过'}`);
  });
  const cur = prog.current_ring_no;
  if (prog.phase_state === 'WAITING_APPROVAL') {
    if ([1, 2, 3, 4, 5, 8].includes(cur) && prog.author_decision_payload) {
      renderRingResult(cur, prog.author_decision_payload);
    } else {
      appendAIMsg(`<p style="font-size:13px;">环${cur}（${RING_NAMES[cur] || ''}）已通过自动验收，等待你的确认。</p>`, '待确认');
    }
    appendGateBlock(cur, prog.author_decision_ready !== false, prog.author_decision_blocker || '');
  } else if (finished.length >= 10) {
    appendAIMsg('<p><strong>十个环节已全部确认完成。</strong></p>', '流程完成');
  } else if (cur <= 10) {
    appendAIMsg(`<p style="font-size:13px;">当前环：<strong>环${cur}（${RING_NAMES[cur] || ''}）</strong>，可点击下方执行当前环节。</p>`, '待执行');
  }
}

// —— 进度 → 阶段条（10 环状态）——
function renderStagesFromProgress(prog) {
  const rings = (prog && prog.rings) || [];
  if (!rings.length) return;
  const STAGE_MAP = {
    1:'选题',2:'开题',3:'文献',4:'综述',5:'大纲',6:'撰写',7:'润色',8:'引用',9:'排版',10:'定稿'
  };
  const states = [];
  rings.forEach(r => {
    let st = 'todo';
    const trust = r.ring_no === 8 ? prog.trust_assessments?.['8'] : null;
    if (r.state === 'PASSED') {
      st = trust && trust.highest_tier !== 'EVIDENCE' ? 'done-limited' : 'done';
    }
    else if (r.state === 'WAITING_APPROVAL') st = 'gate';
    else if (r.state === 'FALLBACK') st = 'revert';
    else if (r.state === 'IN_PROGRESS' || (r.state === 'NOT_STARTED' && r.ring_no && r.ring_no === prog.current_ring_no && prog.complete_percent < 100)) st = 'current';
    states.push({
      no: r.ring_no,
      name: STAGE_MAP[r.ring_no] || ('环'+r.ring_no),
      state: st,
      trustLabel: trust?.highest_tier_label || '',
    });
  });
  // 渲染 stage-bar
  const bar = document.getElementById('stage-bar');
  if (bar) {
    bar.innerHTML = '';
    states.forEach((s, i) => {
      const node = document.createElement('div');
      node.className = 'stage-node ' + s.state;
      const meta = STAGES.find(item => item.name === s.name);
      const icon = s.state === 'done' ? 'check'
        : s.state === 'done-limited' ? 'triangle-alert'
        : (meta?.icon || 'circle');
      node.innerHTML = (
        `<div class="stage-dot"><i data-lucide="${icon}" class="stage-icon"></i></div>`
        + `<div class="stage-label">${s.name}</div>`
      );
      node.title = `${i+1}. ${s.name}${s.trustLabel ? ` · ${s.trustLabel}` : ''}`;
      bar.appendChild(node);
      if (i < states.length - 1) {
        const line = document.createElement('div');
        line.className = 'stage-line' + (
          s.state === 'done' ? ' done' : s.state === 'done-limited' ? ' done-limited' : ''
        );
        bar.appendChild(line);
      }
    });
    renderLucideIcons();
  }
}

// —— 确认进入下一环（闸门按钮）——
async function confirmNextRing(event) {
  if (!currentSession) return;
  const button = event?.currentTarget || document.querySelector('[data-gate]');
  const progress = await apiSessionProgress(currentSession);
  const ringNo = Number(button?.dataset.ring || progress?.current_ring_no || 0);
  if (!ringNo) { toast('无法确定当前环节'); return; }
  if (button) button.disabled = true;
  const r = await apiPost(`/api/v1/console/tasks/${currentSession}/rings/${ringNo}/confirm`, {
    confirmed: true,
  });
  if (r.code === 0) {
    toast(r.msg || (ringNo === 10 ? '论文全流程已完成' : '已确认，进入下一环'));
    button?.closest('.gate-block')?.remove();
    await loadSessionDetail(currentSession);
    await loadSessions();
    await refreshVisibleResumeSummary();
  } else {
    if (button) button.disabled = false;
    toast('确认失败: ' + (r.msg || '当前产物状态异常'));
  }
}
// —— 执行当前环节 ——
let ringRunning = false;
let activeJobRecoveryTask = '';
async function runCurrentRing() {
  if (!currentSession || ringRunning) return;
  const btn = document.getElementById('run-cur-ring');
  const label = document.getElementById('run-btn-label');
  const loading = document.getElementById('run-loading');
  ringRunning = true;
  if (btn) btn.disabled = true;
  if (label) label.style.display = 'none';
  if (loading) loading.style.display = '';
  try {
    const prog = await apiSessionProgress(currentSession);
    const no = prog ? prog.current_ring_no : 1;
    if (!no || no < 1 || no > 10) { toast('无法确定当前环节'); return; }
    appendUserMsg(`后台执行环${no}（${RING_NAMES[no] || ''}）`);
    if (no === 9) {
      const generated = await enqueueJobAndWait('docx.generate', {}, '生成 DOCX');
      if (generated.code !== 0) {
        appendAIMsg(`<div class="warn-card"><div class="warn-title">docx 生成失败</div><div style="font-size:13px;">${escapeHtml2(generated.msg || '')}</div></div>`, '排版准备失败');
        toast('docx 生成失败，不能执行排版检查');
        return;
      }
      appendAIMsg('<p><strong>待排版 docx 已生成</strong>，开始执行版式检查。</p>', '文档生成');
    }
    const result = await enqueueJobAndWait('ring.execute', { ring_no: no }, `环${no} ${RING_NAMES[no] || ''}`);
    if (result.code === 0) {
      renderRingResult(no, result.data);
      appendGateBlock(
        no,
        ![1, 3].includes(no),
        no === 1 ? '请先选择候选题目' : '请先完成文献筛选',
      );
      toast(result.msg || `环${no} 完成`);
    } else {
      const recovery = no === 8
        ? '<button class="btn btn-primary btn-sm" onclick="rollbackRing(6)">回到环6修订正文与引用</button><button class="btn btn-secondary btn-sm" onclick="rollbackRing(3)">回到环3整理文献</button>'
        : no === 7
        ? '<button class="btn btn-primary btn-sm" onclick="rollbackRing(6)">回到环6修订初稿</button>'
        : no === 3
        ? '<button class="btn btn-primary btn-sm" onclick="document.querySelector(\'.kb-tab[data-tab=refs]\')?.click(); document.querySelector(\'.kb-upload-btn\')?.focus()">补充文献后重试</button>'
        : '';
      appendAIMsg(`<div class="warn-card"><div class="warn-title">环${no} 执行未完成</div><div style="font-size:13px;">${escapeHtml2(result.msg || '')}</div><div class="warn-actions">${recovery}<button class="btn btn-secondary btn-sm" onclick="document.querySelector('.kb-tab[data-tab=jobs]')?.click()">查看后台作业</button></div></div>`, '后台作业失败');
    }
    await loadSessionDetail(currentSession);
    await loadSessions();
    // 无论成功或失败，环执行都会改变阶段状态；只有重取摘要才能保证横幅准确。
    await refreshVisibleResumeSummary();
  } finally {
    ringRunning = false;
    if (label) label.style.display = '';
    if (loading) loading.style.display = 'none';
    const latest = currentSession ? await apiSessionProgress(currentSession) : null;
    updateRunBtn(latest);
  }
}

// —— 更新执行按钮状态（选中会话/完成全部后禁用）——
function updateRunBtn(prog) {
  const btn = document.getElementById('run-cur-ring');
  if (!btn) return;
  if (!currentSession) {
    btn.disabled = true;
    document.getElementById('run-btn-label').textContent = '请先选择论文任务';
    return;
  }
  if (activeJobRecoveryTask === currentSession) {
    btn.disabled = true;
    document.getElementById('run-btn-label').textContent = '恢复后台作业状态…';
    return;
  }
  const no = prog ? prog.current_ring_no : 1;
  const finished = prog ? prog.rings.filter(r => r.state === 'PASSED').length : 0;
  if (finished >= 10) { btn.disabled = true; document.getElementById('run-btn-label').textContent = '已全部完成'; }
  else if (prog?.can_confirm) { btn.disabled = true; document.getElementById('run-btn-label').textContent = `等待确认环${no}产物`; }
  else { btn.disabled = false; document.getElementById('run-btn-label').textContent = `执行当前环节（环${no} ${RING_NAMES[no] || ''}）`; }
}

// —— 新建对话（“新建对话”按钮触发）——
function handleNewSession() {
  const modal = document.getElementById('new-session-modal');
  if (modal) showAccessibleDialog(modal, document.getElementById('ns-title-input'));
  const input = document.getElementById('ns-title-input');
  if (input) setTimeout(() => input.focus(), 50);
}

async function submitNewSession() {
  const titleInput = document.getElementById('ns-title-input');
  const titleError = document.getElementById('ns-title-error');
  const title = titleInput.value.trim();
  if (!title) {
    titleInput.setAttribute('aria-invalid', 'true');
    titleError.textContent = '请输入论文题目。';
    titleInput.focus();
    return;
  }
  titleInput.removeAttribute('aria-invalid');
  titleError.textContent = '';
  const degree = document.getElementById('ns-degree').value;
  const subject = document.getElementById('ns-subject').value.trim() || '自然语言处理';
  const scope = document.getElementById('ns-scope')?.value || 'all';
  await window.ThesisAutosave?.flushAllDrafts?.();
  const r = await apiCreateSession({
    title, degree, subject_field: subject, scope,
  });
  const modal = document.getElementById('new-session-modal');
  if (modal) hideAccessibleDialog(modal);
  if (r.code === 0) {
    toast('会话已创建：' + title);
    document.getElementById('ns-title-input').value = '';
    document.getElementById('ns-subject').value = '';
    const createdTaskId = r.data?.task_id || '';
    window.ThesisAutosave?.resetAutosaveIdentity?.();
    workspaceState = { ...workspaceState, expanded_items: [], editor_anchor: '' };
    applyWorkspaceExpandedItems();
    hideResumeBanner();
    // 用创建响应中的 task_id 锁定当前任务，列表刷新后不能跳回旧任务。
    const result = await loadSessions({
      preferredTaskId: createdTaskId,
      forceDetail: true,
    });
    if (result.ok) {
      scheduleWorkspaceSave({
        last_task_id: currentSession || '',
        active_tab: workspaceState.active_tab || 'refs',
        expanded_items: [],
        editor_anchor: '',
      });
    }
  } else {
    toast('创建失败: ' + (r.msg || ''));
  }
}

function bindNewSessionModal() {
  const modal = document.getElementById('new-session-modal');
  document.getElementById('ns-cancel').addEventListener('click', () => hideAccessibleDialog(modal));
  document.getElementById('ns-confirm').addEventListener('click', submitNewSession);
  modal.addEventListener('click', e => { if (e.target === modal) hideAccessibleDialog(modal); });
  const ti = document.getElementById('ns-title-input');
  if (ti) ti.addEventListener('keydown', e => { if (e.key === 'Enter') submitNewSession(); });
}

/* ============================================================
   API 基座（对接后端 http://127.0.0.1:8000）
   ============================================================ */
const API_BASE = (
  window.API_BASE ||
  new URLSearchParams(window.location.search).get('apiBase') ||
  'http://127.0.0.1:8000'
).replace(/\/$/, '');

async function apiRequest(path, options = {}, timeoutMs = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(API_BASE + path, {
      ...options,
      signal: controller.signal,
      credentials: 'include',
      headers: { 'Accept': 'application/json', ...(options.headers || {}) },
    });
    let body;
    try { body = await resp.json(); }
    catch (_) { body = { code: resp.status || -1, msg: '服务返回了无法解析的响应', data: null }; }
    if (resp.status === 401 && !path.startsWith('/api/v1/auth/login')) showLoginModal();
    if (!resp.ok && (!body || body.code === 0)) {
      return { code: resp.status, msg: `请求失败（HTTP ${resp.status}）`, data: body?.data || null };
    }
    return body;
  } catch (error) {
    const timeout = error?.name === 'AbortError';
    return {
      code: -1,
      msg: timeout ? '请求超时，请检查后端任务状态后重试' : `无法连接后端：${error?.message || '网络错误'}`,
      data: null,
    };
  } finally {
    clearTimeout(timer);
  }
}

async function apiGet(path, params) {
  const url = new URL(API_BASE + path);
  if (params) Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v));
  return apiRequest(url.pathname + url.search);
}

async function apiPost(path, body, method = 'POST') {
  return apiRequest(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}

// ---- 会话（console）----
// 返回 null 表示“请求失败”，返回数组表示“请求成功”。调用方不得把失败当成空列表。
async function apiListSessions() {
  const r = await apiGet('/api/v1/console/tasks');
  return r.code === 0 ? (Array.isArray(r.data) ? r.data : []) : null;
}
async function apiWorkspaceState() {
  const response = await apiGet('/api/v1/console/workspace');
  return response.code === 0 ? (response.data || null) : null;
}
async function apiSaveWorkspaceState(payload) {
  return apiPost('/api/v1/console/workspace', payload);
}
async function apiTaskResume(taskId) {
  return apiGet(`/api/v1/console/tasks/${encodeURIComponent(taskId)}/resume`);
}
async function apiCreateSession(payload) {
  return apiPost('/api/v1/console/tasks', payload);
}
async function apiSessionProgress(taskId) {
  const r = await apiGet(`/api/v1/console/tasks/${taskId}/progress`);
  return r.code === 0 ? (r.data || null) : null;
}
async function apiDeepSeekConfig() {
  return apiGet('/api/v1/console/provider/deepseek');
}
async function apiSaveDeepSeekConfig(payload) {
  return apiPost('/api/v1/console/provider/deepseek', payload);
}

window.addEventListener('load', async () => {
  const response = await apiDeepSeekConfig();
  if (response.code === 0) applyDeepSeekConfigView(response.data);
});
async function apiRunRing(taskId, ringPath) {
  return apiPost(`/api/v1/console/tasks/${taskId}${ringPath}`);
}
async function apiSelectCandidate(taskId, candidateIndex, title) {
  return apiPost(`/api/v1/console/tasks/${taskId}/rings/1/select`, {
    candidate_index: candidateIndex, title,
  });
}
async function apiCurateLiterature(taskId, includedIndexes) {
  return apiPost(`/api/v1/console/tasks/${taskId}/rings/3/curate`, {
    included_indexes: includedIndexes,
  });
}
async function apiReopenStage(taskId, targetRingNo, reason) {
  return apiPost(`/api/v1/console/tasks/${taskId}/reopen`, {
    target_ring_no: targetRingNo, reason,
  });
}
async function apiDeleteSession(taskId) {
  return apiRequest(`/api/v1/console/tasks/${taskId}`, { method: 'DELETE' });
}

async function apiGenerateDocx(taskId) {
  return apiPost(`/api/v1/console/tasks/${taskId}/docx/generate`);
}

// ---- 可信工作台：记忆 / 证据 / 分节 / 作业 ----
async function apiTaskClaims(taskId) {
  return apiGet(`/api/v1/console/tasks/${taskId}/claims`);
}
async function apiAcademicFoundation(taskId) {
  return apiGet(`/api/v1/console/tasks/${taskId}/academic-foundation`);
}
async function apiArgumentMaps(taskId) {
  return apiGet(`/api/v1/console/tasks/${taskId}/research/argument-maps`);
}
async function apiSectionDrafts(taskId) {
  return apiGet(`/api/v1/console/tasks/${taskId}/writing/sections`);
}
async function apiSectionAudit(taskId) {
  return apiGet(`/api/v1/console/tasks/${taskId}/writing/sections-audit`);
}
// —— 作者私有自动草稿（未提交工作副本，不推进流程）——
function autosaveDraftsPath(taskId, draftKey = '') {
  const base = `/api/v1/console/tasks/${taskId}/autosave-drafts`;
  return draftKey ? `${base}/${encodeURIComponent(draftKey)}` : base;
}
async function apiListAutosaveDrafts(taskId) {
  return apiGet(autosaveDraftsPath(taskId));
}
async function apiGetAutosaveDraft(taskId, draftKey) {
  return apiGet(autosaveDraftsPath(taskId, draftKey));
}
async function apiSaveAutosaveDraft(taskId, draftKey, payload) {
  return apiPost(autosaveDraftsPath(taskId, draftKey), payload, 'PUT');
}
async function apiDiscardAutosaveDraft(taskId, draftKey, revision) {
  return apiPost(
    `${autosaveDraftsPath(taskId, draftKey)}/discard`,
    { revision },
  );
}
async function apiReviewSection(taskId, draftId, approved, reason = '') {
  return apiPost(`/api/v1/console/tasks/${taskId}/writing/sections/${draftId}/review`, { approved, reason });
}
async function apiReviewAllSections(taskId, approved) {
  return apiPost(`/api/v1/console/tasks/${taskId}/writing/sections/review-all`, {
    approved, actor: 'author',
  });
}
async function apiReviseSection(taskId, draftId, content, title = '', autosave = null) {
  const payload = { content, title, actor: 'author' };
  if (autosave) {
    payload.autosave_draft_key = autosave.draftKey;
    payload.autosave_revision = autosave.revision;
  }
  return apiPost(
    `/api/v1/console/tasks/${taskId}/writing/sections/${draftId}/revise`,
    payload,
  );
}
async function apiTemplateConfig(taskId) {
  return apiGet(`/api/v1/console/tasks/${taskId}/template`);
}
async function apiUploadTaskTemplate(taskId, file) {
  const form = new FormData();
  form.append('file', file);
  return apiRequest(`/api/v1/console/tasks/${taskId}/template`, { method: 'POST', body: form }, 120000);
}
async function apiSaveTemplateMapping(taskId, mapping) {
  return apiPost(`/api/v1/console/tasks/${taskId}/template/mapping`, { mapping });
}
async function apiListJobs(taskId) {
  return apiGet(`/api/v1/console/tasks/${taskId}/jobs`, { limit: 100 });
}
async function apiGetJob(taskId, jobId) {
  return apiGet(`/api/v1/console/tasks/${taskId}/jobs/${jobId}`);
}
async function apiEnqueueJob(taskId, payload) {
  return apiPost(`/api/v1/console/tasks/${taskId}/jobs`, payload);
}
async function apiCancelJob(taskId, jobId) {
  return apiPost(`/api/v1/console/tasks/${taskId}/jobs/${jobId}/cancel`);
}
async function apiRetryJob(taskId, jobId) {
  return apiPost(`/api/v1/console/tasks/${taskId}/jobs/${jobId}/retry`);
}
async function apiResearchProtocols(taskId) {
  return apiGet(`/api/v1/console/tasks/${taskId}/research/protocols`);
}
async function apiCreateProtocol(taskId, payload) {
  return apiPost(`/api/v1/console/tasks/${taskId}/research/protocols`, payload);
}
async function apiReviewProtocol(taskId, artifactId, approved, reason = '') {
  return apiPost(`/api/v1/console/tasks/${taskId}/research/protocols/${artifactId}/review`, { approved, reason });
}
async function apiCreateArgumentMap(taskId, payload) {
  return apiPost(`/api/v1/console/tasks/${taskId}/research/argument-maps`, payload);
}
async function apiReviewArgumentMap(taskId, artifactId, approved, reason = '') {
  return apiPost(`/api/v1/console/tasks/${taskId}/research/argument-maps/${artifactId}/review`, { approved, reason });
}
async function apiResearchRuns(taskId) {
  return apiGet(`/api/v1/console/tasks/${taskId}/research/runs`);
}
async function apiCreateResearchRun(taskId, notes = '') {
  return apiPost(`/api/v1/console/tasks/${taskId}/research/runs`, { notes });
}
async function apiTransitionResearchRun(taskId, runId, payload) {
  return apiPost(`/api/v1/console/tasks/${taskId}/research/runs/${runId}/transition`, payload);
}
async function apiResearchResults(taskId, runId = '') {
  return apiGet(`/api/v1/console/tasks/${taskId}/research/results`, runId ? { run_id: runId } : null);
}
async function apiAddResearchResult(taskId, runId, payload) {
  return apiPost(`/api/v1/console/tasks/${taskId}/research/runs/${runId}/results`, payload);
}
async function apiReviewResearchResult(taskId, resultId, verified) {
  return apiPost(`/api/v1/console/tasks/${taskId}/research/results/${resultId}/review`, { verified_by_user: verified });
}
async function apiResearchAudit(taskId) {
  return apiGet(`/api/v1/console/tasks/${taskId}/research/audit`);
}
async function apiCreateResultLedger(taskId) {
  return apiPost(`/api/v1/console/tasks/${taskId}/research/result-ledgers`);
}
async function apiReviewResultLedger(taskId, artifactId, approved, reason = '') {
  return apiPost(`/api/v1/console/tasks/${taskId}/research/result-ledgers/${artifactId}/review`, { approved, reason });
}
async function apiTaskArtifacts(taskId) {
  return apiGet(`/api/v1/console/tasks/${taskId}/artifacts`);
}
async function apiUploadResearchFile(sessionId, file, kind) {
  const form = new FormData();
  form.append('file', file);
  form.append('title', file.name.replace(/\.[^.]+$/, ''));
  form.append('kind', kind);
  return apiRequest(`/api/v1/kb/${encodeURIComponent(sessionId)}/files`, { method: 'POST', body: form }, 120000);
}
async function apiLogin(username, password) {
  return apiPost('/api/v1/auth/login', { username, password });
}
async function apiLogout() {
  return apiPost('/api/v1/auth/logout');
}
async function apiSecurityAudit() {
  return apiGet('/api/v1/auth/audit', { limit: 200 });
}

// ---- 知识库 ----
async function apiKbList(sessionId) {
  const r = await apiGet(`/api/v1/kb/${encodeURIComponent(sessionId)}/files`);
  return r.code === 0 ? (r.data?.items || []) : [];
}
async function apiKbUpload(sessionId, file) {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('title', file.name.replace(/\.\w+$/, ''));
  return apiRequest(`/api/v1/kb/${encodeURIComponent(sessionId)}/files`, { method: 'POST', body: fd }, 120000);
}
async function apiKbDelete(sessionId, fileId) {
  return apiRequest(`/api/v1/kb/${encodeURIComponent(sessionId)}/files/${encodeURIComponent(fileId)}`, { method: 'DELETE' });
}

// ---- 工具 ----
const DEGREE_LABEL = { BACHELOR: '本科', MASTER: '硕士', PHD: '博士' };

applyI18n();

/* ============================================================
   可信写作工作台：作业 / 证据 / 分节
   ============================================================ */
const JOB_TERMINAL = new Set(['SUCCEEDED', 'FAILED', 'CANCELLED']);
const JOB_STATUS_LABEL = {
  PENDING: '排队中', RUNNING: '执行中', CANCEL_REQUESTED: '取消中',
  SUCCEEDED: '已完成', FAILED: '失败', CANCELLED: '已取消',
};

function wbStatusClass(status) {
  if (['SUCCEEDED', 'APPROVED', 'SUPPORTED'].includes(status)) return 'ok';
  if (['FAILED', 'CANCELLED', 'REJECTED', 'AUTO_REJECTED', 'STALE', 'DISPUTED', 'UNSUPPORTED', 'INVALID_SOURCE'].includes(status)) return 'bad';
  return 'warn';
}

function formatCount(value) {
  return new Intl.NumberFormat(currentLang || 'zh-CN', { maximumFractionDigits: 4 }).format(Number(value || 0));
}

function currentJobBudget() {
  const tokenInput = document.getElementById('job-token-budget');
  const costInput = document.getElementById('job-cost-budget');
  return {
    token_budget: Math.max(0, Number.parseInt(tokenInput?.value || '0', 10) || 0),
    cost_budget: Math.max(0, Number.parseFloat(costInput?.value || '0') || 0),
  };
}

function restoreJobBudget() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('thesis-job-budget') || '{}'); }
  catch (_) { saved = {}; }
  const tokenInput = document.getElementById('job-token-budget');
  const costInput = document.getElementById('job-cost-budget');
  if (tokenInput && Number.isFinite(saved.token_budget)) tokenInput.value = String(saved.token_budget);
  if (costInput && Number.isFinite(saved.cost_budget)) costInput.value = String(saved.cost_budget);
  [tokenInput, costInput].forEach(input => input?.addEventListener('change', () => {
    localStorage.setItem('thesis-job-budget', JSON.stringify(currentJobBudget()));
  }));
}

async function enqueueJobAndWait(operation, payload, label) {
  if (!currentSession) return { code: 1, msg: '请先选择论文任务' };
  const taskId = currentSession;
  const live = document.getElementById('jobs-live');
  const existingResponse = await apiListJobs(taskId);
  const existing = existingResponse.code === 0
    ? (existingResponse.data || []).find(job =>
        job.operation === operation && !JOB_TERMINAL.has(job.status)
        && JSON.stringify(job.payload || {}) === JSON.stringify(payload || {}))
    : null;
  let job = existing;
  if (!job) {
    const randomPart = window.crypto?.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
    const queued = await apiEnqueueJob(taskId, {
      operation,
      payload,
      idempotency_key: `${operation}-${randomPart}`,
      max_attempts: 3,
      ...currentJobBudget(),
    });
    if (queued.code !== 0) return queued;
    job = queued.data;
  }
  if (live) live.textContent = `${label}：${JOB_STATUS_LABEL[job.status] || job.status}`;
  await loadJobsPanel(false);
  return waitForJob(taskId, job.job_id, label);
}

async function waitForJob(taskId, jobId, label) {
  const deadline = Date.now() + 30 * 60 * 1000;
  let networkFailures = 0;
  let pollDelay = 900;
  while (Date.now() < deadline) {
    const response = await apiGetJob(taskId, jobId);
    if (response.code !== 0) {
      networkFailures += 1;
      if (networkFailures >= 5) {
        return { code: response.code, msg: `${label}仍在后台执行，但状态查询连续失败：${response.msg}` };
      }
      await new Promise(resolve => setTimeout(resolve, Math.max(1500, pollDelay)));
      pollDelay = Math.min(pollDelay * 1.6, 5000);
      continue;
    }
    networkFailures = 0;
    const job = response.data;
    const live = document.getElementById('jobs-live');
    if (live) {
      live.textContent = `${label}：${JOB_STATUS_LABEL[job.status] || job.status} · Token ${formatCount(job.tokens_used)}`;
    }
    if (document.querySelector('.kb-tab.active')?.dataset.tab === 'jobs') renderJobs([job]);
    if (JOB_TERMINAL.has(job.status)) {
      await loadJobsPanel(false);
      if (job.status === 'SUCCEEDED') return job.result || { code: 0, msg: `${label}完成`, data: null };
      return { code: 1, msg: job.error || `${label}${JOB_STATUS_LABEL[job.status]}`, data: { job } };
    }
    const effectiveDelay = document.hidden ? Math.max(pollDelay, 10000) : pollDelay;
    await new Promise(resolve => setTimeout(resolve, effectiveDelay));
    pollDelay = Math.min(pollDelay * 1.6, 5000);
  }
  return { code: 1, msg: `${label}超过30分钟仍未完成，可在“作业”页继续查看或取消` };
}

async function resumeActiveJobs(taskId) {
  if (!taskId || activeJobRecoveryTask === taskId) return;
  activeJobRecoveryTask = taskId;
  try {
    const response = await apiListJobs(taskId);
    if (taskId !== currentSession || response.code !== 0) return;
    const activeJobs = (response.data || []).filter(job =>
      ['PENDING', 'RUNNING', 'CANCEL_REQUESTED'].includes(job.status)
      && ['ring.execute', 'docx.generate'].includes(job.operation)
    );
    if (!activeJobs.length) return;
    updateRunBtn(await apiSessionProgress(taskId));
    for (const job of activeJobs) {
      if (taskId !== currentSession) break;
      const ringNo = Number(job.payload?.ring_no || 0);
      const label = job.operation === 'ring.execute'
        ? `环${ringNo || ''} ${RING_NAMES[ringNo] || ''}`.trim()
        : '生成 DOCX';
      const result = await waitForJob(taskId, job.job_id, label);
      if (taskId !== currentSession) break;
      const inner = document.getElementById('chat-flow')?.querySelector('.chat-inner');
      if (inner) inner.dataset.historyBuilt = '';
      await loadSessionDetail(taskId);
      await loadSessions();
      await refreshVisibleResumeSummary();
      if (result.code !== 0) {
        announceWorkspace(result.msg || `${label}执行失败`);
      }
    }
  } finally {
    if (activeJobRecoveryTask === taskId) activeJobRecoveryTask = '';
    if (taskId === currentSession) {
      const latest = await apiSessionProgress(taskId);
      if (taskId === currentSession) updateRunBtn(latest);
    }
  }
}

async function loadJobsPanel(announce = true) {
  const box = document.getElementById('job-list');
  if (!box) return;
  if (!currentSession) {
    box.innerHTML = '<div class="wb-empty">选择论文任务后查看后台作业。</div>';
    return;
  }
  const taskId = currentSession;
  box.setAttribute('aria-busy', 'true');
  const response = await apiListJobs(taskId);
  if (taskId !== currentSession) return;
  box.removeAttribute('aria-busy');
  if (response.code !== 0) {
    box.innerHTML = `<div class="wb-error">${escapeHtml2(response.msg)}<div class="wb-card-actions"><button class="btn btn-secondary btn-sm" onclick="loadJobsPanel()">重试</button></div></div>`;
    return;
  }
  renderJobs(response.data || []);
  if (announce) document.getElementById('jobs-live').textContent = `已加载 ${(response.data || []).length} 个作业`;
  // 轮询发现活动作业集合变化时，横幅必须跟着更新或隐藏。
  syncResumeBannerWithJobs(response.data || []);
}

function renderJobs(jobs) {
  const box = document.getElementById('job-list');
  if (!box) return;
  if (!jobs.length) {
    box.innerHTML = '<div class="wb-empty">暂无后台作业。执行环节或生成分节后会显示在这里。</div>';
    return;
  }
  const html = jobs.map(job => {
    const tokenPct = job.token_budget > 0 ? Math.min(100, (job.tokens_used / job.token_budget) * 100) : 0;
    const canCancel = ['PENDING', 'RUNNING', 'CANCEL_REQUESTED'].includes(job.status);
    const canRetry = ['FAILED', 'CANCELLED'].includes(job.status);
    return `<article class="wb-card" data-job-id="${escapeHtml2(job.job_id)}">
      <div style="display:flex;justify-content:space-between;gap:8px;align-items:start;">
        <div class="wb-card-title">${escapeHtml2(job.operation)}</div>
        <span class="wb-status ${wbStatusClass(job.status)}">${escapeHtml2(JOB_STATUS_LABEL[job.status] || job.status)}</span>
      </div>
      <div class="wb-card-meta">${escapeHtml2(job.job_id)} · 尝试 ${job.attempt}/${job.max_attempts}</div>
      <div class="wb-card-meta">Token ${formatCount(job.tokens_used)}${job.token_budget ? ` / ${formatCount(job.token_budget)}` : '（不限）'} · 费用 ${formatCount(job.cost_used)}</div>
      ${job.token_budget ? `<div class="wb-progress" aria-label="Token 使用 ${Math.round(tokenPct)}%"><span style="width:${tokenPct}%"></span></div>` : ''}
      ${job.error ? `<div class="wb-card-meta" style="color:var(--error)">${escapeHtml2(job.error)}</div>` : ''}
      <div class="wb-card-actions">
        ${canCancel ? `<button class="btn btn-secondary btn-sm" data-job-action="cancel">取消</button>` : ''}
        ${canRetry ? `<button class="btn btn-secondary btn-sm" data-job-action="retry">重试</button>` : ''}
      </div>
    </article>`;
  }).join('');
  box.innerHTML = html;
  box.querySelectorAll('[data-job-action]').forEach(button => button.addEventListener('click', handleJobAction));
}

async function handleJobAction(event) {
  const card = event.currentTarget.closest('[data-job-id]');
  const jobId = card?.dataset.jobId;
  if (!jobId || !currentSession) return;
  event.currentTarget.disabled = true;
  const action = event.currentTarget.dataset.jobAction;
  const response = action === 'cancel'
    ? await apiCancelJob(currentSession, jobId)
    : await apiRetryJob(currentSession, jobId);
  toast(response.code === 0 ? response.msg : `${action === 'cancel' ? '取消' : '重试'}失败：${response.msg}`);
  await loadJobsPanel(false);
  // 取消 / 重试会改变活动作业集合；只有成功才刷新摘要，失败不得伪造新状态。
  if (response.code === 0) await refreshVisibleResumeSummary();
}

async function loadSecurityAudit() {
  const box = document.getElementById('security-audit-list');
  if (!box) return;
  box.setAttribute('aria-busy', 'true');
  const response = await apiSecurityAudit();
  box.removeAttribute('aria-busy');
  if (response.code !== 0) {
    box.innerHTML = `<div class="wb-error">${escapeHtml2(response.msg || '审计日志不可用')}</div>`;
    return;
  }
  const items = response.data || [];
  box.innerHTML = items.length ? items.slice(0, 100).map(item => `<article class="wb-card">
    <div class="wb-card-title">${escapeHtml2(item.action)}</div>
    <div class="wb-card-meta">${escapeHtml2(item.method || '')} ${escapeHtml2(item.path || item.resource_id || '')} · HTTP ${item.status_code || 0}</div>
    <div class="wb-card-meta">${escapeHtml2(item.created_at)} · ${escapeHtml2(item.request_id || '')}</div>
  </article>`).join('') : '<div class="wb-empty">暂无审计记录。</div>';
}

let researchFiles = [];
let researchRuns = [];
let researchResults = [];
let claimRowCounter = 0;
const PROTOCOL_DRAFT_KEY = 'research-protocol:new';
const ARGUMENT_DRAFT_KEY = 'argument-map:new';

function valueLines(id) {
  return (document.getElementById(id)?.value || '').split(/\r?\n/).map(value => value.trim()).filter(Boolean);
}

function buildProtocolPayload() {
  return {
    title: document.getElementById('protocol-title').value.trim(),
    method: document.getElementById('protocol-method').value,
    research_questions: valueLines('protocol-rq'),
    procedure_steps: valueLines('protocol-steps'),
    analysis_plan: valueLines('protocol-analysis'),
    required_outputs: valueLines('protocol-outputs'),
    hypotheses: valueLines('protocol-hypotheses'),
    materials: valueLines('protocol-materials'),
    ethics_requirements: ['作者确认实验材料真实、合法且符合所在机构伦理要求'],
  };
}

function hydrateProtocolPayload(payload = {}) {
  document.getElementById('protocol-title').value = payload.title || '';
  document.getElementById('protocol-method').value = payload.method || 'QUANTITATIVE';
  document.getElementById('protocol-rq').value = (payload.research_questions || []).join('\n');
  document.getElementById('protocol-steps').value = (payload.procedure_steps || []).join('\n');
  document.getElementById('protocol-analysis').value = (payload.analysis_plan || []).join('\n');
  document.getElementById('protocol-outputs').value = (payload.required_outputs || []).join('\n');
  document.getElementById('protocol-hypotheses').value = (payload.hypotheses || []).join('\n');
  document.getElementById('protocol-materials').value = (payload.materials || []).join('\n');
  document.getElementById('protocol-builder').open = true;
}

function buildArgumentPayload() {
  const claims = [...document.querySelectorAll('[data-claim-row]')].map(row => ({
    claim_key: row.querySelector('[data-claim="key"]').value.trim(),
    section_id: row.querySelector('[data-claim="section"]').value.trim(),
    role: row.querySelector('[data-claim="role"]').value,
    epistemic_intent: row.querySelector('[data-claim="intent"]').value,
    claim_type: row.querySelector('[data-claim="type"]').value,
    parent_keys: row.querySelector('[data-claim="parents"]').value
      .split(',').map(value => value.trim()).filter(Boolean),
    text: row.querySelector('[data-claim="text"]').value.trim(),
    evidence_requirements: row.querySelector('[data-claim="evidence"]').value
      .split(',').map(value => value.trim()).filter(Boolean),
  }));
  return {
    title: document.getElementById('argument-title').value.trim(),
    research_questions: valueLines('argument-rq'),
    claims,
  };
}

function hydrateArgumentPayload(payload = {}) {
  document.getElementById('argument-title').value = payload.title || '';
  document.getElementById('argument-rq').value = (payload.research_questions || []).join('\n');
  const host = document.getElementById('argument-claim-rows');
  host.replaceChildren();
  claimRowCounter = 0;
  const claims = payload.claims?.length ? payload.claims : [{}];
  claims.forEach(claim => addArgumentClaimRow(claim, { schedule: false }));
  document.getElementById('argument-builder').open = true;
}

function scheduleArgumentAutosave() {
  window.ThesisAutosave?.scheduleDraftSave?.(ARGUMENT_DRAFT_KEY);
}

async function ensureResearchAutosaves() {
  if (!currentSession || !window.ThesisAutosave?.registerDraftSurface) return;
  const taskId = currentSession;
  const protocolForm = document.getElementById('protocol-form');
  const argumentForm = document.getElementById('argument-form');

  if (window.ThesisAutosave.surfaces.get(PROTOCOL_DRAFT_KEY)?.taskId !== taskId) {
    window.ThesisAutosave.registerDraftSurface({
      draftKey: PROTOCOL_DRAFT_KEY,
      taskId,
      objectType: 'RESEARCH_PROTOCOL_FORM',
      objectId: 'new',
      stageNo: 5,
      label: '研究协议',
      statusEl: document.getElementById('protocol-autosave-status'),
      conflictHost: document.getElementById('protocol-autosave-conflict'),
      serialize: buildProtocolPayload,
      hydrate: hydrateProtocolPayload,
      reset: () => protocolForm?.reset(),
    });
    await window.ThesisAutosave.loadDraft(PROTOCOL_DRAFT_KEY);
  }

  if (window.ThesisAutosave.surfaces.get(ARGUMENT_DRAFT_KEY)?.taskId !== taskId) {
    window.ThesisAutosave.registerDraftSurface({
      draftKey: ARGUMENT_DRAFT_KEY,
      taskId,
      objectType: 'ARGUMENT_MAP_FORM',
      objectId: 'new',
      stageNo: 5,
      label: '论证图',
      statusEl: document.getElementById('argument-autosave-status'),
      conflictHost: document.getElementById('argument-autosave-conflict'),
      serialize: buildArgumentPayload,
      hydrate: hydrateArgumentPayload,
      reset: () => {
        argumentForm?.reset();
        document.getElementById('argument-claim-rows')?.replaceChildren();
        claimRowCounter = 0;
        addArgumentClaimRow({}, { schedule: false });
      },
    });
    await window.ThesisAutosave.loadDraft(ARGUMENT_DRAFT_KEY);
  }

  if (protocolForm && !protocolForm.dataset.autosaveBound) {
    protocolForm.dataset.autosaveBound = '1';
    const schedule = () => window.ThesisAutosave.scheduleDraftSave(PROTOCOL_DRAFT_KEY);
    protocolForm.addEventListener('input', schedule);
    protocolForm.addEventListener('change', schedule);
  }
  if (argumentForm && !argumentForm.dataset.autosaveBound) {
    argumentForm.dataset.autosaveBound = '1';
    argumentForm.addEventListener('input', scheduleArgumentAutosave);
    argumentForm.addEventListener('change', scheduleArgumentAutosave);
  }
}

function addArgumentClaimRow(seed = {}, options = { schedule: true }) {
  const host = document.getElementById('argument-claim-rows');
  if (!host) return;
  const rowId = `claim-row-${++claimRowCounter}`;
  const row = document.createElement('fieldset');
  row.className = 'claim-builder-row';
  row.dataset.claimRow = rowId;
  row.innerHTML = `<legend class="sr-only">论断 ${claimRowCounter}</legend>
    <div class="wb-field"><label for="${rowId}-key">键</label><input id="${rowId}-key" data-claim="key" maxlength="40" value="${escapeHtml2(seed.claim_key || (claimRowCounter === 1 ? 'ROOT' : `C${claimRowCounter - 1}`))}" required></div>
    <div class="wb-field"><label for="${rowId}-section">章节</label><input id="${rowId}-section" data-claim="section" maxlength="40" value="${escapeHtml2(seed.section_id || '1.1')}" required></div>
    <div class="wb-field"><label for="${rowId}-role">角色</label><select id="${rowId}-role" data-claim="role"><option value="THESIS">核心论断</option><option value="CLAIM">子论断</option><option value="COUNTERCLAIM">反论断</option><option value="LIMITATION">局限</option></select></div>
    <div class="wb-field"><label for="${rowId}-intent">认识论意图</label><select id="${rowId}-intent" data-claim="intent"><option value="ASSERTION">明确断言</option><option value="INFERENCE">推论</option><option value="HYPOTHESIS">假设</option></select></div>
    <div class="wb-field"><label for="${rowId}-type">类型</label><select id="${rowId}-type" data-claim="type"><option value="FACTUAL">事实</option><option value="NUMERIC">数字</option><option value="METHOD">方法</option><option value="INTERPRETIVE">解释</option><option value="CONTRIBUTION">贡献</option></select></div>
    <div class="wb-field"><label for="${rowId}-parents">父论断键（逗号分隔）</label><input id="${rowId}-parents" data-claim="parents" value="${escapeHtml2((seed.parent_keys || []).join(','))}"></div>
    <div class="wb-field"><span class="wb-card-meta">操作</span><button id="${rowId}-remove" aria-label="删除论断 ${claimRowCounter}" class="btn btn-secondary btn-sm" type="button" data-remove-claim>删除</button></div>
    <div class="wb-field claim-text"><label for="${rowId}-text">论断文本</label><textarea id="${rowId}-text" data-claim="text" required>${escapeHtml2(seed.text || '')}</textarea></div>
    <div class="wb-field claim-evidence"><label for="${rowId}-evidence">证据需求（逗号分隔）</label><input id="${rowId}-evidence" data-claim="evidence" value="${escapeHtml2((seed.evidence_requirements || []).join(','))}"></div>`;
  row.querySelector('[data-claim="role"]').value = seed.role || (claimRowCounter === 1 ? 'THESIS' : 'CLAIM');
  row.querySelector('[data-claim="intent"]').value = seed.epistemic_intent || 'ASSERTION';
  row.querySelector('[data-claim="type"]').value = seed.claim_type || 'FACTUAL';
  row.querySelector('[data-remove-claim]').addEventListener('click', () => {
    if (host.querySelectorAll('[data-claim-row]').length <= 1) {
      document.getElementById('argument-error').textContent = '论证图至少需要一个核心论断。';
      return;
    }
    row.remove();
    scheduleArgumentAutosave();
  });
  host.appendChild(row);
  if (options.schedule !== false) scheduleArgumentAutosave();
}

function researchFileLabel(fileId) {
  const file = researchFiles.find(item => item.file_id === fileId);
  return file?.file_name || fileId;
}

function renderResearchFileChoices(run, kinds) {
  const selected = new Set([
    ...(run.material_file_ids || []), ...(run.raw_data_file_ids || []),
    ...(run.code_file_ids || []), ...(run.log_file_ids || []),
  ]);
  const files = researchFiles.filter(file => kinds.includes(file.metadata?.kind || 'other'));
  if (!files.length) return '<div class="wb-empty">请先在上方上传对应分类的文件。</div>';
  return `<div class="file-choice-list">${files.map(file => `<label class="file-choice">
    <input type="checkbox" data-run-file value="${escapeHtml2(file.file_id)}" data-kind="${escapeHtml2(file.metadata?.kind || 'other')}" ${selected.has(file.file_id) ? 'checked' : ''}>
    <span>${escapeHtml2(file.file_name)}<span class="wb-card-meta" style="display:block">${escapeHtml2(file.metadata?.kind || 'other')} · ${formatCount(file.file_size)} bytes</span></span>
  </label>`).join('')}</div>`;
}

async function loadResearchPanel() {
  const auditBox = document.getElementById('research-audit');
  const protocolBox = document.getElementById('protocol-list');
  const mapBox = document.getElementById('research-map-list');
  const runBox = document.getElementById('experiment-run-list');
  const resultBox = document.getElementById('research-result-list');
  if (!auditBox || !protocolBox || !mapBox || !runBox || !resultBox) return;
  if (!currentSession) {
    auditBox.className = 'wb-empty';
    auditBox.textContent = '选择论文任务后设计研究。';
    protocolBox.innerHTML = mapBox.innerHTML = runBox.innerHTML = resultBox.innerHTML = '';
    return;
  }
  const taskId = currentSession;
  await ensureResearchAutosaves();
  if (taskId !== currentSession) return;
  auditBox.setAttribute('aria-busy', 'true');
  const [protocolResponse, mapResponse, runResponse, resultResponse, auditResponse, artifactResponse, progress, files] = await Promise.all([
    apiResearchProtocols(taskId), apiArgumentMaps(taskId), apiResearchRuns(taskId),
    apiResearchResults(taskId), apiResearchAudit(taskId), apiTaskArtifacts(taskId),
    apiSessionProgress(taskId), apiKbList(currentKnowledgeSession || taskId),
  ]);
  if (taskId !== currentSession) return;
  auditBox.removeAttribute('aria-busy');
  const responses = [protocolResponse, mapResponse, runResponse, resultResponse, auditResponse, artifactResponse];
  const failed = responses.find(response => response.code !== 0);
  if (failed) {
    auditBox.className = 'wb-error';
    auditBox.innerHTML = `${escapeHtml2(failed.msg)}<div class="wb-card-actions"><button class="btn btn-secondary btn-sm" onclick="loadResearchPanel()">重试</button></div>`;
    return;
  }
  const protocols = protocolResponse.data || [];
  const maps = mapResponse.data || [];
  researchRuns = runResponse.data || [];
  researchResults = resultResponse.data || [];
  researchFiles = files || [];
  const audit = auditResponse.data || {};
  const artifacts = artifactResponse.data || [];
  const currentRing = progress?.current_ring_no || 1;
  const activeProtocol = protocols.find(item => item.status === 'APPROVED');
  const activeMap = maps.find(item => item.status === 'APPROVED');
  const activeLedger = artifacts.find(item => item.kind === 'RESULT_LEDGER' && item.status === 'APPROVED');

  const steps = [
    ['协议', !!activeProtocol], ['论证图', !!activeMap],
    ['实验运行', researchRuns.some(run => run.status === 'COMPLETED')],
    ['结果核验', researchResults.some(result => result.verified_by_user)],
    ['结果账本', !!activeLedger],
  ];
  auditBox.className = 'wb-card';
  auditBox.innerHTML = `<div class="wb-card-title">研究实施 Gate · 当前环${currentRing}</div>
    <div class="research-steps">${steps.map(([label, done], index) => `<span class="research-step ${done ? 'current' : ''}">${done ? '✓ ' : `${index + 1}. `}${label}</span>`).join('')}</div>
    <div class="wb-card-meta">${(audit.blocking_items || []).length ? escapeHtml2((audit.blocking_items || []).join('；')) : '研究材料满足当前写作门禁。'}</div>
    <div class="wb-card-actions">
      ${activeProtocol && !researchRuns.length ? '<button class="btn btn-primary btn-sm" data-research-action="create-run">创建实验运行</button>' : ''}
      ${audit.can_write_results && currentRing === 6 && !activeLedger ? '<button class="btn btn-primary btn-sm" data-research-action="create-ledger">生成结果账本</button>' : ''}
    </div>`;

  protocolBox.innerHTML = `<div class="kb-section-title"><span>研究协议版本</span><span class="count">${protocols.length}</span></div>` +
    (protocols.length ? protocols.map(protocol => `<article class="wb-card" data-artifact-id="${escapeHtml2(protocol.artifact_id)}">
      <div style="display:flex;justify-content:space-between;gap:8px"><div class="wb-card-title">v${protocol.version} ${escapeHtml2(protocol.payload?.title || '研究协议')}</div><span class="wb-status ${wbStatusClass(protocol.status)}">${escapeHtml2(protocol.status)}</span></div>
      <div class="wb-card-meta">${escapeHtml2(protocol.payload?.method || '')} · ${(protocol.payload?.research_questions || []).length} 个研究问题 · ${(protocol.payload?.procedure_steps || []).length} 个步骤</div>
      ${protocol.status === 'WAITING_APPROVAL' ? '<div class="wb-card-actions"><button class="btn btn-primary btn-sm" data-research-action="approve-protocol">批准</button><button class="btn btn-secondary btn-sm" data-research-action="reject-protocol">驳回</button></div>' : ''}
    </article>`).join('') : '<div class="wb-empty">环5创建研究协议后，才能开展实验。</div>');

  mapBox.innerHTML = `<div class="kb-section-title"><span>论证图版本</span><span class="count">${maps.length}</span></div>` +
    (maps.length ? maps.map(map => `<article class="wb-card" data-artifact-id="${escapeHtml2(map.artifact_id)}">
      <div style="display:flex;justify-content:space-between;gap:8px"><div class="wb-card-title">v${map.version} ${escapeHtml2(map.payload?.title || '论证图')}</div><span class="wb-status ${wbStatusClass(map.status)}">${escapeHtml2(map.status)}</span></div>
      <div class="wb-card-meta">${(map.payload?.claims || []).length} 个论断 · ${(map.payload?.research_questions || []).length} 个研究问题</div>
      ${map.status === 'WAITING_APPROVAL' ? '<div class="wb-card-actions"><button class="btn btn-primary btn-sm" data-research-action="approve-map">批准</button><button class="btn btn-secondary btn-sm" data-research-action="reject-map">驳回</button></div>' : ''}
    </article>`).join('') : '<div class="wb-empty">论证图会把研究问题、章节、论断与证据需求连接起来。</div>');

  const experimentFiles = researchFiles.filter(file => (file.metadata?.kind || 'literature') !== 'literature');
  document.getElementById('research-file-list').innerHTML = experimentFiles.length
    ? experimentFiles.map(file => `<div class="wb-card-meta">${escapeHtml2(file.file_name)} · ${escapeHtml2(file.metadata?.kind || 'other')} · ${formatCount(file.file_size)} bytes</div>`).join('')
    : '<div class="wb-empty">尚未上传实验材料、数据、代码或日志。</div>';

  runBox.innerHTML = `<div class="kb-section-title"><span>实验运行</span><span class="count">${researchRuns.length}</span></div>` +
    (researchRuns.length ? researchRuns.map(run => renderResearchRun(run)).join('') : '<div class="wb-empty">批准研究协议后创建实验运行。</div>');

  resultBox.innerHTML = `<div class="kb-section-title"><span>结果记录</span><span class="count">${researchResults.length}</span></div>` +
    (researchResults.length ? researchResults.map(result => `<article class="wb-card" data-result-id="${escapeHtml2(result.result_id)}">
      <div style="display:flex;justify-content:space-between;gap:8px"><div class="wb-card-title">${escapeHtml2(result.metric)} = ${escapeHtml2(result.value)} ${escapeHtml2(result.unit || '')}</div><span class="wb-status ${result.verified_by_user ? 'ok' : 'warn'}">${result.verified_by_user ? '已核验' : '待核验'}</span></div>
      <div class="wb-card-meta">来源：${escapeHtml2(researchFileLabel(result.source_file_id))} · ${escapeHtml2(result.computation)}</div>
      ${!result.verified_by_user ? '<div class="wb-card-actions"><button class="btn btn-primary btn-sm" data-research-action="verify-result">确认结果真实</button><button class="btn btn-secondary btn-sm" data-research-action="reject-result">撤销核验</button></div>' : ''}
    </article>`).join('') : '<div class="wb-empty">完成实验运行后登记可复算结果。</div>') +
    (activeLedger ? `<article class="wb-card" data-artifact-id="${escapeHtml2(activeLedger.artifact_id)}"><div class="wb-card-title">结果账本 v${activeLedger.version}</div><div class="wb-card-meta">已批准，可供环6分节写作引用。</div></article>` :
      artifacts.filter(item => item.kind === 'RESULT_LEDGER' && item.status === 'WAITING_APPROVAL').map(item => `<article class="wb-card" data-artifact-id="${escapeHtml2(item.artifact_id)}"><div class="wb-card-title">结果账本 v${item.version}</div><div class="wb-card-actions"><button class="btn btn-primary btn-sm" data-research-action="approve-ledger">批准结果账本</button><button class="btn btn-secondary btn-sm" data-research-action="reject-ledger">驳回</button></div></article>`).join(''));

  document.querySelectorAll('[data-research-action]').forEach(button => button.addEventListener('click', handleResearchAction));
  document.querySelectorAll('[data-result-form]').forEach(form => form.addEventListener('submit', submitResultForm));
  document.getElementById('research-live').textContent = `研究工作台已更新：${protocols.length} 个协议版本，${researchRuns.length} 次运行，${researchResults.length} 条结果`;
}

function renderResearchRun(run) {
  const statusOrder = ['PLANNED', 'MATERIALS_READY', 'RUNNING', 'COMPLETED'];
  const currentIndex = statusOrder.indexOf(run.status);
  const next = run.status === 'PLANNED' ? 'MATERIALS_READY' : run.status === 'MATERIALS_READY' ? 'RUNNING' : run.status === 'RUNNING' ? 'COMPLETED' : '';
  const kinds = run.status === 'PLANNED' ? ['material'] : run.status === 'MATERIALS_READY' ? ['code'] : run.status === 'RUNNING' ? ['raw_data', 'log'] : [];
  const registered = [...(run.raw_data_file_ids || []), ...(run.log_file_ids || []), ...(run.code_file_ids || []), ...(run.material_file_ids || [])];
  return `<article class="wb-card" data-run-id="${escapeHtml2(run.run_id)}">
    <div style="display:flex;justify-content:space-between;gap:8px"><div class="wb-card-title">${escapeHtml2(run.run_id)}</div><span class="wb-status ${wbStatusClass(run.status)}">${escapeHtml2(run.status)}</span></div>
    <div class="research-steps">${statusOrder.map((status, index) => `<span class="research-step ${index <= currentIndex ? 'current' : ''}">${index < currentIndex ? '✓ ' : ''}${status}</span>`).join('')}</div>
    <div class="wb-card-meta">已登记文件 ${registered.length} 个${run.user_attested ? ' · 用户已确认真实性' : ''}</div>
    ${next ? renderResearchFileChoices(run, kinds) : ''}
    ${run.status === 'RUNNING' ? '<label class="file-choice"><input type="checkbox" data-run-attested> 我确认本次实验材料与运行记录真实、未伪造</label>' : ''}
    <div class="wb-card-actions">
      ${next ? `<button class="btn btn-primary btn-sm" data-research-action="transition-run" data-next-status="${next}">${next === 'MATERIALS_READY' ? '确认材料就绪' : next === 'RUNNING' ? '开始运行' : '确认完成实验'}</button>` : ''}
      ${run.status === 'COMPLETED' ? '<button class="btn btn-secondary btn-sm" data-research-action="toggle-result-form">登记结果</button>' : ''}
    </div>
    ${run.status === 'COMPLETED' ? renderResultForm(run) : ''}
  </article>`;
}

function renderResultForm(run) {
  const fileIds = [...new Set([...(run.raw_data_file_ids || []), ...(run.log_file_ids || []), ...(run.code_file_ids || [])])];
  return `<form class="wb-form result-form" data-result-form hidden>
    <div class="wb-form-row"><div class="wb-field"><label>指标</label><input data-result="metric" aria-label="结果指标" required></div><div class="wb-field"><label>值</label><input data-result="value" aria-label="结果值" required></div></div>
    <div class="wb-form-row"><div class="wb-field"><label>单位</label><input data-result="unit" aria-label="结果单位"></div><div class="wb-field"><label>表/图编号</label><input data-result="target" aria-label="表或图编号" placeholder="TABLE-4-1"></div></div>
    <div class="wb-field"><label>来源文件</label><select data-result="source" aria-label="结果来源文件" required>${fileIds.map(fileId => `<option value="${escapeHtml2(fileId)}">${escapeHtml2(researchFileLabel(fileId))}</option>`).join('')}</select></div>
    <div class="wb-field"><label>复算方法/命令</label><textarea data-result="computation" aria-label="复算方法或命令" required></textarea></div>
    <div class="wb-card-meta" data-result-error style="color:var(--error)" role="alert"></div>
    <button class="btn btn-primary btn-sm" type="submit">保存结果记录</button>
  </form>`;
}

async function handleResearchAction(event) {
  const button = event.currentTarget;
  const action = button.dataset.researchAction;
  const artifactId = button.closest('[data-artifact-id]')?.dataset.artifactId;
  const runCard = button.closest('[data-run-id]');
  const runId = runCard?.dataset.runId;
  const resultId = button.closest('[data-result-id]')?.dataset.resultId;
  if (!currentSession) return;
  if (action === 'toggle-result-form') {
    const form = runCard.querySelector('[data-result-form]');
    form.hidden = !form.hidden;
    if (!form.hidden) form.querySelector('input')?.focus();
    return;
  }
  button.disabled = true;
  let response;
  if (action === 'approve-protocol' || action === 'reject-protocol') {
    response = await apiReviewProtocol(currentSession, artifactId, action === 'approve-protocol', action === 'reject-protocol' ? '作者驳回' : '');
  } else if (action === 'approve-map' || action === 'reject-map') {
    response = await apiReviewArgumentMap(currentSession, artifactId, action === 'approve-map', action === 'reject-map' ? '作者驳回' : '');
  } else if (action === 'create-run') {
    response = await apiCreateResearchRun(currentSession, '由作者工作台创建');
  } else if (action === 'transition-run') {
    const next = button.dataset.nextStatus;
    const selected = [...runCard.querySelectorAll('[data-run-file]:checked')];
    const payload = { status: next };
    if (next === 'MATERIALS_READY') payload.material_file_ids = selected.map(input => input.value);
    if (next === 'RUNNING') payload.code_file_ids = selected.map(input => input.value);
    if (next === 'COMPLETED') {
      payload.raw_data_file_ids = selected.filter(input => input.dataset.kind === 'raw_data').map(input => input.value);
      payload.log_file_ids = selected.filter(input => input.dataset.kind === 'log').map(input => input.value);
      payload.user_attested = !!runCard.querySelector('[data-run-attested]')?.checked;
    }
    response = await apiTransitionResearchRun(currentSession, runId, payload);
  } else if (action === 'verify-result' || action === 'reject-result') {
    response = await apiReviewResearchResult(currentSession, resultId, action === 'verify-result');
  } else if (action === 'create-ledger') {
    response = await apiCreateResultLedger(currentSession);
  } else if (action === 'approve-ledger' || action === 'reject-ledger') {
    response = await apiReviewResultLedger(currentSession, artifactId, action === 'approve-ledger', action === 'reject-ledger' ? '作者驳回' : '');
  }
  toast(response?.code === 0 ? response.msg : `研究操作失败：${response?.msg || '未知错误'}`);
  await loadResearchPanel();
  // 协议 / 论证图 / 结果账本审批会改变待审批集合；只有成功才刷新摘要。
  if (response?.code === 0) await refreshVisibleResumeSummary();
}

async function submitProtocolForm(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const error = document.getElementById('protocol-error');
  const payload = buildProtocolPayload();
  const missing = !payload.title || !payload.research_questions.length || !payload.procedure_steps.length || !payload.analysis_plan.length || !payload.required_outputs.length;
  if (missing) { error.textContent = '请填写协议名称、研究问题、实施步骤、分析计划和必须产物。'; return; }
  error.textContent = '';
  submit.disabled = true;
  const surface = window.ThesisAutosave?.surfaces?.get(PROTOCOL_DRAFT_KEY);
  if (surface) {
    await window.ThesisAutosave.flushDraft(PROTOCOL_DRAFT_KEY);
    if (['conflict', 'stale', 'failed', 'saving', 'dirty'].includes(surface.status)) {
      error.textContent = '自动草稿尚未安全保存或需要处理冲突。';
      submit.disabled = false;
      return;
    }
    if (surface.revision > 0) {
      payload.autosave_draft_key = PROTOCOL_DRAFT_KEY;
      payload.autosave_revision = surface.revision;
    }
  }
  const response = await apiCreateProtocol(currentSession, payload);
  if (response?.data?.conflict && surface) {
    window.ThesisAutosave.reportDraftConflict(PROTOCOL_DRAFT_KEY, response);
    error.textContent = '正式提交基于旧草稿，请先处理冲突。';
    submit.disabled = false;
    return;
  }
  if (response.code !== 0) {
    error.textContent = response.msg;
    submit.disabled = false;
  } else {
    toast(response.msg);
    if (response.data?.autosave_draft) {
      window.ThesisAutosave.markDraftSubmitted(
        PROTOCOL_DRAFT_KEY, response.data.autosave_draft,
      );
    }
    form.reset();
    document.getElementById('protocol-builder').open = false;
    await loadResearchPanel();
    await refreshVisibleResumeSummary();
  }
}

async function submitArgumentForm(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const error = document.getElementById('argument-error');
  const payload = buildArgumentPayload();
  const claims = payload.claims;
  if (!payload.title || !payload.research_questions.length || claims.some(claim => !claim.claim_key || !claim.section_id || !claim.text) || !claims.some(claim => claim.role === 'THESIS')) {
    error.textContent = '请填写名称、研究问题和全部论断字段，并至少保留一个核心论断。';
    return;
  }
  error.textContent = '';
  submit.disabled = true;
  const surface = window.ThesisAutosave?.surfaces?.get(ARGUMENT_DRAFT_KEY);
  if (surface) {
    await window.ThesisAutosave.flushDraft(ARGUMENT_DRAFT_KEY);
    if (['conflict', 'stale', 'failed', 'saving', 'dirty'].includes(surface.status)) {
      error.textContent = '自动草稿尚未安全保存或需要处理冲突。';
      submit.disabled = false;
      return;
    }
    if (surface.revision > 0) {
      payload.autosave_draft_key = ARGUMENT_DRAFT_KEY;
      payload.autosave_revision = surface.revision;
    }
  }
  const response = await apiCreateArgumentMap(currentSession, payload);
  submit.disabled = false;
  if (response?.data?.conflict && surface) {
    window.ThesisAutosave.reportDraftConflict(ARGUMENT_DRAFT_KEY, response);
    error.textContent = '正式提交基于旧草稿，请先处理冲突。';
    return;
  }
  if (response.code !== 0) error.textContent = response.msg;
  else {
    toast(response.msg);
    if (response.data?.autosave_draft) {
      window.ThesisAutosave.markDraftSubmitted(
        ARGUMENT_DRAFT_KEY, response.data.autosave_draft,
      );
      surface.reset?.();
    }
    document.getElementById('argument-builder').open = false;
    await loadResearchPanel();
    await refreshVisibleResumeSummary();
  }
}

async function uploadResearchFiles(files) {
  if (!currentSession || !files?.length) return;
  const kind = document.getElementById('research-file-kind').value;
  const live = document.getElementById('research-live');
  let succeeded = 0;
  for (const file of files) {
    live.textContent = `上传 ${file.name}…`;
    const response = await apiUploadResearchFile(currentKnowledgeSession || currentSession, file, kind);
    if (response.code === 0) succeeded += 1;
    else toast(`上传 ${file.name} 失败：${response.msg}`);
  }
  live.textContent = `已上传 ${succeeded}/${files.length} 个实验文件`;
  await loadResearchPanel();
}

async function submitResultForm(event) {
  const form = event.target.closest('[data-result-form]');
  if (!form) return;
  event.preventDefault();
  const runId = form.closest('[data-run-id]').dataset.runId;
  const payload = {
    metric: form.querySelector('[data-result="metric"]').value.trim(),
    value: form.querySelector('[data-result="value"]').value.trim(),
    unit: form.querySelector('[data-result="unit"]').value.trim(),
    table_or_figure_id: form.querySelector('[data-result="target"]').value.trim(),
    source_file_id: form.querySelector('[data-result="source"]').value,
    computation: form.querySelector('[data-result="computation"]').value.trim(),
  };
  const error = form.querySelector('[data-result-error]');
  if (!payload.metric || !payload.value || !payload.source_file_id || !payload.computation) { error.textContent = '请填写指标、值、来源文件和复算方法。'; return; }
  const response = await apiAddResearchResult(currentSession, runId, payload);
  if (response.code !== 0) error.textContent = response.msg;
  else {
    toast(response.msg);
    await loadResearchPanel();
    await refreshVisibleResumeSummary();
  }
}

let sectionDraftCache = new Map();

async function teardownSectionDraftSurfaces({ flush = true } = {}) {
  if (!window.ThesisAutosave?.surfaces) return;
  const keys = [...window.ThesisAutosave.surfaces.keys()]
    .filter(key => key.startsWith('section-revision:'));
  for (const key of keys) {
    if (flush) await window.ThesisAutosave.flushDraft(key);
    window.ThesisAutosave.unregisterDraftSurface(key);
  }
  activeSectionDraftKey = '';
}

async function loadSectionsPanel() {
  const listBox = document.getElementById('section-list');
  const auditBox = document.getElementById('section-audit');
  if (!listBox || !auditBox) return;
  await teardownSectionDraftSurfaces();
  if (!currentSession) {
    auditBox.className = 'wb-empty';
    auditBox.textContent = '选择论文任务后查看分节。';
    listBox.innerHTML = '';
    return;
  }
  const taskId = currentSession;
  listBox.setAttribute('aria-busy', 'true');
  const [auditResponse, draftResponse, templateResponse] = await Promise.all([
    apiSectionAudit(taskId), apiSectionDrafts(taskId), apiTemplateConfig(taskId),
  ]);
  if (taskId !== currentSession) return;
  listBox.removeAttribute('aria-busy');
  if (auditResponse.code !== 0 || draftResponse.code !== 0) {
    const message = auditResponse.code !== 0 ? auditResponse.msg : draftResponse.msg;
    auditBox.className = 'wb-error';
    auditBox.innerHTML = `${escapeHtml2(message)}<div class="wb-card-actions"><button class="btn btn-secondary btn-sm" onclick="loadSectionsPanel()">重试</button></div>`;
    listBox.innerHTML = '';
    return;
  }
  const audit = auditResponse.data || {};
  const drafts = draftResponse.data || [];
  const waitingDraftCount = drafts.filter(draft => draft.status === 'WAITING_APPROVAL').length;
  renderTemplateConfig(templateResponse);
  sectionDraftCache = new Map(drafts.map(draft => [draft.section_draft_id, draft]));
  auditBox.className = 'wb-card';
  auditBox.innerHTML = `<div class="wb-card-title">已批准 ${(audit.approved_section_ids || []).length}/${(audit.expected_section_ids || []).length} 节</div>
    <div class="wb-card-meta">${audit.can_assemble ? '全部分节已就绪，可以汇编环6初稿。' : `待完成：${escapeHtml2((audit.missing_section_ids || []).join('、') || '等待大纲')}`}</div>
    <div class="wb-card-actions">
      ${(audit.missing_section_ids || []).length ? '<button class="btn btn-primary btn-sm" data-action="generate-all-sections">批量生成全部缺失分节</button>' : ''}
      ${waitingDraftCount ? `<button class="btn btn-secondary btn-sm" data-action="approve-all-sections">批量批准 ${waitingDraftCount} 个待审分节</button>` : ''}
      ${audit.can_assemble ? '<button class="btn btn-primary btn-sm" id="assemble-sections">汇编环6初稿</button>' : ''}
    </div>`;
  auditBox.querySelector('[data-action="generate-all-sections"]')?.addEventListener('click', generateAllSectionsFromPanel);
  auditBox.querySelector('[data-action="approve-all-sections"]')?.addEventListener('click', approveAllSectionsFromPanel);
  document.getElementById('assemble-sections')?.addEventListener('click', assembleSectionsFromPanel);
  const latestBySection = new Map();
  const versionsBySection = new Map();
  drafts.forEach(draft => {
    if (!versionsBySection.has(draft.section_id)) versionsBySection.set(draft.section_id, []);
    versionsBySection.get(draft.section_id).push(draft);
    const current = latestBySection.get(draft.section_id);
    if (!current || draft.version > current.version) latestBySection.set(draft.section_id, draft);
  });
  const missingCards = (audit.missing_section_ids || []).filter(id => !latestBySection.has(id)).map(sectionId => `<article class="wb-card" data-section-id="${escapeHtml2(sectionId)}">
    <div class="wb-card-title">${escapeHtml2(sectionId)}</div><div class="wb-card-meta">尚未生成草稿</div>
    <div class="wb-card-actions"><button class="btn btn-primary btn-sm" data-section-action="generate">生成本节</button></div>
  </article>`);
  const draftCards = [...latestBySection.values()].sort((a, b) => a.section_id.localeCompare(b.section_id, undefined, { numeric: true })).map(draft => {
    const versions = (versionsBySection.get(draft.section_id) || []).sort((a, b) => b.version - a.version);
    const versionOptions = versions.map(version => `<option value="${escapeHtml2(version.section_draft_id)}">v${version.version} ${escapeHtml2(version.status)}</option>`).join('');
    return `<article class="wb-card" data-draft-id="${escapeHtml2(draft.section_draft_id)}" data-section-id="${escapeHtml2(draft.section_id)}">
    <div style="display:flex;justify-content:space-between;gap:8px;align-items:start;"><div class="wb-card-title">${escapeHtml2(draft.section_id)} ${escapeHtml2(draft.title)}</div><span class="wb-status ${wbStatusClass(draft.status)}">v${draft.version} ${escapeHtml2(draft.status)}</span></div>
    <div class="wb-card-meta">${versions.length} 个版本 · 证据 ${(draft.evidence_ids || []).length} · 结果 ${(draft.result_ids || []).length} · 审批 ${(draft.approvals || []).length}</div>
    <details><summary class="wb-card-meta">查看正文</summary><pre class="section-preview">${escapeHtml2(draft.content)}</pre></details>
    ${versions.length > 1 ? `<div class="section-diff-controls"><select data-diff-left aria-label="较早版本">${versionOptions}</select><select data-diff-right aria-label="较新版本">${versionOptions}</select><button class="btn btn-secondary btn-sm" data-section-action="compare">比较</button></div><div class="section-diff-host" hidden></div>` : ''}
    <div class="wb-card-actions">
      ${draft.status === 'WAITING_APPROVAL' ? '<button class="btn btn-primary btn-sm" data-section-action="approve">批准</button><button class="btn btn-secondary btn-sm" data-section-action="reject">驳回</button>' : ''}
      ${draft.status !== 'STALE' ? '<button class="btn btn-secondary btn-sm" data-section-action="edit">修订为新版本</button>' : ''}
      ${['REJECTED','AUTO_REJECTED','STALE'].includes(draft.status) ? '<button class="btn btn-secondary btn-sm" data-section-action="generate">重新生成</button>' : ''}
    </div>
    <div class="section-edit-area" hidden>
      <label class="sr-only" for="editor-${escapeHtml2(draft.section_draft_id)}">编辑 ${escapeHtml2(draft.section_id)} 正文</label>
      <textarea class="section-editor" id="editor-${escapeHtml2(draft.section_draft_id)}">${escapeHtml2(draft.content)}</textarea>
      <div class="autosave-status" data-autosave-status role="status" aria-live="polite"></div>
      <div class="autosave-conflict" data-autosave-conflict hidden></div>
      <div class="wb-card-actions"><button class="btn btn-primary btn-sm" data-section-action="save">保存新版本</button><button class="btn btn-secondary btn-sm" data-section-action="cancel-edit">取消</button></div>
    </div>
  </article>`;
  });
  listBox.innerHTML = [...missingCards, ...draftCards].join('') || '<div class="wb-empty">进入环6并批准大纲后，这里会显示可写分节。</div>';
  listBox.querySelectorAll('[data-diff-left]').forEach(select => {
    if (select.options.length > 1) select.selectedIndex = 1;
  });
  listBox.querySelectorAll('[data-section-action]').forEach(button => button.addEventListener('click', handleSectionAction));
  await bindSectionDraftSurfaces(listBox, [...latestBySection.values()]);
  document.getElementById('sections-live').textContent = `已加载 ${drafts.length} 个分节版本`;
}

/* —— 分节修订自动草稿：一个分节一个 draft_key，切换前 flush —— */
let activeSectionDraftKey = '';

function sectionDraftKey(sectionId) {
  return `section-revision:${sectionId}`;
}

async function bindSectionDraftSurfaces(listBox, drafts) {
  if (typeof window.ThesisAutosave?.registerDraftSurface !== 'function') return;
  const taskId = currentSession;
  const listed = await apiListAutosaveDrafts(taskId);
  if (taskId !== currentSession) return;
  const activeKeys = new Set(
    listed?.code === 0
      ? (listed.data?.items || []).map(item => item.draft_key)
      : [],
  );
  for (const draft of drafts) {
    const card = listBox.querySelector(
      `[data-section-id="${CSS.escape(draft.section_id)}"][data-draft-id="${CSS.escape(draft.section_draft_id)}"]`,
    );
    if (!card) continue;
    const editor = card.querySelector('.section-editor');
    if (!editor) continue;
    const draftKey = sectionDraftKey(draft.section_id);
    const surface = window.ThesisAutosave.registerDraftSurface({
      draftKey,
      taskId,
      objectType: 'SECTION_REVISION',
      objectId: draft.section_id,
      stageNo: 6,
      label: `${draft.section_id} ${draft.title}`.trim(),
      statusEl: card.querySelector('[data-autosave-status]'),
      conflictHost: card.querySelector('[data-autosave-conflict]'),
      baseArtifactId: draft.section_draft_id,
      baseVersion: draft.version || 0,
      serialize: () => ({
        content: editor.value,
        title: draft.title || '',
        section_id: draft.section_id,
        base_section_draft_id: draft.section_draft_id,
      }),
      hydrate: content => {
        // 只写 value，不使用 innerHTML 恢复用户输入。
        if (typeof content?.content === 'string') editor.value = content.content;
      },
      reset: () => { editor.value = draft.content || ''; },
    });
    surface.editor = editor;
    editor.addEventListener('input', () => {
      window.ThesisAutosave.scheduleDraftSave(draftKey);
    });
    editor.addEventListener('blur', () => {
      window.ThesisAutosave.flushDraft(draftKey);
      updateEditorAnchor(draftKey, editor);
    });
    editor.addEventListener('select', () => updateEditorAnchor(draftKey, editor));
    if (activeKeys.has(draftKey)) {
      await window.ThesisAutosave.loadDraft(draftKey);
    }
  }
}

async function switchActiveSectionDraft(draftKey) {
  if (typeof window.ThesisAutosave?.flushDraft !== 'function') return;
  if (activeSectionDraftKey && activeSectionDraftKey !== draftKey) {
    await window.ThesisAutosave.flushDraft(activeSectionDraftKey);
  }
  activeSectionDraftKey = draftKey || '';
}

function updateEditorAnchor(draftKey, editor) {
  // 编辑锚点是 UI 位置：低频更新，不参与正式版本或 FSM。
  if (!draftKey) return;
  const start = Number(editor?.selectionStart || 0);
  const end = Number(editor?.selectionEnd || 0);
  scheduleWorkspaceSave({ editor_anchor: `${draftKey}#${start}:${end}` });
}

function restoreEditorAnchor(draftKey, editor) {
  if (!draftKey || !editor) return;
  const raw = String(workspaceState.editor_anchor || '');
  const prefix = draftKey + '#';
  if (!raw.startsWith(prefix)) return;
  const match = raw.slice(prefix.length).match(/^(\d+):(\d+)$/);
  if (!match) return;
  const length = editor.value.length;
  const start = Math.min(length, Math.max(0, Number(match[1]) || 0));
  const end = Math.min(length, Math.max(start, Number(match[2]) || start));
  editor.setSelectionRange(start, end);
  editor.scrollIntoView({ block: 'nearest' });
}

async function generateAllSectionsFromPanel(event) {
  event.currentTarget.disabled = true;
  const response = await enqueueJobAndWait(
    'sections.generate_all',
    {},
    '批量生成全部分节',
  );
  toast(response.code === 0 ? response.msg : `批量生成失败：${response.msg}`);
  await loadSectionsPanel();
  if (response.code === 0) await refreshVisibleResumeSummary();
}

async function approveAllSectionsFromPanel(event) {
  event.currentTarget.disabled = true;
  const response = await apiReviewAllSections(currentSession, true);
  toast(response.code === 0 ? response.msg : `批量批准失败：${response.msg}`);
  await loadSectionsPanel();
  if (response.code === 0) await refreshVisibleResumeSummary();
}

function renderTemplateConfig(response) {
  const box = document.getElementById('template-config');
  if (!box) return;
  if (!response || response.code !== 0) {
    box.innerHTML = `<div class="wb-error">${escapeHtml2(response?.msg || '模板配置读取失败')}</div>`;
    return;
  }
  const config = response.data || {};
  const placeholders = config.placeholders || [];
  if (!config.is_custom) {
    box.innerHTML = '<div class="wb-card-meta">当前使用内置论文模板。上传学校 DOCX 后可映射占位符。</div>';
    return;
  }
  const sourceOptions = [
    ['','请选择内容源'], ['title','论文题目'], ['abstract','摘要'], ['content','完整正文'], ['outline','论文大纲'],
    ['chapter','章节正文'], ['references','参考文献'], ['degree','学位层次'], ['subject_field','学科方向'],
  ];
  box.innerHTML = `<div class="wb-card-meta">模板：${escapeHtml2(config.template_name || config.template_id)} · ${placeholders.length} 个占位符</div>
    <div class="wb-form" id="template-mapping-fields">${placeholders.map((placeholder, index) => `<div class="wb-field"><label for="template-map-${index}">{{ ${escapeHtml2(placeholder)} }}</label><select id="template-map-${index}" data-template-placeholder="${escapeHtml2(placeholder)}">${sourceOptions.map(([value,label]) => `<option value="${value}" ${config.mapping?.[placeholder] === value ? 'selected' : ''}>${label}</option>`).join('')}</select></div>`).join('')}</div>
    <div id="template-mapping-error" class="wb-card-meta" style="color:var(--error)" role="alert"></div>
    <div class="wb-card-actions"><button class="btn btn-primary btn-sm" id="save-template-mapping">保存映射</button></div>`;
  document.getElementById('save-template-mapping')?.addEventListener('click', saveTemplateMappingFromPanel);
}

async function saveTemplateMappingFromPanel(event) {
  event.currentTarget.disabled = true;
  const mapping = {};
  document.querySelectorAll('[data-template-placeholder]').forEach(select => {
    if (select.value) mapping[select.dataset.templatePlaceholder] = select.value;
  });
  const response = await apiSaveTemplateMapping(currentSession, mapping);
  const error = document.getElementById('template-mapping-error');
  if (response.code !== 0) {
    error.textContent = response.msg;
    event.currentTarget.disabled = false;
  } else {
    toast(response.msg);
    await loadSectionsPanel();
  }
}

async function uploadTaskTemplate(file) {
  if (!currentSession || !file) return;
  const live = document.getElementById('sections-live');
  live.textContent = `正在解析学校模板 ${file.name}…`;
  const response = await apiUploadTaskTemplate(currentSession, file);
  if (response.code !== 0) toast(`模板上传失败：${response.msg}`);
  else toast(`模板已解析：${(response.data?.placeholders || []).length} 个占位符`);
  await loadSectionsPanel();
}

async function handleSectionAction(event) {
  const button = event.currentTarget;
  const card = button.closest('[data-section-id]');
  const sectionId = card?.dataset.sectionId;
  const draftId = card?.dataset.draftId;
  const action = button.dataset.sectionAction;
  if (!currentSession || !sectionId) return;
  const autosaveKey = sectionDraftKey(sectionId);
  if (action === 'compare') {
    renderSectionDiff(card);
    return;
  }
  if (action === 'edit' || action === 'cancel-edit') {
    const area = card.querySelector('.section-edit-area');
    if (action === 'edit') {
      await switchActiveSectionDraft(autosaveKey);
      area.hidden = false;
      const editor = area.querySelector('textarea');
      restoreEditorAnchor(autosaveKey, editor);
      editor?.focus();
    } else {
      await window.ThesisAutosave?.flushDraft?.(autosaveKey);
      area.hidden = true;
      if (activeSectionDraftKey === autosaveKey) activeSectionDraftKey = '';
      button.closest('.wb-card')?.querySelector('[data-section-action="edit"]')?.focus();
    }
    return;
  }
  button.disabled = true;
  let response;
  if (action === 'generate') {
    response = await enqueueJobAndWait('section.generate', { section_id: sectionId }, `生成分节 ${sectionId}`);
  } else if (action === 'approve') {
    response = await apiReviewSection(currentSession, draftId, true);
  } else if (action === 'reject') {
    const reason = window.prompt('请输入驳回原因：', '需要补充证据或修改表述');
    if (reason === null) { button.disabled = false; return; }
    response = await apiReviewSection(currentSession, draftId, false, reason);
  } else if (action === 'save') {
    const surface = window.ThesisAutosave?.surfaces?.get(autosaveKey);
    if (surface) {
      await window.ThesisAutosave.flushDraft(autosaveKey);
      if (['conflict', 'stale', 'failed', 'saving', 'dirty'].includes(surface.status)) {
        toast('自动草稿尚未安全保存或需要处理冲突，暂不能创建正式版本');
        button.disabled = false;
        return;
      }
    }
    const content = card.querySelector('.section-editor')?.value || '';
    const autosave = surface && surface.revision > 0 ? {
      draftKey: autosaveKey,
      revision: surface.revision,
    } : null;
    response = await apiReviseSection(
      currentSession, draftId, content, '', autosave,
    );
    if (response?.data?.conflict && surface) {
      window.ThesisAutosave.reportDraftConflict(
        autosaveKey, response,
      );
      toast('正式提交基于旧草稿，已停止并显示冲突');
      button.disabled = false;
      return;
    }
    if (response?.code === 0 && response.data?.autosave_draft) {
      window.ThesisAutosave.markDraftSubmitted(
        autosaveKey, response.data.autosave_draft,
      );
    }
  }
  toast(response?.code === 0 ? response.msg : `操作失败：${response?.msg || '未知错误'}`);
  await loadSectionsPanel();
  // 分节生成 / 修订 / 审批会改变待审批集合；只有成功才刷新摘要。
  if (response?.code === 0) await refreshVisibleResumeSummary();
}

function renderSectionDiff(card) {
  const left = sectionDraftCache.get(card.querySelector('[data-diff-left]')?.value);
  const right = sectionDraftCache.get(card.querySelector('[data-diff-right]')?.value);
  const host = card.querySelector('.section-diff-host');
  if (!left || !right || !host) return;
  const diff = computeLineDiff(left.content, right.content);
  host.hidden = false;
  host.innerHTML = `<div class="section-diff-grid">
    <section class="diff-column" tabindex="0" aria-label="v${left.version} 内容"><h4>v${left.version} · ${escapeHtml2(left.status)}</h4>${diff.left.map(line => `<div class="diff-line ${line.changed ? 'removed' : ''}">${escapeHtml2(line.text || ' ')}</div>`).join('')}</section>
    <section class="diff-column" tabindex="0" aria-label="v${right.version} 内容"><h4>v${right.version} · ${escapeHtml2(right.status)}</h4>${diff.right.map(line => `<div class="diff-line ${line.changed ? 'added' : ''}">${escapeHtml2(line.text || ' ')}</div>`).join('')}</section>
  </div>`;
  host.querySelector('.diff-column')?.focus?.();
}

function computeLineDiff(leftText, rightText) {
  const leftLines = String(leftText || '').split(/\r?\n/).slice(0, 250);
  const rightLines = String(rightText || '').split(/\r?\n/).slice(0, 250);
  const rows = leftLines.length + 1, cols = rightLines.length + 1;
  const matrix = Array.from({ length: rows }, () => new Uint16Array(cols));
  for (let i = leftLines.length - 1; i >= 0; i--) {
    for (let j = rightLines.length - 1; j >= 0; j--) {
      matrix[i][j] = leftLines[i] === rightLines[j]
        ? matrix[i + 1][j + 1] + 1
        : Math.max(matrix[i + 1][j], matrix[i][j + 1]);
    }
  }
  const left = [], right = [];
  let i = 0, j = 0;
  while (i < leftLines.length || j < rightLines.length) {
    if (i < leftLines.length && j < rightLines.length && leftLines[i] === rightLines[j]) {
      left.push({ text: leftLines[i], changed: false });
      right.push({ text: rightLines[j], changed: false });
      i++; j++;
    } else if (j < rightLines.length && (i >= leftLines.length || matrix[i][j + 1] >= matrix[i + 1][j])) {
      right.push({ text: rightLines[j], changed: true });
      left.push({ text: '', changed: true });
      j++;
    } else {
      left.push({ text: leftLines[i], changed: true });
      right.push({ text: '', changed: true });
      i++;
    }
  }
  if (String(leftText || '').split(/\r?\n/).length > 250 || String(rightText || '').split(/\r?\n/).length > 250) {
    left.push({ text: '仅比较前 250 行', changed: true });
    right.push({ text: '仅比较前 250 行', changed: true });
  }
  return { left, right };
}

async function assembleSectionsFromPanel(event) {
  event.currentTarget.disabled = true;
  const response = await apiPost(`/api/v1/console/tasks/${currentSession}/rings/6/assemble`);
  if (response.code === 0) {
    renderRingResult(6, response.data);
    appendGateBlock(6);
    await loadSessionDetail(currentSession);
  } else toast(`汇编失败：${response.msg}`);
}

async function loadActiveWorkbenchPane() {
  const target = document.querySelector('.kb-tab.active')?.dataset.tab || 'refs';
  if (target === 'memory') await window.ThesisProjectMemory.loadPanel();
  else if (target === 'evidence') await window.ThesisEvidence.loadPanel();
  else if (target === 'writing') await loadSectionsPanel();
  else if (target === 'research') await loadResearchPanel();
  else if (target === 'jobs') await loadJobsPanel(false);
}

// —— 启动初始化：加载会话列表 + 绑定新建按钮 ——


/* ============================================================
   知识图谱（Cytoscape.js，Obsidian Graph View 风格配方）
   ============================================================ */
let cyGraph = null;
let graphFocus = null;      // depth 局部视图中心节点
const GRAPH_TYPE_NAME = { note: '笔记', concept: '概念', paper: '文献' };

async function renderGraph(sessionId) {
  const apiGraph = await apiGet(`/api/v1/kb/${encodeURIComponent(sessionId || 'default')}/graph`);
  const data = apiGraph.code === 0 ? (apiGraph.data || { nodes: [], links: [] }) : { nodes: [], links: [] };
  const count = document.getElementById('graph-count');
  if (count) count.textContent = (data.stats?.node_count || data.nodes?.length || 0) + ' 节点';
  const el = document.getElementById('kb-graph');
  if (!el || typeof cytoscape === 'undefined') return;
  if (cyGraph) { cyGraph.destroy(); cyGraph = null; }
  graphFocus = null;
  const elements = [
    ...(data.nodes || []).map(n => ({ data: { id: n.id, label: n.label, type: n.type }, classes: n.type })),
    ...(data.links || []).map(l => ({ data: { source: l.source, target: l.target } })),
  ];
  if (!elements.length) {
    el.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#888;font-size:12px;">暂无图谱数据（在笔记中用 [[双链]] 关联）</div>';
    return;
  }
  cyGraph = cytoscape({
    container: el,
    elements,
    style: [
      { selector: 'node', style: {
          'background-color': '#A8A8A8',
          'label': 'data(label)', 'color': '#D4D4D4',
          'font-size': '10px', 'text-valign': 'bottom', 'text-wrap': 'wrap',
          'text-max-width': '60px', 'text-opacity': 0,
          'width': 'mapData(degree, 0, 10, 18, 40)', 'height': 'mapData(degree, 0, 10, 18, 40)',
      }},
      { selector: 'node.note', style: { 'background-color': '#22c55e' } },
      { selector: 'node.concept', style: { 'background-color': '#E9973F' } },
      { selector: 'node.paper', style: { 'background-color': '#6FB7FF' } },
      { selector: 'node.focus', style: { 'border-width': 2, 'border-color': '#FFF', 'overlay-color': '#FFF', 'overlay-padding': 8, 'overlay-opacity': 0.12 } },
      { selector: 'node.neighbor', style: { 'border-width': 2, 'border-color': '#8ab4f8' } },
      { selector: 'node.dimmed', style: { 'opacity': 0.12 } },
      { selector: 'node.hover-label', style: { 'text-opacity': 1, 'font-size': '11px', 'text-background-color': '#222', 'text-background-opacity': 0.8, 'text-background-padding': 3, 'text-border-radius': 4 } },
      { selector: 'edge', style: { 'width': 1, 'line-color': 'rgba(255,255,255,0.15)', 'curve-style': 'bezier', 'target-arrow-shape': 'none' } },
      { selector: 'edge.neighbor', style: { 'line-color': '#8ab4f8', 'width': 2.5 } },
      { selector: 'edge.dimmed', style: { 'opacity': 0.05 } },
      { selector: '.depth-out', style: { 'display': 'none' } },
    ],
    layout: { name: 'cose', animate: true, padding: 20, nodeRepulsion: () => 5000, idealEdgeLength: () => 60 },
    wheelSensitivity: 0.2,
    minZoom: 0.25, maxZoom: 4,
  });

  // hover 邻接高亮 + 其余淡化（Obsidian 默认）
  cyGraph.on('mouseover', 'node', evt => {
    const n = evt.target;
    const nb = n.neighborhood();
    cyGraph.batch(() => {
      cyGraph.elements().addClass('dimmed');
      nb.removeClass('dimmed');
      n.addClass('neighbor'); n.addClass('hover-label');
      nb.edges().addClass('neighbor'); nb.nodes().addClass('neighbor');
    });
  });
  cyGraph.on('mouseout', 'node', evt => {
    cyGraph.batch(() => { cyGraph.elements().removeClass('dimmed neighbor hover-label'); });
  });

  // 缩放渐显标签（Obsidian：(zoom-1)/3.75）
  const labelOpacity = () => {
    const z = cyGraph.zoom();
    const o = Math.max(0, Math.min(1, (z - 1) / 3.75));
    cyGraph.nodes().not('.hover-label').style('text-opacity', o);
  };
  cyGraph.on('zoom', labelOpacity);
  labelOpacity();

  // 点击节点 → 详情抽屉（且设为中心 focus）
  cyGraph.on('tap', 'node', evt => {
    graphFocus = evt.target.id();
    cyGraph.elements().removeClass('focus');
    evt.target.addClass('focus');
    openNodeDrawer(evt.target);
  });

  applyDepth(0);
}

// depth 滤镜（0=全部, 1-3=N跳内；BFS 子图，Obsidian local graph 同款）
function applyDepth(depth) {
  if (!cyGraph) return;
  if (depth <= 0 || !graphFocus) {
    cyGraph.elements().removeClass('depth-out');
    document.querySelectorAll('#graph-depth .dg-btn').forEach(b => b.classList.toggle('active', b.dataset.depth === '0'));
    return;
  }
  const center = cyGraph.$('#' + CSS.escape(graphFocus));
  if (!center.length) return;
  const dist = new Map();
  cyGraph.elements().bfs({ roots: center, directed: false, visit: (v, e, u, i, d) => { dist.set(v.id(), d); } });
  cyGraph.batch(() => {
    cyGraph.elements().removeClass('depth-out');
    const keep = cyGraph.elements().filter(ele => {
      if (ele.isNode()) return (dist.get(ele.id()) ?? 1e9) <= depth;
      const s = dist.get(ele.source().id()) ?? 1e9, t = dist.get(ele.target().id()) ?? 1e9;
      return s <= depth && t <= depth;
    });
    cyGraph.elements().difference(keep).addClass('depth-out');
  });
  document.querySelectorAll('#graph-depth .dg-btn').forEach(b => b.classList.toggle('active', b.dataset.depth === String(depth)));
}

// 节点详情抽屉
function openNodeDrawer(node) {
  const id = node.id(), type = node.data('type'), label = node.data('label');
  const neighbors = node.connectedEdges().connectedNodes().map(x => ({ id: x.id(), label: x.data('label'), type: x.data('type') })).filter(x => x.id !== id);
  const div = document.getElementById('node-drawer');
  if (!div) return;
  document.getElementById('nd-title').textContent = label;
  document.getElementById('nd-type').textContent = GRAPH_TYPE_NAME[type] || type;
  document.getElementById('nd-summary').textContent = type === 'concept' ? '待创建笔记的概念节点（在笔记中用 [[链接]] 关联）' : '';
  document.getElementById('nd-neighbors').innerHTML = neighbors.length
    ? neighbors.map(nb => `<button class="nd-link" data-target-id="${nb.id}">${nb.label}</button>`).join('')
    : '暂无关联节点';
  showAccessibleDialog(div, document.getElementById('nd-close'));
  div.dataset.nodeId = id;
  div.dataset.nodeType = type;
  const openBtn = document.getElementById('nd-open');
  openBtn.textContent = type === 'paper' ? '在文献池查看' : (type === 'note' ? '打开笔记' : '创建笔记');
  openBtn.style.display = 'inline-flex';
  div.querySelectorAll('.nd-link').forEach(b => {
    b.onclick = (e) => {
      e.stopPropagation();
      const target = cyGraph.$('#' + CSS.escape(b.dataset.targetId));
      if (target.length) { target.select(); cyGraph.animate({ center: { eles: target }, zoom: 1.1 }, { duration: 300 }); }
    };
  });
}

/* ============================================================
   笔记模块（接 /api/v1/kb/{sid}/notes）
   ============================================================ */
let currentNoteId = null;

async function loadNotes(sessionId) {
  const r = await apiGet(`/api/v1/kb/${encodeURIComponent(sessionId || 'default')}/notes`);
  const items = r.code === 0 ? (r.data?.items || []) : [];
  const box = document.getElementById('notes-list');
  if (!box) return;
  window.notesCache = items;
  if (!items.length) {
    box.innerHTML = '<div style="padding:8px;font-size:12px;color:var(--text-subtle);">暂无笔记，点击「新建笔记」开始</div>';
    return;
  }
  box.innerHTML = items.map(n => `
    <div class="note-item" data-note-id="${n.note_id}" onclick="openNote('${n.note_id.replace(/'/g, "\\'")}')"
         style="padding:6px 8px;font-size:12px;cursor:pointer;border-radius:6px;border-bottom:1px solid var(--border-divider);">
      ${escapeHtml(n.title)}
    </div>`).join('');
}

function openNote(noteId) {
  const editor = document.getElementById('note-editor');
  if (!editor) return;
  const items = window.notesCache || [];
  const n = items.find(x => x.note_id === noteId);
  if (!n) return;
  editor.innerHTML = n.content.split('&').join('&amp;').split('<').join('&lt;').split('>').join('&gt;');
  editor.dataset.noteId = noteId;
  currentNoteId = noteId;
  document.querySelectorAll('.note-item').forEach(el => el.style.background = el.dataset.noteId === noteId ? 'var(--claude-soft)' : '');
}

function newNote() {
  const title = prompt('笔记标题：', '新笔记');
  if (!title) return;
  const editor = document.getElementById('note-editor');
  editor.innerHTML = '';
  editor.dataset.noteId = '';
  currentNoteId = '';
  editor.dataset.newTitle = title;
  editor.focus();
  toast('标题：' + title + '（输入内容后点保存）');
}

async function saveNote() {
  const editor = document.getElementById('note-editor');
  const title = editor.dataset.newTitle || (editor.dataset.noteId ? '' : prompt('笔记标题：', '新笔记'));
  if (!title) { toast('请先设置标题'); return; }
  const content = editor.innerText.trim();
  const sid = currentKnowledgeSession || currentSession || 'default';
  const r = await apiPost(`/api/v1/kb/${encodeURIComponent(sid)}/notes`, {
    title, content,
  });
  if (r.code === 0) {
    toast('笔记已保存');
    editor.dataset.noteId = '';
    delete editor.dataset.newTitle;
    await loadNotes(sid);
    await renderGraph(sid);
  } else toast('保存失败: ' + (r.msg || ''));
}

function noteInsert(before, after) {
  const editor = document.getElementById('note-editor');
  if (!editor) return;
  editor.focus();
  const sel = window.getSelection();
  if (!sel.rangeCount) return;
  const range = sel.getRangeAt(0);
  const text = range.toString();
  range.deleteContents();
  const newNode = document.createTextNode(before + text + after);
  range.insertNode(newNode);
}

/* ============================================================
   知识库面板（对接 /api/v1/kb/{session}/files）
   ============================================================ */
async function loadKbPanel(sessionId) {
  const items = await apiKbList(sessionId || 'default');
  // 头部标题 = 当前会话名
  const headName = document.getElementById('kb-head-name');
  if (headName) {
    const title = currentSessionTitle || '';
    headName.textContent = title ? `知识库 · ${title.slice(0, 18)}` : '知识库';
  }
  const pane = document.querySelector('.kb-pane[data-pane="refs"]');
  if (!pane) return;
  const countSpan = pane.querySelector('.count');
  if (countSpan) countSpan.textContent = items.length;
  const emptyEl = document.getElementById('kb-refs-empty');
  // 清理旧列表（保留标题行与上传行）
  pane.querySelectorAll('.ref-item,.ref-kb-none').forEach(el => el.remove());
  if (!items.length) {
    if (emptyEl) emptyEl.style.display = '';
    // 同步侧栏统计
    syncKbStats(0, 0);
    return;
  }
  if (emptyEl) emptyEl.style.display = 'none';
  const body = items.map(doc => {
    const meta = doc.metadata || {};
    const year = meta.year || '';
    const authors = (meta.authors || []).join(', ');
    const gbt = formatGbtLocal(doc);
    return `
    <div class="ref-item" data-file-id="${escapeHtml(doc.file_id || '')}">
      <div class="ref-item-title">${escapeHtml(meta.title || doc.file_name || '文献')}</div>
      <div class="ref-item-meta"><span class="badge verified" style="font-size:10px;padding:1px 6px;">✓</span><span>${escapeHtml((year ? year + ' ' : '') + authors)}</span></div>
      <div class="ref-item-actions">
        <button class="icon-btn" onclick="kbCopyGbt(this)">复制 GB/T 7714</button>
        <button class="icon-btn" onclick="kbDownload(this)">下载</button>
        <button class="icon-btn" style="color:var(--error)" onclick="kbDelete(this)">删除</button>
      </div>
    </div>`;
  }).join('');
  pane.insertAdjacentHTML('beforeend', body);
  // 侧栏统计（按 metadata.title 有无粗分类）
  const withTitle = items.filter(d => d.metadata?.title).length;
  syncKbStats(withTitle, items.length - withTitle);
}

/* —— 知识库统计（侧栏 核心/边缘） —— */
function syncKbStats(core, edge) {
  const els = document.querySelectorAll('.kb-stats .stat-num');
  if (els.length >= 2) { els[0].textContent = core; els[1].textContent = edge; }
}

/* —— 本地 GB/T 7714 格式化（题录元数据；与后端 format_gbt7714 对齐） —— */
function formatGbtLocal(doc) {
  const meta = doc.metadata || {};
  const authors = (meta.authors || []).join(', ');
  const title = meta.title || doc.file_name || '';
  const year = meta.year ? meta.year + '.' : '';
  const venue = meta.venue ? meta.venue + '.' : '';
  return `${authors}.${title}.${year}${venue}`;
}

/* —— 复制 GB/T 7714（真实剪贴板） —— */
function kbCopyGbt(btn) {
  const item = btn.closest('.ref-item');
  const title = item?.querySelector('.ref-item-title')?.textContent || '';
  const metaTxt = item?.querySelector('.ref-item-meta span:last-child')?.textContent || '';
  copyText(title + '. ' + metaTxt);
}

/* —— 下载知识库文献 —— */
async function kbDownload(btn) {
  const item = btn.closest('.ref-item');
  const fileId = item?.dataset.fileId;
  const sid = currentKnowledgeSession || currentSession || 'default';
  if (!fileId) { toast('文件标识缺失'); return; }
  const url = `${API_BASE}/api/v1/kb/${encodeURIComponent(sid)}/files/${encodeURIComponent(fileId)}`;
  try {
    const resp = await fetch(url, { credentials: 'include' });
    if (!resp.ok) { toast('下载失败: HTTP ' + resp.status); return; }
    const blob = await resp.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (item?.querySelector('.ref-item-title')?.textContent || 'document').slice(0, 80);
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e) { toast('下载失败: ' + e.message); }
}

/* —— 删除知识库文献 —— */
async function kbDelete(btn) {
  const item = btn.closest('.ref-item');
  const fileId = item?.dataset.fileId;
  const sid = currentKnowledgeSession || currentSession || 'default';
  if (!fileId) { toast('文件标识缺失'); return; }
  const r = await apiKbDelete(sid, fileId);
  if (r.code === 0) {
    toast('已删除');
    await loadKbPanel(sid);
    await renderGraph(sid);
  } else toast('删除失败: ' + (r.msg || ''));
}

/* —— 上传知识库文件（多选） —— */
async function kbUpload(files) {
  const sid = currentKnowledgeSession || currentSession || 'default';
  if (!files || !files.length) return;
  let ok = 0, fail = 0;
  for (const f of files) {
    const fd = new FormData();
    fd.append('file', f);
    try {
      const resp = await fetch(`${API_BASE}/api/v1/kb/${encodeURIComponent(sid)}/files`, {
        method: 'POST', headers: { 'Accept': 'application/json' }, body: fd,
        credentials: 'include',
      });
      const r = await resp.json();
      if (r.code === 0) ok++; else fail++;
    } catch (e) { fail++; }
  }
  toast(`上传完成：成功 ${ok} 个${fail ? '，失败 ' + fail : ''}`);
  await loadKbPanel(sid);
  await renderGraph(sid);
  if (window.notesCache && window.notesCache.refs) window.notesCache.refs = null;
}


async function initApp() {
  restoreJobBudget();
  bindSessionSearch();
  bindWorkspaceExpandedItems();
  // 1. 恢复完成前必须保持持久化关闭，禁止把本地默认值回写到服务端。
  pauseWorkspacePersistence();
  // 2. 先读取服务端工作区；失败时保留安全本地默认值。
  const restoredWorkspace = await loadWorkspaceState();
  applyWorkspaceExpandedItems();
  currentSession = restoredWorkspace.last_task_id || null;
  // 3. 加载任务列表，优先选择服务端的最后活动任务。
  const sessionResult = await loadSessionsWithWorkspaceFallback({
    preferredTaskId: restoredWorkspace.last_task_id,
    forceDetail: true,
  });
  // 页签以重新读取后的服务端状态为准，避免用过期的本地默认值覆盖。
  const restoredTab = workspaceState.active_tab || 'refs';
  if (sessionResult.ok && !sessionResult.selected) {
    scheduleWorkspaceSave({ last_task_id: '', active_tab: restoredTab });
  }
  // 新建对话按钮（.new-chat-btn 或 sidebar 新建）
  const newBtn = document.querySelector('.new-chat-btn') || document.querySelector('.sidebar-top button.btn-primary, #new-chat');
  if (newBtn && !newBtn.dataset.bound) {
    newBtn.dataset.bound = '1';
    newBtn.addEventListener('click', handleNewSession);
  }
  // 执行当前环节/确认闸门按钮绑定（消息流中的 [data-gate] / 运行按钮）
  document.querySelectorAll('[data-gate]').forEach(b => {
    if (!b.dataset.bound) { b.dataset.bound = '1'; b.addEventListener('click', confirmNextRing); }
  });
  // 图谱抽屉关闭
  const ndClose = document.getElementById('nd-close');
  if (ndClose && !ndClose.dataset.bound) { ndClose.dataset.bound = '1'; ndClose.addEventListener('click', () => hideAccessibleDialog(document.getElementById('node-drawer'))); }
  const ndOpen = document.getElementById('nd-open');
  if (ndOpen && !ndOpen.dataset.bound) {
    ndOpen.dataset.bound = '1';
    ndOpen.addEventListener('click', () => {
      const d = document.getElementById('node-drawer');
      const type = d.dataset.nodeType;
      const id = d.dataset.nodeId;
      if (type === 'paper') {
        // 切文献池页签（refs）
        document.querySelector('.kb-tab[data-tab="refs"]')?.click();
        const fileId = id.replace('paper:', '');
        const item = document.querySelector(`.ref-item[data-file-id="${fileId}"]`);
        if (item) { item.classList.add('flash'); item.scrollIntoView({ behavior: 'smooth', block: 'center' }); setTimeout(() => item.classList.remove('flash'), 1500); }
      } else {
        toast(type === 'note' ? '打开笔记（笔记编辑器建设中）' : '创建笔记（笔记编辑器建设中）');
      }
      hideAccessibleDialog(d);
    });
  }

  const runBtn = document.getElementById('run-cur-ring');
  if (runBtn && !runBtn.dataset.bound) { runBtn.dataset.bound = '1'; runBtn.addEventListener('click', runCurrentRing); }
  if (!document.getElementById('ns-confirm').dataset.bound) { document.getElementById('ns-confirm').dataset.bound = '1'; bindNewSessionModal(); }
  // 上传知识库文献
  const kbInput = document.getElementById('kb-file-input');
  if (kbInput && !kbInput.dataset.bound) {
    kbInput.dataset.bound = '1';
    kbInput.addEventListener('change', (e) => {
      if (e.target.files && e.target.files.length) kbUpload(e.target.files);
      e.target.value = '';
    });
  }
  const refreshBindings = [
    ['memory-refresh', window.ThesisProjectMemory.loadPanel],
    ['evidence-refresh', window.ThesisEvidence.loadPanel],
    ['research-refresh', loadResearchPanel],
    ['sections-refresh', loadSectionsPanel],
    ['jobs-refresh', loadJobsPanel],
    ['audit-refresh', loadSecurityAudit],
  ];
  refreshBindings.forEach(([id, handler]) => {
    const button = document.getElementById(id);
    if (button && !button.dataset.bound) {
      button.dataset.bound = '1';
      button.addEventListener('click', () => handler());
    }
  });
  const memoryForm = document.getElementById('memory-form');
  if (memoryForm && !memoryForm.dataset.bound) {
    memoryForm.dataset.bound = '1';
    memoryForm.addEventListener('submit', window.ThesisProjectMemory.submitForm);
  }
  const protocolForm = document.getElementById('protocol-form');
  if (protocolForm && !protocolForm.dataset.bound) {
    protocolForm.dataset.bound = '1';
    protocolForm.addEventListener('submit', submitProtocolForm);
  }
  const argumentForm = document.getElementById('argument-form');
  if (argumentForm && !argumentForm.dataset.bound) {
    argumentForm.dataset.bound = '1';
    argumentForm.addEventListener('submit', submitArgumentForm);
  }
  const addClaim = document.getElementById('argument-add-claim');
  if (addClaim && !addClaim.dataset.bound) {
    addClaim.dataset.bound = '1';
    addClaim.addEventListener('click', () => addArgumentClaimRow());
  }
  if (!document.querySelector('[data-claim-row]')) addArgumentClaimRow();
  const loginForm = document.getElementById('login-form');
  if (loginForm && !loginForm.dataset.bound) {
    loginForm.dataset.bound = '1';
    loginForm.addEventListener('submit', submitLogin);
  }
  const researchFileInput = document.getElementById('research-file-input');
  if (researchFileInput && !researchFileInput.dataset.bound) {
    researchFileInput.dataset.bound = '1';
    researchFileInput.addEventListener('change', event => {
      uploadResearchFiles(event.target.files);
      event.target.value = '';
    });
  }
  const templateFileInput = document.getElementById('task-template-file');
  if (templateFileInput && !templateFileInput.dataset.bound) {
    templateFileInput.dataset.bound = '1';
    templateFileInput.addEventListener('change', event => {
      uploadTaskTemplate(event.target.files?.[0]);
      event.target.value = '';
    });
  }
  // 使用服务端保存的页签，不能用 HTML 里的默认选中项覆盖恢复页签。
  await activateWorkbenchTab(restoredTab);
  // 横幅只展示当前选中任务的摘要，避免显示已失效的恢复信息。
  renderResumeBanner(await resolveResumeForSelected(currentSession, resumeSummaryCache));
  const continueButton = document.getElementById('resume-continue');
  if (continueButton && !continueButton.dataset.bound) {
    continueButton.dataset.bound = '1';
    continueButton.addEventListener('click', continueLastThesis);
  }
  // 恢复链路全部完成后才允许写回服务端。
  workspacePersistenceReady = true;
  void resumeActiveJobs(currentSession);
}
initApp();
