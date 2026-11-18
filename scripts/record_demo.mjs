/** Records the running console while actual Agentforce/API actions execute.
 * npm --prefix demo install; PUPPETEER_MODULE can point to an existing install.
 * Raw footage stays in ignored tmp; render_demo.py assembles narrated chapters.
 */
import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
import path from 'node:path';
const require=createRequire(import.meta.url);
const puppeteer=require(process.env.PUPPETEER_MODULE||'../demo/node_modules/puppeteer');
const out=path.resolve('tmp/recording/footage');await fs.mkdir(out,{recursive:true});
const browser=await puppeteer.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--no-sandbox','--disable-dev-shm-usage']});
const page=await browser.newPage();await page.setViewport({width:1920,height:1080,deviceScaleFactor:1});
await page.goto(process.env.DEMO_CONSOLE_URL||'http://127.0.0.1:8765',{waitUntil:'networkidle0'});
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function click(selector){const box=await page.$eval(selector,e=>{let r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}});await page.mouse.move(box.x,box.y,{steps:25});await pause(500);await page.mouse.click(box.x,box.y);await pause(500)}
const chapters=['event','identity','status','options','book','voucher','conflict'];
const only=process.env.RECORD_ONLY;
const timings=only?JSON.parse(await fs.readFile(path.join(out,'manifest.json'),'utf8')).filter(x=>x.chapter!==only):[];
try{
 for(let i=0;i<chapters.length;i++){
  const name=chapters[i];
  if(only&&name!==only)continue;
  if(name==='conflict'&&!process.env.SKIP_CONFLICT_PREP){
   await page.evaluate(()=>window.demo.launch('conflict-prepare'));
   await page.waitForFunction(async()=>{let s=await(await fetch('/state')).json();return !s.busy&&s.events.at(-1)?.action==='conflict-prepare'},{timeout:300000,polling:1000});
   const prep=await page.evaluate(async()=> (await(await fetch('/state')).json()).events.at(-1));
   if(!prep.success)throw Error('Failure ledger preparation failed: '+prep.error);
  }
  await click(`[data-action="${name}"]`);
  const directory=path.join(out,String(i).padStart(2,'0'));await fs.mkdir(directory,{recursive:true});
  let capturing=true,count=0;
  const capture=(async()=>{while(capturing){const start=Date.now();await page.screenshot({path:path.join(directory,String(count++).padStart(6,'0')+'.jpg'),type:'jpeg',quality:88});await pause(Math.max(0,500-(Date.now()-start)))}})();
  await pause(1500);await click('#run');
  await page.waitForFunction(async action=>{let s=await(await fetch('/state')).json();return !s.busy&&s.events.at(-1)?.action===action},{timeout:600000,polling:1000},name);
  const result=await page.evaluate(async()=> (await(await fetch('/state')).json()).events.at(-1));
  await pause(9000);
  await page.screenshot({path:path.join(out,`${name}.png`)});
  // Slow, deliberate inspection of the actual generated response.
  if(['status','options','book','voucher','conflict'].includes(name)){
   const center=await page.$('#content');const rect=await center.boundingBox();await page.mouse.move(rect.x+rect.width*.7,rect.y+rect.height*.7,{steps:20});
   for(let j=0;j<3;j++){await page.mouse.wheel({deltaY:250});await pause(2200)}
   await page.evaluate(()=>document.getElementById('content').scrollTo({top:0,behavior:'smooth'}));await pause(2500);
  }
  capturing=false;await capture;
  timings.push({chapter:name,frames:count,capture_fps:2,duration_seconds:count/2,execution_success:result.success});
  await fs.writeFile(path.join(out,'manifest.json'),JSON.stringify(timings,null,2));
  console.log(`Captured ${name}: ${count} frames, execution=${result.success}`);
  if(!result.success)throw Error(`${name}: ${result.error}`);
 }
}finally{await browser.close()}
