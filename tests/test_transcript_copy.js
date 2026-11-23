'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const copy = require('../frontend/transcript-copy.js');

const segments = [
  { id: 7, start: 1.125, end: 3.789, text: 'Hello, world.', translation: '你好，世界。' },
  { id: 29, start: 3600.001, end: 3602.5, text: 'We are learning.', translation: '我们正在学习。' },
];

const expected = {
  original: ['Hello, world.', 'We are learning.'],
  bilingual: ['Hello, world.\n你好，世界。', 'We are learning.\n我们正在学习。'],
  chinese: ['你好，世界。', '我们正在学习。'],
};

for (const mode of ['original', 'bilingual', 'chinese']) {
  test(`${mode}: TXT contains only current-mode text, without title, indices or times`, () => {
    const result = copy.formatTranscript(segments, mode, 'txt');
    assert.equal(result, expected[mode].join('\n'));
    assert.doesNotMatch(result, /00:00|01:00| --> |^1\n|Freddie/);
    if (mode === 'chinese') assert.doesNotMatch(result, /Hello|learning/);
    if (mode === 'original') assert.doesNotMatch(result, /你好|学习/);
  });
  test(`${mode}: SRT has standard cues, consecutive indices and precise source times`, () => {
    assert.equal(copy.formatTranscript(segments, mode, 'srt'),
      `1\n00:00:01,125 --> 00:00:03,789\n${expected[mode][0]}\n\n2\n01:00:00,001 --> 01:00:02,500\n${expected[mode][1]}\n`);
  });
}

test('milliseconds round across minute/hour boundaries without losing long hours', () => {
  assert.equal(copy.srtTimestamp(59.9996), '00:01:00,000');
  assert.equal(copy.srtTimestamp(3599.9996), '01:00:00,000');
  assert.equal(copy.srtTimestamp(100 * 3600 + 62.007), '100:01:02,007');
  assert.equal(copy.srtTimestamp(0), '00:00:00,000');
});

test('empty cues are skipped and indices do not derive from source IDs', () => {
  const source = [{ start: null, end: null, text: '   ', translation: '\n' }, segments[0], { id: 'last', start: 4, end: 5, text: '\r\nDone\r\n', translation: '' }];
  const result = copy.formatTranscript(source, 'original', 'srt');
  assert.equal(result, '1\n00:00:01,125 --> 00:00:03,789\nHello, world.\n\n2\n00:00:04,000 --> 00:00:05,000\nDone\n');
});

test('partial Chinese copies only available Chinese, never original or placeholder text', () => {
  const partial = [segments[0], { start: 4, end: 5, text: 'English without translation.', translation: '' }, { start: 6, end: 7, text: 'More English.', translation: '更多内容。' }];
  const txt = copy.formatTranscript(partial, 'chinese', 'txt');
  assert.equal(txt, '你好，世界。\n更多内容。');
  assert.doesNotMatch(txt, /English|translation|暂无|准备中|未翻译/);
  const srt = copy.formatTranscript(partial, 'chinese', 'srt');
  assert.equal(srt, '1\n00:00:01,125 --> 00:00:03,789\n你好，世界。\n\n2\n00:00:06,000 --> 00:00:07,000\n更多内容。\n');
  assert.equal(copy.availability(partial, 'chinese', 'translating').partial, true);
});

test('partial bilingual preserves existing original and translations without generated placeholders', () => {
  const partial = [segments[0], { start: 4, end: 5, text: 'Untranslated source.', translation: '' }];
  assert.equal(copy.formatTranscript(partial, 'bilingual', 'txt'), 'Hello, world.\n你好，世界。\nUntranslated source.');
  assert.match(copy.availability(partial, 'bilingual', 'partial').message, /仅复制当前已有内容/);
});

test('without Chinese, Chinese copying is disabled and reports a clear reason', () => {
  const source = [{ start: 0, end: 1, text: 'Only English.', translation: '' }];
  assert.equal(copy.availability(source, 'chinese', 'translating').enabled, false);
  assert.match(copy.availability(source, 'chinese', 'translating').message, /中文翻译尚未生成/);
  assert.throws(() => copy.formatTranscript(source, 'chinese', 'txt'), /没有生成中文翻译/);
  assert.equal(copy.availability(source, 'bilingual', 'translating').enabled, true);
});

test('missing or invalid SRT timestamps throw, while TXT requires no time metadata', () => {
  for (const [start, end] of [[undefined, 1], [null, 1], ['', 1], ['0', 1], [NaN, 1], [Infinity, 1], [-1, 1], [1, 1], [2, 1], [0, Infinity], [0, 0.0001], [1e20, 1e21]]) {
    const source = [{ start, end, text: 'Valid content.', translation: '有效内容。' }];
    assert.throws(() => copy.formatTranscript(source, 'bilingual', 'srt'), /时间|有效范围/);
    assert.equal(copy.formatTranscript(source, 'bilingual', 'txt'), 'Valid content.\n有效内容。');
  }
});

test('time validation applies only to current-mode cues', () => {
  const source = [{ text: 'Untranslated English.', translation: '', start: null, end: null }, segments[0]];
  assert.equal(copy.formatTranscript(source, 'chinese', 'srt'), '1\n00:00:01,125 --> 00:00:03,789\n你好，世界。\n');
  assert.throws(() => copy.formatTranscript(source, 'original', 'srt'), /有效时间/);
});

test('SRT internal blank lines cannot accidentally create extra cues', () => {
  const source = [{ start: 0, end: 1, text: 'First\n\nSecond', translation: '第一\r\n\r\n第二' }];
  assert.equal(copy.formatTranscript(source, 'bilingual', 'srt'), '1\n00:00:00,000 --> 00:00:01,000\nFirst\nSecond\n第一\n第二\n');
});

test('formatting preserves source objects and rejects unknown modes or formats', () => {
  const before = JSON.stringify(segments);
  for (const mode of Object.keys(expected)) for (const format of ['txt', 'srt']) copy.formatTranscript(segments, mode, format);
  assert.equal(JSON.stringify(segments), before);
  assert.throws(() => copy.formatTranscript(segments, '__proto__', 'txt'), /阅读模式/);
  assert.throws(() => copy.formatTranscript(segments, 'chinese', 'md'), /复制格式/);
  assert.throws(() => copy.formatTranscript([], 'original', 'txt'), /没有可复制的原文/);
});

test('browser global loads without CommonJS or a DOM', () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../frontend/transcript-copy.js'), 'utf8'), context);
  assert.equal(typeof context.FreddieTranscriptCopy.formatTranscript, 'function');
  assert.equal(context.FreddieTranscriptCopy.formatTranscript(segments, 'chinese', 'txt'), '你好，世界。\n我们正在学习。');
});
