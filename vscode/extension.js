const vscode=require('vscode'),fs=require('fs'),path=require('path'),cp=require('child_process');
let child=null,panel=null;
async function health(){let h;try{const r=await fetch('http://127.0.0.1:8765/api/health');h=await r.json();}catch{return false;}if(h.ok&&h.version!=='0.3.1')throw Error('本地服务版本不匹配；请在项目目录运行 stop.ps1 后重新启动，再重新打开练习面板');return h.ok&&h.engine==='NautilusTrader 1.231.0'&&h.version==='0.3.1';}
async function ensureServer(root,output){
 if(await health())return;
 const python=path.join(root,'.venv','Scripts','python.exe');if(!fs.existsSync(python))throw Error('找不到项目 Python 环境: '+python);
 child=cp.spawn(python,['-m','uvicorn','app.server:app','--host','127.0.0.1','--port','8765'],{cwd:root,windowsHide:true});
 child.stdout.on('data',b=>output.append(b.toString()));child.stderr.on('data',b=>output.append(b.toString()));
 child.on('error',e=>output.appendLine(e.message));
 for(let i=0;i<100;i++){await new Promise(r=>setTimeout(r,300));if(await health())return;}
 throw Error('服务启动超时，请查看 Replay Lab 输出窗口');
}
function activate(context){
 const output=vscode.window.createOutputChannel('Replay Lab');context.subscriptions.push(output);
 context.subscriptions.push(vscode.commands.registerCommand('replayLab.open',async()=>{
 try{
 const root=vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
 if(!root)throw Error('请先在 VS Code 中打开 Replay Lab 项目文件夹');
 await vscode.window.withProgress({location:vscode.ProgressLocation.Notification,title:'正在启动本地回放服务'},()=>ensureServer(root,output));
 if(panel){panel.reveal();return;}
 panel=vscode.window.createWebviewPanel('replayLab','Replay Lab · 交易练习',vscode.ViewColumn.One,{enableScripts:true,retainContextWhenHidden:true,localResourceRoots:[vscode.Uri.joinPath(context.extensionUri,'media')]});
 panel.onDidDispose(()=>{panel=null;});
 let html=fs.readFileSync(path.join(context.extensionPath,'media','index.html'),'utf8');
 for(const name of ['style.css','lightweight-charts.js','app.js'])html=html.replace('/static/'+name,panel.webview.asWebviewUri(vscode.Uri.joinPath(context.extensionUri,'media',name)).toString());
 html=html.replace('<meta charset="utf-8">',`<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${panel.webview.cspSource} data:; style-src ${panel.webview.cspSource} 'unsafe-inline'; script-src ${panel.webview.cspSource};">`);
 panel.webview.html=html;
 panel.webview.onDidReceiveMessage(async m=>{
  try{
   if(m.action==='openCode'){
    if(typeof m.name!=='string'||path.basename(m.name)!==m.name||!m.name.endsWith('.py'))throw Error('无效策略文件');
    await vscode.window.showTextDocument(vscode.Uri.file(path.join(root,'strategies',m.name)),{viewColumn:vscode.ViewColumn.Beside});return;
   }
   if(m.action==='exportImage'||m.action==='exportFile'){
    const png=m.action==='exportImage';
    if(png&&(!/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(m.dataUrl)||m.dataUrl.length>15000000))throw Error('无效报告图片');
    if(!png&&(m.filename!=='replay-report.html'||typeof m.text!=='string'||m.text.length>30000000))throw Error('无效报告文件');
    const dest=await vscode.window.showSaveDialog({defaultUri:vscode.Uri.file(path.join(root,'reports',png?'replay-report.png':'replay-report.html')),filters:png?{PNG:['png']}:{HTML:['html']}});
    if(dest)await vscode.workspace.fs.writeFile(dest,png?Buffer.from(m.dataUrl.split(',')[1],'base64'):Buffer.from(m.text));return;
   }
   if(m.action==='export'){
    const csv=m.data?.filename==='replay-events.csv';
    const dest=await vscode.window.showSaveDialog({defaultUri:vscode.Uri.file(path.join(root,'reports',csv?'replay-events.csv':'replay-report.json')),filters:csv?{CSV:['csv']}:{JSON:['json']}});
    if(dest)await vscode.workspace.fs.writeFile(dest,Buffer.from(csv?m.data.text:JSON.stringify(m.data,null,2)));return;
   }
   if(typeof m.path!=='string'||!m.path.startsWith('/api/')||m.path.includes('..')||!['GET','POST','DELETE'].includes(m.method))throw Error('无效 API 请求');
   const r=await fetch('http://127.0.0.1:8765'+m.path,{method:m.method,headers:{'Content-Type':'application/json'},body:m.body===undefined?undefined:JSON.stringify(m.body)});
   const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail));
   panel?.webview.postMessage({id:m.id,data:d});
  }catch(e){panel?.webview.postMessage({id:m.id,error:e.message});vscode.window.setStatusBarMessage('Replay Lab: '+e.message,5000);}
 });
 }catch(e){output.show();vscode.window.showErrorMessage(e.message);}
 }));
}
function deactivate(){if(child)child.kill();}
module.exports={activate,deactivate};
