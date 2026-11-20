// 实际窗口验证：独立开发数据目录，不读取发布包 data；截图与 DOM 断言同时记录。
const {app,BrowserWindow}=require('electron');
const fs=require('fs');
const path=require('path');
const {DatabaseSync}=require('node:sqlite');
const {randomUUID}=require('node:crypto');
const project=path.resolve(__dirname,'..');
const data=path.join(project,'data');
if(process.env.VERIFY_V2_ALLOW_DATA_RESET!=='1'){console.error('VERIFY_ABORT: 该脚本会重建开发目录 data。设置 VERIFY_V2_ALLOW_DATA_RESET=1 后再运行。');process.exit(2);}
fs.rmSync(data,{recursive:true,force:true});
fs.mkdirSync(path.join(data,'backups'),{recursive:true});
fs.writeFileSync(path.join(data,'application-preferences.json'),JSON.stringify({launchAtLogin:false,widgetOnLaunch:true,closeBehavior:'tray'}));
const {TaskRepository}=require('../dist-backend/main/repository');
const {MailWorkspaceStore}=require('../dist-backend/main/mail-workspace');
const {localDay}=require('../dist-backend/shared/planner');
const repo=new TaskRepository(path.join(data,'tasks.sqlite'));
const today=localDay(new Date());
const root=repo.create({title:'准备课程展示',notes:'周五前完成。',due:{mode:'value',value:{kind:'date',date:today}}}).value;
const prep=repo.create({title:'整理讲稿',notes:'保留例子。',parentId:root.id,due:{mode:'inherit'}}).value;
repo.create({title:'补充演示截图',notes:'截取关键页面。',parentId:prep.id,due:{mode:'inherit'}});
repo.create({title:'核对教室设备',notes:'投影与转接头。',parentId:root.id,due:{mode:'value',value:{kind:'date',date:today}}});
repo.create({title:'阅读《设计的法则》',notes:'每天十分钟。',due:{mode:'none'}});
repo.close();
const store=new MailWorkspaceStore(data);
const mail=store.put('verify-binding','verify-identity','verify@example.com',{id:'remote-verify',subject:'课程项目邮件',sender:'teacher@school.edu',receivedAt:new Date().toISOString(),preview:'课程展示要求与材料',body:'课程展示要求：准备十分钟讲解，保留演示截图，并在周五前完成。正文其余部分尚未完整读取。',bodyStatus:'partial',bodyNote:'已保存已读取的前10MB，可继续补读。',attachments:[{name:'展示要求.pdf',type:'application/pdf',size:184320,inline:false}],unread:false,webUrl:'',imported:false});
store.saveAnalysis({id:randomUUID(),messageIds:[mail.localId],instructions:'整理课程展示待办',notes:'根据邮件整理出展示准备事项。',drafts:[
 {tempId:'p',parentTempId:null,title:'准备课程展示',notes:'本地邮件：课程项目邮件',due:{mode:'value',value:{kind:'date',date:today}},source:'邮件要求周五前完成'},
 {tempId:'c',parentTempId:'p',title:'整理十分钟讲稿',notes:'本地邮件：课程项目邮件',due:{mode:'inherit'},source:'保留例子'},
 {tempId:'x',parentTempId:null,title:'核对教室设备',notes:'本地邮件：课程项目邮件',due:{mode:'value',value:{kind:'date',date:today}},source:'投影与转接头'},
],createdAt:new Date().toISOString(),saved:false,complete:true,model:'verify-model',baseUrl:'https://example.org/v1'});
store.close();
const {startDesktop}=require('../dist-backend/main/main.js');
startDesktop();
const shotDir=path.join(project,'docs','verification');
fs.mkdirSync(shotDir,{recursive:true});
let mainWindow,widgetWindow;
function sleep(ms){return new Promise(resolve=>setTimeout(resolve,ms));}
async function waitFor(fn,timeout=15000){const end=Date.now()+timeout;while(Date.now()<end){const value=await fn();if(value)return value;await sleep(100);}throw new Error('等待超时');}
async function page(win,code){return win.webContents.executeJavaScript(`(async()=>{${code}})()`,true);}
async function shot(win,name){const image=await win.capturePage();fs.writeFileSync(path.join(shotDir,name),image.toPNG());return name;}
function insertFailureJob(){
 const db=new DatabaseSync(path.join(data,'mail-operations.sqlite'));
 try{
  const id=randomUUID();
  const payload={id,kind:'import',label:'导入课程邮件',state:'failed',done:2,total:3,createdAt:new Date().toISOString(),updatedAt:new Date().toISOString(),error:'部分邮件未能完成，可重试。',notificationAcknowledged:false,
   report:{added:2,skipped:0,failed:1,limited:false,errors:[],bodyRead:1,bodyPending:0,pendingLocalIds:[],mailboxErrors:[],failures:[{key:'verify-key',bindingId:'verify-binding',mailboxEmail:'verify@example.com',remoteId:'remote-failed',identity:'verify-identity',subject:'未完成的课程通知',sender:'assistant@school.edu',receivedAt:new Date().toISOString(),stage:'transfer',code:'TRANSFER_RETRY_FAILED',reason:'下载正文中断，已自动重试一次仍失败。',retryable:true}]},
   work:{input:{bindingIds:['verify-binding'],onlyNew:true},cursor:1}};
  db.prepare('INSERT INTO jobs VALUES(?,?)').run(id,JSON.stringify(payload));
  return id;
 }finally{db.close();}
}
app.whenReady().then(async()=>{
 try{
  await waitFor(()=>{const windows=BrowserWindow.getAllWindows();return windows.length>=2&&windows.some(win=>win.webContents.getURL().includes('widget=1'))&&windows.some(win=>!win.webContents.getURL().includes('widget=1'));},30000);
  const windows=BrowserWindow.getAllWindows();
  widgetWindow=windows.find(win=>win.webContents.getURL().includes('widget=1'));
  mainWindow=windows.find(win=>!win.webContents.getURL().includes('widget=1'));
  if(!widgetWindow||!mainWindow)throw new Error('未创建主窗口或悬浮窗');
  await waitFor(async()=>{try{return await mainWindow.webContents.executeJavaScript('!!document.querySelector(\'.planner-app\')',true);}catch{return false;}},20000);
  await waitFor(async()=>{try{return await widgetWindow.webContents.executeJavaScript('!!document.querySelector(\'.crow-widget\')',true);}catch{return false;}},20000);
  await sleep(1200);
  await page(widgetWindow,`const wait=(fn)=>new Promise((resolve,reject)=>{const end=Date.now()+12000;const tick=()=>{if(fn())return resolve(true);if(Date.now()>end)return reject(new Error('widget timeout'));setTimeout(tick,100);};tick();});await wait(()=>document.querySelector('.crow-bird'));`);
  await page(widgetWindow,`const birds=[...document.querySelectorAll('.crow-bird')];const bird=birds.find(b=>b.getAttribute('aria-label')?.includes('准备课程展示'));if(!bird)throw new Error('找不到课程展示乌鸦');bird.click();return true;`);
  await sleep(700);
  const widgetState=await page(widgetWindow,`const wait=(fn)=>new Promise((resolve,reject)=>{const end=Date.now()+12000;const tick=()=>{if(fn())return resolve(true);if(Date.now()>end)return reject(new Error('widget timeout'));setTimeout(tick,100);};tick();});await wait(()=>document.querySelector('.crow-subtasks'));const area=document.querySelector('.crow-subtasks');const slots=[...document.querySelectorAll('.crow-slot')].map(s=>s.getAttribute('data-slot')+':'+s.getAttribute('style'));const rows=[...document.querySelectorAll('.crow-subtask-row')].map(r=>r.textContent);const before=slots.join('|');const edit=[...document.querySelectorAll('.crow-subtask-edit')].find(b=>b.getAttribute('aria-label')?.includes('整理讲稿'));edit.click();await wait(()=>document.querySelector('.crow-edit'));const input=document.querySelector('.crow-edit input');if(!input.value.includes('整理讲稿'))throw new Error('编辑未预填: '+input.value);Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'整理讲稿（不应保存）');input.dispatchEvent(new Event('input',{bubbles:true}));[...document.querySelectorAll('.crow-edit button')].find(b=>b.textContent.trim()==='取消').click();await wait(()=>document.querySelector('.crow-detail'));const title=document.querySelector('.crow-detail h3')?.textContent??'';const after=[...document.querySelectorAll('.crow-slot')].map(s=>s.getAttribute('data-slot')+':'+s.getAttribute('style')).join('|');if(before!==after)throw new Error('子任务编辑改变了乌鸦站位');const toggle=[...document.querySelectorAll('.crow-subtask-toggle')].find(b=>b.getAttribute('aria-label')?.includes('准备课程展示'));const rowsBefore=document.querySelectorAll('.crow-subtask-row').length;toggle.click();await new Promise(r=>setTimeout(r,100));const rowsCollapsed=document.querySelectorAll('.crow-subtask-row').length;toggle.click();await new Promise(r=>setTimeout(r,100));return {rows,before,after,title,rowsBefore,rowsCollapsed,maxHeight:getComputedStyle(document.querySelector('.crow-subtasks')).maxHeight,overflow:getComputedStyle(document.querySelector('.crow-subtasks')).overflowY,scrollHeight:document.querySelector('.crow-subtasks').scrollHeight,clientHeight:document.querySelector('.crow-subtasks').clientHeight};`);
  await shot(widgetWindow,'v2-widget-subtasks.png');
  insertFailureJob();
  await page(mainWindow,`const wait=(fn)=>new Promise((resolve,reject)=>{const end=Date.now()+15000;const tick=()=>{if(fn())return resolve(true);if(Date.now()>end)return reject(new Error('main timeout'));setTimeout(tick,100);};tick();});const click=(text)=>{const el=[...document.querySelectorAll('button')].find(b=>b.textContent.trim().includes(text));if(!el)throw new Error('找不到按钮 '+text);el.click();return true;};await wait(()=>[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='邮箱'));click('邮箱');await wait(()=>document.querySelector('.mw-panel'));await wait(()=>document.querySelector('.mw-jobs'));return true;`);
  await sleep(600);
  await shot(mainWindow,'v2-mail-failure-details.png');
  await page(mainWindow,`const details=[...document.querySelectorAll('.mw-jobs .mw-job-failures')];if(!details.length)throw new Error('失败明细未显示');details[0].open=true;return true;`);
  await sleep(200);
  await shot(mainWindow,'v2-mail-failure-open.png');
  const reviewReady=await page(mainWindow,`const wait=(fn)=>new Promise((resolve,reject)=>{const end=Date.now()+15000;const tick=()=>{if(fn())return resolve(true);if(Date.now()>end)return reject(new Error('review timeout'));setTimeout(tick,100);};tick();});const click=(text)=>{const el=[...document.querySelectorAll('button')].find(b=>b.textContent.trim().includes(text));if(!el)throw new Error('找不到按钮 '+text);el.click();return true;};click('AI 对话历史');await wait(()=>document.querySelector('.mw-history'));await wait(()=>[...document.querySelectorAll('.mw-history button')].some(b=>b.textContent.includes('整理课程展示待办')));[...document.querySelectorAll('.mw-history button')].find(b=>b.textContent.includes('整理课程展示待办')).click();await wait(()=>[...document.querySelectorAll('button')].some(b=>b.textContent.includes('审核本轮待办草稿')));click('审核本轮待办草稿');await wait(()=>document.querySelector('.tools-panel'));await wait(()=>document.querySelector('.tools-draft'));return true;`);
  await sleep(200);
  await shot(mainWindow,'v2-review-modal.png');
  const review=await page(mainWindow,`const wait=(fn)=>new Promise((resolve,reject)=>{const end=Date.now()+15000;const tick=()=>{if(fn())return resolve(true);if(Date.now()>end)return reject(new Error('review timeout'));setTimeout(tick,100);};tick();});const click=(text)=>{const el=[...document.querySelectorAll('button')].find(b=>b.textContent.trim().includes(text));if(!el)throw new Error('找不到按钮 '+text);el.click();return true;};const input=document.querySelector('.tools-draft input:not([type="checkbox"])');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'准备课程展示（已编辑）');input.dispatchEvent(new Event('input',{bubbles:true}));await new Promise(r=>setTimeout(r,150));document.querySelector('.tools-backdrop').dispatchEvent(new MouseEvent('click',{bubbles:true}));await wait(()=>!document.querySelector('.tools-panel'));const focusText=document.activeElement?.textContent??'';click('审核本轮待办草稿');await wait(()=>document.querySelector('.tools-panel'));const restored=document.querySelector('.tools-draft input:not([type="checkbox"])').value;const all=[...document.querySelectorAll('.tools-panel button')].find(b=>b.textContent.includes('全部添加（3 项）'));if(!all)throw new Error('没有全部添加按钮');all.click();await wait(()=>!document.querySelector('.tools-panel'));const result=await window.desktop.listTodos(true);if(!result.ok)throw new Error(result.error);const todos=result.data;const live=todos.filter(t=>!t.deletedAt);const byId=new Map(live.map(t=>[t.id,t]));const added=live.filter(t=>(t.notes||'').includes('本地邮件：')).map(t=>({title:t.title,parent:byId.get(t.parentId)?.title??null,notes:t.notes}));return {focusText,restored,titles:live.map(t=>t.title),added};`);
  await shot(mainWindow,'v2-all-add-result.png');
  const afterAdd=await page(mainWindow,`const wait=(fn)=>new Promise((resolve)=>{const end=Date.now()+8000;const tick=()=>{if(fn()||Date.now()>end)return resolve(!!fn());setTimeout(tick,100);};tick();});await wait(()=>document.querySelector('.mw-panel'));return {panel:!!document.querySelector('.mw-panel')};`);
  if(widgetState.title!=='整理讲稿'||widgetState.rowsBefore!==4||widgetState.rowsCollapsed!==1||widgetState.before!==widgetState.after||widgetState.maxHeight!=='190px'||widgetState.overflow!=='auto'||widgetState.scrollHeight<widgetState.clientHeight)throw new Error('子任务区域验证失败 '+JSON.stringify(widgetState));
  if(review.restored!=='准备课程展示（已编辑）')throw new Error('关闭后草稿没有保留');
  if(!review.focusText.includes('审核本轮待办草稿'))throw new Error('关闭审核后焦点没有回到原入口: '+review.focusText.slice(0,80));
  if(review.titles.filter(t=>t==='准备课程展示（已编辑）').length!==1||review.titles.filter(t=>t==='整理十分钟讲稿').length!==1||review.titles.filter(t=>t==='核对教室设备').length!==2)throw new Error('全部添加结果不正确 '+JSON.stringify(review.titles));
  if(review.added.length!==3||review.added.find(t=>t.title==='整理十分钟讲稿')?.parent!=='准备课程展示（已编辑）'||!review.added.every(t=>t.notes.includes('本地邮件：')))throw new Error('全部添加层级或来源不正确 '+JSON.stringify(review.added));
  console.log('VERIFY_JSON='+JSON.stringify({widgetState,review,afterAdd}));
  await shot(mainWindow,'v2-main-review-saved.png');
  const bodyState=await page(mainWindow,`const wait=(fn)=>new Promise((resolve,reject)=>{const end=Date.now()+12000;const tick=()=>{if(fn())return resolve(true);if(Date.now()>end)return reject(new Error('body timeout'));setTimeout(tick,100);};tick();});const click=(text)=>{const el=[...document.querySelectorAll('button')].find(b=>b.textContent.trim().includes(text));if(!el)throw new Error('找不到按钮 '+text);el.click();return true;};if([...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='返回邮件'))click('返回邮件');await wait(()=>[...document.querySelectorAll('.mw-row button')].some(b=>b.textContent.includes('课程项目邮件')));[...document.querySelectorAll('.mw-row button')].find(b=>b.textContent.includes('课程项目邮件')).click();await wait(()=>document.querySelector('.mw-body'));const status=document.querySelector('.mw-body-status')?.textContent;const attachment=document.querySelector('.mw-attachments')?.textContent;const body=document.querySelector('.mw-body')?.textContent;click('在阅读窗格查看全文');await wait(()=>document.querySelector('.mw-body-reader'));return {status,attachment,bodyPreview:body?.slice(0,40),reader:!!document.querySelector('.mw-body-reader')};`);
  await shot(mainWindow,'v2-mail-body-reader.png');
  await page(mainWindow,`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));return true;`);
  if(bodyState.status!=='正文尚未完整'||!bodyState.attachment?.includes('展示要求.pdf')||!bodyState.reader)throw new Error('正文状态/附件/阅读窗格验证失败 '+JSON.stringify(bodyState));
  console.log('VERIFY_BODY='+JSON.stringify(bodyState));
  console.log('VERIFY_PASS');
  app.exit(0);
 }catch(error){
  console.error('VERIFY_FAIL',error.stack||error.message);
  try{if(mainWindow&&!mainWindow.isDestroyed())await shot(mainWindow,'v2-failure-main.png');if(widgetWindow&&!widgetWindow.isDestroyed())await shot(widgetWindow,'v2-failure-widget.png');}catch{}
  app.exit(1);
 }
});
