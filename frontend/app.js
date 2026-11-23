(() => {
  'use strict';

  const $ = (selector, scope = document) => scope.querySelector(selector);
  const $$ = (selector, scope = document) => [...scope.querySelectorAll(selector)];
  const icons = {
    panels: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M9 10h12"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    settings: '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="var(--bg)"/><circle cx="15" cy="17" r="3" fill="var(--bg)"/>',
    download: '<path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    'chevron-down': '<path d="m6 9 6 6 6-6"/>',
    shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/>',
    audio: '<path d="M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4"/>',
    cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4"/><rect x="10" y="10" width="4" height="4"/>',
    'arrow-up-right': '<path d="M6 18 18 6M6 6h12v12"/>',
    play: '<path d="m8 4 12 8-12 8Z"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    expand: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',
    captions: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M6 10h4m4 0h4M6 14h7m3 0h2"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    minus: '<path d="M5 12h14"/>',
    sparkles: '<path d="m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6Z"/><path d="M20 2v4m-2-2h4"/>',
    copy: '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V4a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h4"/>',
    scan: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5M7 9h10M7 13h10M7 17h6"/>',
    list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    corner: '<path d="M20 7v5a5 5 0 0 1-5 5H4m5-5-5 5 5 5"/>',
    upload: '<path d="M12 17V3m-5 5 5-5 5 5M3 16v5h18v-5"/>',
    x: '<path d="m6 6 12 12M6 18 18 6"/>',
    chevron: '<path d="m9 5 7 7-7 7"/>',
    video: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m10 8 6 4-6 4Z"/>',
  };

  function icon(name) {
    const span = document.createElement('span');
    span.setAttribute('aria-hidden', 'true');
    span.innerHTML = `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.video}</svg>`;
    return span;
  }

  function element(tag, className = '', text = '') {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== '') node.textContent = String(text);
    return node;
  }

  function button(label, className = 'button', onClick, iconName) {
    const node = element('button', className);
    node.type = 'button';
    if (iconName) node.append(icon(iconName));
    node.append(document.createTextNode(label));
    if (onClick) node.addEventListener('click', onClick);
    return node;
  }

  $$('[data-icon]').forEach(node => node.replaceChildren(icon(node.dataset.icon)));

  const state = {
    settings: null, models: [], projects: [], project: null,
    language: 'bilingual', follow: true, segmentNodes: new Map(),
    currentSegment: null, currentChapter: null, pendingSeek: null,
    toastTimer: null, polling: false, dialogKind: null, projectRequest: 0,
    projectGeneration: 0, projectMutationsPending: 0,
    importing: false, lastRenderSignature: '', lastSummarySignature: '',
    lastTaskSignature: '', announcedStatus: null, serviceAvailable: true, dragDepth: 0,
  };
  const video = $('#video');
  const dialog = $('#dialog');
  const busyStatuses = new Set(['queued', 'extracting', 'transcribing', 'translating', 'summarizing']);
  const stages = ['extracting', 'transcribing', 'translating', 'summarizing'];
  const statusNames = { imported: '已导入，准备识别', queued: '正在等待处理', extracting: '正在提取音频', transcribing: '正在识别原文', translating: '正在翻译中文', summarizing: '正在生成分段总结', completed: '理解完成', partial: '部分内容已完成', error: '处理遇到问题', cancelled: '已取消，已完成内容已保留' };
  const languageNames = { auto: '自动识别', en: '英语', zh: '中文', ja: '日语', ko: '韩语', fr: '法语', de: '德语', es: '西班牙语', it: '意大利语', pt: '葡萄牙语', ru: '俄语', ar: '阿拉伯语', hi: '印地语', th: '泰语', vi: '越南语', tr: '土耳其语', nl: '荷兰语' };

  function formatTime(value) {
    const seconds = Math.max(0, Math.floor(Number(value) || 0));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor(seconds % 3600 / 60);
    const rest = String(seconds % 60).padStart(2, '0');
    return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${String(minutes).padStart(2, '0')}:${rest}`;
  }

  function projectSegments() { return Array.isArray(state.project?.segments) ? state.project.segments : []; }
  function projectChapters() { return Array.isArray(state.project?.chapters) ? state.project.chapters : []; }
  function isBusy() { return busyStatuses.has(state.project?.status); }
  function modelInstalled(id) { return state.models.some(model => model.id === id && model.installed); }

  function toast(message, duration = 4300) {
    $('#toast').textContent = message;
    $('#toast').hidden = false;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => { $('#toast').hidden = true; }, duration);
  }

  function announce(message) { $('#announcement').textContent = message; }

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    let body = options.body;
    if (body !== undefined && !(body instanceof Blob) && typeof body !== 'string') {
      headers.set('Content-Type', 'application/json');
      body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, { ...options, body, headers, credentials: 'same-origin', cache: 'no-store' });
    } catch (_) {
      throw new Error('无法连接本地服务。请稍后重试，或重新打开 Freddie Spark。');
    }
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.error || `操作未完成（${response.status}），请重试。`);
    return result;
  }

  function bridge(action, detail = {}) {
    const handler = window.webkit?.messageHandlers?.freddie;
    if (!handler) return false;
    handler.postMessage({ action, ...detail });
    return true;
  }

  function setConnected(connected) {
    state.serviceAvailable = connected;
    $('#connection-warning').hidden = connected;
  }

  function showDialog(title, kind) {
    state.dialogKind = kind;
    $('#dialog-title').textContent = title;
    $('#dialog-content').replaceChildren();
    if (!dialog.open) dialog.showModal();
  }

  function closeDialog() {
    state.dialogKind = null;
    if (dialog.open) dialog.close();
  }

  function dialogError(message) {
    let error = $('.dialog-error', dialog);
    if (!error) {
      error = element('p', 'dialog-error');
      error.setAttribute('role', 'alert');
      $('#dialog-content').append(error);
    }
    error.textContent = message;
  }

  function renderMode() {
    const actual = state.project?.mode_used;
    const configured = state.settings?.mode || 'auto';
    const local = actual === 'local' || (!actual && configured === 'local');
    $('#mode-button').classList.toggle('local', local);
    $('#mode-label').textContent = actual === 'local' ? '本地处理' : actual === 'cloud' ? '云端增强' : ({ auto: '自动模式', cloud: '优先云端', local: '仅本地' })[configured];
    $('#footer-mode').textContent = actual === 'local' || configured === 'local' ? '识别、翻译与总结均在本机完成' : '云端仅处理转写文字';
  }

  function renderReadiness() {
    const asr = state.models.find(model => model.id === 'asr');
    const llm = state.models.find(model => model.id === 'llm');
    const container = $('#readiness-actions');
    container.replaceChildren();
    $('#model-readiness').hidden = Boolean(state.project && modelInstalled('asr'));
    if (!asr) {
      $('#model-readiness-text').textContent = state.serviceAvailable ? '正在检查本机模型…' : '连接本地服务后可检查模型状态。';
      return;
    }
    if (asr.installed) {
      $('#model-readiness-text').textContent = llm?.installed ? '识别与离线语言模型均已就绪，断网也能继续。' : state.settings?.cloud?.has_api_key ? '语音识别已就绪。下载离线语言模型后，断网也能翻译和总结。' : '语音识别已就绪。下一步配置云端密钥，或下载离线语言模型，即可翻译与总结。';
      const ready = element('span', 'ready-note', '本地识别已就绪');
      ready.prepend(icon('check'));
      container.append(ready);
      if (!state.settings?.cloud?.has_api_key) container.append(button('配置云端服务', 'text-button', () => openSettings()));
      if (!llm?.installed) container.append(button('准备离线保底', 'text-button', () => openSettings(true), 'download'));
    } else if (asr.downloading) {
      const progress = normalizeProgress(asr.progress);
      $('#model-readiness-text').textContent = `正在下载本地识别模型${progress ? ` · ${Math.round(progress)}%` : ''}。首次准备完成后，识别不再需要联网。`;
      container.append(button('查看下载状态', 'text-button', () => openSettings(true)));
    } else {
      $('#model-readiness-text').textContent = `首次需要下载语音识别模型（${asr.size_label || '约 150 MB'}）。模型留在本机，后续识别可离线运行。`;
      container.append(button('下载识别模型', 'button small', () => downloadModel('asr'), 'download'));
      if (asr.error) container.append(element('span', 'dialog-error', asr.error));
    }
  }

  function normalizeProgress(value) {
    const n = Number(value) || 0;
    return Math.max(0, Math.min(100, n));
  }

  function renderTask() {
    const project = state.project;
    $('#task-panel').hidden = !project;
    if (!project) return;
    const signature = JSON.stringify([project.status, project.progress, project.stage_message, project.error, project.warnings]);
    if (signature === state.lastTaskSignature) return;
    state.lastTaskSignature = signature;
    const busy = isBusy();
    const progress = normalizeProgress(project.progress);
    $('#task-label').textContent = project.stage_message || statusNames[project.status] || '准备处理';
    $('#task-percent').textContent = busy ? `${Math.round(progress)}%` : '';
    $('#task-indicator').classList.toggle('busy', busy);
    $('#task-indicator').classList.toggle('error', ['error', 'partial'].includes(project.status));
    $('#progress-track').hidden = !busy;
    $('#progress-fill').style.width = `${progress}%`;
    $('#progress-track').setAttribute('aria-valuenow', String(Math.round(progress)));
    $('#task-stages').hidden = !busy;
    const currentStage = stages.indexOf(project.status);
    $$('#task-stages li').forEach((item, index) => {
      item.classList.toggle('active', index === currentStage);
      item.classList.toggle('done', index < currentStage);
    });
    $('#cancel-button').hidden = !busy;
    $('#cancel-button').disabled = false;
    $('#cancel-button').textContent = '取消处理';
    const process = $('#process-button');
    process.hidden = busy;
    process.disabled = false;
    process.textContent = project.status === 'imported' ? '开始识别' : project.status === 'completed' ? '重新处理' : '重试处理';
    if (project.status === 'completed') process.classList.remove('primary');
    else process.classList.add('primary');
    $('#task-error').hidden = !project.error;
    $('#task-error').textContent = project.error || '';
    const warnings = Array.isArray(project.warnings) ? [...new Set(project.warnings.filter(Boolean))] : [];
    $('#task-warnings').hidden = !warnings.length;
    $('#task-warnings').textContent = warnings.join('\n');
    if (state.announcedStatus !== project.status) {
      state.announcedStatus = project.status;
      announce(statusNames[project.status] || '项目已更新');
    }
  }

  function renderTranscript(force = false) {
    transcriptCopy?.update();
    const segments = projectSegments();
    const signature = JSON.stringify([state.language, segments]);
    if (!force && signature === state.lastRenderSignature) return;
    state.lastRenderSignature = signature;
    const panel = $('#transcript');
    const top = panel.scrollTop;
    const panelTop = panel.getBoundingClientRect().top;
    const firstVisible = [...panel.children].find(row => row.dataset.segment !== undefined && row.getBoundingClientRect().bottom > panelTop + 1);
    const anchor = firstVisible ? { key: firstVisible.dataset.segment, offset: firstVisible.getBoundingClientRect().top - panelTop } : null;
    const fragment = document.createDocumentFragment();
    state.segmentNodes.clear();
    panel.dataset.language = state.language;
    panel.setAttribute('aria-labelledby', `tab-${state.language}`);
    if (!segments.length) {
      const placeholder = element('div', 'content-placeholder');
      placeholder.append(icon('audio'), element('h3', '', '原文将在这里出现'), element('p', '', isBusy() ? '模型正在聆听。识别出的原文会逐步显示。' : '开始识别后，带时间戳的原文会显示在这里。'));
      fragment.append(placeholder);
    }
    segments.forEach((segment, index) => {
      const row = element('div', 'transcript-row');
      const key = String(segment.id ?? index);
      row.dataset.segment = key;
      const timeButton = button(formatTime(segment.start), 'timestamp', () => seekTo(segment.start));
      timeButton.setAttribute('aria-label', `定位到 ${formatTime(segment.start)}`);
      const content = element('div');
      if (state.language !== 'chinese') {
        const original = element('p', 'segment-original', segment.text || '');
        original.lang = state.project?.detected_language || 'und';
        content.append(original);
      }
      if (state.language !== 'original') {
        if (segment.translation) {
          const translation = element('p', 'segment-translation', segment.translation);
          translation.lang = 'zh-CN';
          content.append(translation);
        } else content.append(element('p', 'translation-pending', isBusy() ? '中文翻译准备中…' : '此句暂无中文翻译'));
      }
      row.append(timeButton, content);
      fragment.append(row);
      state.segmentNodes.set(key, row);
    });
    panel.replaceChildren(fragment);
    panel.scrollTop = top;
    if (anchor && state.segmentNodes.has(anchor.key)) {
      const newTop = state.segmentNodes.get(anchor.key).getBoundingClientRect().top - panel.getBoundingClientRect().top;
      panel.scrollTop += newTop - anchor.offset;
    }
    $('#segment-count').textContent = `${segments.length} 句原文`;
    $$('.tab').forEach(tab => {
      const selected = tab.dataset.language === state.language;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    updatePlaybackHighlight(false);
  }

  function renderSummary() {
    const project = state.project;
    const chapters = projectChapters();
    const signature = JSON.stringify([project?.overview || '', chapters]);
    if (signature === state.lastSummarySignature) return;
    state.lastSummarySignature = signature;
    const sourceColumn = $('#source-column');
    const sourceTop = sourceColumn.scrollTop;
    const hasSummary = Boolean(project?.overview || chapters.length);
    $('#summary-empty').hidden = hasSummary;
    $('#summary-content').hidden = !hasSummary;
    $('#copy-summary-button').disabled = !hasSummary;
    $('#overview-text').textContent = project?.overview || (chapters.length ? '正在整理全文概览…' : '');
    $('.overview').hidden = !project?.overview;
    $('.chapter-heading').hidden = !chapters.length;
    $('.summary-foot').hidden = !chapters.length;
    $('#chapter-count').textContent = `${chapters.length} 个章节`;
    const fragment = document.createDocumentFragment();
    chapters.forEach((chapter, index) => {
      const item = element('button', 'chapter');
      item.type = 'button';
      item.dataset.chapter = String(index);
      item.setAttribute('aria-label', `${formatTime(chapter.start)}，${chapter.title || `章节 ${index + 1}`}`);
      item.addEventListener('click', () => seekTo(chapter.start));
      const number = element('span', 'chapter-number', String(index + 1).padStart(2, '0'));
      const content = element('span');
      const meta = element('span', 'chapter-meta');
      meta.append(element('span', '', `${formatTime(chapter.start)} — ${formatTime(chapter.end)}`), icon('arrow-up-right'));
      content.append(meta, element('h3', '', chapter.title || `章节 ${index + 1}`), element('p', '', chapter.summary || ''));
      if (Array.isArray(chapter.bullets) && chapter.bullets.length) {
        const list = element('ul');
        chapter.bullets.forEach(point => list.append(element('li', '', point)));
        content.append(list);
      }
      item.append(number, content);
      fragment.append(item);
    });
    $('#chapters').replaceChildren(fragment);
    sourceColumn.scrollTop = sourceTop;
    updatePlaybackHighlight(false);
  }

  function renderProject(reset = false) {
    const project = state.project;
    $('#empty-import').hidden = Boolean(project);
    $('#player').hidden = !project;
    $('#reader').hidden = !project;
    $('#reader-empty').hidden = Boolean(project);
    $('#project-title').textContent = project ? project.title || project.file_name || '未命名视频' : '你的下一段理解，从这里开始。';
    $('#project-meta').textContent = project ? `${project.file_name || ''}${project.duration ? ` · ${formatTime(project.duration)}` : ''}` : '将本地外语视频，变成清晰的中文与重点。';
    const detected = project?.detected_language;
    $('#language-label').textContent = detected ? `已识别为${languageNames[detected] || detected}` : '等待识别语种';
    $('#tab-original').textContent = detected === 'en' ? '英文原文' : '原文';
    $('#tab-bilingual').textContent = detected === 'en' ? '中英对照' : '中外对照';
    $('#export-button').disabled = !project || !(projectSegments().length || project.overview || projectChapters().length);
    $('#total-time').textContent = formatTime(project?.duration || video.duration);
    if (reset && project) {
      video.pause();
      state.pendingSeek = null;
      $('#video-message').hidden = true;
      video.src = `/api/projects/${encodeURIComponent(project.id)}/media`;
      video.load();
      $('#source-column').scrollTop = 0;
      $('#transcript').scrollTop = 0;
      $('#current-time').textContent = '00:00';
      $('#seek').value = '0';
      $('#seek').style.setProperty('--progress', '0%');
    }
    renderTask();
    renderTranscript(reset);
    renderSummary();
    renderReadiness();
    renderMode();
  }

  function updatePlaybackHighlight(scroll = true) {
    const time = state.pendingSeek ?? video.currentTime ?? 0;
    const segments = projectSegments();
    let activeIndex = -1;
    for (let i = 0; i < segments.length; i++) {
      if (time >= Number(segments[i].start) && time < Number(segments[i].end)) { activeIndex = i; break; }
    }
    const activeKey = activeIndex >= 0 ? String(segments[activeIndex].id ?? activeIndex) : null;
    const changed = state.currentSegment !== activeKey;
    state.currentSegment = activeKey;
    state.segmentNodes.forEach((node, key) => node.classList.toggle('current', key === activeKey));
    if (changed && scroll && state.follow && activeKey !== null) {
      const row = state.segmentNodes.get(activeKey);
      const panel = $('#transcript');
      if (row) {
        const rowTop = row.getBoundingClientRect().top - panel.getBoundingClientRect().top + panel.scrollTop;
        const rowBottom = rowTop + row.offsetHeight;
        if (rowTop < panel.scrollTop + 15 || rowBottom > panel.scrollTop + panel.clientHeight - 15) {
          panel.scrollTo({ top: Math.max(0, rowTop - panel.clientHeight * .25), behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
        }
      }
    }
    const chapters = projectChapters();
    let activeChapter = -1;
    chapters.forEach((chapter, index) => { if (time >= chapter.start && time < chapter.end) activeChapter = index; });
    if (activeChapter !== state.currentChapter) state.currentChapter = activeChapter;
    $$('#chapters .chapter').forEach((node, index) => {
      node.classList.toggle('current', index === activeChapter);
      node.setAttribute('aria-pressed', String(index === activeChapter));
    });
  }

  function updateClock() {
    const time = state.pendingSeek ?? video.currentTime ?? 0;
    const duration = Number.isFinite(video.duration) ? video.duration : Number(state.project?.duration) || 0;
    $('#current-time').textContent = formatTime(time);
    $('#total-time').textContent = formatTime(duration);
    $('#seek').max = String(duration || 1);
    $('#seek').value = String(time);
    $('#seek').style.setProperty('--progress', `${duration ? time / duration * 100 : 0}%`);
    updatePlaybackHighlight();
  }

  function seekTo(value) {
    const time = Math.max(0, Number(value) || 0);
    if (!state.project) return;
    if (video.readyState > 0) {
      state.pendingSeek = null;
      try { video.currentTime = Math.min(time, Number.isFinite(video.duration) ? video.duration : time); } catch (_) { state.pendingSeek = time; }
    } else state.pendingSeek = time;
    updateClock();
    announce(`已定位到 ${formatTime(time)}`);
  }

  async function openProject(projectOrId) {
    const request = ++state.projectRequest;
    const generation = ++state.projectGeneration;
    const id = typeof projectOrId === 'string' ? projectOrId : projectOrId.id;
    try {
      const result = await api(`/api/projects/${encodeURIComponent(id)}`);
      if (request !== state.projectRequest || generation !== state.projectGeneration) return false;
      ++state.projectGeneration;
      const changed = state.project?.id !== id;
      state.project = result.project;
      if (changed) {
        state.lastRenderSignature = '';
        state.lastSummarySignature = '';
        state.lastTaskSignature = '';
        state.currentSegment = null;
        state.currentChapter = null;
        state.announcedStatus = null;
      }
      renderProject(changed);
      closeDialog();
      try { localStorage.setItem('freddie-last-project', id); } catch (_) { /* Storage may be disabled. */ }
      return true;
    } catch (error) { toast(error.message); return false; }
  }

  function chooseVideo() {
    if (state.importing) return toast('正在导入，请稍候。');
    if (isBusy()) return toast('当前视频正在处理，请等待完成或取消后再导入。');
    try { if (!bridge('chooseVideo')) $('#file-input').click(); }
    catch (error) { toast(`无法打开文件选择器：${error.message}`); }
  }

  async function importVideo(input) {
    if (state.importing) return;
    if (isBusy()) return toast('当前视频正在处理，请等待完成或取消后再导入。');
    state.importing = true;
    $('#import-button').disabled = true;
    $('#empty-import-button').disabled = true;
    try {
      toast('正在导入本地视频…', 15000);
      let result;
      if (Array.isArray(input)) {
        result = await api('/api/import-path', { method: 'POST', body: { paths: input.slice(0, 1) } });
        if (input.length > 1) toast('每次处理一个视频，本次已导入第一个。');
      } else {
        result = await api('/api/import', { method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(input.name) }, body: input });
      }
      const importedId = result.project.id;
      const opened = await openProject(importedId);
      if (!opened) throw new Error('视频已导入，但暂时无法打开项目。可稍后从资料库继续。');
      const openedGeneration = state.projectGeneration;
      await refreshModels();
      await refreshProjects();
      if (state.project?.id !== importedId || state.projectGeneration !== openedGeneration) return;
      if (processingPrerequisite()) {
        toast('视频已导入。准备好模型与处理方式后，即可开始识别。');
      } else await processProject(importedId);
    } catch (error) { toast(error.message, 7000); }
    finally {
      state.importing = false;
      $('#import-button').disabled = false;
      $('#empty-import-button').disabled = false;
      $('#file-input').value = '';
    }
  }

  function processingPrerequisite() {
    if (!modelInstalled('asr')) return '请先下载本地语音识别模型。';
    const mode = state.settings?.mode || 'auto';
    const cloud = state.settings?.cloud || {};
    const cloudReady = Boolean(cloud.base_url && cloud.model && cloud.has_api_key);
    if (mode === 'local' && !modelInstalled('llm')) return '仅本地模式需要离线语言模型，请先下载。';
    if (mode === 'cloud' && !cloudReady) return '请先设置云端服务地址、模型与 API 密钥。';
    if (mode === 'auto' && !cloudReady && !modelInstalled('llm')) return '请配置云端服务，或下载离线语言模型。';
    return '';
  }

  async function processProject(expectedId = state.project?.id) {
    if (!state.project || state.project.id !== expectedId || isBusy() || state.projectMutationsPending) return;
    const prerequisite = processingPrerequisite();
    if (prerequisite) { toast(prerequisite, 6000); await openSettings(true); return; }
    const id = state.project.id;
    const generation = ++state.projectGeneration;
    state.projectMutationsPending++;
    $('#process-button').disabled = true;
    try {
      const result = await api(`/api/projects/${encodeURIComponent(id)}/process`, { method: 'POST', body: {} });
      if (state.project?.id !== id || state.projectGeneration !== generation) return;
      ++state.projectGeneration;
      if (result.project) state.project = result.project;
      else state.project.status = 'queued';
      state.lastTaskSignature = '';
      renderProject();
      toast('已开始处理。你可以先阅读已识别的内容。');
    } catch (error) {
      if (state.project?.id === id && state.projectGeneration === generation) {
        ++state.projectGeneration;
        toast(error.message, 7000);
        $('#process-button').disabled = false;
      }
    } finally { state.projectMutationsPending--; }
  }

  async function cancelProject() {
    if (!state.project || !isBusy() || state.projectMutationsPending) return;
    const id = state.project.id;
    const generation = ++state.projectGeneration;
    state.projectMutationsPending++;
    $('#cancel-button').disabled = true;
    $('#cancel-button').textContent = '正在取消…';
    try {
      const result = await api(`/api/projects/${encodeURIComponent(id)}/cancel`, { method: 'POST', body: {} });
      if (state.project?.id !== id || state.projectGeneration !== generation) return;
      ++state.projectGeneration;
      if (result.project) state.project = result.project;
      state.lastTaskSignature = '';
      renderProject();
      toast('已请求取消，正在完成当前步骤。已有内容会保留。');
    } catch (error) {
      if (state.project?.id === id && state.projectGeneration === generation) {
        ++state.projectGeneration;
        $('#cancel-button').disabled = false;
        $('#cancel-button').textContent = '取消处理';
        toast(error.message);
      }
    } finally { state.projectMutationsPending--; }
  }

  async function refreshProjects() {
    const result = await api('/api/projects');
    state.projects = Array.isArray(result.projects) ? result.projects : [];
    if (state.dialogKind === 'library') renderLibrary();
  }

  async function refreshModels() {
    const result = await api('/api/models');
    state.models = Array.isArray(result.models) ? result.models : [];
    renderReadiness();
    if (state.dialogKind === 'settings') renderModelList();
  }

  async function downloadModel(id) {
    try {
      await api(`/api/models/${encodeURIComponent(id)}/download`, { method: 'POST', body: {} });
      toast('已开始下载模型。请保持网络连接，下载完成后即可在本机使用。', 6000);
      await refreshModels();
    } catch (error) {
      if (state.dialogKind === 'settings') dialogError(error.message);
      else toast(error.message, 7000);
    }
  }

  function labeledField(label, control, hint = '') {
    const wrapper = element('label', 'field');
    wrapper.append(document.createTextNode(label), control);
    if (hint) wrapper.append(element('small', '', hint));
    return wrapper;
  }

  function select(options, value, name) {
    const control = element('select');
    control.name = name;
    options.forEach(([id, label]) => {
      const option = element('option', '', label);
      option.value = id;
      control.append(option);
    });
    control.value = value;
    return control;
  }

  function input(type, name, value = '', placeholder = '') {
    const control = element('input');
    control.type = type;
    control.name = name;
    control.value = value;
    control.placeholder = placeholder;
    control.autocomplete = 'off';
    control.spellcheck = false;
    return control;
  }

  async function openSettings(modelsFirst = false) {
    showDialog('处理与离线设置', 'settings');
    const container = $('#dialog-content');
    container.append(element('p', 'dialog-intro', '联网时用云端获得更好的中文，断网时用本地模型继续理解。'));
    try {
      const result = await api('/api/settings');
      if (state.dialogKind !== 'settings') return;
      state.settings = result;
      renderMode();
      renderSettingsForm();
      await refreshModels();
      if (modelsFirst) $('#settings-models')?.scrollIntoView({ block: 'nearest' });
    } catch (error) { dialogError(error.message); }
  }

  function renderSettingsForm() {
    const settings = state.settings || {};
    const container = $('#dialog-content');
    container.replaceChildren(element('p', 'dialog-intro', '本地识别始终留在本机。云端仅接收转写文字，用于翻译和总结。'));
    const form = element('form');
    form.id = 'settings-form';
    const fields = element('div', 'fields-row');
    fields.append(labeledField('处理方式', select([['auto', '自动 · 云端优先，离线保底'], ['cloud', '优先云端 · 失败时提示重试'], ['local', '仅本地 · 不发送内容到云端']], settings.mode || 'auto', 'mode')));
    fields.append(labeledField('视频语种', select(Object.entries(languageNames), settings.recognition_language || 'auto', 'recognition_language')));
    form.append(fields, element('p', 'settings-note', '自动模式在云端不可用时，使用已安装的本地语言模型。更改设置会在下一次处理时生效。'));
    const cloudSection = element('section', 'settings-section');
    cloudSection.append(element('h3', '', '云端服务'));
    cloudSection.append(labeledField('服务地址', input('url', 'base_url', settings.cloud?.base_url || '', 'https://api.example.com/v1'), '支持 OpenAI 兼容的服务接口。请使用你信任的服务地址。'));
    cloudSection.append(labeledField('模型名称', input('text', 'model', settings.cloud?.model || '', '填写服务商提供的模型名称')));
    const key = input('password', 'api_key', '', settings.cloud?.has_api_key ? '已保存密钥，留空保持原值' : '输入 API Key');
    key.autocomplete = 'new-password';
    cloudSection.append(labeledField('API 密钥', key, '密钥仅供本地服务调用，不会显示在项目或导出内容中。'));
    if (settings.cloud?.has_api_key) {
      const clearLabel = element('label', 'checkbox-label');
      clearLabel.append(input('checkbox', 'clear_api_key'), document.createTextNode('清除已保存的密钥'));
      cloudSection.append(clearLabel);
    }
    if (settings.credential_persistent === false) cloudSection.append(element('p', 'settings-warning', settings.credential_warning || '系统钥匙串当前不可用。密钥仅在本次运行期间保存，退出软件后需要重新填写。'));
    form.append(cloudSection);
    const modelsSection = element('section', 'settings-section');
    modelsSection.id = 'settings-models';
    modelsSection.append(element('h3', '', '本地模型与离线包'), element('p', 'settings-note', '模型需提前联网下载。语音识别模型为必需；离线语言模型用于本地翻译与基础总结。'));
    const list = element('div');
    list.id = 'model-list';
    modelsSection.append(list);
    form.append(modelsSection);
    const actions = element('div', 'dialog-actions');
    const cancel = button('关闭', 'button quiet', closeDialog);
    const save = button('保存设置', 'button primary', null, 'check');
    save.type = 'submit';
    actions.append(cancel, save);
    form.append(actions);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      save.disabled = true;
      $('.dialog-error', dialog)?.remove();
      const data = new FormData(form);
      const body = {
        mode: String(data.get('mode') || 'auto'),
        recognition_language: String(data.get('recognition_language') || 'auto'),
        cloud: { base_url: String(data.get('base_url') || '').trim(), model: String(data.get('model') || '').trim() },
      };
      const apiKey = String(data.get('api_key') || '').trim();
      if (apiKey) body.cloud.api_key = apiKey;
      if (data.get('clear_api_key')) body.cloud.clear_api_key = true;
      try {
        await api('/api/settings', { method: 'PUT', body });
        state.settings = await api('/api/settings');
        key.value = '';
        renderMode();
        closeDialog();
        toast('设置已保存，下一次处理将使用新的设置。');
      } catch (error) { dialogError(error.message); save.disabled = false; }
    });
    container.append(form);
    renderModelList();
  }

  function renderModelList() {
    const list = $('#model-list');
    if (!list) return;
    const focusedModel = document.activeElement?.dataset?.downloadModel;
    const fragment = document.createDocumentFragment();
    if (!state.models.length) fragment.append(element('p', 'settings-note', '正在检查本机模型…'));
    state.models.forEach(model => {
      const row = element('div', 'model-row');
      const head = element('div', 'model-row-head');
      const title = element('div');
      title.append(element('h4', '', model.name || (model.id === 'asr' ? '语音识别模型' : '离线语言模型')), element('p', '', `${model.description || ''}${model.size_label ? ` · ${model.size_label}` : ''}`));
      head.append(title);
      if (model.installed) head.append(element('span', 'ready-note', '已就绪'));
      else {
        const download = button(model.downloading ? '正在下载…' : model.error ? '重新下载' : '下载模型', 'button small', () => downloadModel(model.id), model.downloading ? null : 'download');
        download.disabled = Boolean(model.downloading);
        download.setAttribute('aria-label', `${model.downloading ? '正在下载' : model.error ? '重新下载' : '下载'}${model.name || (model.id === 'asr' ? '语音识别模型' : '离线语言模型')}`);
        download.dataset.downloadModel = model.id;
        head.append(download);
      }
      row.append(head);
      if (model.downloading) {
        const progress = normalizeProgress(model.progress);
        const bar = element('div', 'progress-track');
        const fill = element('div');
        fill.style.width = `${progress}%`;
        bar.append(fill);
        bar.setAttribute('role', 'progressbar');
        bar.setAttribute('aria-label', `${model.name || '模型'}下载进度`);
        bar.setAttribute('aria-valuemin', '0');
        bar.setAttribute('aria-valuemax', '100');
        bar.setAttribute('aria-valuenow', String(Math.round(progress)));
        row.append(bar, element('p', 'model-status', progress ? `下载中 · ${Math.round(progress)}%` : '正在连接模型下载源…'));
      }
      if (model.error) row.append(element('p', 'model-error', model.error));
      fragment.append(row);
    });
    list.replaceChildren(fragment);
    if (focusedModel) $$('[data-download-model]', list).find(node => node.dataset.downloadModel === focusedModel)?.focus({ preventScroll: true });
  }

  async function openLibrary() {
    showDialog('本地资料库', 'library');
    renderLibrary();
    try { await refreshProjects(); } catch (error) { dialogError(error.message); }
  }

  function renderLibrary() {
    if (state.dialogKind !== 'library') return;
    const container = $('#dialog-content');
    const focusedProject = document.activeElement?.dataset?.projectId;
    container.replaceChildren(element('p', 'dialog-intro', '视频与阅读结果保存在这台 Mac 上，处理过的内容断网也能查看。'));
    if (!state.projects.length) {
      const empty = element('div', 'content-placeholder');
      empty.append(icon('folder'), element('h3', '', '还没有视频项目'), element('p', '', '导入第一个视频，开始你的理解工作台。'));
      container.append(empty, button('导入视频', 'button primary', () => { closeDialog(); chooseVideo(); }, 'plus'));
      return;
    }
    const list = element('div', 'library-list');
    state.projects.forEach(project => {
      const item = element('button', 'library-item');
      item.type = 'button';
      item.dataset.projectId = project.id;
      const content = element('span', 'library-details');
      content.append(element('h3', '', project.title || project.file_name || '未命名视频'));
      const lang = languageNames[project.detected_language] || project.detected_language || '等待识别';
      content.append(element('p', '', `${lang}${project.duration ? ` · ${formatTime(project.duration)}` : ''} · ${statusNames[project.status] || project.status || '已导入'}`));
      item.append(icon('video'), content, icon('chevron'));
      item.addEventListener('click', () => openProject(project.id));
      list.append(item);
    });
    container.append(list);
    if (focusedProject) $$('.library-item', list).find(node => node.dataset.projectId === focusedProject)?.focus({ preventScroll: true });
  }

  function summaryText() {
    if (!state.project) return '';
    const parts = [state.project.title || state.project.file_name || '视频总结'];
    if (state.project.overview) parts.push(state.project.overview);
    projectChapters().forEach(chapter => {
      parts.push(`${formatTime(chapter.start)} — ${formatTime(chapter.end)}  ${chapter.title || ''}\n${chapter.summary || ''}${Array.isArray(chapter.bullets) && chapter.bullets.length ? `\n${chapter.bullets.map(point => `• ${point}`).join('\n')}` : ''}`);
    });
    return parts.join('\n\n');
  }

  let transcriptCopy = null;

  function installTranscriptCopy() {
    const helper = window.FreddieTranscriptCopy;
    if (!helper) return;
    let anchor = $('#transcript-copy-anchor');
    if (!anchor) {
      const heading = $('.reader-heading');
      if (!heading) return;
      anchor = element('span');
      anchor.id = 'transcript-copy-anchor';
      heading.append(anchor);
    }
    transcriptCopy = helper.mount({
      anchor,
      getContext: () => ({ segments: projectSegments(), mode: state.language, status: state.project?.status }),
      onCopy: copyTranscript,
    });
  }

  async function copyTranscript(format) {
    const helper = window.FreddieTranscriptCopy;
    if (!helper) { toast('复制功能尚未载入，请重新打开应用。'); return; }
    const mode = state.language;
    const segments = projectSegments();
    let text, current;
    try {
      current = helper.availability(segments, mode, state.project?.status);
      text = helper.formatTranscript(segments, mode, format);
    } catch (error) { toast(error.message, 6500); return; }
    const title = `${current.label} · ${format.toUpperCase()}`;
    const success = `${title} 已复制。${current.partial ? '仅包含当前已生成内容。' : ''}`;
    try {
      if (bridge('copy', { text })) { toast(success); return; }
    } catch (_) { /* Fall back to the browser clipboard if the native bridge fails. */ }
    try {
      await navigator.clipboard.writeText(text);
      toast(success);
    } catch (_) {
      showDialog(`复制${title}`, 'copy');
      const area = element('textarea');
      area.value = text;
      area.readOnly = true;
      $('#dialog-content').append(labeledField('选择并复制以下内容', area), element('p', 'settings-note', '当前系统未开放自动剪贴板权限，可按 ⌘C 复制。'));
      area.focus();
      area.select();
    }
  }

  async function copySummary() {
    const text = summaryText();
    if (!text) return;
    try {
      if (bridge('copy', { text })) { toast('中文总结已复制。'); return; }
    } catch (_) { /* A browser clipboard remains available if the native bridge fails. */ }
    try {
      await navigator.clipboard.writeText(text);
      toast('中文总结已复制。');
    } catch (_) {
      showDialog('复制中文总结', 'copy');
      const area = element('textarea');
      area.value = text;
      area.readOnly = true;
      const field = labeledField('选择并复制以下内容', area);
      $('#dialog-content').append(field, element('p', 'settings-note', '当前系统未开放自动剪贴板权限，可按 ⌘C 复制。'));
      area.focus();
      area.select();
    }
  }

  function openExport() {
    if (!state.project) return;
    showDialog('导出内容', 'export');
    const container = $('#dialog-content');
    container.append(element('p', 'dialog-intro', '把理解后的内容，带到你的下一步工作里。'));
    const contents = [];
    if (state.project.overview || projectChapters().length) contents.push(['summary', '中文总结与章节时间']);
    if (projectSegments().length) {
      contents.push(['original', '外语原文']);
      if (projectSegments().some(segment => segment.translation)) contents.push(['bilingual', '中外对照字幕'], ['chinese', '中文翻译']);
    }
    const contentSelect = select(contents, contents[0]?.[0], 'content');
    const formatSelect = select([['md', 'Markdown 文档'], ['txt', '纯文本 TXT'], ['srt', '字幕 SRT']], 'md', 'format');
    const updateFormat = () => {
      const summary = contentSelect.value === 'summary';
      const srt = $('option[value="srt"]', formatSelect);
      srt.disabled = summary;
      if (summary && formatSelect.value === 'srt') formatSelect.value = 'md';
    };
    contentSelect.addEventListener('change', updateFormat);
    updateFormat();
    container.append(labeledField('导出内容', contentSelect), labeledField('文件格式', formatSelect));
    const actions = element('div', 'dialog-actions');
    actions.append(button('取消', 'button quiet', closeDialog), button('保存文件', 'button primary', () => {
      const url = `/api/projects/${encodeURIComponent(state.project.id)}/export?format=${encodeURIComponent(formatSelect.value)}&content=${encodeURIComponent(contentSelect.value)}`;
      try {
        if (!bridge('export', { url })) {
          const link = element('a');
          link.href = url;
          link.download = '';
          document.body.append(link);
          link.click();
          link.remove();
        }
        closeDialog();
      } catch (error) { dialogError(error.message); }
    }, 'download'));
    container.append(actions);
  }

  async function poll() {
    if (state.polling) return;
    state.polling = true;
    const generation = state.projectGeneration;
    const projectId = state.project?.id;
    try {
      const results = await Promise.allSettled([
        api('/api/models'),
        projectId ? api(`/api/projects/${encodeURIComponent(projectId)}`) : Promise.resolve(null),
        !state.settings ? api('/api/settings') : Promise.resolve(null),
      ]);
      const [models, project, settings] = results;
      if (settings.status === 'fulfilled' && settings.value) {
        state.settings = settings.value;
        renderMode();
      }
      if (models.status === 'fulfilled') {
        setConnected(true);
        state.models = Array.isArray(models.value.models) ? models.value.models : [];
        renderReadiness();
        if (state.dialogKind === 'settings') renderModelList();
      } else setConnected(false);
      if (!state.projectMutationsPending && generation === state.projectGeneration && projectId === state.project?.id && project.status === 'fulfilled' && project.value?.project && project.value.project.id === projectId) {
        const oldStatus = state.project.status;
        state.project = project.value.project;
        renderProject();
        if (oldStatus !== state.project.status && ['completed', 'partial', 'error', 'cancelled'].includes(state.project.status)) {
          toast(statusNames[state.project.status], 6000);
          refreshProjects().catch(() => {});
        }
      }
      if (state.dialogKind === 'library') await refreshProjects();
    } finally { state.polling = false; }
  }

  function installEvents() {
    installTranscriptCopy();
    $('#import-button').addEventListener('click', chooseVideo);
    $('#empty-import-button').addEventListener('click', chooseVideo);
    $('#workspace-button').addEventListener('click', () => {
      closeDialog();
      const behavior = matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
      $('#source-column').scrollTo({ top: 0, behavior });
      $('#transcript').scrollTo({ top: 0, behavior });
      window.scrollTo({ top: 0, behavior });
    });
    $('#library-button').addEventListener('click', openLibrary);
    $('#mobile-library-button').addEventListener('click', openLibrary);
    $('#settings-button').addEventListener('click', () => openSettings());
    $('#mode-button').addEventListener('click', () => openSettings());
    $('#model-settings-button').addEventListener('click', () => openSettings(true));
    $('#export-button').addEventListener('click', openExport);
    $('#copy-summary-button').addEventListener('click', copySummary);
    $('#process-button').addEventListener('click', () => processProject());
    $('#cancel-button').addEventListener('click', cancelProject);
    $('#dialog-close').addEventListener('click', closeDialog);
    dialog.addEventListener('close', () => { state.dialogKind = null; });
    dialog.addEventListener('click', event => { if (event.target === dialog) { const bounds = dialog.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closeDialog(); } });
    $('#file-input').addEventListener('change', event => { const file = event.target.files?.[0]; if (file) importVideo(file); });
    window.addEventListener('freddie:import', event => {
      const paths = event.detail?.paths;
      if (Array.isArray(paths) && paths.length) importVideo(paths);
    });
    window.addEventListener('freddie:error', event => toast(event.detail?.message || '操作未完成，请重试。', 7000));
    window.addEventListener('freddie:exported', () => toast('文件已保存。'));
    $$('.tab').forEach(tab => tab.addEventListener('click', () => { state.language = tab.dataset.language; renderTranscript(); }));
    $('.tabs').addEventListener('keydown', event => {
      if (!event.target.classList.contains('tab') || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const tabs = $$('.tab');
      const current = tabs.indexOf(event.target);
      const index = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length;
      tabs[index].click();
      tabs[index].focus();
    });
    $('#follow-button').addEventListener('click', () => {
      state.follow = !state.follow;
      $('#follow-button').setAttribute('aria-pressed', String(state.follow));
      $('#follow-button').replaceChildren(icon(state.follow ? 'check' : 'minus'), element('span', '', '跟随播放'));
      if (state.follow) { state.currentSegment = null; updatePlaybackHighlight(true); }
    });
    $('#transcript').addEventListener('wheel', () => {
      if (!state.follow || video.paused) return;
      state.follow = false;
      $('#follow-button').setAttribute('aria-pressed', 'false');
      $('#follow-button').replaceChildren(icon('minus'), element('span', '', '跟随播放'));
    }, { passive: true });
    video.controls = false;
    $('#play-button').addEventListener('click', async () => {
      if (video.paused) {
        try { await video.play(); } catch (_) { toast('这个视频暂时无法播放，可继续识别音频或尝试 MP4 格式。'); }
      } else video.pause();
    });
    video.addEventListener('play', () => { $('#play-button').replaceChildren(icon('pause')); $('#play-button').setAttribute('aria-label', '暂停'); });
    video.addEventListener('pause', () => { $('#play-button').replaceChildren(icon('play')); $('#play-button').setAttribute('aria-label', '播放'); });
    video.addEventListener('timeupdate', updateClock);
    video.addEventListener('loadedmetadata', () => {
      $('#video-message').hidden = true;
      if (!video.videoWidth) {
        $('#video-message').textContent = '音频已载入。播放后可跟随原文阅读。';
        $('#video-message').hidden = false;
      }
      if (state.pendingSeek !== null) seekTo(state.pendingSeek);
      updateClock();
    });
    video.addEventListener('durationchange', updateClock);
    video.addEventListener('error', () => {
      if (!state.project || !video.error) return;
      $('#video-message').textContent = '此格式暂时无法预览，但仍可识别音频。建议使用 MP4（H.264）获得更好的播放体验。';
      $('#video-message').hidden = false;
    });
    $('#seek').addEventListener('input', event => seekTo(Number(event.target.value)));
    $('#speed-button').addEventListener('click', () => {
      const speeds = [1, 1.25, 1.5, 2];
      video.playbackRate = speeds[(speeds.indexOf(video.playbackRate) + 1) % speeds.length];
      $('#speed-button').textContent = `${video.playbackRate}×`;
    });
    $('#fullscreen-button').addEventListener('click', () => {
      try {
        if (video.webkitEnterFullscreen) video.webkitEnterFullscreen();
        else if (video.requestFullscreen) video.requestFullscreen().catch(() => toast('当前窗口不支持全屏播放。'));
        else toast('当前窗口不支持全屏播放。');
      } catch (_) { toast('视频准备好后即可进入全屏。'); }
    });
    document.addEventListener('dragenter', event => {
      if (![...(event.dataTransfer?.types || [])].includes('Files')) return;
      event.preventDefault();
      state.dragDepth++;
      $('#drop-overlay').hidden = false;
    });
    document.addEventListener('dragover', event => { if ([...(event.dataTransfer?.types || [])].includes('Files')) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; } });
    document.addEventListener('dragleave', event => { event.preventDefault(); state.dragDepth = Math.max(0, state.dragDepth - 1); if (!state.dragDepth) $('#drop-overlay').hidden = true; });
    document.addEventListener('drop', event => {
      event.preventDefault();
      state.dragDepth = 0;
      $('#drop-overlay').hidden = true;
      const files = [...(event.dataTransfer?.files || [])];
      if (!files.length) return;
      if (files.length > 1) toast('每次处理一个视频，本次使用第一个文件。');
      importVideo(files[0]);
    });
    window.addEventListener('blur', () => { state.dragDepth = 0; $('#drop-overlay').hidden = true; });
  }

  async function initialize() {
    installEvents();
    const results = await Promise.allSettled([api('/api/settings'), api('/api/models'), api('/api/projects')]);
    if (results[0].status === 'fulfilled') state.settings = results[0].value;
    if (results[1].status === 'fulfilled') state.models = results[1].value.models || [];
    if (results[2].status === 'fulfilled') state.projects = results[2].value.projects || [];
    setConnected(results.every(result => result.status === 'fulfilled'));
    renderMode();
    renderReadiness();
    let lastProject;
    try { lastProject = localStorage.getItem('freddie-last-project'); } catch (_) { /* Optional preference. */ }
    const active = state.projects.find(project => busyStatuses.has(project.status));
    const restore = active || state.projects.find(project => project.id === lastProject);
    if (restore) await openProject(restore.id);
    setInterval(() => { poll().catch(() => setConnected(false)); }, 2500);
  }

  initialize().catch(error => { setConnected(false); toast(error.message, 8000); });
})();
