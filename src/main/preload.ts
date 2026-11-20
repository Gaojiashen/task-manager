import { contextBridge, ipcRenderer } from 'electron';
import type { WidgetAPI } from '../shared/widget';
import type { MailAPI } from '../shared/mail';
import type { DesktopAPI } from '../shared/contracts';
const invoke=(name:keyof DesktopAPI,...args:unknown[])=>ipcRenderer.invoke('backend:'+name,...args);
const api:DesktopAPI={
  getCanvasSource:id=>invoke('getCanvasSource',id), openCanvasOriginal:id=>invoke('openCanvasOriginal',id),
  getCanvasConfig:()=>invoke('getCanvasConfig'), saveCanvasFeed:url=>invoke('saveCanvasFeed',url),
  clearCanvasFeed:()=>invoke('clearCanvasFeed'), syncCanvas:()=>invoke('syncCanvas'),
  getDayOrder:day=>invoke('getDayOrder',day), setDayOrder:(day,ids)=>invoke('setDayOrder',day,ids),
  listTodos:include=>invoke('listTodos',include), effectiveDue:id=>invoke('effectiveDue',id),
  editTodo:(id,patch,completed,rev)=>invoke('editTodo',id,patch,completed,rev),
  createTodo:value=>invoke('createTodo',value), updateTodo:(id,patch,rev)=>invoke('updateTodo',id,patch,rev),
  moveTodo:(id,parent,rev)=>invoke('moveTodo',id,parent,rev), setCompleted:(id,value,rev)=>invoke('setCompleted',id,value,rev),
  trashTodo:(id,rev)=>invoke('trashTodo',id,rev), restoreBatch:id=>invoke('restoreBatch',id),
  saveDrafts:(drafts,token)=>invoke('saveDrafts',drafts,token),
  getCompletionConfig:()=>invoke('getCompletionConfig'),setCompletionConfig:value=>invoke('setCompletionConfig',value),
  getSettings:()=>invoke('getSettings'), saveSettings:value=>invoke('saveSettings',value),clearKey:()=>invoke('clearKey'),
  importText:()=>invoke('importText'),extract:text=>invoke('extract',text),exportBackup:()=>invoke('exportBackup'),importBackup:()=>invoke('importBackup'),
};
contextBridge.exposeInMainWorld('desktop',Object.freeze(api));

const widget: WidgetAPI = {
  getState: () => ipcRenderer.invoke('widget:getState'),
  setEnabled: enabled => ipcRenderer.invoke('widget:setEnabled', enabled),
  setExpanded: expanded => ipcRenderer.invoke('widget:setExpanded', expanded),
  setPointerPassthrough: ignore => ipcRenderer.invoke('widget:setPointerPassthrough',ignore),
  moveBy: (dx, dy) => ipcRenderer.invoke('widget:moveBy', dx, dy),
  minimizeToTray: () => ipcRenderer.invoke('widget:minimizeToTray'),
  close: () => ipcRenderer.invoke('widget:close'),
  showMain: () => ipcRenderer.invoke('widget:showMain'),
  quit: () => ipcRenderer.invoke('widget:quit'),
  onChanged: callback => {
    const listener = () => callback();
    ipcRenderer.on('desktop:changed', listener);
    return () => { ipcRenderer.removeListener('desktop:changed', listener); };
  },
};
contextBridge.exposeInMainWorld('widget', Object.freeze(widget));

const mailInvoke=(name:keyof MailAPI,...args:unknown[])=>ipcRenderer.invoke('mail:'+name,...args);
const mail:MailAPI={
  getState:()=>mailInvoke('getState'),selectMethod:method=>mailInvoke('selectMethod',method),configureImap:input=>mailInvoke('configureImap',input),configure:id=>mailInvoke('configure',id),connect:()=>mailInvoke('connect'),disconnect:()=>mailInvoke('disconnect'),
  listFolders:parent=>mailInvoke('listFolders',parent),saveFilter:filter=>mailInvoke('saveFilter',filter),read:filter=>mailInvoke('read',filter),
  getMessage:id=>mailInvoke('getMessage',id),openMessage:id=>mailInvoke('openMessage',id),extract:(id,target)=>mailInvoke('extract',id,target),
};
contextBridge.exposeInMainWorld('mail',Object.freeze(mail));

import type { PreferencesAPI } from '../shared/preferences';
const preferences:PreferencesAPI={get:()=>ipcRenderer.invoke('preferences:get'),save:value=>ipcRenderer.invoke('preferences:save',value)};
contextBridge.exposeInMainWorld('preferences',Object.freeze(preferences));

const workspaceInvoke=(name:keyof import('../shared/mail-workspace').MailWorkspaceAPI,...args:unknown[])=>ipcRenderer.invoke('mail-workspace:'+name,...args);
const workspace:import('../shared/mail-workspace').MailWorkspaceAPI={
 listPresets:id=>workspaceInvoke('listPresets',id),savePreset:(id,input)=>workspaceInvoke('savePreset',id,input),deletePreset:id=>workspaceInvoke('deletePreset',id),knownSenders:id=>workspaceInvoke('knownSenders',id),
 listFoldersLocal:()=>workspaceInvoke('listFoldersLocal'),createLocalFolder:name=>workspaceInvoke('createLocalFolder',name),renameLocalFolder:(id,name)=>workspaceInvoke('renameLocalFolder',id,name),deleteLocalFolder:id=>workspaceInvoke('deleteLocalFolder',id),moveLocal:(ids,folder)=>workspaceInvoke('moveLocal',ids,folder),deleteLocal:ids=>workspaceInvoke('deleteLocal',ids),
 getAccounts:()=>workspaceInvoke('getAccounts'),addAccount:method=>workspaceInvoke('addAccount',method),removeAccount:id=>workspaceInvoke('removeAccount',id),getAccount:id=>workspaceInvoke('getAccount',id),
 configureImap:(id,input)=>workspaceInvoke('configureImap',id,input),configureMicrosoft:(id,clientId)=>workspaceInvoke('configureMicrosoft',id,clientId),
 connect:id=>workspaceInvoke('connect',id),disconnect:id=>workspaceInvoke('disconnect',id),listFolders:(id,parent)=>workspaceInvoke('listFolders',id,parent),
 saveFilter:(id,filter)=>workspaceInvoke('saveFilter',id,filter),importMail:input=>workspaceInvoke('importMail',input),
 listLocal:query=>workspaceInvoke('listLocal',query),getLocal:id=>workspaceInvoke('getLocal',id),openOriginal:id=>workspaceInvoke('openOriginal',id),
 analyze:input=>workspaceInvoke('analyze',input),getAnalysis:id=>workspaceInvoke('getAnalysis',id),saveAnalysis:(id,drafts)=>workspaceInvoke('saveAnalysis',id,drafts),
};
contextBridge.exposeInMainWorld('mailWorkspace',Object.freeze(workspace));

const operationsInvoke=(name:keyof import('../shared/mail-operations').MailOperationsAPI,...args:unknown[])=>ipcRenderer.invoke('mail-operations:'+name,...args);
const operations:import('../shared/mail-operations').MailOperationsAPI={
 acknowledgeJob:id=>operationsInvoke('acknowledgeJob',id),
 listJobs:()=>operationsInvoke('listJobs'),getJob:id=>operationsInvoke('getJob',id),startImport:input=>operationsInvoke('startImport',input),startAnalysis:input=>operationsInvoke('startAnalysis',input),
 pauseJob:id=>operationsInvoke('pauseJob',id),resumeJob:id=>operationsInvoke('resumeJob',id),cancelJob:id=>operationsInvoke('cancelJob',id),
 retryImportFailures:input=>operationsInvoke('retryImportFailures',input),retryBodies:input=>operationsInvoke('retryBodies',input),
 listConversations:()=>operationsInvoke('listConversations'),getConversation:id=>operationsInvoke('getConversation',id),
 continueConversation:(id,text,target)=>operationsInvoke('continueConversation',id,text,target),deleteConversation:id=>operationsInvoke('deleteConversation',id),startConversation:(text,target)=>operationsInvoke('startConversation',text,target),
};
contextBridge.exposeInMainWorld('mailOperations',Object.freeze(operations));
