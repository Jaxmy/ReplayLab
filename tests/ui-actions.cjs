/* Run the shipped UI in a DOM, with its real HTTP backend and both transport paths.
   Chart painting is stubbed; actual canvas/pan/zoom is checked in the browser. */
const {JSDOM}=require('jsdom'),fs=require('fs'),path=require('path'),assert=require('node:assert/strict'),vm=require('vm');
const {spawn}=require('child_process'),net=require('net');
const root=path.resolve(__dirname,'..');
const png='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII=';
async function main(){
 const port=await new Promise(resolve=>{const s=net.createServer().listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>resolve(p));});});
 const python=process.argv[2]||path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
 const backend=spawn(python,[path.join(__dirname,'ui_server.py'),String(port)],{cwd:root,windowsHide:true});
 let log='';backend.stderr.on('data',b=>log+=b);backend.on('error',e=>log+=e.message);
 const base=`http://127.0.0.1:${port}`;
 try{
  let ready=false;for(let i=0;i<150;i++){try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;if(backend.exitCode!==null)throw Error(log);await new Promise(r=>setTimeout(r,100));}assert(ready,log);
  for(const bridge of [false,true]){
   const dom=new JSDOM(fs.readFileSync(path.join(root,'web/index.html'),'utf8'),{runScripts:'outside-only',pretendToBeVisual:true,url:base});
   const w=dom.window,doc=w.document,calls=[],errors=[];let exports=0;
   w.addEventListener('error',e=>errors.push(e.error));w.structuredClone=structuredClone;w.AbortController=AbortController;
   w.URL.createObjectURL=()=>{exports++;return 'blob:test';};w.URL.revokeObjectURL=()=>{};w.HTMLAnchorElement.prototype.click=function(){};
   w.HTMLCanvasElement.prototype.getContext=()=>new Proxy({},{get:()=>()=>{}});w.HTMLCanvasElement.prototype.toDataURL=()=>png;
   const panes=[{setHeight(){}}],time={getVisibleLogicalRange:()=>({from:0,to:50}),setVisibleLogicalRange(){},scrollToRealTime(){},fitContent(){}};
   const chart=()=>({addSeries:()=>({setData(){},priceScale:()=>({applyOptions(){}})}),removeSeries(){},panes:()=>panes,timeScale:()=>time,priceScale:()=>({applyOptions(){}}),takeScreenshot:()=>doc.createElement('canvas'),remove(){}});
   w.LightweightCharts={createChart:chart,createSeriesMarkers:()=>({setMarkers(){}})};
   async function request(p,options={}){calls.push({path:p,method:options.method||'GET',body:options.body?JSON.parse(options.body):undefined});return fetch(base+p,options);}
   w.fetch=request;
   if(bridge)w.acquireVsCodeApi=()=>({postMessage:async m=>{if(!m.path){exports++;return;}try{const r=await request(m.path,{method:m.method,headers:{'Content-Type':'application/json'},body:m.body===undefined?undefined:JSON.stringify(m.body)}),d=await r.json();w.dispatchEvent(new w.MessageEvent('message',{data:r.ok?{id:m.id,data:d}:{id:m.id,error:typeof d.detail==='string'?d.detail:JSON.stringify(d.detail)}}));}catch(e){w.dispatchEvent(new w.MessageEvent('message',{data:{id:m.id,error:e.message}}));}}});
   const script=fs.readFileSync(path.join(root,'web/app.js'),'utf8');
   try{
    vm.runInContext(script,dom.getInternalVMContext());
    async function settle(){await vm.runInContext('actionQueue',dom.getInternalVMContext());await new Promise(r=>setTimeout(r,20));}
    async function click(selector,allowError=false){const el=doc.querySelector(selector);assert(el,selector);assert(!el.disabled,selector+' disabled');el.click();await settle();assert(!errors.length,String(errors));if(!allowError)assert.notEqual(doc.querySelector('#status').style.color,'rgb(241, 130, 145)',selector+': '+doc.querySelector('#status').textContent);}
    function change(selector,value){const el=doc.querySelector(selector);el.value=value;el.dispatchEvent(new w.Event('change',{bubbles:true}));}
    await settle();assert.match(doc.querySelector('#status').textContent,/已连接/);
    // Every static button must have an event hook (tabs use the same delegation).
    for(const el of doc.querySelectorAll('button[id]'))assert.equal(typeof el.onclick,'function','unbound button '+el.id);
    assert.equal(doc.querySelectorAll('.indicator-card').length,4);
    await click('#addIndicator');assert.equal(doc.querySelectorAll('.indicator-card').length,5);
    await click('[data-copy]');assert.equal(doc.querySelectorAll('.indicator-card').length,6);
    await click('[data-remove]');assert.equal(doc.querySelectorAll('.indicator-card').length,5);
    doc.querySelector('[data-instance-param]').value='7';await click('[data-apply]');
    await click('#applyIndicators');
    await click('#create');assert.match(doc.querySelector('#clock').textContent,/2023-12-31/);
    let live=await (await fetch(base+'/api/sessions')).json(),sid=live[0].id;
    let state=await (await fetch(base+'/api/sessions/'+sid)).json();assert.equal(state.warmup.available,300);assert.equal(state.indicator_instances.length,5);assert.equal(state.indicator_instances[0].params.period,7);
    // Checkbox click bubbles before change; it must still send the new enabled flag.
    const enabled=doc.querySelector('[data-enable]');enabled.click();await settle();
    state=await (await fetch(base+'/api/sessions/'+sid)).json();assert.equal(state.indicator_instances[0].enabled,false);
    const toggles=doc.querySelectorAll('[data-enable]');toggles[1].click();toggles[2].click();await settle();
    state=await (await fetch(base+'/api/sessions/'+sid)).json();assert.equal(state.indicator_instances[1].enabled,false);assert.equal(state.indicator_instances[2].enabled,false);
    doc.querySelector('#step').click();doc.querySelector('#step').click();await settle();
    state=await (await fetch(base+'/api/sessions/'+sid)).json();assert.equal(state.cursor,2,'rapid commands must not disappear');
    await click('#play');await settle();await click('#play');await click('#jump');
    change('#timeframe','5m');await settle();doc.querySelector('#customTf').value='7m';await click('#applyTf');
    await click('#history');await click('#follow');await click('#fit');await click('#settingsToggle');
    await click('#long');await click('#short');await click('#step');
    await click('[data-adjust]');await click('[data-close]');await click('#step');await click('#cancelOrders');
    for(const tab of ['strategy','report','news','positions'])await click(`[data-tab="${tab}"]`);
    doc.querySelector('#recordName').value='UI regression';await click('#renameRecord');await click('#save');
    await click('#saveCode');await click('#openCode');await click('#runStrategy');await click('#stopStrategy');
    await click('#branch');await click('#save');
    await click('#batch');await click('#cancelBatch');await new Promise(r=>setTimeout(r,1100));await settle();
    // Export, finishes and restoration remain functional after the batch ends.
    await click('#finish');await click('#finishClose');await click('#export');await click('#exportCsv');await click('#exportPng');await click('#exportHtml');assert(exports>=(bridge?4:3));
    change('#saved',doc.querySelector('#saved option[value]:not([value=""])').value);await click('#restore');
    doc.querySelector('#start').value='1900-01-01';await click('#create',true);assert.match(doc.querySelector('#status').textContent,/覆盖|最多/);await click('#step');
    change('#asset','TESTUSD');assert.notEqual(doc.querySelector('#start').value,'1900-01-01');
    await click('#updateData');
    doc.querySelector('#selectAllRecords').click();await click('#deleteRecords');assert.equal(doc.querySelector('#deleteConfirm').hidden,false);await click('#cancelDelete');
    await click('#deleteRecords');await click('#confirmDelete');assert.equal((await (await fetch(base+'/api/saved')).json()).length,0);assert.match(doc.querySelector('#clock').textContent,/尚未开始/);
    await click('#create');assert.match(doc.querySelector('#status').textContent,/记录已创建/);
    // Leave the disposable backend clean for the next transport mode.
    const files=(await (await fetch(base+'/api/saved')).json()).map(x=>x.file);
    await fetch(base+'/api/saved',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({files})});
    assert(!errors.length,String(errors));console.log(`${bridge?'VS Code bridge':'Browser HTTP'}: all button bindings, create, indicators, checkbox, queued actions, trading, strategy, reports, restore, delete and warmup PASS (${calls.length} API requests)`);
   }finally{dom.window.close();}
  }
 }finally{backend.kill();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
