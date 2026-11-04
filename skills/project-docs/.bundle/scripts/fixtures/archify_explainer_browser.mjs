// Acceptance driver: use the official browser runtime and the delivered page's export API.
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';

const [cli, html, output] = process.argv.slice(2);
const runtime = await import(pathToFileURL(path.join(path.dirname(fs.realpathSync(cli)), 'visual-check.mjs')));
const chrome = runtime.findChrome();
if (!chrome) throw new Error('Chrome/Chromium is required for explainer browser acceptance');
const browser = new runtime.ChromeVisualBrowser(chrome);
try {
  const session = await browser.sessionPromise;
  const evaluate = async expression => {
    const result = await browser.cdp.send('Runtime.evaluate', {
      expression, awaitPromise:true, returnByValue:true,
    }, session);
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result?.value;
  };
  const observations = [];
  for (const width of [1440, 390]) {
    await browser.cdp.send('Emulation.setDeviceMetricsOverride', {
      width, height:900, deviceScaleFactor:1, mobile:false,
    }, session);
    const loaded = browser.cdp.waitFor('Page.loadEventFired', session);
    await browser.cdp.send('Page.navigate', {url:pathToFileURL(html).href}, session);
    await loaded;
    await evaluate(`(async()=>{await document.fonts.ready; await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))); if(!window.ArchifyExplainer?.pageImage)throw new Error('Explainer reader unavailable'); return true;})()`);
    const measured = await evaluate(`({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,panels:document.querySelectorAll('.panel').length})`);
    if (measured.scrollWidth > width + 1 || measured.panels < 3) throw new Error(JSON.stringify(measured));
    observations.push(measured);
    const capture = await browser.cdp.send('Page.captureScreenshot', {format:'png',captureBeyondViewport:true}, session);
    fs.writeFileSync(path.join(output, `viewport-${width}.png`), Buffer.from(capture.data,'base64'));
    if (width === 1440) {
      for (const format of ['png','webp','jpeg']) {
        const encoded = await evaluate(`(async()=>{const blob=await ArchifyExplainer.pageImage(${JSON.stringify(format)});if(blob.type!==${JSON.stringify('image/' + format)})throw new Error('Unexpected export MIME: '+blob.type);return await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(blob);});})()`);
        fs.writeFileSync(path.join(output, `answer.${format === 'jpeg' ? 'jpg' : format}`), Buffer.from(encoded,'base64'));
      }
      const pdf = await browser.cdp.send('Page.printToPDF', {printBackground:true,preferCSSPageSize:true}, session);
      fs.writeFileSync(path.join(output, 'answer.pdf'), Buffer.from(pdf.data,'base64'));
    }
  }
  console.log(JSON.stringify(observations));
} finally {
  await browser.close();
}
