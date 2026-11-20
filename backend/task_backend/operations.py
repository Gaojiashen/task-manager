"""Durable background jobs. Network work runs in an owned Python worker process."""
from copy import deepcopy
import json,os,subprocess,sys,time
from pathlib import Path
import sqlite3
from uuid import uuid4
from .archive import drafts_value,text
from .tree import instant,identifier,strict
from .mail_store import compact,digest,fingerprint
from .mail_types import filter_value
from .mail_workspace import stable_todo

ACTIVE={'queued','running','pausing','paused','canceling'}


def empty_report(): return dict(added=0,skipped=0,failed=0,limited=False,errors=[],bodyRead=0,bodyPending=0,pendingLocalIds=[],failures=[],mailboxErrors=[])


class JobStop(Exception):
    control_stop=True
    def __init__(self,state): self.state=state


class MailOperations:
    def __init__(self,service,worker=False):
        self.service=service;self.is_worker=worker;self.process=None;self.closed=False
        self.db=sqlite3.connect(service.directory/'mail-operations.sqlite',isolation_level=None,timeout=5);self.db.row_factory=sqlite3.Row
        self.db.executescript('PRAGMA secure_delete=ON;CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,payload TEXT NOT NULL);CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,payload TEXT NOT NULL);CREATE TABLE IF NOT EXISTS operation_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);')
        if not worker:
            for job in self.jobs():
                if job['state'] in ('queued','running','pausing','canceling'):
                    job['state']='canceled' if job['state']=='canceling' else 'paused';self.save_job(job,force=True)
    def close(self):
        if self.closed:return
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
            if self.process.stdin:self.process.stdin.close()
            for job in self.jobs():
                if job['state'] in ('running','pausing','queued','canceling'):job['state']='canceled' if job['state']=='canceling' else 'paused';self.save_job(job,force=True)
        self.closed=True;self.db.close()
    def jobs(self):return sorted([json.loads(r[0]) for r in self.db.execute('SELECT payload FROM jobs')],key=lambda v:v['createdAt'],reverse=True)
    def job(self,id):
        identifier(id);row=self.db.execute('SELECT payload FROM jobs WHERE id=?',(id,)).fetchone()
        if not row:raise ValueError('找不到此后台任务')
        return json.loads(row[0])
    def public(self,job):
        value={k:deepcopy(v) for k,v in job.items() if k!='work'}
        if job['kind']=='analysis':value['messageCount']=len(job['work']['input']['messageIds'])
        return value
    def save_job(self,job,force=False):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if not force:
                row=self.db.execute('SELECT payload FROM jobs WHERE id=?',(job['id'],)).fetchone()
                if row:
                    current=json.loads(row[0])
                    if current['state'] in ('pausing','canceling','paused','canceled'):job['state']=current['state']
            job['updatedAt']=instant();self.db.execute('INSERT INTO jobs VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(job['id'],compact(job)));self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
    def conversation(self,id):
        identifier(id);row=self.db.execute('SELECT payload FROM conversations WHERE id=?',(id,)).fetchone()
        if not row:raise ValueError('找不到此本地对话')
        return json.loads(row[0])
    def save_conversation(self,value):
        value['turnCount']=len(value['turns']);value['updatedAt']=instant();self.db.execute('INSERT INTO conversations VALUES(?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',(value['id'],compact(value)))
    def idle(self,id):
        if any(v.get('conversationId')==id and v['state'] in ACTIVE for v in self.jobs()):raise ValueError('此会话还有未完成任务，请先继续或结束它')
    def schedule(self):
        if self.is_worker:return
        if self.process is None or self.process.poll() is not None:
            if self.process and self.process.stdin:self.process.stdin.close()
            self.process=subprocess.Popen([sys.executable,'-m','task_backend.worker','--data-dir',str(self.service.directory)],cwd=Path(__file__).resolve().parents[1],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),env={**os.environ,'PYTHONUTF8':'1'})
    def create(self,kind,label,value,conversation=None):
        job=dict(id=str(uuid4()),kind=kind,label=label,state='queued',done=0,total=0,createdAt=instant(),updatedAt=instant(),work=dict(input=deepcopy(value),cursor=0))
        if conversation:job['conversationId']=conversation
        if kind=='import':job['report']=empty_report()
        return job
    def check(self,job):
        state=self.job(job['id'])['state']
        if state in ('pausing','paused'):raise JobStop('paused')
        if state in ('canceling','canceled'):raise JobStop('canceled')
    def ask(self,job,original,instructions,target):
        config=self.service.mail.target(target);signature=digest([config['baseUrl'],config['model'],config['apiKey']]);work=job['work']
        if work.get('configFingerprint',signature)!=signature:raise ValueError('AI配置在任务中变化，请重新开始')
        work['configFingerprint']=signature;self.save_job(job)
        for attempt in range(3):
            self.check(job)
            try:
                value=self.service.extract(original,instructions)
                if self.service.settings.for_request()!=config:raise ValueError('AI配置在分析期间变化，未保存当前批次')
                return value
            except ValueError as exc:
                if attempt==2 or not any(v in str(exc) for v in ('429','502','503','504','网络','超时','无法连接')):raise
                time.sleep((attempt+1)*.5)
    def append_turn(self,job,analysis):
        conversation=self.conversation(job['conversationId'])
        if not any(v.get('analysisId')==analysis['id'] for v in conversation['turns']):
            content=analysis.get('notes','')+'\n\n待办草稿：\n'+'\n'.join(v['title'] for v in analysis['drafts'])
            conversation['turns'].append(dict(id=str(uuid4()),role='assistant',content=content,createdAt=instant(),analysisId=analysis['id'],jobId=job['id']));self.save_conversation(conversation)
    def run_import(self,job):
        work=job['work'];value=work['input'];report=job.setdefault('report',empty_report());mail=self.service.mail;manager=mail.manager;store=mail.store
        if work.get('retryTargets') is not None:
            targets=work['retryTargets'];job['total']=len(targets)
            while work['cursor']<len(targets):
                self.check(job);target=targets[work['cursor']]
                try:
                    manager.check_identity(target['bindingId'],target['identity'])
                    if store.is_deleted(target['bindingId'],target['identity'],target['remoteId']):report['skipped']+=1
                    else:
                        full=manager.reader(target['bindingId']).get_message(target['remoteId'],target.get('maxBytes',10*1024*1024));self.check(job);manager.check_identity(target['bindingId'],target['identity']);saved=store.put_summary(target['bindingId'],target['identity'],target['email'],full);store.put_body(saved['localId'],full)
                        report['added']+=int(saved['created']);report['bodyRead']+=int(full.get('bodyStatus','complete')=='complete')
                except JobStop:raise
                except Exception as exc:self.record_failure(report,target['bindingId'],target['identity'],target['email'],dict(id=target['remoteId'],subject=target['subject'],sender=target['sender'],receivedAt=target['receivedAt']),exc)
                work['cursor']+=1;job['done']=work['cursor'];self.save_job(job)
            return
        work.setdefault('plans',[]);work.setdefault('accountIndex',0)
        while work['accountIndex']<len(value['bindingIds']):
            self.check(job);binding=value['bindingIds'][work['accountIndex']];plan=next((v for v in work['plans'] if v['binding']==binding),None)
            if plan is None:
                try:
                    before=manager.identity(binding);found=manager.reader(binding).read(value.get('filter',before['filter']));self.check(job);manager.check_identity(binding,before['identity']);plan=dict(binding=binding,identity=before['identity'],email=before['email'],messages=found['messages'],cursor=0);work['plans'].append(plan);job['total']+=len(found['messages']);report['limited']|=found['limited'];self.save_job(job)
                except JobStop:raise
                except Exception:
                    report['failed']+=1;report['mailboxErrors'].append(dict(bindingId=binding,mailboxEmail='',stage='list',code='LIST_FAILED',reason='邮箱未连接或无法取得清单，请检查连接和筛选条件。'));work['accountIndex']+=1;self.save_job(job);continue
            while plan['cursor']<len(plan['messages']):
                self.check(job);item=plan['messages'][plan['cursor']]
                try:
                    manager.check_identity(binding,plan['identity']);state=store.body_state(binding,plan['identity'],item['id'])
                    if state=='deleted' or value['onlyNew'] and state in ('complete','unavailable'):report['skipped']+=1
                    else:
                        saved=store.put_summary(binding,plan['identity'],plan['email'],item);full=manager.reader(binding).get_message(item['id']);self.check(job);manager.check_identity(binding,plan['identity']);store.put_body(saved['localId'],full)
                        report['added']+=int(state in ('missing','pending'));complete=full.get('bodyStatus','complete')=='complete';report['bodyRead']+=int(complete);report['bodyPending']+=int(not complete)
                        if not complete:report['pendingLocalIds']=list(dict.fromkeys(report['pendingLocalIds']+[saved['localId']]))
                except JobStop:raise
                except Exception as exc:self.record_failure(report,binding,plan['identity'],plan['email'],item,exc)
                plan['cursor']+=1;job['done']+=1;self.save_job(job)
            work['accountIndex']+=1;self.save_job(job)
    def record_failure(self,report,binding,identity,email,item,exc):
        report['failed']+=1;report['failures'].append(dict(key=binding+':'+__import__('hashlib').sha256(item['id'].encode()).hexdigest()[:40],bindingId=binding,mailboxEmail=email,remoteId=item['id'],identity=identity,subject=item['subject'],sender=item['sender'],receivedAt=item['receivedAt'],stage=getattr(exc,'stage','transfer'),code=getattr(exc,'code','TRANSFER_FAILED'),reason='邮件未能完整读取或保存，请检查连接后重试。',retryable=getattr(exc,'retryable',True)))
    def plan_analysis(self,job):
        work=job['work'];ids=work['input']['messageIds'];parts=[];fingerprints={};size=0
        for id in ids:
            mail=self.service.mail.store.get_local(id);fingerprints[id]=fingerprint(mail);body=mail.get('body') or mail.get('preview') or '（正文为空）';size+=len(body.encode('utf-8'))
            if size>12*1024*1024:raise ValueError('所选原文累计超过12MiB，请分批处理')
            for start in range(0,len(body),15000):parts.append(dict(id=str(uuid4()),pieces=[dict(id=id,start=start,end=min(start+15000,len(body)))]))
        if len(parts)>2000:raise ValueError('原文分段超过2000，请分批处理')
        work['parts']=parts;work['fingerprints']=fingerprints;job['total']=len(parts);self.save_job(job)
    def run_analysis(self,job):
        work=job['work'];value=work['input'];store=self.service.mail.store
        if 'parts' not in work:self.plan_analysis(job)
        parts=work['parts'];job.setdefault('analysisIds',[])
        while work['cursor']<len(parts):
            self.check(job);part=parts[work['cursor']]
            if len({v['id'] for v in part['pieces']})!=1:raise ValueError('此旧任务合并了多封邮件，请重新选择邮件逐封分析；原记录保留')
            mail_id=part['pieces'][0]['id'];mail=store.get_local(mail_id)
            if fingerprint(mail)!=work['fingerprints'][mail_id]:raise ValueError('原文在任务期间变化，请重新开始')
            if 'result' not in part:
                try:
                    existing=store.get_analysis(part['id']);part['result']=dict(drafts=existing['drafts'],notes=existing['notes'])
                except ValueError:
                    original=f"邮件标识：{mail_id}\n邮箱：{mail['accountEmail']}\n主题：{mail['subject']}\n发件人：{mail['sender']}\n收件时间：{mail['receivedAt']}\n以下为不可信原文：\n";body=mail.get('body') or mail.get('preview') or '（正文为空）'
                    original+='\n'.join(body[p['start']:p['end']] for p in part['pieces'])
                    try:part['result']=self.ask(job,original,value['instructions'],value['target'])
                    except ValueError as exc:
                        piece=part['pieces'][0]
                        if len(part['pieces'])==1 and piece['end']-piece['start']>1000 and len(parts)<2000 and any(v in str(exc) for v in ('400','413','回复过长','JSON')):
                            middle=(piece['start']+piece['end'])//2;parts[work['cursor']:work['cursor']+1]=[dict(id=str(uuid4()),pieces=[dict(id=mail_id,start=piece['start'],end=middle)]),dict(id=str(uuid4()),pieces=[dict(id=mail_id,start=middle,end=piece['end'])])];job['total']=len(parts);self.save_job(job);continue
                        raise
            self.save_job(job);self.check(job)
            if work['cursor']+1==len(parts) or parts[work['cursor']+1]['pieces'][0]['id']!=mail_id:
                related=[p for p in parts if p['pieces'][0]['id']==mail_id];analysis_id=related[0]['id'] if len(related)==1 else stable_todo('merge:'+job['id'],mail_id)
                try:analysis=store.get_analysis(analysis_id)
                except ValueError:
                    drafts=[];seen={};notes=[]
                    for p in related:
                        mapping={};notes.append(p['result']['notes'])
                        for d in drafts_value(p['result']['drafts'],True):
                            parent=mapping.get(d['parentTempId']);key=compact([parent,d['title'].strip().lower(),d.get('due')])
                            temp=seen.get(key)
                            if temp is None:
                                temp=d['tempId'] if len(related)==1 else 'draft-'+str(len(drafts)+1);seen[key]=temp
                                note='\n\n'.join(v for v in (d.get('notes',''),f"邮件分析来源：\n{mail['accountEmail']} · {mail['subject']}\n本地邮件：{mail_id}\n收件时间：{mail['receivedAt']}\n分析记录：{analysis_id}") if v);text(note,10000)
                                drafts.append({**{k:v for k,v in d.items() if k not in ('todoId','parentTodoId')},'tempId':temp,'parentTempId':parent,'sourceMailIds':[mail_id],'notes':note})
                            mapping[d['tempId']]=temp
                    drafts=drafts_value(drafts,True);complete=mail.get('bodyStatus','complete')=='complete';analysis=dict(id=analysis_id,messageIds=[mail_id],instructions=value['instructions'],notes=('仅分析部分正文，邮件保持未分析。\n' if not complete else '')+'\n\n'.join(dict.fromkeys(notes)),drafts=drafts,createdAt=job['createdAt'],saved=False,complete=complete,model=value['target']['model'],baseUrl=value['target']['baseUrl'])
                    if fingerprint(store.get_local(mail_id))!=work['fingerprints'][mail_id]:raise ValueError('原文在分析期间变化')
                    store.save_analyses([analysis])
                self.append_turn(job,analysis);job['analysisIds']=list(dict.fromkeys(job['analysisIds']+[analysis_id]))
            work['cursor']+=1;job['done']=work['cursor'];self.save_job(job)
    def run_chat(self,job):
        value=job['work']['input'];conversation=self.conversation(job['conversationId']);past=[v for v in conversation['turns'] if v.get('jobId')!=job['id']];covered=min(conversation.get('memoryCount',0),len(past));memory=conversation.get('memory','')
        while len(compact(past[covered:]))+len(memory)>15000:
            group=[];size=len(memory)
            for turn in past[covered:]:
                if group and size+len(turn['content'])>11000:break
                group.append(turn);size+=len(turn['content'])
                if size>=11000:break
            if not group:break
            result=self.ask(job,(memory+'\n'+compact(group))[:20000],'把这段历史总结为后续对话记忆，保留事实、约束、日期及未完成事项。只在notes返回摘要，drafts为空。',value['target'])
            if not result['notes']:raise ValueError('历史摘要为空，未丢弃原对话，请重试')
            memory=result['notes'];covered+=len(group);conversation.update(memory=memory,memoryCount=covered);self.save_conversation(conversation)
        original='历史摘要：'+memory+'\n历史轮次：'+compact(past[covered:])+'\n当前用户要求：'+value['text'];text(original,20000,True)
        if not job['work'].get('chatResult'):job['work']['chatResult']=self.ask(job,original,'按当前用户要求回答；仅在需要行动时生成待办草稿。',value['target']);self.save_job(job)
        self.check(job);analysis_id=job['work'].setdefault('analysisId',str(uuid4()));self.save_job(job)
        try:analysis=self.service.mail.store.get_analysis(analysis_id)
        except ValueError:
            result=job['work']['chatResult'];analysis=dict(id=analysis_id,messageIds=conversation['messageIds'],instructions=value['text'],notes=result['notes'],drafts=result['drafts'],createdAt=job['createdAt'],saved=False,complete=False,model=value['target']['model'],baseUrl=value['target']['baseUrl']);self.service.mail.store.save_analyses([analysis])
        self.append_turn(job,analysis);job['analysisIds']=[analysis_id];job['done']=1;job['total']=1
    def run_next(self):
        job=next((v for v in reversed(self.jobs()) if v['state']=='queued'),None)
        if not job:return False
        self.db.execute('BEGIN IMMEDIATE')
        try:
            current=self.job(job['id'])
            if current['state']!='queued':self.db.execute('COMMIT');return True
            job=current;job['state']='running';job['updatedAt']=instant();self.db.execute('UPDATE jobs SET payload=? WHERE id=?',(compact(job),job['id']));self.db.execute('COMMIT')
        except BaseException:self.db.execute('ROLLBACK');raise
        try:
            {'import':self.run_import,'analysis':self.run_analysis,'chat':self.run_chat}[job['kind']](job);self.check(job);job['state']='completed';job.pop('error',None);self.save_job(job,force=True)
        except JobStop as exc:job['state']=exc.state;self.save_job(job,force=True)
        except Exception as exc:
            import re
            job['state']='failed';job['error']=re.sub(r'(?:https?|webcal)://\S+|Bearer\s+\S+','［已隐藏］',str(exc) if isinstance(exc,ValueError) else '后台处理失败，请检查连接或配置后重试')[:400];self.save_job(job,force=True)
        return True
    def call(self,method,*args):
        if method=='listJobs':
            if args:raise ValueError('无效参数')
            completed=0;result=[]
            for job in self.jobs():
                if job['state']=='completed':
                    completed+=1
                    if completed>100:continue
                result.append(self.public(job))
            return result
        if method=='getJob':id,=args;return self.public(self.job(id))
        if method in ('pauseJob','resumeJob','cancelJob','acknowledgeJob'):
            id,=args;job=self.job(id)
            if method=='pauseJob' and job['state'] in ('queued','running','pausing'):job['state']='pausing' if job['state']=='running' else 'paused'
            elif method=='resumeJob':
                if job['state'] not in ('paused','failed'):raise ValueError('此任务当前不能继续')
                job['state']='queued';job.pop('error',None)
            elif method=='cancelJob' and job['state'] in ACTIVE:job['state']='canceling' if job['state'] in ('running','pausing') else 'canceled'
            elif method=='acknowledgeJob' and job['state'] in ('completed','failed','canceled'):job['notificationAcknowledged']=True
            self.save_job(job,force=True)
            if method=='resumeJob':self.schedule()
            return None if method=='acknowledgeJob' else self.public(job)
        if method=='listConversations':
            if args:raise ValueError('无效参数')
            return [{k:v[k] for k in ('id','title','createdAt','updatedAt','turnCount')} for v in sorted([json.loads(r[0]) for r in self.db.execute('SELECT payload FROM conversations')],key=lambda v:v['updatedAt'],reverse=True)]
        if method=='getConversation':
            id,=args;value=self.conversation(id);return {k:v for k,v in value.items() if k not in ('memory','memoryCount')}
        if method=='deleteConversation':
            id,=args;self.conversation(id)
            if any(v.get('conversationId')==id and v['state'] in ('running','pausing','canceling','queued') for v in self.jobs()):raise ValueError('请先暂停此对话的后台任务')
            self.db.execute('BEGIN IMMEDIATE')
            try:
                for job in self.jobs():
                    if job.get('conversationId')==id:self.db.execute('DELETE FROM jobs WHERE id=?',(job['id'],))
                self.db.execute('DELETE FROM conversations WHERE id=?',(id,));self.db.execute('COMMIT')
            except BaseException:self.db.execute('ROLLBACK');raise
            return None
        if method=='startImport':
            value,=args;strict(value,('bindingIds','filter','onlyNew'),('bindingIds','onlyNew'))
            if not isinstance(value['bindingIds'],list) or not 1<=len(value['bindingIds'])<=100 or len(set(value['bindingIds']))!=len(value['bindingIds']) or type(value['onlyNew']) is not bool:raise ValueError('无效导入参数')
            for id in value['bindingIds']:text(id,2048,True)
            if 'filter' in value:filter_value(value['filter'])
            existing=next((v for v in self.jobs() if v['kind']=='import' and v['state'] in ACTIVE and v['work']['input']==value and not v['work'].get('retryTargets')),None)
            if existing:return self.public(existing)
            job=self.create('import','导入邮件',value)
        elif method=='startAnalysis':
            value,=args;strict(value,('messageIds','instructions','target'),('messageIds','instructions','target'));ids=value['messageIds']
            if not isinstance(ids,list) or not 1<=len(ids)<=1000 or len(ids)!=len(set(ids)):raise ValueError('分析邮件数量无效')
            text(value['instructions'],4000);self.service.mail.target(value['target'])
            for id in ids:self.service.mail.store.get_local(id)
            conversation=dict(id=str(uuid4()),title='邮件分析',createdAt=instant(),updatedAt=instant(),turnCount=0,messageIds=ids,turns=[]);self.save_conversation(conversation);job=self.create('analysis','分析邮件',value,conversation['id'])
        elif method in ('startConversation','continueConversation'):
            if method=='startConversation':
                original,target=args;text(original,20000,True);conversation=dict(id=str(uuid4()),title=original[:60],createdAt=instant(),updatedAt=instant(),turnCount=0,messageIds=[],turns=[])
            else:
                id,original,target=args;text(original,4000,True);conversation=self.conversation(id);self.idle(id)
            if not original.strip():raise ValueError('输入不能为空')
            self.service.mail.target(target);job=self.create('chat','AI对话',dict(text=original,target=target),conversation['id']);job['total']=1
            conversation['turns'].append(dict(id=str(uuid4()),role='user',content=original,createdAt=instant(),jobId=job['id']));self.save_conversation(conversation)
        elif method in ('retryBodies','retryImportFailures'):
            value,=args
            if method=='retryBodies':
                strict(value,('localIds',),('localIds',));ids=value['localIds']
                if not isinstance(ids,list) or not 1<=len(ids)<=500 or len(ids)!=len(set(ids)):raise ValueError('无效补读选择')
                targets=[]
                for id in ids:
                    mail=self.service.mail.store.get_local(id);targets.append(dict(key=digest([mail['bindingId'],mail['id']]),bindingId=mail['bindingId'],identity=mail['mailboxIdentity'],email=mail['accountEmail'],remoteId=mail['id'],subject=mail['subject'],sender=mail['sender'],receivedAt=mail['receivedAt'],maxBytes=25*1024*1024))
            else:
                strict(value,('jobId','keys'),('jobId',));source=self.job(value['jobId'])
                if source['kind']!='import':raise ValueError('此任务不是邮件导入')
                failures=[v for v in source.get('report',{}).get('failures',[]) if v['retryable']];keys=value.get('keys')
                if keys is not None and (not isinstance(keys,list) or len(keys)>1000 or any(k not in {v['key'] for v in failures} for k in keys)):raise ValueError('失败明细已变化，请重新导入')
                selected=failures if keys is None else [v for v in failures if v['key'] in keys]
                targets=[{**v,'email':v['mailboxEmail']} for v in selected]
            if not targets:raise ValueError('没有可重试的邮件')
            job=self.create('import','补读或重试邮件',dict(bindingIds=list(dict.fromkeys(v['bindingId'] for v in targets)),onlyNew=False));job['work']['retryTargets']=targets;job['total']=len(targets)
        else:raise ValueError('未知后台任务接口')
        self.save_job(job,force=True);self.schedule();return self.public(job)
