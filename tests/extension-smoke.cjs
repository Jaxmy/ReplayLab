/* Exercise the actual extension entry point, Webview bridge and editor path with a VS Code API stub. */
const fs=require('fs'),vm=require('vm'),path=require('path'),assert=require('assert');
const root=path.resolve(__dirname,'..');let open,message,openedCode,savedBytes;
const panel={webview:{cspSource:'vscode-webview://test',asWebviewUri:u=>u.path,postMessage:m=>{message=m;}},onDidDispose(){},reveal(){}};
panel.webview.onDidReceiveMessage=callback=>panel.receive=callback;
const vscode={Uri:{file:p=>({path:p}),joinPath:(u,...p)=>({path:path.join(u.path,...p)})},ViewColumn:{One:1,Beside:2},ProgressLocation:{Notification:15},
 workspace:{getConfiguration:()=>({get:()=>root}),fs:{writeFile:async(uri,bytes)=>{savedBytes=bytes;}}},commands:{registerCommand:(id,callback)=>{open=callback;return {dispose(){}};}},
 window:{createOutputChannel:()=>({append(){},appendLine(){},show(){},dispose(){}}),withProgress:(_,f)=>f(),createWebviewPanel:()=>panel,
   showSaveDialog:async()=>({path:'report.png'}),showTextDocument:uri=>{openedCode=uri.path;},showErrorMessage:m=>{throw Error(m);},setStatusBarMessage(){}}};
const context={exports:{},module:{exports:{}},require:n=>n==='vscode'?vscode:require(n),fetch,setTimeout,console,Buffer};
vm.runInNewContext(fs.readFileSync(path.join(root,'vscode','extension.js'),'utf8'),context);
(async()=>{context.module.exports.activate({extensionPath:path.join(root,'vscode'),extensionUri:{path:path.join(root,'vscode')},subscriptions:[]});await open();
 assert(panel.webview.html.includes('Content-Security-Policy'));assert(!panel.webview.html.includes('src="/static/'));
 await panel.receive({id:1,path:'/api/catalog',method:'GET'});assert(Array.isArray(message.data)&&message.data.length>=14);
 await panel.receive({action:'openCode',name:'01_sma_cross.py'});assert( openedCode===path.join(root,'strategies','01_sma_cross.py'));
 await panel.receive({id:2,path:'https://example.com',method:'GET'});assert(message.error);
 await panel.receive({action:'exportImage',filename:'replay-report.png',dataUrl:'data:image/png;base64,aGVsbG8='});assert(savedBytes.toString()==='hello');
 await panel.receive({action:'exportFile',filename:'replay-report.html',text:'<!doctype html><title>test</title>'});assert(savedBytes.toString().includes('<title>test</title>'));
 assert(fs.readFileSync(path.join(root,'web','app.js'),'utf8')===fs.readFileSync(path.join(root,'vscode','media','app.js'),'utf8'));
 console.log('Extension entry point, shared assets, CSP, local API, editor, PNG/HTML saving and URL rejection: PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
