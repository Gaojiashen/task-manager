import test from 'node:test';
import assert from 'node:assert/strict';
import { dispatchPython } from '../src/main/python-desktop';

test('Python desktop dispatcher rejects untrusted frames before execution', async () => {
  let calls = 0;
  const backend = {call: async () => {calls++; return {ok:true as const,data:[]};}};
  const result = await dispatchPython(backend, false, 'backend:listTodos', [], () => {});
  assert.equal(result.ok, false);
  assert.equal(calls, 0);
});

test('successful task mutation broadcasts while reads and failures do not', async () => {
  let broadcasts = 0;
  const backend = {call: async (method:string) => method === 'updateTodo' ? {ok:false as const,error:'conflict'} : {ok:true as const,data:[]}};
  const changed = () => broadcasts++;
  await dispatchPython(backend, true, 'backend:listTodos', [], changed);
  await dispatchPython(backend, true, 'backend:createTodo', [{title:'a'}], changed);
  await dispatchPython(backend, true, 'backend:updateTodo', [], changed);
  assert.equal(broadcasts, 1);
  const unavailable = await dispatchPython(backend, true, 'mail:startAnalysis', [], changed);
  assert.equal(unavailable.ok, false);
  assert.equal(broadcasts, 1);
});

test('backup dialogs supply paths and renderer cannot supply arbitrary file paths', async () => {
  const calls:unknown[]=[];
  const backend={call:async(...args:unknown[])=>{calls.push(args);return {ok:true as const,data:true};}};
  const ports={chooseBackup:async()=>'/selected.json',saveBackup:async()=>'/export.json'};
  let broadcasts=0;
  assert.equal((await dispatchPython(backend,true,'backend:importBackup',[],()=>broadcasts++,ports)).ok,true);
  assert.deepEqual(calls,[['importBackupFile','/selected.json']]);
  assert.equal(broadcasts,1);
  assert.equal((await dispatchPython(backend,true,'backend:exportBackup',['/untrusted'],()=>{},ports)).ok,false);
  assert.equal((await dispatchPython(backend,true,'backend:importBackupFile',['/untrusted'],()=>{},ports)).ok,false);
  assert.equal(calls.length,1);
});
