/* Transcript copying is independent of document exports: TXT contains text only. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.FreddieTranscriptCopy = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const modeLabels = Object.freeze({ original: '原文', bilingual: '中外对照', chinese: '纯中文' });
  const activeStatuses = new Set(['queued', 'extracting', 'transcribing', 'translating', 'summarizing']);

  function validateMode(mode) {
    if (!Object.prototype.hasOwnProperty.call(modeLabels, mode)) throw new Error('请选择原文、中外对照或纯中文阅读模式。');
  }

  function cleanText(value) {
    return typeof value === 'string' ? value.replace(/\r\n?/g, '\n').trim() : '';
  }

  function segmentText(segment, mode) {
    validateMode(mode);
    const original = cleanText(segment?.text);
    const chinese = cleanText(segment?.translation);
    if (mode === 'original') return original;
    if (mode === 'chinese') return chinese;
    return [original, chinese].filter(Boolean).join('\n');
  }

  function availableSegments(segments, mode) {
    validateMode(mode);
    return (Array.isArray(segments) ? segments : []).filter(segment => segmentText(segment, mode));
  }

  function milliseconds(seconds) {
    if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) {
      throw new Error('有字幕片段缺少有效时间，无法复制 SRT。可先复制 TXT，或重新识别后重试。');
    }
    const value = Math.round(seconds * 1000);
    if (!Number.isSafeInteger(value)) throw new Error('字幕时间超出有效范围，无法复制 SRT。');
    return value;
  }

  function srtTimestamp(seconds) {
    const value = milliseconds(seconds);
    const hours = Math.floor(value / 3600000);
    const minutes = Math.floor(value % 3600000 / 60000);
    const rest = Math.floor(value % 60000 / 1000);
    return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')},${String(value % 1000).padStart(3, '0')}`;
  }

  function formatTranscript(segments, mode, format) {
    validateMode(mode);
    if (!['srt', 'txt'].includes(format)) throw new Error('请选择 SRT 或 TXT 复制格式。');
    const selected = availableSegments(segments, mode);
    if (!selected.length) throw new Error(mode === 'chinese' ? '当前还没有生成中文翻译，请等待翻译完成后再复制。' : '当前还没有可复制的原文，请先识别视频。');
    if (format === 'txt') return selected.map(segment => segmentText(segment, mode)).join('\n');
    return selected.map((segment, index) => {
      const start = milliseconds(segment.start);
      const end = milliseconds(segment.end);
      if (end <= start) throw new Error(`第 ${index + 1} 个字幕片段的结束时间必须晚于开始时间，无法复制 SRT。可先复制 TXT。`);
      // Blank lines delimit SRT cues, so preserve text lines without empty cue separators.
      const text = segmentText(segment, mode).split('\n').map(line => line.trim()).filter(Boolean).join('\n');
      return `${index + 1}\n${srtTimestamp(segment.start)} --> ${srtTimestamp(segment.end)}\n${text}`;
    }).join('\n\n') + '\n';
  }

  function availability(segments, mode, status) {
    validateMode(mode);
    const source = Array.isArray(segments) ? segments : [];
    const count = availableSegments(source, mode).length;
    const missingTranslations = mode !== 'original' && source.some(segment => cleanText(segment?.text) && !cleanText(segment?.translation));
    const partial = Boolean(activeStatuses.has(status) || ['partial', 'cancelled', 'error'].includes(status) || missingTranslations);
    let message = '';
    if (!count) message = mode === 'chinese' ? '中文翻译尚未生成，暂时无法复制。' : '识别出原文后即可复制。';
    else if (missingTranslations) message = '部分中文尚未生成，仅复制当前已有内容。';
    else if (partial) message = '处理尚未完成，仅复制当前已有内容。';
    else message = '按当前阅读模式复制到系统剪贴板。';
    return { enabled: count > 0, count, partial, message, label: modeLabels[mode] };
  }

  function mount(options) {
    const { anchor, getContext, onCopy } = options;
    if (!anchor || typeof document === 'undefined') return null;
    if (anchor._freddieTranscriptCopy) return anchor._freddieTranscriptCopy;
    if (!document.getElementById('transcript-copy-styles')) {
      const style = document.createElement('style');
      style.id = 'transcript-copy-styles';
      style.textContent = '.transcript-copy-anchor{position:relative;display:inline-flex;align-items:center;flex-shrink:0}.transcript-copy-popover{position:absolute;right:0;top:calc(100% + 9px);z-index:30;width:min(255px,calc(100vw - 40px));padding:12px;background:var(--surface,#10151b);border:1px solid var(--line,#26313b);border-radius:10px;box-shadow:0 14px 36px #0006}.transcript-copy-label{font-size:12px;font-weight:600;color:var(--accent,#91ead8);padding:1px 4px 5px}.transcript-copy-note{font-size:11px;line-height:1.5;color:var(--muted,#8494a4);padding:0 4px 9px}.transcript-copy-choice{display:flex;flex-direction:column;align-items:flex-start;gap:1px;width:100%;text-align:left;border-radius:6px;padding:9px 10px;min-height:44px;font-size:13px}.transcript-copy-choice:hover:not(:disabled){background:var(--raised,#17212a)}.transcript-copy-choice span{font-size:11px;color:var(--muted,#8494a4)}';
      document.head.append(style);
    }
    anchor.classList.add('transcript-copy-anchor');
    const trigger = document.createElement('button');
    trigger.type = 'button';
    trigger.id = 'copy-transcript-button';
    trigger.className = 'icon-button';
    trigger.setAttribute('aria-label', '复制当前阅读内容');
    trigger.setAttribute('aria-haspopup', 'dialog');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-controls', 'transcript-copy-popover');
    trigger.innerHTML = '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V4a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h4"/></svg>';
    const popover = document.createElement('div');
    popover.id = 'transcript-copy-popover';
    popover.className = 'transcript-copy-popover';
    popover.hidden = true;
    popover.setAttribute('role', 'dialog');
    popover.setAttribute('aria-labelledby', 'transcript-copy-label');
    popover.setAttribute('aria-describedby', 'transcript-copy-note');
    const label = document.createElement('p');
    label.id = 'transcript-copy-label';
    label.className = 'transcript-copy-label';
    const note = document.createElement('p');
    note.id = 'transcript-copy-note';
    note.className = 'transcript-copy-note';
    popover.append(label, note);
    const choices = ['srt', 'txt'].map(format => {
      const choice = document.createElement('button');
      choice.type = 'button';
      choice.className = 'transcript-copy-choice';
      choice.dataset.copyFormat = format;
      choice.append(document.createTextNode(format.toUpperCase()));
      const description = document.createElement('span');
      description.textContent = format === 'srt' ? '标准字幕 · 序号与时间戳' : '纯文本 · 不含序号与时间';
      choice.append(description);
      choice.addEventListener('click', async () => {
        close(true);
        await onCopy(format);
      });
      popover.append(choice);
      return choice;
    });
    anchor.append(trigger, popover);

    function close(restoreFocus = false) {
      const wasOpen = !popover.hidden;
      popover.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      if (wasOpen && restoreFocus && !trigger.disabled) trigger.focus({ preventScroll: true });
    }

    function update() {
      const context = getContext();
      const current = availability(context.segments, context.mode, context.status);
      trigger.disabled = !current.enabled;
      trigger.title = current.enabled ? `复制${current.label} · 选择 SRT 或 TXT` : current.message;
      trigger.setAttribute('aria-label', `复制${current.label}，选择 SRT 或 TXT${current.enabled ? '' : '，' + current.message}`);
      label.textContent = `复制当前内容 · ${current.label}`;
      note.textContent = current.message;
      choices.forEach(choice => { choice.disabled = !current.enabled; });
      if (!current.enabled) close();
    }

    trigger.addEventListener('click', () => {
      update();
      if (trigger.disabled) return;
      if (!popover.hidden) { close(); return; }
      popover.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      choices[0].focus();
    });
    anchor.addEventListener('keydown', event => {
      if (popover.hidden) return;
      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true); }
      else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        const index = choices.indexOf(document.activeElement);
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? choices.length - 1 : (index + (event.key === 'ArrowDown' ? 1 : choices.length - 1)) % choices.length;
        choices[next].focus();
      }
    });
    document.addEventListener('pointerdown', event => { if (!anchor.contains(event.target)) close(); });
    document.addEventListener('focusin', event => { if (!anchor.contains(event.target)) close(); });
    const controller = { update, close };
    anchor._freddieTranscriptCopy = controller;
    update();
    return controller;
  }

  return Object.freeze({ modeLabels, segmentText, srtTimestamp, formatTranscript, availability, mount });
});
