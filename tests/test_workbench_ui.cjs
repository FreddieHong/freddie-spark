/* Run with Node + Playwright. Exercises the real frontend and local HTTP backend. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const { formatTranscript } = require('../frontend/transcript-copy.js');

async function main() {
  const root = path.resolve(__dirname, '..');
  const service = spawn(process.env.FREDDIE_TEST_PYTHON || 'python3', ['tests/ui_fixture.py'], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  let browser;
  let serviceError = '';
  service.stderr.on('data', bytes => { serviceError += bytes; });
  try {
    const url = await new Promise((resolve, reject) => {
      let pending = '';
      const timer = setTimeout(() => reject(new Error(`UI fixture startup timed out: ${serviceError}`)), 10000);
      service.stdout.on('data', bytes => {
        pending += bytes;
        if (pending.includes('\n')) { clearTimeout(timer); resolve(JSON.parse(pending.split('\n')[0]).url); }
      });
      service.once('exit', code => { clearTimeout(timer); reject(new Error(`UI fixture exit ${code}: ${serviceError}`)); });
    });
    browser = await chromium.launch({ channel: 'chrome', headless: true });
    const context = await browser.newContext({ viewport: { width: 1280, height: 850 }, permissions: ['clipboard-read', 'clipboard-write'] });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(url);
    await page.locator('#copy-transcript-button').waitFor({ state: 'attached' });
    await page.locator('#library-button').click();
    await page.locator('.library-item').click();
    await page.locator('.transcript-row').first().waitFor();
    const project = await page.evaluate(async () => (await (await fetch('/api/projects/ui-check')).json()).project);

    // The two columns must be independently scrollable; HTML/body stay fixed.
    const layout = await page.evaluate(() => {
      const left = document.getElementById('source-column');
      const transcript = document.getElementById('transcript');
      const reader = document.querySelector('.reader-column');
      return {
        summaryInsideLeft: left.contains(document.querySelector('.summary-column')),
        readerOnRight: reader.getBoundingClientRect().left > left.getBoundingClientRect().right,
        leftScrolls: left.scrollHeight > left.clientHeight,
        rightScrolls: transcript.scrollHeight > transcript.clientHeight,
        noDocumentScroll: document.documentElement.scrollHeight <= innerHeight + 1,
        noHorizontalOverflow: document.documentElement.scrollWidth <= innerWidth,
      };
    });
    Object.entries(layout).forEach(([label, value]) => assert.equal(value, true, label));
    await page.locator('#video').evaluate(video => { video.muted = true; });
    await page.locator('#play-button').click();
    await page.waitForFunction(() => !document.getElementById('video').paused && document.getElementById('video').currentTime > .1);
    const before = await page.evaluate(() => ({ time: document.getElementById('video').currentTime, left: document.getElementById('source-column').scrollTop, videoTop: document.getElementById('player').getBoundingClientRect().top }));
    await page.locator('#transcript').hover();
    await page.mouse.wheel(0, 520);
    await page.waitForFunction(() => document.getElementById('transcript').scrollTop > 200);
    const afterRight = await page.evaluate(() => ({ time: document.getElementById('video').currentTime, paused: document.getElementById('video').paused, left: document.getElementById('source-column').scrollTop, right: document.getElementById('transcript').scrollTop, videoTop: document.getElementById('player').getBoundingClientRect().top }));
    assert.equal(afterRight.paused, false);
    assert.ok(afterRight.time > before.time);
    assert.equal(afterRight.left, before.left);
    assert.equal(afterRight.videoTop, before.videoTop);
    await page.locator('#source-column').hover();
    await page.mouse.wheel(0, 640);
    await page.waitForFunction(() => document.getElementById('source-column').scrollTop > 200);
    const afterLeft = await page.evaluate(() => ({ left: document.getElementById('source-column').scrollTop, right: document.getElementById('transcript').scrollTop, paused: document.getElementById('video').paused }));
    assert.equal(afterLeft.right, afterRight.right);
    assert.equal(afterLeft.paused, false);
    assert.ok(afterLeft.left > 200);
    await page.waitForTimeout(2800); // A real poll must preserve both scroll positions and playing video.
    const afterPoll = await page.evaluate(() => ({ left: document.getElementById('source-column').scrollTop, right: document.getElementById('transcript').scrollTop, paused: document.getElementById('video').paused }));
    assert.deepEqual(afterPoll, afterLeft);
    await page.locator('#play-button').click();

    // Read the real browser clipboard for every tab/format combination.
    for (const mode of ['original', 'bilingual', 'chinese']) {
      await page.locator(`#tab-${mode}`).click();
      for (const format of ['srt', 'txt']) {
        await page.locator('#copy-transcript-button').click();
        assert.equal(await page.locator('#transcript-copy-popover').isVisible(), true);
        await page.locator(`[data-copy-format="${format}"]`).click();
        const copied = await page.evaluate(() => navigator.clipboard.readText());
        assert.equal(copied, formatTranscript(project.segments, mode, format));
      }
    }
    await page.locator('#copy-transcript-button').click();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#transcript-copy-popover').isVisible(), false);

    // A native copy message must take priority over browser permissions.
    await page.evaluate(() => { window.webkit = { messageHandlers: { freddie: { postMessage(message) { window.nativeCopyCheck = message; } } } }; });
    await page.locator('#tab-original').click();
    await page.locator('#copy-transcript-button').click();
    await page.locator('[data-copy-format="txt"]').click();
    const native = await page.evaluate(() => window.nativeCopyCheck);
    assert.equal(native.action, 'copy');
    assert.equal(native.text, formatTranscript(project.segments, 'original', 'txt'));
    await page.evaluate(() => { delete window.webkit; });

    // Minimum desktop window, then narrow/mobile fallback: no hidden actions or page clipping.
    for (const viewport of [{ width: 920, height: 620 }, { width: 320, height: 740 }]) {
      await page.setViewportSize(viewport);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      assert.equal(await page.locator('#copy-transcript-button').isVisible(), true);
      if (viewport.width > 760) {
        assert.ok(await page.locator('#transcript').evaluate(el => el.clientHeight) > 120);
        assert.equal(await page.evaluate(() => document.documentElement.scrollHeight <= innerHeight + 1), true);
      }
    }
    await page.setViewportSize({ width: 1440, height: 960 });
    await page.locator('#workspace-button').click();
    await page.waitForTimeout(500);
    await page.locator('#tab-bilingual').click();
    await page.locator('#toast').waitFor({ state: 'hidden' });
    await page.locator('#copy-transcript-button').click();
    await fs.mkdir(path.join(root, 'build/screenshots'), { recursive: true });
    await page.screenshot({ path: path.join(root, 'build/screenshots/freddie-spark-1.1.png') });
    assert.deepEqual(errors, []);
    console.log('PASS: actual clipboard × 6, native bridge, independent wheel scrolling, uninterrupted playback, polling preservation, small-window layout, keyboard dismissal.');
    console.log('Screenshot: build/screenshots/freddie-spark-1.1.png');
    await context.close();
  } finally {
    if (browser) await browser.close();
    service.kill('SIGTERM');
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
