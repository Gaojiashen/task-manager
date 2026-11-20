import type { BrowserWindow, IpcMain } from 'electron';
import { pathToFileURL } from 'node:url';
import { PythonBackend } from './python-backend';
import { pythonChannels } from './python-channels';
import { mutationMethods, rendererAllowed } from './widget-policy';
import type { Result, DesktopAPI } from '../shared/contracts';

interface Backend {call(method: string, ...args: unknown[]): Promise<Result<unknown>>}

export interface PythonDesktopPorts {runtime?:{python:string;backendDirectory:string}; notifyJob?(job:{id:string;kind:string;label:string},acknowledge:()=>void):void;chooseBackup?(): Promise<string | null>; saveBackup?(): Promise<string | null>; chooseText?(): Promise<string | null>; openExternal?(url:string):Promise<void>; decryptLegacy?(cipher:Buffer):Promise<string>}

export async function migratePythonCredentials(backend:Backend, decrypt:(cipher:Buffer)=>Promise<string>):Promise<Result<unknown>> {
  const response=await backend.call('_legacySecrets');
  if (!response.ok) return response;
  for (const entry of response.data as {kind:string;encrypted:string}[]) {
    try {
      const plain=await decrypt(Buffer.from(entry.encrypted,'base64'));
      const result=await backend.call('_migrateLegacySecret',entry.kind,entry.encrypted,plain);
      if (!result.ok) return result;
    } catch {return {ok:false,error:'旧凭据无法迁移，请在当前设备重新保存或授权。'};}
  }
  return {ok:true,data:null};
}

export async function dispatchPython(backend: Backend, trusted: boolean, channel: string, args: unknown[], changed: () => void, ports: PythonDesktopPorts = {}): Promise<Result<unknown>> {
  if (!trusted) return {ok: false, error: '拒绝未知页面请求。'};
  if (!pythonChannels.includes(channel)) return {ok:false,error:'拒绝未知接口。'};
  const method = channel.startsWith('backend:') ? channel.slice('backend:'.length) : channel;
  let result: Result<unknown>;
  try {
    if (method === 'importBackup' || method === 'exportBackup' || method === 'importText') {
      if (args.length) return {ok:false,error:'文件路径只能由桌面对话框选择。'};
      const choose = method === 'importBackup' ? ports.chooseBackup : method === 'exportBackup' ? ports.saveBackup : ports.chooseText;
      if (!choose) return {ok:false,error:'当前环境无法打开文件选择窗口。'};
      const path = await choose();
      if (!path) return {ok:true,data:method === 'importText' ? null : false};
      result = await backend.call(method === 'importBackup' ? 'importBackupFile' : method === 'exportBackup' ? 'exportBackupFile' : 'importTextFile', path);
    } else if (method === 'openCanvasOriginal') {
      const source = await backend.call('getCanvasSource', ...args);
      if (!source.ok) return source;
      const url = new URL((source.data as {url:string} | null)?.url ?? '');
      if (!['http:','https:'].includes(url.protocol) || url.username || url.password || !ports.openExternal) return {ok:false,error:'无法打开Canvas原文链接。'};
      await ports.openExternal(url.href); return {ok:true,data:null};
    } else result = await backend.call(method, ...args);
  } catch {return {ok:false,error:'文件操作或打开外部链接失败，请重试。'};}
  if (result.ok && (mutationMethods.has(method as keyof DesktopAPI) || (channel.startsWith('mail-workspace:') || channel.startsWith('mail-operations:')) && !/:(get|list|known|open)/.test(channel))) changed();
  return result;
}

export function attachPythonDesktop(ipc: IpcMain, getWindows: () => BrowserWindow[], directory: string, rendererFile: string, ports: PythonDesktopPorts = {}) {
  const bridge = new PythonBackend(directory,ports.runtime);
  const prepared=ports.decryptLegacy ? migratePythonCredentials(bridge, ports.decryptLegacy).catch(()=>({ok:false as const,error:'旧凭据迁移失败，请重新保存。'})) : Promise.resolve();
  const allowed = pathToFileURL(rendererFile).href;
  const broadcast = () => getWindows().forEach(window => {if (!window.isDestroyed()) window.webContents.send('desktop:changed');});
  const notified=new Set<string>();
  let lastJobs='';
  for (const channel of pythonChannels) {
    ipc.handle(channel, async (event, ...args) => {
      const source = getWindows().find(window => !window.isDestroyed() && event.sender === window.webContents);
      const trusted = !!source && event.senderFrame === source.webContents.mainFrame && rendererAllowed(event.senderFrame.url, allowed);
      if (trusted) await prepared;
      const result=await dispatchPython(bridge, trusted, channel, args, broadcast, ports);
      if (trusted && channel==='mail-operations:listJobs' && result.ok) {
        const jobs=result.data as {id:string;kind:string;label:string;state:string;notificationAcknowledged?:boolean}[];
        const snapshot=JSON.stringify(jobs);
        if (lastJobs && lastJobs!==snapshot) broadcast();
        lastJobs=snapshot;
        for (const job of jobs) if (['completed','failed','canceled'].includes(job.state) && !job.notificationAcknowledged && !notified.has(job.id)) {
          notified.add(job.id);
          ports.notifyJob?.(job,()=>{void bridge.call('mail-operations:acknowledgeJob',job.id).then(()=>broadcast());});
        }
      }
      return result;
    });
  }
  return {broadcast, dispose: async () => {
    for (const channel of pythonChannels) ipc.removeHandler(channel);
    await bridge.dispose();
  }};
}
