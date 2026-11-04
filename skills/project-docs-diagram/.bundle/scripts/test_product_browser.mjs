import assert from 'node:assert/strict';
import { test, before, after } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';
import { mkdir, access } from 'node:fs/promises';

import { launchBrowser, stable } from './product_browser.mjs';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const example = join(root, 'skills/project-docs-product/assets/examples/prototype.html');


let browser;
before(async () => {
  await access(example);
  browser = await launchBrowser();
});
after(async () => { await browser?.close(); });

async function session(t) {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  t.after(async () => { assert.deepEqual(errors, []); await page.close(); });
  await page.setViewport({ width: 1440, height: 1000 });
  await page.goto(pathToFileURL(example).href);
  assert.ok(await page.$('#create-request'), 'A complete workflow needs an actual create entry and shared request list');
  return page;
}
const text = (page, selector) => page.$eval(selector, node => node.textContent);
const disabled = (page, selector) => page.$eval(selector, node => node.disabled);
async function fill(page, selector, value) {
  await page.$eval(selector, (node, input) => { node.value = input; node.dispatchEvent(new Event('input', { bubbles: true })); }, value);
}
async function create(page, amount, customer = '旅程验收用户') {
  await page.click('#create-request');
  await fill(page, '#order-id', 'OD-JOURNEY');
  await fill(page, '#customer', customer);
  await fill(page, '#amount', amount);
  await fill(page, '#request-reason', '商品退货，演示申请');
  await page.click('#create-submit');
}
async function role(page, value) { await page.select('#role-select', value); }

test('note counter explains emoji, trims consistently and preserves over-limit input', async t => {
  const page = await session(t);
  await page.click('#create-request');
  assert.match(await text(page, '#note-help'), /普通汉字.*1.*表情.*2/);
  assert.equal(await text(page, '#note-count'), '已用 0 / 200');
  await fill(page, '#request-note', '  ' + '😀'.repeat(100) + '  ');
  assert.equal(await text(page, '#note-count'), '已用 200 / 200');
  await fill(page, '#order-id', 'OD-COUNT');
  await fill(page, '#customer', '计数用户');
  await fill(page, '#amount', '100');
  await fill(page, '#request-reason', '说明');
  await page.focus('#request-note');
  await page.keyboard.press('End');
  await page.keyboard.type('A');
  assert.equal(await text(page, '#note-count'), '已用 203 / 200，超出 3');
  await page.click('#create-submit');
  assert.match(await text(page, '#create-error'), /超出 3/);
  assert.equal(await page.$eval('#request-note', node => node.value), '  ' + '😀'.repeat(100) + '  A');
  await fill(page, '#request-note', '😀'.repeat(100));
  await page.click('#create-submit');
  assert.equal(await text(page, '#detail-note'), '😀'.repeat(100));
  await page.click('#create-request');
  assert.equal(await text(page, '#note-count'), '已用 0 / 200');
});

test('scenario entries navigate shared records without executing business actions', async t => {
  const page = await session(t);
  await page.click('#journey-guide summary');
  await page.click('[data-guide="reject"]');
  assert.match(await text(page, '#guide-instructions'), /审批人.*拒绝.*已拒绝/);
  await page.click('#guide-start');
  assert.equal(await text(page, '#detail-id'), 'RF-001');
  assert.match(await text(page, '#detail-status'), /待审批/);
  assert.equal(await page.$eval('#role-select', node => node.value), 'approver');
  assert.equal(await page.$eval('#history-list', node => node.children.length), 2);
  await page.click('#guide-exit');
  assert.equal(await page.$eval('#journey-guide', node => node.open), false);
  assert.match(await text(page, '#detail-status'), /待审批/);
  await page.click('#journey-guide summary');
  await page.click('[data-guide="retry"]');
  await page.click('#guide-start');
  assert.equal(await text(page, '#detail-id'), 'RF-002');
  await page.click('#simulate-failure');
  await page.click('#retry-request');
  await page.click('#simulate-success');
  assert.match(await text(page, '#detail-status'), /退款成功/);
  await page.click('[data-guide="auto"]');
  await page.click('#guide-start');
  assert.equal(await page.$eval('#request-dialog', node => node.open), true);
  assert.equal(await text(page, '#metric-total'), '3');
  await page.click('#create-cancel');
  await page.click('#reset-demo');
  assert.equal(await page.$eval('#journey-guide', node => node.open), false);
  await page.click('#journey-guide summary');
  await page.click('[data-guide="retry"]');
  await page.click('#guide-start');
  assert.equal(await text(page, '#detail-id'), 'RF-002');
});

test('mobile puts the first business record within the initial viewport', async t => {
  const page = await session(t);
  await page.setViewport({ width: 390, height: 844 });
  const box = await page.$eval('#request-table tbody tr', node => node.getBoundingClientRect().toJSON());
  assert.ok(box.top < 800, `first record begins at ${box.top}`);
  const actionBottom = await page.$eval('#request-table [data-open]', node => node.getBoundingClientRect().bottom);
  assert.ok(actionBottom <= 844, `first detail action ends at ${actionBottom}`);
  assert.equal(await page.$eval('#journey-guide', node => node.open), false);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
});

test('guide with no matching request reports recovery without creating or resetting data', async t => {
  const page = await session(t);
  await page.click('#journey-guide summary');
  await page.click('[data-guide="reject"]');
  await page.click('#guide-start');
  await page.type('#rejection-reason', '模拟拒绝');
  await page.click('#reject-request');
  const history = await text(page, '#history-list');
  await page.click('#guide-start');
  assert.match(await text(page, '#guide-instructions'), /没有适用.*创建.*重置/);
  assert.equal(await text(page, '#metric-total'), '3');
  assert.equal(await text(page, '#history-list'), history);
  assert.match(await text(page, '#detail-status'), /已拒绝/);
  await page.focus('#guide-exit');
  await page.keyboard.press('Enter');
  assert.equal(await page.$eval('#journey-guide', node => node.open), false);
  assert.equal(await page.$eval('#journey-guide summary', node => node === document.activeElement), true);
});

test('renamed field labels remain consistent in mobile cards and current-version chrome', async t => {
  const page = await session(t);
  await page.setViewport({ width: 390, height: 844 });
  const label = await page.$eval('#request-table tbody td:nth-child(2)', node => getComputedStyle(node, '::before').content);
  assert.match(label, /客户 \/ 企业名称/);
  assert.match(await text(page, '.footer-version'), /02/);
  assert.ok(await page.$('#requests-view .mobile-change-note'), 'list changes must survive the clipped mobile table header');
  assert.equal(await page.$eval('#requests-view .mobile-change-note', node => getComputedStyle(node).display), 'none');
  await page.click('#review-mode');
  for (const view of ['requests', 'approvals']) {
    if (view === 'approvals') { await role(page, 'approver'); await page.click('[data-view="approvals"]'); }
    const note = `#${view}-view .mobile-change-note`;
    await page.waitForSelector(note, { visible: true });
    assert.match(await text(page, note), /修改.*客户.*客户.*企业名称/);
    assert.ok(await page.$(`${note} a[href*="fr-001"]`));
    if (process.env.PRODUCT_SCREENSHOT_DIR) {
      await mkdir(process.env.PRODUCT_SCREENSHOT_DIR, { recursive: true });
      await stable(page);
      await page.screenshot({ path: join(process.env.PRODUCT_SCREENSHOT_DIR, `changes-${view}-mobile.png`), fullPage: true });
    }
  }
});

test('business pages and annotated field changes share the complete refund journey', async t => {
  const page = await session(t);
  assert.deepEqual(await page.$$eval('[data-page]', nodes => nodes.map(node => node.dataset.page).sort()),
    ['approvals', 'create', 'detail', 'requests', 'settings']);
  assert.ok(await page.$('#review-mode'), 'review mode must be available without replacing business pages');
  await page.click('#request-table [data-open="RF-001"]');
  assert.match(await text(page, '#detail-note'), /历史申请未提供/);
  await page.click('#back-to-list');
  await page.click('#create-request');
  await fill(page, '#order-id', 'OD-CHANGE');
  await fill(page, '#customer', '变更核对企业');
  await fill(page, '#amount', '500');
  await fill(page, '#request-reason', '正常退款');
  await fill(page, '#request-note', '跨页面保留的补充说明');
  if (process.env.PRODUCT_SCREENSHOT_DIR) {
    await mkdir(process.env.PRODUCT_SCREENSHOT_DIR, { recursive: true });
    await stable(page);
    await page.screenshot({ path: join(process.env.PRODUCT_SCREENSHOT_DIR, 'changes-clean.png'), fullPage: true });
  }
  await page.click('#review-create');
  assert.equal(await page.$eval('#request-note', node => node.value), '跨页面保留的补充说明');
  assert.equal(await page.$eval('#review-mode', node => node.getAttribute('aria-pressed')), 'true');
  for (const kind of ['added', 'modified']) {
    assert.ok(await page.$(`#request-dialog [data-change="${kind}"] .change-note`));
  }
  assert.match(await text(page, '#request-dialog [data-change="modified"] .change-note'), /客户.*客户.*企业/);
  if (process.env.PRODUCT_SCREENSHOT_DIR) {
    await stable(page);
    await page.screenshot({ path: join(process.env.PRODUCT_SCREENSHOT_DIR, 'changes-annotated.png'), fullPage: true });
  }
  await page.click('#create-submit');
  const id = (await text(page, '#detail-id')).trim();
  assert.equal(await text(page, '#detail-note'), '跨页面保留的补充说明');
  await page.click('#review-mode');
  assert.match(await text(page, '#detail-status'), /待审批/);
  assert.equal(await page.$eval('#detail-view .change-note', node => getComputedStyle(node).display), 'none');
  await role(page, 'approver');
  await page.click('#back-to-list');
  await page.click('[data-view="approvals"]');
  await page.click(`#approval-table [data-open="${id}"]`);
  assert.equal(await text(page, '#detail-note'), '跨页面保留的补充说明');
  await page.click('#approve-request');
  await page.click('#simulate-failure');
  await page.click('#retry-request');
  await page.click('#simulate-success');
  assert.match(await text(page, '#detail-status'), /退款成功/);
  assert.equal(await text(page, '#detail-note'), '跨页面保留的补充说明');
});

test('new optional field preserves over-limit input, empty values and narrow-screen annotations', async t => {
  const page = await session(t);
  await page.setViewport({ width: 390, height: 844 });
  await create(page, '200');
  assert.equal(await text(page, '#detail-note'), '未填写');
  await page.click('#back-to-list');
  await page.click('#create-request');
  await fill(page, '#order-id', 'OD-NOTE');
  await fill(page, '#customer', '客户');
  await fill(page, '#amount', '200');
  await fill(page, '#request-reason', '退款');
  assert.ok(await page.$('#request-note'), 'new field must be an actual editable control');
  await page.type('#request-note', '长'.repeat(201));
  const count = await text(page, '#metric-total');
  await page.click('#review-create');
  if (process.env.PRODUCT_SCREENSHOT_DIR) {
    await stable(page);
    await page.screenshot({ path: join(process.env.PRODUCT_SCREENSHOT_DIR, 'changes-mobile.png'), fullPage: true });
  }
  await page.click('#create-submit');
  assert.match(await text(page, '#create-error'), /补充说明.*200/);
  assert.equal(await page.$eval('#request-note', node => node.value.length), 201);
  assert.equal(await text(page, '#metric-total'), count);
  await page.focus('#request-note');
  await page.keyboard.press('End');
  await page.keyboard.press('Backspace');
  await page.click('#create-submit');
  assert.equal((await text(page, '#detail-note')).length, 200);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
});

test('complete journey shares one request across list, approval, execution failure, retry and history', async t => {
  const page = await session(t);
  assert.match(await text(page, '#prototype-notice'), /模拟/);
  await fill(page, '#search', 'OD-20261021-081');
  assert.equal(await page.$$eval('#request-table tbody [data-request-id]', rows => rows.length), 1);
  await page.click('#request-table [data-open="RF-001"]');
  assert.equal((await text(page, '#detail-id')).trim(), 'RF-001');
  assert.equal(await text(page, '#detail-order'), 'OD-20261021-081');
  await page.click('#back-to-list');
  await fill(page, '#search', '');
  await create(page, '500');
  const id = (await text(page, '#detail-id')).trim();
  assert.match(await text(page, '#detail-status'), /待审批/);
  assert.equal(await disabled(page, '#approve-request'), true);
  // An action guard must survive a stale or tampered visual disabled state.
  await page.$eval('#approve-request', node => node.disabled = false);
  await page.click('#approve-request');
  assert.match(await text(page, '#detail-status'), /待审批/);
  assert.match(await text(page, '#action-error'), /审批人/);
  await role(page, 'approver');
  assert.equal(await disabled(page, '#create-request'), true);
  await page.$eval('#create-request', node => node.disabled = false);
  await page.click('#create-request');
  assert.equal(await page.$eval('#request-dialog', node => node.open), false);
  await page.click('#back-to-list');
  await page.click('[data-view="approvals"]');
  await page.click(`#approval-table [data-open="${id}"]`);
  await page.click('#approve-request');
  assert.match(await text(page, '#detail-status'), /退款处理中/);
  assert.equal((await text(page, '#metric-pending')).trim(), '1');
  assert.equal(await disabled(page, '#approve-request'), true);
  await page.click('#simulate-failure');
  assert.match(await text(page, '#detail-status'), /执行失败/);
  await page.click('#retry-request');
  assert.match(await text(page, '#detail-status'), /退款处理中/);
  await page.click('#simulate-success');
  assert.match(await text(page, '#detail-status'), /退款成功/);
  assert.equal(await disabled(page, '#retry-request'), true);
  assert.equal(await disabled(page, '#simulate-success'), true);
  await page.click('#show-history');
  const history = await text(page, '#history-list');
  let previous = -1;
  for (const action of ['创建申请', '审批通过', '执行失败', '重试', '退款成功']) {
    const position = history.indexOf(action); assert.ok(position > previous, action); previous = position;
  }
  if (process.env.PRODUCT_SCREENSHOT_DIR) {
    await mkdir(process.env.PRODUCT_SCREENSHOT_DIR, { recursive: true });
    await stable(page);
    await page.screenshot({ path: join(process.env.PRODUCT_SCREENSHOT_DIR, 'product-detail.png'), fullPage: true });
  }
  await page.click('#back-to-list');
  await page.click('[data-view="requests"]');
  assert.match(await text(page, `#request-table [data-request-id="${id}"]`), /退款成功/);
  assert.match(await text(page, '#request-table [data-request-id="RF-001"]'), /待审批/);
  await page.click('[data-view="approvals"]');
  assert.equal(await page.$(`#approval-table [data-request-id="${id}"]`), null);
});

test('input boundaries, cancellation, rejection and safe rendering preserve request state', async t => {
  const page = await session(t);
  const initial = await text(page, '#metric-total');
  await page.click('#create-request');
  assert.equal(await page.$eval('#order-id', node => document.activeElement === node), true);
  await page.keyboard.press('Escape');
  assert.equal(await text(page, '#metric-total'), initial);
  await page.click('#create-request');
  for (const [selector, value] of [['#order-id', 'ORDER'], ['#customer', '客户'], ['#request-reason', '原因'], ['#amount', '200']]) await fill(page, selector, value);
  for (const selector of ['#order-id', '#customer', '#request-reason']) {
    await fill(page, selector, ''); await page.click('#create-submit');
    assert.ok((await text(page, '#create-error')).trim());
    assert.equal(await text(page, '#metric-total'), initial);
    await fill(page, selector, '恢复有效文本');
  }
  await page.click('#create-cancel');
  for (const amount of ['', '0', '-1', '1.234', '1e3', '9007199254740992']) {
    await create(page, amount);
    assert.ok((await text(page, '#create-error')).trim(), `Must reject ${amount}`);
    assert.equal(await text(page, '#metric-total'), initial);
    await page.click('#create-cancel');
  }
  await create(page, '0.01', '<img src=x onerror=alert(1)>');
  assert.match(await text(page, '#detail-status'), /退款处理中/);
  assert.equal(await text(page, '#detail-customer'), '<img src=x onerror=alert(1)>');
  assert.equal(await page.$('#detail-customer img'), null);
  await page.click('#back-to-list');
  await create(page, '499.99');
  assert.match(await text(page, '#detail-status'), /退款处理中/);
  await page.click('#back-to-list');
  await create(page, '500.01');
  await role(page, 'approver');
  await page.click('#reject-request');
  assert.match(await text(page, '#action-error'), /原因/);
  assert.match(await text(page, '#detail-status'), /待审批/);
  await fill(page, '#rejection-reason', '订单尚未完成退货');
  await page.click('#reject-request');
  assert.match(await text(page, '#detail-status'), /已拒绝/);
  assert.equal(await disabled(page, '#approve-request'), true);
  assert.equal(await disabled(page, '#simulate-success'), true);
  await page.click('#show-history');
  assert.match(await text(page, '#history-list'), /订单尚未完成退货/);
  await page.click('#back-to-list');
  await page.click('[data-view="requests"]');
  await fill(page, '#search', '不存在的申请');
  assert.match(await text(page, '#request-table'), /没有符合条件/);
  await fill(page, '#search', '');
  await page.select('#status-filter', 'rejected');
  assert.equal(await page.$$eval('#request-table tbody [data-request-id]', rows => rows.length), 1);
});

test('rule changes affect only new requests, reset restores seeds, and narrow screens remain usable', async t => {
  const page = await session(t);
  await create(page, '800');
  const pendingId = (await text(page, '#detail-id')).trim();
  await page.click('#settings-button');
  await fill(page, '#threshold-value', '0');
  await page.click('#save-settings');
  assert.ok((await text(page, '#settings-error')).trim());
  await fill(page, '#threshold-value', '1000');
  await page.click('#save-settings');
  assert.match(await text(page, '#detail-status'), /待审批/);
  await page.click('#back-to-list');
  await create(page, '800');
  assert.match(await text(page, '#detail-status'), /退款处理中/);
  await page.click('#back-to-list');
  await create(page, '1000');
  assert.match(await text(page, '#detail-status'), /待审批/);
  await page.click('#back-to-list');
  assert.match(await text(page, `#request-table [data-request-id="${pendingId}"]`), /待审批/);
  const beforeReset = await text(page, '#metric-total');
  page.removeAllListeners('dialog');
  page.once('dialog', dialog => dialog.dismiss());
  await page.click('#reset-demo');
  assert.equal(await text(page, '#metric-total'), beforeReset);
  page.on('dialog', dialog => dialog.accept());
  await role(page, 'approver');
  await page.click('#reset-demo');
  assert.equal((await text(page, '#metric-total')).trim(), '3');
  assert.equal(await page.$eval('#role-select', node => node.value), 'support');
  await page.click('#settings-button');
  assert.equal(await page.$eval('#threshold-value', node => node.value), '500.00');
  await page.click('#cancel-settings');
  await page.setViewport({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await create(page, '200');
  assert.match(await text(page, '#detail-status'), /退款处理中/);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.click('#back-to-list');
  if (process.env.PRODUCT_SCREENSHOT_DIR) {
    await mkdir(process.env.PRODUCT_SCREENSHOT_DIR, { recursive: true });
    await stable(page);
    await page.screenshot({ path: join(process.env.PRODUCT_SCREENSHOT_DIR, 'product-mobile.png'), fullPage: true });
    await page.setViewport({ width: 1440, height: 1000 });
    await stable(page);
    await page.screenshot({ path: join(process.env.PRODUCT_SCREENSHOT_DIR, 'product-desktop.png'), fullPage: true });
  }
});

test('automatic approval reaches a terminal result and rejects stale terminal actions', async t => {
  const page = await session(t);
  await create(page, '200');
  const id = (await text(page, '#detail-id')).trim();
  assert.match(await text(page, '#detail-status'), /退款处理中/);
  await role(page, 'approver');
  await page.click('#simulate-success');
  assert.match(await text(page, '#detail-status'), /退款成功/);
  await page.click('#show-history');
  const history = await text(page, '#history-list');
  for (const selector of ['#approve-request', '#simulate-success', '#retry-request']) {
    await page.$eval(selector, node => node.disabled = false);
    await page.click(selector);
    assert.match(await text(page, '#detail-status'), /退款成功/);
    assert.match(await text(page, '#action-error'), /当前状态/);
    assert.equal(await text(page, '#history-list'), history);
  }
  await page.click('#back-to-list');
  assert.match(await text(page, `#request-table [data-request-id="${id}"]`), /退款成功/);
});

test('mobile entry stays visible and keyboard focus follows state transitions', async t => {
  const page = await session(t);
  await page.setViewport({ width: 390, height: 844 });
  const geometry = await page.$eval('#request-table [data-open="RF-001"]', node => {
    const box = node.getBoundingClientRect(); const table = node.closest('.table-wrap');
    return { left: box.left, right: box.right, width: innerWidth, scrolled: table.scrollLeft, fits: table.scrollWidth <= table.clientWidth };
  });
  assert.ok(geometry.fits && geometry.left >= 0 && geometry.right <= geometry.width && geometry.scrolled === 0, JSON.stringify(geometry));
  await page.click('#request-table [data-open="RF-001"]');
  await role(page, 'approver');
  for (const reason of ['', 'x'.repeat(201)]) {
    await fill(page, '#rejection-reason', reason);
    await page.focus('#reject-request'); await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'rejection-reason');
    assert.match(await text(page, '#detail-status'), /待审批/);
  }
  await fill(page, '#rejection-reason', '');
  await page.focus('#approve-request');
  await page.keyboard.press('Enter');
  assert.match(await text(page, '#detail-status'), /退款处理中/);
  assert.equal(await page.evaluate(() => document.activeElement.id), 'detail-status');
  await page.focus('#simulate-failure'); await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'detail-status');
  await page.focus('#retry-request'); await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'detail-status');
  await page.focus('#back-to-list'); await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'page-title');
  await role(page, 'support');
  await page.focus('#create-request'); await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'order-id');
  await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'create-request');
  await page.click('#create-request'); await page.click('#create-submit');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'order-id');
  await page.click('#create-cancel');
  await page.click('#settings-button'); await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'settings-button');
});

test('small table and progress text meets contrast and screenshots wait for animation', async t => {
  const page = await session(t);
  await page.click('#request-table [data-open="RF-001"]');
  const contrast = await page.evaluate(() => {
    const luminance = rgb => rgb.map(x => { const c = x / 255; return c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4; }).reduce((sum, c, i) => sum + c * [.2126, .7152, .0722][i], 0);
    for (const status of ['pending','processing','refunded','failed','rejected']) {
      const probe = document.createElement('span'); probe.className = 'badge ' + status; probe.id = 'contrast-' + status; probe.textContent = status; document.body.append(probe);
    }
    return ['#stepper span:last-child', '.role-field', '.detail-notice', '.footer-version', ...['pending','processing','refunded','failed','rejected'].map(status => '#contrast-' + status)].map(selector => {
      const node = document.querySelector(selector); const style = getComputedStyle(node);
      let parent = node; let background;
      do { background = getComputedStyle(parent).backgroundColor; parent = parent.parentElement; } while (background === 'rgba(0, 0, 0, 0)' && parent);
      const foreground = luminance(style.color.match(/[\d.]+/g).slice(0, 3).map(Number));
      const back = luminance(background.match(/[\d.]+/g).slice(0, 3).map(Number));
      return { selector, ratio: (Math.max(foreground, back) + .05) / (Math.min(foreground, back) + .05) };
    });
  });
  for (const value of contrast) assert.ok(value.ratio >= 4.5, JSON.stringify(value));
  await stable(page);
  assert.equal(await page.evaluate(() => document.getAnimations().filter(animation => animation.playState === 'running').length), 0);
});

test('oversized keyboard input remains intact until validation and can be corrected', async t => {
  const page = await session(t);
  const initial = await text(page, '#metric-total');
  await page.click('#create-request');
  for (const [selector, value] of [['#order-id', 'ORDER'], ['#customer', '客户'], ['#request-reason', '原因'], ['#amount', '500']]) await fill(page, selector, value);
  async function typeAll(selector, value) {
    await page.$eval(selector, node => { node.focus(); node.select(); });
    await page.keyboard.press('Backspace');
    await page.type(selector, value);
  }
  for (const [selector, limit] of [['#order-id', 40], ['#customer', 40], ['#request-reason', 200]]) {
    const oversized = 'x'.repeat(limit + 1);
    await typeAll(selector, oversized);
    assert.equal(await page.$eval(selector, node => node.value), oversized, 'Native input must not silently truncate text');
    await page.click('#create-submit');
    assert.equal(await text(page, '#metric-total'), initial);
    assert.ok((await text(page, '#create-error')).trim());
    assert.equal(await page.$eval(selector, node => node.value), oversized);
    assert.equal(await page.evaluate(() => document.activeElement.id), selector.slice(1));
    await typeAll(selector, 'x'.repeat(limit));
  }
  await typeAll('#order-id', '😀'.repeat(21));
  await page.click('#create-submit');
  assert.equal(await text(page, '#metric-total'), initial);
  assert.equal(await page.$eval('#order-id', node => node.value), '😀'.repeat(21));
  await typeAll('#order-id', '😀'.repeat(20));
  await page.click('#create-submit');
  assert.equal((await text(page, '#detail-order')).trim(), '😀'.repeat(20));
  assert.match(await text(page, '#detail-status'), /待审批/);
  await role(page, 'approver');
  await typeAll('#rejection-reason', '理'.repeat(201));
  await page.click('#reject-request');
  assert.match(await text(page, '#action-error'), /200/);
  assert.match(await text(page, '#detail-status'), /待审批/);
  assert.equal(await page.$eval('#rejection-reason', node => node.value), '理'.repeat(201));
  await typeAll('#rejection-reason', '理'.repeat(200));
  await page.click('#reject-request');
  assert.match(await text(page, '#detail-status'), /已拒绝/);
  await page.click('#show-history');
  assert.ok((await text(page, '#history-list')).includes('理'.repeat(200)));
});
