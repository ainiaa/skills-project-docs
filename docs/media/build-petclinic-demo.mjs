// Rebuild the edited walkthrough from the checked-in case, without opening a desktop app.
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir, copyFile } from 'node:fs/promises';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { launchBrowser } from '../../scripts/product_browser.mjs';

const media = dirname(fileURLToPath(import.meta.url));
const root = resolve(media, '../..');
assert(process.argv[2], 'Usage: node docs/media/build-petclinic-demo.mjs <frames-directory> [zh-CN|en]');
const locale = process.argv[3] ?? 'zh-CN';
assert(['zh-CN', 'en'].includes(locale), 'Supported locales: zh-CN, en');
const english = locale === 'en';
const pick = (zh, en) => english ? en : zh;
const stem = english ? 'petclinic-demo.en' : 'petclinic-demo';
const casePath = `docs/examples/petclinic/README${english ? '.en' : ''}.md`;
const guidePath = `docs/examples/petclinic/developer-guide${english ? '.en' : ''}.md`;
const work = resolve(process.argv[2]);
await mkdir(work, { recursive: true });
const text = path => readFile(join(root, path), 'utf8');
const escape = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const guide = await text(guidePath);
const source = JSON.parse(await text('docs/examples/petclinic/verification.json'));
const results = JSON.parse(await text('docs/examples/petclinic/controller-test-results.json'));
const evidence = JSON.parse(await text('docs/examples/petclinic/architecture.evidence.json'));
assert.equal(source.sourceCommit, results.sourceCommit);
assert.equal(results.counts.tests, results.tests.length);
assert.equal(results.counts.failures + results.counts.errors + results.counts.skipped, 0);
const headings = [...guide.matchAll(/^## (.+)$/gm)].map(m => m[1]);
assert.equal(headings.length, 9);
const task = (await text(casePath)).match(/```text\n([\s\S]*?)```/)[1].trim();
const rule = guide.split('\n').find(line => line.startsWith(english ? 'Petclinic is' : 'Petclinic 是'));
const save = evidence.claims.find(claim => claim.artifactQuote.includes('save owner')).evidence;
const code = save.map(anchor => `<div class="file">${escape(anchor.path.split('/').pop())} · L${anchor.line}</div><pre>${escape(anchor.quote)}</pre>`).join('');
const image = name => `<img src="${pathToFileURL(join(root, 'docs/examples/petclinic', name + '.png')).href}" alt="${name}">`;
const scenes = [
  ['Ask one useful question', pick('限定读者与范围', 'Define the reader and scope'), `<span class="tag">INPUT · TASK BRIEF</span><h2>A Java developer.<br>A new codebase.</h2><pre class="task">${escape(task)}</pre><p>Spring Petclinic · Owner creation</p>`],
  ['Follow a reading path', pick('查看已有上手手册', 'Read the existing guide'), `<span class="tag">OUTPUT · ONBOARDING GUIDE</span><div class="chapters">${headings.map(h => `<div>${escape(h)}</div>`).join('')}</div><p class="excerpt">${escape(rule)}</p>`],
  ['Check the source', pick('回查固定提交', 'Check the pinned revision'), `<span class="tag">EVIDENCE · ACTUAL SOURCE EXCERPTS</span><h2>Keep the real structure.</h2>${code}<p>Controller → Repository<br>${pick('来源：案例图形证据中的逐行引用', 'Sources: line quotes from the case evidence.')}</p>`],
  ['See the module map', pick('查看实际模块关系', 'Follow the actual dependencies'), `<span class="tag">OUTPUT · MODULE MAP</span><div class="diagram">${image('architecture')}<div class="diagram-notes"><h2>MVC → JPA → H2</h2><p>Direct repository call</p><p>${pick('Controller 直接访问 Repository，<br>保留代码中的实际结构。', 'The Controller calls the Repository directly, preserving the implementation.')}</p><p>Default: in-memory H2</p></div></div>`],
  ['Keep the failure path', pick('保留校验失败分支', 'Keep both validation branches'), `<span class="tag">OUTPUT · CORE FLOW</span><div class="diagram">${image('owner-flow')}<div class="diagram-notes"><h2>Invalid input?</h2><p>Return to the form.</p><h2>Valid input?</h2><p>Save, then redirect.</p><p>${pick('保留校验失败与成功两条分支。', 'Keep both success and validation failure paths.')}</p></div></div>`],
  ['Read the test evidence', pick('核对实际测试结果', 'Check the recorded test run'), `<span class="tag">VERIFICATION · RECORDED SUREFIRE RESULT</span><div class="total">${results.counts.tests}<span>tests passed</span></div><div class="counts">${results.counts.failures} failures · ${results.counts.errors} errors · ${results.counts.skipped} skipped</div><pre>./mvnw -B -ntp\n  -Dtest=OwnerControllerTests test</pre><p>MockMvc + mocked Repository<br>${pick('实际 Controller 测试记录；非数据库集成或浏览器 E2E。', 'Recorded Controller tests; not database integration or browser E2E.')}</p><div class="cta">Read the guide. Check the source.</div>`],
];
const html = `<!doctype html><html lang="${locale}"><meta charset="utf-8"><title>Petclinic · edited artifact walkthrough</title><style>
*{box-sizing:border-box}body{margin:0;background:#f5f1e8;color:#173b2d;font-family:Georgia,'PingFang SC',serif;width:960px;height:600px}header{height:64px;display:flex;align-items:center;justify-content:space-between;padding:0 30px;border-bottom:1px solid #d4d8cc}header b{font-size:20px;letter-spacing:2px}header span,.tag,.file,footer{font-family:Menlo,Consolas,monospace}header span{font-size:12px;color:#54645a}main{display:grid;grid-template-columns:230px 1fr;gap:24px;margin:24px 28px;height:442px}aside{background:#173b2d;color:#f5f1e8;padding:24px;display:flex;flex-direction:column;justify-content:space-between}.number{color:#e9b578;font-size:66px;line-height:1}h1{font-size:31px;line-height:1.13;letter-spacing:-.5px;margin:14px 0}aside p{font-family:'PingFang SC',sans-serif;font-size:15px;line-height:1.6;color:#d4ddce}.steps{display:flex;gap:7px}.steps i{width:24px;height:4px;background:#53745f}.steps i.on{background:#e9b578}.pane{background:#fffdf8;border:1px solid #d4d8cc;padding:20px 24px;height:442px;overflow:visible}.tag{font-size:11px;letter-spacing:1.2px;color:#626f61;display:block;margin-bottom:18px}h2{font-size:33px;line-height:1.12;margin:14px 0 22px;letter-spacing:-.4px}p{font-size:17px;line-height:1.6;margin:18px 0}pre{background:#edf0e8;padding:14px 16px;font-family:Menlo,Consolas,'PingFang SC',monospace;font-size:15px;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0 18px}.task{font-size:17px;line-height:1.8;margin-top:24px}.chapters{display:grid;grid-template-columns:1fr 1fr;gap:8px}.chapters div{font-size:17px;padding:9px 10px;border-bottom:1px solid #e0e4d9;line-height:1.5}.excerpt{font-size:15px;line-height:1.65;margin-top:17px}.file{font-size:13px;color:#656f5f;margin-top:20px}.diagram{height:382px;display:grid;grid-template-columns:235px 1fr;gap:24px;align-items:center}.diagram-notes h2{font-size:26px;margin:14px 0}.diagram-notes p{font-size:16px;margin:16px 0}.diagram img{max-height:382px;max-width:100%;width:auto;object-fit:contain}.total{font-size:93px;line-height:1.1;margin:12px 0 10px;letter-spacing:-4px}.total span{font-size:30px;letter-spacing:-.5px;margin-left:20px}.counts{font-family:Menlo,Consolas,monospace;color:#527054;margin-bottom:18px}.cta{font-size:23px;font-weight:bold;border-top:1px solid #d4d8cc;padding-top:14px}footer{position:absolute;bottom:0;left:0;right:0;height:46px;border-top:1px solid #d4d8cc;padding:14px 30px;display:flex;justify-content:space-between;font-size:11px;color:#52654f}.scene{display:none}.scene.active{display:contents}
</style><header><b>PROJECT DOCS</b><span>SPRING PETCLINIC / OWNER CREATION</span></header>${scenes.map(([title, subtitle, body], index) => `<div class="scene" data-scene="${index}"><main><aside><div><div class="number">0${index + 1}</div><h1>${title}</h1><p>${subtitle}</p></div><div class="steps">${scenes.map((_, n) => `<i class="${n === index ? 'on' : ''}"></i>`).join('')}</div></aside><section class="pane">${body}</section></main></div>`).join('')}<footer><span>${pick('EDITED WALKTHROUGH · 剪辑演示 · NOT GENERATION SPEED', 'EDITED ARTIFACT WALKTHROUGH · NOT GENERATION SPEED')}</span><span>SOURCE ${source.sourceCommit.slice(0, 12)}</span></footer></html>`;
await writeFile(join(work, 'storyboard.html'), html);
const browser = await launchBrowser();
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 960, height: 600, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(join(work, 'storyboard.html')).href);
  await page.evaluate(async () => { await document.fonts.ready; await Promise.all([...document.images].map(img => img.decode())); });
  for (let index = 0; index < scenes.length; index++) {
    await page.evaluate(i => document.querySelectorAll('.scene').forEach((s, n) => s.classList.toggle('active', n === i)), index);
    if (english) assert(!/[\u4e00-\u9fff]/u.test(await page.$eval('body', body => body.innerText)), `Scene ${index + 1} contains untranslated text`);
    const overflow = await page.evaluate(() => ({ width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight,
      paneOverflow: [...document.querySelectorAll('.active .pane')].some(p => p.scrollHeight > p.clientHeight) }));
    assert(overflow.width <= 960 && overflow.height <= 600 && !overflow.paneOverflow, `Scene ${index + 1} overflows: ${JSON.stringify(overflow)}`);
    await page.screenshot({ path: join(work, `frame-${index}.png`) });
  }
} finally { await browser.close(); }
const encoded = spawnSync('python3', ['-c', `
from PIL import Image
from pathlib import Path
import sys, json, hashlib
work=Path(sys.argv[1])
frames=[Image.open(work/f'frame-{i}.png').convert('RGB') for i in range(6)]
output=work/'petclinic-demo.gif'
frames[0].save(output, save_all=True, append_images=frames[1:], duration=[3500,4000,4000,4000,4000,4500], loop=0, optimize=True, disposal=2)
with Image.open(output) as gif:
 assert gif.n_frames==6 and gif.info['loop']==0 and gif.size==(960,600)
 durations=[]
 for i in range(gif.n_frames):
  gif.seek(i); gif.load(); durations.append(gif.info['duration'])
 data=output.read_bytes()
 assert sum(durations)==24000 and len(data)<=5*1024*1024
 print(json.dumps(dict(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),width=960,height=600,frames=6,durationMs=sum(durations),frameDurationsMs=durations,loop=0)))
`, work], { encoding: 'utf8' });
assert.equal(encoded.status, 0, encoded.stderr);
const receipt = { ...JSON.parse(encoded.stdout), sourceCommit: source.sourceCommit, locale, mode: 'edited-artifact-walkthrough',
  sources: ['docs/examples/petclinic/verification.json', casePath, guidePath, 'docs/examples/petclinic/architecture.evidence.json', 'docs/examples/petclinic/architecture.png', 'docs/examples/petclinic/owner-flow.png', 'docs/examples/petclinic/controller-test-results.json'] };
receipt.sourceSha256 = Object.fromEntries(await Promise.all(receipt.sources.map(async path => [path, createHash('sha256').update(await readFile(join(root, path))).digest('hex')])));
await copyFile(join(work, 'petclinic-demo.gif'), join(media, `${stem}.gif`));
await writeFile(join(media, `${stem}.json`), JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify(receipt, null, 2));
