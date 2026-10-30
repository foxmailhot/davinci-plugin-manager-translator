"""Bounded producer / sender / verifier pipeline with durable, numbered batch manifests."""
from __future__ import annotations
from collections import Counter, deque
import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import hashlib
import html
import json
from pathlib import Path
import queue
import re
import threading
import unicodedata
import urllib.parse
import uuid
from core import read_json, write_json

MARKER = re.compile(r'(?<!\[)\[{1,2}([0-9]{8})\]{1,2}(?!\])')
ISSUE_LABELS={'duplicate_id':'重复编号','unknown_id':'陌生编号','ambiguous_lines':'多行混入或编号丢失',
              'missing_chinese':'接口未译为中文','missing_markers':'编号丢失','unmatched':'未收到可核对的译文'}

def tagged(record):
    return f'[[{record["id"]}]] ' + record.get('request_source',record['source']).replace('\r',' ').replace('\n',' ')

def repair_record(record,reason):
    if reason!='missing_chinese': return dict(record)
    source=record['source']; prefix=''
    match=re.match(r'^(BCC\+?\s+)(.+)$',source)
    if match: prefix,source=match.groups()
    source=re.sub(r'([a-z])([A-Z])',r'\1 \2',source)
    source=re.sub(r'([A-Z])([A-Z][a-z])',r'\1 \2',source)
    return {**record,'request_source':source,'restore_prefix':prefix}

def make_record(index, source):
    if MARKER.search(source): raise ValueError(f'第 {index+1} 条原文包含保留编号格式，不能安全批量翻译。')
    return {'id':f'{index+1:08d}', 'line':index+1, 'source':source,
            'sha256':hashlib.sha256(source.encode('utf-8')).hexdigest()}

def plan_chunks(records, provider, cap=None):
    """Transport limits are separate from the user-visible 1000-item work unit."""
    from translation import PROVIDERS
    max_items = 128 if provider==PROVIDERS[2] else 1000
    if cap is not None: max_items=min(max_items,cap)
    result=[]; current=[]
    for record in records:
        attempt=current+[record]
        text='\n'.join(tagged(r) for r in attempt)
        if provider==PROVIDERS[0]: fits=len(text.encode('utf-8'))<=500
        elif provider==PROVIDERS[1]: fits=len(text)<=4500 and len(urllib.parse.urlencode({'q':text}).encode())<=6500
        else: fits=len(text)<=(200000 if provider==PROVIDERS[3] else 25000)
        if current and (not fits or len(attempt)>max_items):
            result.append(current); current=[record]
        else: current=attempt
        if provider==PROVIDERS[0] and len(tagged(record).encode('utf-8'))>500:
            raise ValueError(f'第 {record["line"]} 条超过 MyMemory 单次 500 字节限制。请选择其他接口。')
    if current: result.append(current)
    return result

def validate_response(records, raw):
    """Match only immutable IDs; never fall back to position for a damaged response."""
    expected={r['id']:r for r in records}
    values=raw if isinstance(raw,list) else [raw]
    candidates=[]; issues=[]
    for block_index, block in enumerate(values):
        if not isinstance(block,str):
            issues.append({'kind':'invalid_response_type','response_block':block_index+1}); continue
        block=unicodedata.normalize('NFKC',html.unescape(block))
        matches=list(MARKER.finditer(block))
        if not matches:
            issues.append({'kind':'missing_markers','response_block':block_index+1,'sample':block[:160]}); continue
        if block[:matches[0].start()].strip(): issues.append({'kind':'unexpected_prefix','response_block':block_index+1})
        for i,match in enumerate(matches):
            value=block[match.end():matches[i+1].start() if i+1<len(matches) else len(block)].strip()
            candidates.append((match.group(1),value,block_index+1))
    counts=Counter(key for key,_,_ in candidates)
    accepted={}
    for key,value,block in candidates:
        reason=None
        if key not in expected: reason='unknown_id'
        elif counts[key]!=1: reason='duplicate_id'
        elif len([line for line in value.splitlines() if line.strip()])!=1: reason='ambiguous_lines'
        elif not re.search(r'[\u3400-\u9fff]',value): reason='missing_chinese'
        if reason:
            issues.append({'kind':reason,'id':key,'source_line':expected.get(key,{}).get('line'),
                           'source':expected.get(key,{}).get('source'),'response_block':block,'sample':value[:160]})
        else:
            prefix=expected[key].get('restore_prefix','')
            accepted[key]=prefix+value if prefix and not value.startswith(prefix.strip()) else value
    for key,record in expected.items():
        if key not in accepted:
            issues.append({'kind':'unmatched','id':key,'source_line':record['line'],'source':record['source']})
    return accepted,issues

def send_chunk(records, provider, api_key, endpoint, data):
    from translation import PROVIDERS, request_json
    text='\n'.join(tagged(r) for r in records)
    if provider==PROVIDERS[0]:
        quota_path=Path(data)/'mymemory-usage.json'; quota=read_json(quota_path,{})
        if not isinstance(quota,dict) or quota.get('day')!=date.today().isoformat(): quota={'day':date.today().isoformat(),'characters':0}
        if quota.get('characters',0)+len(text)>4500: raise RuntimeError('MyMemory 今日 4500 字符预算已用完，已保留已完成的批次；可明日继续或更换接口。')
        quota['characters']=quota.get('characters',0)+len(text); write_json(quota_path,quota)
        response=request_json('https://api.mymemory.translated.net/get?'+urllib.parse.urlencode({'q':text,'langpair':'en|zh-CN'}))
        if str(response.get('responseStatus'))!='200' or response.get('quotaFinished'): raise RuntimeError('MyMemory 额度不足或拒绝请求，已保存进度。')
        return response.get('responseData',{}).get('translatedText','')
    if provider==PROVIDERS[1]:
        response=request_json('https://translate.googleapis.com/translate_a/single?'+urllib.parse.urlencode({'client':'gtx','sl':'en','tl':'zh-CN','dt':'t','q':text}))
        return ''.join(item[0] for item in response[0] if item and item[0])
    if provider==PROVIDERS[2]:
        if not api_key.strip(): raise ValueError('请填写 Google Cloud 密钥或选择免密钥接口。')
        response=request_json('https://translation.googleapis.com/language/translate/v2',
            {'q':[tagged(r) for r in records],'source':'en','target':'zh-CN','format':'text'},{'X-Goog-Api-Key':api_key.strip()})
        return [item.get('translatedText','') for item in response.get('data',{}).get('translations',[])]
    if provider==PROVIDERS[3]:
        url=urllib.parse.urlparse(endpoint)
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password: raise ValueError('LibreTranslate 地址无效。')
        if url.scheme=='http' and url.hostname not in ('localhost','127.0.0.1','::1'): raise ValueError('远程服务必须使用 HTTPS。')
        payload={'q':[tagged(r) for r in records],'source':'en','target':'zh','format':'text'}
        if api_key: payload['api_key']=api_key
        return request_json(endpoint.rstrip('/')+'/translate',payload).get('translatedText',[])
    raise ValueError('所选接口不支持在线翻译。')

def send_bundle(bundle,provider,api_key,endpoint,data,folder,progress,cancel):
    chunks=deque(plan_chunks(bundle['records'],provider,cap=bundle.get('cap')))
    responses=[]; error=None; sequence=0
    while chunks:
        if cancel.is_set(): error='已停止，已返回的结果仍会核对和保存。'; break
        chunk=chunks.popleft(); sequence+=1
        progress(f'发送任务包 {bundle["number"]} / 第 {sequence} 个子请求（{len(chunk)} 条），下一包正在预打包')
        request_path=folder/f'{bundle["name"]}.part-{sequence:04d}.request.json'
        write_json(request_path,{'provider':provider,'records':chunk,'sent_at':datetime.now().isoformat(timespec='seconds')})
        try:
            raw=send_chunk(chunk,provider,api_key,endpoint,data)
            write_json(folder/f'{bundle["name"]}.part-{sequence:04d}.response.json',{'raw':raw})
            responses.append({'records':chunk,'raw':raw,'part':sequence})
        except Exception as e:
            message=str(e)
            # A service can impose a lower array/body limit than its documented maximum.
            if len(chunk)>1 and any(code in message for code in ('HTTP 400','HTTP 413','HTTP 414','HTTP 422')):
                mid=len(chunk)//2; chunks.appendleft(chunk[mid:]); chunks.appendleft(chunk[:mid])
                write_json(folder/f'{bundle["name"]}.part-{sequence:04d}.error.json',{'error':message,'action':'split_half','records':chunk})
                continue
            error=message
            write_json(folder/f'{bundle["name"]}.part-{sequence:04d}.error.json',{'error':message,'records':chunk})
            break
    return {'bundle':bundle,'responses':responses,'error':error}

def run_catalog(catalog,dictionary,provider,data,api_key,endpoint,progress,cancel,batch_size=1000):
    from translation import COMMON,SEED,PROVIDERS
    if not isinstance(batch_size,int) or not 1<=batch_size<=1000: raise ValueError('每个任务包须为 1 至 1000 条。')
    data=Path(data); cache_path=data/'translation-cache.json'; cache=read_json(cache_path,{})
    if not isinstance(cache,dict): cache={}
    local={**COMMON,**SEED,**cache,**dictionary}
    texts=list(dict.fromkeys(catalog['texts']))
    translations={t:local[t] for t in texts if isinstance(local.get(t),str) and local[t].strip()}
    pending=[make_record(i,t) for i,t in enumerate(texts) if t not in translations]
    folder=data/'batch-jobs'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]); folder.mkdir(parents=True)
    write_json(folder/'job.json',{'path':catalog['path'],'provider':provider,'batch_size':batch_size,
                                'pending':len(pending),'records':pending,'protocol':'numbered-v1'})
    stop=threading.Event(); cancel=cancel or threading.Event(); ready=queue.Queue(maxsize=2)
    failures=[]; issue_count=0; verified_bundles=0; error=None; last_issues={}
    summary={'job_folder':str(folder.resolve()),'batch_size':batch_size,'task_packages':(len(pending)+batch_size-1)//batch_size}
    def producer():
        try:
            for number,start in enumerate(range(0,len(pending),batch_size),1):
                if stop.is_set() or cancel.is_set(): break
                bundle={'number':number,'name':f'batch-{number:04d}','records':pending[start:start+batch_size],'round':0}
                write_json(folder/(bundle['name']+'.request.json'),bundle)
                while not stop.is_set() and not cancel.is_set():
                    try: ready.put(bundle,timeout=.1); break
                    except queue.Full: pass
        except Exception as e: failures.append(str(e))
        finally:
            while not stop.is_set():
                try: ready.put(None,timeout=.1); break
                except queue.Full: pass
    def next_prepared():
        while True:
            if cancel.is_set(): return None
            try: return ready.get(timeout=.1)
            except queue.Empty:
                if not packing.is_alive(): return None
    packing=threading.Thread(target=producer,name='translation-packager',daemon=True)
    retries=deque(); exhausted=False
    def next_work():
        nonlocal exhausted
        if cancel.is_set(): return None
        if retries: return retries.popleft()
        if exhausted: return None
        work=next_prepared()
        if work is None: exhausted=True
        return work
    def submit(pool,work):
        return pool.submit(send_bundle,work,provider,api_key,endpoint,data,folder,progress,cancel)
    try:
        if provider!=PROVIDERS[-1] and pending:
            packing.start()
            with ThreadPoolExecutor(max_workers=1,thread_name_prefix='translation-sender') as pool:
                work=next_work(); future=submit(pool,work) if work else None
                while future:
                    returned=future.result()
                    if returned['error']:
                        error=error or returned['error']; cancel.set(); next_item=None
                    else: next_item=next_work()
                    # Launch the next network request BEFORE validating and persisting this response.
                    future=submit(pool,next_item) if next_item else None
                    accepted={}; issues=[]
                    for response in returned['responses']:
                        valid,problems=validate_response(response['records'],response['raw'])
                        accepted.update(valid)
                        issues.extend({**p,'part':response['part']} for p in problems)
                    work=returned['bundle']
                    for record in work['records']:
                        if record['id'] in accepted:
                            text=record['source']; translations[text]=accepted[record['id']]; cache[text]=accepted[record['id']]
                    write_json(cache_path,cache)
                    issue_count+=len(issues); verified_bundles+=1
                    report={'bundle':work['name'],'round':work['round'],'accepted_ids':list(accepted),'issues':issues,'error':returned['error']}
                    write_json(folder/(work['name']+'.validation.json'),report)
                    for problem in issues:
                        if problem.get('id') and problem['kind']!='unmatched': last_issues[problem['id']]=problem['kind']
                    progress(f'已核对 {verified_bundles} 个任务包；译文 {len(translations)}/{len(texts)}；异常记录 {issue_count} 条。'+('下一包正在发送。' if future else ''))
                    missing=[r for r in work['records'] if r['source'] not in translations]
                    if missing and not accepted and work['round']>=1 and not error and not any(p['kind']=='missing_chinese' for p in issues):
                        error='接口连续返回无法核对的批量结果，已停止自动重试，避免退化为大量逐条请求；请查看批次报告或切换服务。'
                        cancel.set()
                    if missing and not error and not cancel.is_set() and work['round']<2:
                        retry_records=[repair_record(r,last_issues.get(r['id'])) for r in missing
                                       if work['round']==0 or last_issues.get(r['id'])!='missing_chinese']
                        if not retry_records: continue
                        retry={**work,'records':retry_records,'round':work['round']+1,'cap':16 if work['round']==0 else 1}
                        retry['name']=work['name']+f'-retry{retry["round"]}'
                        write_json(folder/(retry['name']+'.request.json'),retry); retries.append(retry)
                    if not future and not error:
                        item=next_work(); future=submit(pool,item) if item else None
    except Exception as e: error=str(e)
    finally:
        stop.set()
        if packing.is_alive(): packing.join(timeout=2)
    if failures and not error: error='打包失败：'+'；'.join(failures)
    if cancel.is_set() and not error: error='已停止，已核对的译文已保存。'
    remaining=len(texts)-len(translations)
    if remaining and not error and provider!=PROVIDERS[-1]: error=f'{remaining} 条未译或未通过编号/内容核对，未写入缓存；请查看批次报告中的原文行号和异常位置。'
    result={**catalog,'translations':translations,'remaining':remaining,'provider':provider,'error':error,
            **summary,'issue_count':issue_count,'verified_packages':verified_bundles,
            'unmatched_records':[{**r,'reason':last_issues.get(r['id'],'unmatched')} for r in pending if r['source'] not in translations]}
    with (folder/'未通过核对.csv').open('w',encoding='utf-8-sig',newline='') as report_file:
        writer=csv.writer(report_file);writer.writerow(['原文行号','编号','英文名称','异常原因'])
        for record in result['unmatched_records']:
            writer.writerow([record['line'],record['id'],record['source'],ISSUE_LABELS.get(record['reason'],record['reason'])])
    write_json(folder/'summary.json',{**summary,'remaining':remaining,'translated':len(translations),'issue_count':issue_count,'error':error})
    key=hashlib.sha256(catalog['path'].encode()).hexdigest()[:24]
    write_json(data/'catalogs'/(key+'.json'),result)
    return result
