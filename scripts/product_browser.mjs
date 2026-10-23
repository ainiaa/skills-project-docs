/** Existing Puppeteer runtime, actual delivery tests, and current-input evidence. */
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join, resolve, relative, isAbsolute } from 'node:path';
import { mkdir, readdir, readFile, writeFile, appendFile, realpath, stat, lstat } from 'node:fs/promises';
import { accessSync, constants, readFileSync, realpathSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';

const require = createRequire(import.meta.url);
const runtimeRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
export async function launchBrowser() {
  // Reuse renderer precedence and parse simple CLI wrappers as data, never as shell code.
  const probe = spawnSync('python3', ['-c', `
import json, os, shlex, shutil, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from engine_paths import find_engine
cli = find_engine('mermaid')
if os.environ.get('MERMAID_OFFICIAL_CLI') and not cli:
    raise ValueError('MERMAID_OFFICIAL_CLI is unavailable; correct its executable path')
paths, config = [], None
if cli:
    path = Path(cli).resolve()
    paths.append(str(path.parent))
    if path.suffix not in ('.js', '.mjs', '.cjs'):
        lines = path.read_text().splitlines()
        if len(lines) == 2 and lines[0] == '#!/bin/sh':
            words = shlex.split(lines[1])
            if len(words) >= 4 and words[0] == 'exec' and words[-1] == '$@':
                paths.extend(str(Path(word).parent) for word in words[2:-1] if Path(word).suffix in ('.js', '.mjs', '.cjs') and Path(word).is_absolute())
                for flag in ('-p', '--puppeteerConfigFile'):
                    if flag in words:
                        config = str((path.parent / words[words.index(flag)+1]).resolve())
browsers = [shutil.which(name) for name in ('google-chrome', 'chromium', 'chromium-browser')]
if sys.platform == 'darwin':
    browsers += [str(base / 'Google Chrome.app/Contents/MacOS/Google Chrome') for base in (Path('/Applications'), Path.home() / 'Applications')]
print(json.dumps({'paths': paths, 'config': config, 'browsers': [p for p in browsers if p]}))
`, join(runtimeRoot, 'scripts')], { encoding: 'utf8', timeout: 10000 });
  if (probe.error || probe.status !== 0) throw new Error(`Browser discovery failed: ${probe.error?.message || probe.stderr.trim()}. Check python3 and MERMAID_OFFICIAL_CLI.`);
  const found = JSON.parse(probe.stdout), errors = [];
  let puppeteer, executablePath = process.env.PUPPETEER_EXECUTABLE_PATH;
  const modulePath = process.env.PRODUCT_BROWSER_MODULES;
  try {
    const module = modulePath
      ? require.resolve(join(realpathSync(modulePath), 'puppeteer'))
      : require.resolve('puppeteer', { paths: [...found.paths, runtimeRoot] });
    puppeteer = require(module);
  } catch {
    errors.push('Puppeteer unavailable: correct PRODUCT_BROWSER_MODULES or the existing Mermaid installation (bash install.sh --doctor --engine mermaid).');
  }
  if (!executablePath && found.config) {
    try {
      const config = JSON.parse(readFileSync(found.config, 'utf8'));
      if (config.executablePath !== undefined && (typeof config.executablePath !== 'string' || !config.executablePath.trim())) throw new Error('executablePath must be a non-empty string');
      executablePath = config.executablePath && resolve(dirname(found.config), config.executablePath);
    } catch (error) { errors.push(`Invalid Mermaid browser config ${found.config}: ${error.message}; correct the JSON or set PUPPETEER_EXECUTABLE_PATH.`); }
  }
  const executable = path => {
    try { accessSync(path, constants.X_OK); return statSync(path).isFile(); } catch { return false; }
  };
  if (executablePath && !executable(executablePath)) errors.push(`PUPPETEER_EXECUTABLE_PATH / Mermaid executablePath is unavailable: ${executablePath}; correct the browser path.`);
  if (!executablePath) {
    let cached;
    try { cached = puppeteer?.executablePath(); } catch { /* Try existing system Chrome next. */ }
    executablePath = [cached, ...found.browsers].find(path => path && executable(path));
    if (!executablePath) errors.push('Chrome/Chromium unavailable: set PUPPETEER_EXECUTABLE_PATH to an installed browser.');
  }
  if (errors.length) throw new Error(errors.join('\n'));
  return puppeteer.launch({ headless: true, executablePath, args: process.env.CI === 'true' ? ['--no-sandbox'] : [] });
}
async function contained(root, path) {
  if (typeof path !== 'string' || !path || isAbsolute(path)) throw new Error('Expected a delivery-relative path');
  const actual = await realpath(join(root, path));
  const local = relative(await realpath(root), actual);
  if (local === '..' || local.startsWith('../') || isAbsolute(local)) throw new Error('Path escapes delivery');
  return actual;
}
async function event(value) {
  if (process.env.PRODUCT_BROWSER_EVENTS) await appendFile(process.env.PRODUCT_BROWSER_EVENTS, JSON.stringify(value) + '\n');
}
async function pageIdentity(page) {
  const root = await realpath(process.env.PRODUCT_DELIVERY_DIR);
  const url = new URL(page.url());
  if (url.protocol !== 'file:') throw new Error('Evidence requires a delivery-local HTML page');
  const path = await contained(root, relative(root, fileURLToPath(url)));
  return { path: relative(root, path), sha256: hash(await readFile(path)) };
}
export async function openPage(browser, path = 'prototype.html', viewport = { width: 1440, height: 1000 }) {
  const root = process.env.PRODUCT_DELIVERY_DIR;
  if (!root) throw new Error('PRODUCT_DELIVERY_DIR is required');
  const page = await browser.newPage();
  if (process.env.PRODUCT_BROWSER_INPUTS) {
    const source = JSON.parse(process.env.PRODUCT_BROWSER_INPUTS);
    await page.setRequestInterception(true);
    page.on('request', async request => {
      try {
        const url = new URL(request.url());
        if (url.protocol === 'data:') return await request.continue();
        if (url.protocol !== 'file:') throw new Error('Browser resources must be snapshotted delivery inputs');
        const path = await contained(root, relative(root, fileURLToPath(url)));
        if (!(relative(root, path) in source)) throw new Error('Browser resource is excluded from the input snapshot');
        await request.continue();
      } catch (error) {
        process.exitCode = 1;
        await event({ error: error.message });
        await request.abort();
      }
    });
  }
  page.on('pageerror', error => { process.exitCode = 1; void event({ error: error.message }); });
  page.on('requestfailed', request => { process.exitCode = 1; void event({ error: request.failure()?.errorText || 'resource failed' }); });
  await page.setViewport(viewport);
  await page.goto(pathToFileURL(await contained(root, path)).href, { waitUntil: 'load' });
  await event({ page: await pageIdentity(page) });
  return page;
}
export async function stable(page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all([...document.images].map(image => image.decode().catch(() => {})));
    await Promise.all(document.getAnimations().filter(animation => Number.isFinite(animation.effect?.getComputedTiming().endTime))
      .map(animation => animation.finished.catch(() => {})));
    await new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done)));
  });
}
async function ordinaryOutput(path) {
  try {
    if (!(await lstat(path)).isFile()) throw new Error('Output must be an ordinary file, not a symlink');
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
}
export async function capture(page, filename, { role, scenario }) {
  if (!role || !scenario || !/^[a-zA-Z0-9._-]+\.png$/.test(filename)) throw new Error('Capture requires a PNG filename, role and scenario');
  await stable(page);
  const directory = process.env.PRODUCT_SCREENSHOT_DIR;
  if (!directory) throw new Error('PRODUCT_SCREENSHOT_DIR is required');
  await mkdir(directory, { recursive: true });
  if (await realpath(directory) !== resolve(directory)) throw new Error('Capture directory cannot be a symlink');
  const path = join(directory, filename);
  await ordinaryOutput(path);
  const identity = await pageIdentity(page);
  await page.screenshot({ path, fullPage: true });
  if (JSON.stringify(identity) !== JSON.stringify(await pageIdentity(page))) throw new Error('Page changed during screenshot capture');
  await event({ page: identity, screenshot: { path: relative(process.env.PRODUCT_DELIVERY_DIR, path), sha256: hash(await readFile(path)), viewport: page.viewport(), role, scenario, page: identity } });
}
async function inputs(root) {
  const files = {};
  async function walk(directory) {
    for (const item of await readdir(directory, { withFileTypes: true })) {
      const path = join(directory, item.name), local = relative(root, path);
      if (directory === root && ['evidence', 'bundle.json', 'review.md'].includes(item.name)) continue;
      if (item.isSymbolicLink()) throw new Error('Snapshot requires ordinary files, not symlinks');
      if (item.isDirectory()) await walk(path);
      else if (item.isFile()) {
        if (Object.keys(files).length >= 4096 || (await stat(path)).size > 8 * 1024 * 1024) throw new Error('Delivery snapshot limit exceeded');
        files[local] = hash(await readFile(path));
      }
    }
  }
  await walk(root);
  return files;
}
async function run(directory, test) {
  const root = await realpath(directory);
  const path = await contained(root, test);
  test = relative(root, path);
  const evidence = join(root, 'evidence');
  // Evidence is local output only: reject a pre-existing link before creating files.
  await mkdir(evidence, { recursive: true });
  if (await realpath(evidence) !== evidence) throw new Error('Evidence directory cannot be a symlink');
  for (const name of ['browser.json', 'browser-events.jsonl', 'browser.tap']) await ordinaryOutput(join(evidence, name));
  const events = join(evidence, 'browser-events.jsonl');
  const report = { schemaVersion: 1, tool: 'product-browser-v1', result: 'unverified', exitCode: null,
    tests: 0, passed: 0, failed: 0, skipped: 0, errors: [], source: {}, test, screenshots: [], pages: [],
    runnerFingerprint: hash(await readFile(fileURLToPath(import.meta.url))) };
  try {
    const probe = await launchBrowser();
    report.environment = { node: process.version, platform: process.platform, browser: await probe.version() };
    await probe.close();
    report.source = await inputs(root);
    if (!(test in report.source)) throw new Error('Test entry must be a snapshotted delivery input');
    await writeFile(events, '');
    const argv = ['--test', '--test-reporter=tap', path];
    const result = spawnSync(process.execPath, argv, { cwd: root, encoding: 'utf8', timeout: 120000, maxBuffer: 4 * 1024 * 1024,
      env: { ...process.env, PRODUCT_DELIVERY_DIR: root, PRODUCT_SCREENSHOT_DIR: evidence, PRODUCT_BROWSER_EVENTS: events,
        PRODUCT_BROWSER_INPUTS: JSON.stringify(report.source) } });
    await writeFile(join(evidence, 'browser.tap'), (result.stdout || '') + (result.stderr || ''));
    report.argv = [process.execPath, ...argv];
    report.exitCode = result.status;
    for (const [key, label] of [['tests', 'tests'], ['passed', 'pass'], ['failed', 'fail'], ['skipped', 'skipped']]) {
      report[key] = Number((result.stdout || '').match(new RegExp(`^# ${label} (\\d+)$`, 'm'))?.[1] || 0);
    }
    const observations = (await readFile(events, 'utf8')).split('\n').filter(Boolean).map(line => JSON.parse(line));
    report.errors = observations.filter(item => item.error).map(item => item.error);
    report.screenshots = observations.filter(item => item.screenshot).map(item => item.screenshot);
    report.pages = [...new Map(observations.filter(item => item.page).map(item => [JSON.stringify(item.page), item.page])).values()];
    if (result.error) report.errors.push(result.error.message);
    if (report.pages.length === 0) report.errors.push('No prototype page was observed during tests');
    // Node counts an empty test file as one passing file; require an explicit case.
    const cases = [...(result.stdout || '').matchAll(/^\s*# Subtest: (.+)$/gm)].map(match => match[1]);
    if (!cases.some(name => name !== path && name !== test)) report.errors.push('No explicit test cases executed');
    if (JSON.stringify(report.source) !== JSON.stringify(await inputs(root))) report.errors.push('Delivery inputs changed while testing');
    report.result = report.exitCode === 0 && report.tests > 0 && report.passed === report.tests && report.failed === 0 && report.skipped === 0 && report.errors.length === 0 ? 'pass' : 'fail';
  } catch (error) { report.errors.push(error.message); }
  await writeFile(join(evidence, 'browser.json'), JSON.stringify(report, null, 2) + '\n');
  return report;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const args = process.argv.slice(2);
    if (args.length !== 4 || args[0] !== '--directory' || args[2] !== '--test') throw new Error('Usage: node product_browser.mjs --directory <delivery> --test <journey.test.mjs>');
    const report = await run(args[1], args[3]);
    process.stdout.write(JSON.stringify(report) + '\n');
    process.exitCode = report.result === 'pass' ? 0 : report.result === 'unverified' ? 2 : 1;
  } catch (error) { process.stderr.write(error.message + '\n'); process.exitCode = 2; }
}
