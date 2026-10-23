import assert from 'node:assert/strict';
import { test, before, after } from 'node:test';
import { launchBrowser, openPage, capture } from '../../../../../scripts/product_browser.mjs';

let browser;
before(async () => { browser = await launchBrowser(); });
after(async () => { await browser?.close(); });
const text = (page, selector) => page.$eval(selector, node => node.textContent);
async function fill(page, selector, value) {
  await page.$eval(selector, (node, input) => {
    node.value = input; node.dispatchEvent(new Event('input', { bubbles: true }));
  }, value);
}
async function session(t, mobile = false) {
  const page = await openPage(browser, 'prototype.html', { width: mobile ? 390 : 1280, height: mobile ? 844 : 900 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  t.after(async () => { assert.deepEqual(errors, []); await page.close(); });
  return page;
}
async function create(page) {
  await page.click('#new-request');
  await fill(page, '#resource', '  resource-a  ');
  await fill(page, '#reason', '  项目协作  ');
  await page.click('#submit-request');
  if (!await page.$eval('#simulate', node => node.open)) await page.click('#simulate summary');
  return text(page, '#request-id');
}
async function role(page, value) { await page.select('#role', value); }
async function screenshot(page, filename, actor, scenario) {
  if (process.env.PRODUCT_SCREENSHOT_DIR) await capture(page, filename, { role: actor, scenario });
}

test('AC-001/004/009/013/015: one application crosses roles and waits for an external result', async t => {
  const page = await session(t);
  const id = await create(page);
  assert.equal(await text(page, '#saved-resource'), 'resource-a');
  assert.equal(await text(page, '#saved-reason'), '项目协作');
  await role(page, 'manager'); await page.click('[data-view="tasks"]');
  assert.match(await text(page, '#records'), new RegExp(id));
  await page.click(`[data-open="${id}"]`);
  await page.click('#approve');
  assert.equal(await text(page, '#status'), '待开通');
  await page.click('[data-view="tasks"]');
  assert.doesNotMatch(await text(page, '#records'), new RegExp(id));
  await role(page, 'admin');
  await page.click(`[data-open="${id}"]`);
  await page.click('#execute');
  assert.equal(await text(page, '#status'), '开通中');
  assert.equal(await text(page, '#external-count'), '1');
  await screenshot(page, 'access-processing.png', '资源管理员', 'AC-009');
  await page.click('#external-success');
  assert.equal(await text(page, '#status'), '已开通');
  const history = await text(page, '#history');
  await page.evaluate(() => perform('success'));
  assert.equal(await text(page, '#history'), history);
  assert.equal(await text(page, '#external-count'), '1');
  await role(page, 'employee');
  assert.equal(await text(page, '#request-id'), id);
  assert.equal(await text(page, '#status'), '已开通');
  await page.click('[data-view="mine"]');
  assert.match(await text(page, '#records'), /已开通/);
  await page.click('[data-view="results"]');
  assert.match(await text(page, '#records'), /已开通/);
  await page.click(`[data-open="${id}"]`);
  assert.equal(await text(page, '#request-id'), id);
  assert.equal(await text(page, '#status'), '已开通');
});

test('AC-002/003: validation and submission failure retain input without creating tasks', async t => {
  const page = await session(t);
  await page.click('#new-request');
  await fill(page, '#resource', ' '); await fill(page, '#reason', '工作需要');
  await page.click('#submit-request');
  assert.match(await text(page, '#create-error'), /资源标识.*必填/);
  await fill(page, '#resource', 'resource-a'); await fill(page, '#reason', ' ');
  await page.click('#submit-request');
  assert.match(await text(page, '#create-error'), /申请理由.*必填/);
  await fill(page, '#reason', '长'.repeat(1001));
  await page.click('#fail-create'); await page.click('#submit-request');
  assert.match(await text(page, '#create-error'), /失败.*保留/);
  assert.equal(await page.$eval('#reason', node => node.value.length), 1001);
  assert.equal(await page.$$eval('[data-open]', nodes => nodes.length), 0);
  await page.click('#submit-request');
  assert.equal(await text(page, '#saved-reason'), '长'.repeat(1001));
  await role(page, 'manager'); await page.click('[data-view="tasks"]');
  assert.equal(await page.$$eval('[data-open]', nodes => nodes.length), 1);
});

test('AC-005/006/012: self approval, failure, rejection and repeated decisions preserve the correct state', async t => {
  const page = await session(t);
  await create(page);
  await page.evaluate(() => perform('approve'));
  assert.equal(await text(page, '#status'), '待审批');
  assert.match(await text(page, '#action-error'), /角色|权限/);
  await role(page, 'manager');
  await page.click('#reject');
  assert.match(await text(page, '#action-error'), /拒绝原因/);
  await fill(page, '#rejection', '资料不足');
  await page.click('#fail-action'); await page.click('#reject');
  assert.equal(await text(page, '#status'), '待审批');
  await page.click('#reject');
  assert.equal(await text(page, '#status'), '已拒绝');
  assert.match(await text(page, '#history'), /资料不足/);
  const history = await text(page, '#history');
  await page.evaluate(() => perform('approve'));
  await page.evaluate(() => perform('reject'));
  assert.equal(await text(page, '#status'), '已拒绝');
  assert.equal(await text(page, '#history'), history);
  await role(page, 'employee');
  assert.match(await text(page, '#outcome'), /资料不足/);
});

test('AC-007/008/012: withdrawal blocks stale approval; approved applications cannot be withdrawn', async t => {
  const page = await session(t);
  await create(page); await page.click('#withdraw');
  assert.equal(await text(page, '#status'), '已撤回');
  await role(page, 'manager'); await page.evaluate(() => perform('approve'));
  assert.equal(await text(page, '#status'), '已撤回');
  await role(page, 'employee'); await create(page);
  await role(page, 'manager'); await page.click('#approve');
  await role(page, 'employee'); await page.evaluate(() => perform('withdraw'));
  assert.equal(await text(page, '#status'), '待开通');
  await role(page, 'other'); await page.evaluate(() => perform('withdraw'));
  assert.equal(await text(page, '#status'), '待开通');
});

test('AC-010/011/013/014: execution failure, failure results and retry have a reachable recovery path', async t => {
  const page = await session(t);
  const id = await create(page);
  await role(page, 'admin'); await page.evaluate(() => perform('execute'));
  assert.equal(await text(page, '#status'), '待审批');
  assert.equal(await text(page, '#external-count'), '0');
  await role(page, 'manager'); await page.click('#approve');
  await page.evaluate(() => perform('execute'));
  assert.equal(await text(page, '#external-count'), '0');
  await role(page, 'admin'); await page.click('#fail-action'); await page.click('#execute');
  assert.equal(await text(page, '#status'), '待开通');
  assert.equal(await text(page, '#external-count'), '0');
  await page.click('#execute'); await page.evaluate(() => perform('execute'));
  assert.equal(await text(page, '#external-count'), '1');
  await page.click('#external-failure');
  assert.equal(await text(page, '#status'), '开通失败');
  await page.click('[data-view="tasks"]');
  assert.match(await text(page, '#records'), new RegExp(id));
  await page.click(`[data-open="${id}"]`);
  await screenshot(page, 'access-retry.png', '资源管理员', 'AC-010');
  await page.click('#fail-action'); await page.click('#retry');
  assert.equal(await text(page, '#status'), '开通失败');
  assert.equal(await text(page, '#external-count'), '1');
  await page.click('#retry');
  assert.equal(await text(page, '#status'), '开通中');
  assert.equal(await text(page, '#external-count'), '2');
  await page.click('#external-success');
  assert.equal(await text(page, '#status'), '已开通');
  await page.evaluate(() => perform('execute'));
  assert.equal(await text(page, '#external-count'), '2');
});

test('keyboard and narrow viewport can create, cancel and follow a result without horizontal overflow', async t => {
  const page = await session(t, true);
  await page.focus('#new-request'); await page.keyboard.press('Enter');
  await page.keyboard.press('Escape');
  assert.equal(await page.$eval('#create-dialog', node => node.open), false);
  assert.equal(await page.evaluate(() => document.activeElement.id), 'new-request');
  await page.focus('#new-request'); await page.keyboard.press('Enter');
  await page.keyboard.type('resource-keyboard');
  await page.keyboard.press('Tab'); await page.keyboard.type('keyboard reason');
  await page.keyboard.press('Tab'); await page.keyboard.press('Tab'); await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'submit-request');
  await page.keyboard.press('Enter');
  assert.equal(await text(page, '#saved-resource'), 'resource-keyboard');
  await page.focus('#withdraw'); await page.keyboard.press('Enter');
  assert.equal(await text(page, '#status'), '已撤回');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'status');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await screenshot(page, 'access-mobile.png', '员工', 'AC-007');
});

test('AC-015: returning preserves records; reset requires confirmation and other employees have no tasks', async t => {
  const page = await session(t);
  const id = await create(page);
  await page.click('#back');
  assert.match(await text(page, '#records'), new RegExp(id));
  await role(page, 'other');
  assert.equal(await page.$$eval('[data-open]', nodes => nodes.length), 0);
  await page.click('[data-view="tasks"]');
  assert.equal(await page.$$eval('[data-open]', nodes => nodes.length), 0);
  await role(page, 'employee'); await page.click('[data-view="mine"]');
  page.once('dialog', dialog => dialog.dismiss());
  await page.click('#reset');
  assert.match(await text(page, '#records'), new RegExp(id));
  page.once('dialog', dialog => dialog.accept());
  await page.click('#reset');
  assert.equal(await page.$$eval('[data-open]', nodes => nodes.length), 0);
  assert.match(await text(page, '#message'), /已清空/);
});

test('two applications keep rejection drafts and one-shot failure controls separate', async t => {
  const page = await session(t);
  const first = await create(page);
  await role(page, 'manager');
  await fill(page, '#rejection', '第一条资料不足');
  await page.click('#reject');
  await page.click('#fail-action');
  await role(page, 'employee');
  const second = await create(page);
  assert.notEqual(first, second);
  await role(page, 'manager');
  assert.equal(await page.$eval('#rejection', node => node.value), '');
  await page.click('#reject');
  assert.equal(await text(page, '#status'), '待审批');
  assert.match(await text(page, '#action-error'), /拒绝原因/);
  await fill(page, '#rejection', '第二条原因');
  await page.click('#fail-action');
  await page.click('#back');
  await page.click('[data-view="tasks"]');
  await page.click(`[data-open="${second}"]`);
  assert.equal(await page.$eval('#fail-action', node => node.checked), false);
  assert.equal(await page.$eval('#rejection', node => node.value), '');
  await fill(page, '#rejection', '第二条原因');
  await page.click('#reject');
  assert.equal(await text(page, '#outcome'), '第二条原因');
});
