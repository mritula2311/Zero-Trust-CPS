// Local browser regression checks. Fixture responses are test-only, never served by the gateway.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {readFile, writeFile, mkdir, mkdtemp} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {dirname, join, resolve, extname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {tmpdir} from 'node:os';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const output = process.env.DASHBOARD_QA_DIR || await mkdtemp(join(tmpdir(), 'zt-dashboard-qa-'));
await mkdir(output, {recursive:true});
const profile = await mkdtemp(join(tmpdir(), 'zt-dashboard-browser-'));
const chromePath = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
assert(existsSync(chromePath), 'Set CHROME_PATH to an installed Chrome/Chromium executable');
let apiAvailable = true, requests = 0;
const fixtures = {
  '/api/status': {use_rl_policy:true, security_threshold:0.6, process_threshold:0.6},
  '/api/devices': {devices:[{device_id:'esp32-vib-001',kind:'vibration'},{device_id:'esp32-vib-002',kind:'vibration_sw420'},{device_id:'sensor-001',kind:'scalar'}]},
  '/api/decisions': {rows:[]},
  '/api/chain': {chain_ok:true,checkpoint_ok:true,full_scan_ok:true,tail_ok:true,rows_verified:0},
  '/api/governance': {coverage:{},tenets:{},sample_size:0},
  '/api/iec62443': {frs:[]},
  '/api/qtable': {trained:false}
};
const server = createServer(async (req,res) => {
  try {
    const path = decodeURIComponent(new URL(req.url,'http://localhost').pathname);
    if(path.startsWith('/api/')) {
      requests++;
      res.writeHead(apiAvailable?200:503,{'Content-Type':'application/json'});
      res.end(JSON.stringify(apiAvailable?fixtures[path]||{}:{error:'test outage'})); return;
    }
    const target = resolve(root, '.'+path);
    if(!target.startsWith(root+'/') && !target.startsWith(root+'\\')) {res.writeHead(403).end();return;}
    const types={'.html':'text/html','.css':'text/css','.js':'text/javascript','.md':'text/plain'};
    res.writeHead(200,{'Content-Type':types[extname(target)]||'application/octet-stream'});
    res.end(await readFile(target));
  } catch { if(!res.headersSent)res.writeHead(404);res.end(); }
});
await new Promise(done=>server.listen(0,'127.0.0.1',done));
const base = `http://127.0.0.1:${server.address().port}`;
const chrome = spawn(chromePath,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run','--no-default-browser-check','--disable-background-networking','about:blank'],{stdio:'ignore',windowsHide:true});
let socket;
const checks=[], errors=[];
const benchmark=JSON.parse(await readFile(join(root,'results/crossdevice_benchmark/metrics.json'),'utf8'));
const delay=ms=>new Promise(done=>setTimeout(done,ms));
try {
  let port;
  for(let attempt=0;attempt<100;attempt++) {
    try{port=Number((await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]);break;}catch{await delay(100);}
  }
  assert(port,'Headless Chrome did not start');
  const targets=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket=new WebSocket(targets.find(t=>t.type==='page').webSocketDebuggerUrl);
  await new Promise((done,reject)=>{socket.onopen=done;socket.onerror=reject});
  let seq=0;const pending=new Map();
  socket.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.method==='Runtime.exceptionThrown')errors.push(msg.params.exceptionDetails);
    if(pending.has(msg.id)){const {done,reject,timer}=pending.get(msg.id);clearTimeout(timer);pending.delete(msg.id);msg.error?reject(new Error(JSON.stringify(msg.error))):done(msg.result);}
  };
  const send=(method,params={})=>new Promise((done,reject)=>{
    const id=++seq,timer=setTimeout(()=>{pending.delete(id);reject(new Error(`CDP timeout: ${method}`))},15000);
    pending.set(id,{done,reject,timer});socket.send(JSON.stringify({id,method,params}));
  });
  const evaluate=async expression=>{
    const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    assert(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));return result.result.value;
  };
  const waitFor=async expression=>{
    for(let n=0;n<100;n++){if(await evaluate(expression))return;await delay(100);}
    throw new Error('Condition not reached: '+expression);
  };
  const navigate=async path=>{await send('Page.navigate',{url:base+path});await waitFor('document.readyState === "complete"');};
  const click=async selector=>{
    const rect=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
    await send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...rect});
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...rect});
  };
  const key=async (key,code)=>{await send('Input.dispatchKeyEvent',{type:'keyDown',key,code,windowsVirtualKeyCode:{Home:36,End:35,Enter:13,ArrowRight:39}[key]});await send('Input.dispatchKeyEvent',{type:'keyUp',key,code});};
  const screenshot=async name=>{const r=await send('Page.captureScreenshot',{format:'png'});await writeFile(join(output,name+'.png'),Buffer.from(r.data,'base64'));};
  await send('Page.enable');await send('Runtime.enable');
  for(const path of ['/design/Main.dc.html','/design/extracted/Main.dc.html']) {
    await navigate(path);
    assert(await evaluate('document.body.innerText.includes("PRESENTATION · NO LIVE TELEMETRY")'));
    assert.equal(await evaluate('document.querySelectorAll(".evidence-table tbody tr").length'),13);
    assert.equal(await evaluate('document.body.innerText.includes("{{")'),false);
    const measuredRows=await evaluate('Array.from(document.querySelectorAll("#models-title")[0].closest("section").querySelectorAll("tbody tr"),r=>Array.from(r.cells,c=>c.textContent))');
    assert.equal(measuredRows.length,9);
    Object.values(benchmark.results).forEach((entry,index)=>{
      assert.equal(Number(measuredRows[index][1]),entry.test_macro_f1);
      assert.equal(Number(measuredRows[index][2]),entry.test.false_positive_rate);
    });
    for(const url of await evaluate('Array.from(document.querySelectorAll("a[href],link[href],script[src]"),e=>e.href||e.src)')){
      const localPath=resolve(root,'.'+decodeURIComponent(new URL(url).pathname));
      assert(existsSync(localPath),'Missing presentation reference: '+localPath);
    }
    await click('[data-device="sw"]');
    assert(await evaluate('document.getElementById("sensor-title").textContent.includes("TRAIN capture only")'));
    assert.equal(await evaluate('document.querySelectorAll("#sensor-schema li").length'),4);
    await click('[data-device="mpu"]');
    assert.equal(await evaluate('document.querySelectorAll("#sensor-schema li").length'),5);
    await click('[data-policy="bandit"]');
    assert(await evaluate('!document.getElementById("bandit-policy").hidden && document.getElementById("static-policy").hidden'));
    await click('[data-policy="static"]');
    for(const [sec,proc,expected] of [['End','End','ALLOW'],['End','Home','ALERT'],['Home','End','STEP_UP'],['Home','Home','BLOCK']]) {
      await click('#security');await key(sec,sec);await click('#process');await key(proc,proc);
      assert.equal(await evaluate('document.getElementById("policy-result").textContent'),expected);
    }
    // Exact threshold boundary, driven by keyboard rather than a replacement policy implementation.
    for(const selector of ['#security','#process']){await click(selector);await key('Home','Home');for(let n=0;n<60;n++)await key('ArrowRight','ArrowRight');}
    assert.equal(await evaluate('document.getElementById("policy-result").textContent'),'ALLOW');
    await click('[data-device="sw"]');await key('Enter','Enter');
    assert.equal(await evaluate('document.activeElement.getAttribute("aria-pressed")'),'true');
    for(const width of [320,768,1024,1440]) {
      await send('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});
      await evaluate('window.scrollTo(0,0)');
      const dimensions=await evaluate('({viewport:innerWidth,content:document.documentElement.scrollWidth})');
      assert(dimensions.content<=width+1,`${path}: overflow at ${width}: ${dimensions.content}`);
      checks.push({page:path,width,horizontalOverflow:false});
      if(path.includes('/design/Main'))await screenshot('presentation-'+width);
    }
    await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
    const artboardHeight=await evaluate('document.documentElement.scrollHeight');
    checks.push({page:path,width:1600,contentHeight:artboardHeight,horizontalOverflow:false});
    const canvas=JSON.parse(await readFile(join(root,path.includes('/extracted/')?'design/extracted/canvas.json':'design/canvas.json'),'utf8'));
    assert(canvas.artboards[0].h>=artboardHeight,`Canvas height ${canvas.artboards[0].h} is below content height ${artboardHeight}`);
    if(path==='/design/Main.dc.html'){
      await evaluate('document.getElementById("models-title").scrollIntoView({block:"start"})');await screenshot('presentation-models');
      await evaluate('document.getElementById("policy-title").scrollIntoView({block:"start"})');await screenshot('presentation-policy');
    }
  }
  assert.equal(requests,0,'Presentation unexpectedly contacted gateway API');
  await navigate('/design/zero-trust-cps-command-center.html');
  await waitFor('document.getElementById("liveword").textContent === "API CONNECTED"');
  assert(await evaluate('document.getElementById("devs").textContent.includes("PHYSICAL ID · SW-420")'));
  assert(await evaluate('document.getElementById("p-policy").textContent.includes("offline bandit")'));
  for(const width of [320,768,1024,1440]){
    await send('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});
    const content=await evaluate('document.documentElement.scrollWidth');
    assert(content<=width+1,`Live page overflow at ${width}: ${content}`);
    checks.push({page:'gateway view',width,horizontalOverflow:false});
    await screenshot('gateway-'+width);
  }
  apiAvailable=false;
  await waitFor('document.getElementById("liveword").textContent === "RECONNECTING"');
  assert(await evaluate('document.getElementById("banner").textContent.includes("not current")'));
  apiAvailable=true;
  await waitFor('document.getElementById("liveword").textContent === "API CONNECTED"');
  assert.equal(await evaluate('document.getElementById("banner").textContent'),'');
  fixtures['/api/decisions']={rows:[
    {device_id:'esp32-vib-001',decision:'ALERT',timestamp:new Date().toISOString(),security_trust_score:0.8,process_trust_score:0.4,rule_score:0.7,anomaly_score:0.4,lstm_score:0.3,gnn_score:0.5,fused_score:0.4,shap_rule:0.1,shap_isolation_forest:-0.2,shap_lstm_ae:-0.3,shap_gnn:-0.1,reason:'Synthetic browser fixture',confidence:0.6},
    {device_id:'esp32-vib-002',decision:'ALLOW',timestamp:new Date().toISOString(),security_trust_score:0.8,process_trust_score:0.9,rule_score:0.9,anomaly_score:0.9,lstm_score:0.9,gnn_score:0.9,fused_score:0.9,reason:'Synthetic fixture with unavailable SHAP'},
    {device_id:'esp32-vib-001',decision:'REJECTED',timestamp:new Date().toISOString(),reason:'Synthetic rejected fixture'}
  ]};
  await waitFor('document.querySelectorAll("#devs .preds").length === 2');
  assert.equal(await evaluate('document.querySelectorAll("#devs .dev")[0].querySelector(".badge").textContent'),'ALERT');
  assert.equal(await evaluate('Array.from(document.querySelectorAll("#devs .dev")[1].querySelectorAll(".sv"),e=>e.textContent).join("")'),'————');
  await evaluate('document.getElementById("devs").scrollIntoView({block:"start"})');await screenshot('gateway-observations');
  fixtures['/api/devices']={devices:[]};
  await waitFor('document.getElementById("devs").textContent.includes("No registered identities")');
  assert.equal(errors.length,0,JSON.stringify(errors));
  const result={ok:true,checks,interactions:['sensor selection and schema','policy explanation switch','four static actions','0.6 threshold equality','keyboard activation','physical SW identity','API disconnect/recovery','empty registry','accepted/rejected observations','unavailable SHAP shown as missing'],numericComparisons:18,localPresentationReferences:'All file targets exist',presentationApiRequests:0,runtimeExceptions:errors.length,fixtureScope:'Synthetic API responses for browser tests only; no production gateway or hardware contacted.'};
  await writeFile(join(output,'verification.json'),JSON.stringify(result,null,2));
  console.log(JSON.stringify({ok:true,output,viewportChecks:checks.length,interactions:result.interactions.length}));
  await send('Browser.close').catch(()=>{});
} finally {
  socket?.close();chrome.kill();server.close();
}
