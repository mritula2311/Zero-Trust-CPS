// Static presentation only. No credentials, gateway startup or attack traffic.
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {dirname,resolve,extname} from 'node:path';
import {fileURLToPath} from 'node:url';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const entries=['Main.dc.html','extracted/Main.dc.html','presentation.css','presentation.js','zero-trust-cps-command-center.html','README.md','DEMO_CHECKLIST.md','DATA_CONTRACT.md','CLEANUP_MANIFEST.md','READINESS.md'];
const allowed=new Set(entries.map(name=>'/design/'+name));
// Also serve only the exact public reference targets used by the presentation.
const presentation=await readFile(resolve(root,'design/Main.dc.html'),'utf8');
for(const [,href] of presentation.matchAll(/href="([^"]+)"/g))allowed.add(new URL(href,'http://localhost/design/Main.dc.html').pathname);
const server=createServer(async(req,res)=>{
  const path=new URL(req.url,'http://localhost').pathname;
  if(path==='/'){res.writeHead(302,{Location:'/design/Main.dc.html'}).end();return;}
  if(path.startsWith('/api/')){res.writeHead(503,{'Content-Type':'application/json'}).end('{"error":"Static presentation server: no gateway API"}');return;}
  if(!allowed.has(path)){res.writeHead(404).end('Not found');return;}
  try{
    const data=await readFile(resolve(root,'.'+path));
    res.writeHead(200,{'Content-Type':({'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript','.md':'text/plain; charset=utf-8','.json':'application/json'})[extname(path)]||'application/octet-stream','Cache-Control':'no-store'}).end(data);
  }catch{res.writeHead(404).end('Not found');}
});
server.listen(8768,'127.0.0.1',()=>console.log('PRESENTATION ONLY · http://127.0.0.1:8768 · no live telemetry · Ctrl+C to stop'));
server.on('error',error=>{console.error(error.message);process.exitCode=1});
