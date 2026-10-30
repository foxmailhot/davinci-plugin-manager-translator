"""Display-text extraction, optional online translation, and reversible OFX adapter deployment."""
from __future__ import annotations
import html
import json
import os
import re
import shutil
import struct
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
import xml.etree.ElementTree as ET
from core import DATA, SEED, digest, read_json, write_json, resolve_running

ORIGINAL = '.rpm-original'
WORDS = '.rpm-translations.tsv'
STATE = '.rpm-state.json'
PROVIDERS = ['MyMemory（免密钥，有每日额度）', 'Google 网页翻译（非官方实验接口）', 'Google Cloud（官方，需密钥）', 'LibreTranslate（自建服务）', '仅本地词库']
COMMON = dict(zip(
    'Blur|Glow|Exposure|Gamma|Hue|Light|Shadow|Highlights|Shadows|Midtones|Color|Red|Green|Blue|White|Black|Width|Height|Speed|Angle|Position|Center|Offset|Quality|Input|Output|Mask|Invert|Enabled|Enable|Mix|Softness|Intensity|Size|Depth|Distance|Direction|Frequency|Seed|Random Seed|Falloff|Feather|Gain|Temperature|Tint|Noise|Sharpen|Smooth|Reset|Help|About|Apply|Cancel|OK|None|Normal|Screen|Multiply|Add|Subtract|Overlay|Difference|Source|Destination|Transform|Texture|Lighting|Material|Reflection|Refraction|Metallic|Roughness|Bump Map|Displacement|Ambient|Diffuse|Specular'.split('|'),
    '模糊|辉光|曝光|伽马|色相|光线|阴影|高光|暗部|中间调|颜色|红色|绿色|蓝色|白色|黑色|宽度|高度|速度|角度|位置|中心|偏移|质量|输入|输出|遮罩|反转|已启用|启用|混合|柔和度|强度|大小|深度|距离|方向|频率|种子|随机种子|衰减|羽化|增益|色温|色调|噪点|锐化|平滑|重置|帮助|关于|应用|取消|确定|无|正常|滤色|正片叠底|相加|相减|叠加|差值|源|目标|变换|纹理|灯光|材质|反射|折射|金属度|粗糙度|凹凸贴图|置换|环境光|漫反射|镜面反射'.split('|')))

def asset_path():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'assets' / 'translation_proxy.ofx'

def original_path(row):
    path = Path(row['path'])
    from core import SUFFIX
    if str(path).endswith(SUFFIX): path = Path(str(path).removesuffix(SUFFIX))
    saved = Path(str(path) + ORIGINAL)
    return saved if saved.exists() else path

def is_candidate(value):
    if not 2 <= len(value) <= 180 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9 \-+()/.,:'&!?\[\]]+", value): return False
    if any(s in value.lower() for s in ('.dll','.exe','.png','.jpg','copyright','http','microsoft','exception','operator','std::')): return False
    return bool(re.search('[a-z]',value)) and (value[0].isupper() or ' ' in value)

def text_sections(data):
    """Read non-executable PE data sections to avoid mistaking machine code for English."""
    if data[:2]!=b'MZ' or len(data)<64: return []
    try:
        pe=struct.unpack_from('<I',data,0x3c)[0]
        if data[pe:pe+4]!=b'PE\0\0': return []
        count=struct.unpack_from('<H',data,pe+6)[0]
        optional_size=struct.unpack_from('<H',data,pe+20)[0]
        table=pe+24+optional_size; sections=[]
        if count>96: return []
        for i in range(count):
            offset=table+40*i
            size,pointer=struct.unpack_from('<II',data,offset+16)
            flags=struct.unpack_from('<I',data,offset+36)[0]
            if flags&0x20000000 or not flags&0x40: continue
            if pointer+size<=len(data): sections.append(data[pointer:pointer+size])
        return sections
    except struct.error: return []

def extract(row):
    """Only read files; never load third-party binaries during extraction."""
    path = original_path(row)
    if not path.is_file(): raise FileNotFoundError('模块文件不存在，请重新扫描。')
    files = [path]
    files += list(path.parent.glob('*.dll'))
    # BCC's small OFX loader delegates to versioned shared binaries outside its bundle.
    if 'boris' in str(path).lower():
        base = Path(os.environ.get('ProgramFiles', r'C:\Program Files'))/'BorisFX'/'ContinuumOFX'
        match = re.search(rb'ContinuumOFX[\\/](\d+)',path.read_bytes())
        versions = [base/match.group(1).decode()] if match else sorted(base.glob('*'))[-1:]
        for version in versions:
            files += list((version/'lib').glob('*OFX*.dll'))
    files = list(dict.fromkeys(p.resolve() for p in files))
    found, sources = set(), []
    for file in files:
        if file.stat().st_size > 180*1024*1024: continue
        data = file.read_bytes()
        sections=text_sections(data)
        ascii_values = [x.decode('ascii') for section in sections for x in re.findall(rb'(?<![\x20-\x7e])[\x20-\x7e]{2,180}(?=\x00)',section)]
        wide_values = [x.decode('utf-16-le') for section in sections for x in re.findall(rb'(?:[\x20-\x7e]\x00){2,180}(?=\x00\x00)',section)]
        found.update(x.strip() for x in ascii_values + wide_values if is_candidate(x.strip()))
        sources.append(str(file))
    resources = Path(row.get('bundle',path.parent))/'Contents'/'Resources'
    for file in resources.glob('*.xml'):
        if file.stat().st_size > 8*1024*1024: continue
        try:
            tree = ET.parse(file)
            for element in tree.iter():
                for key,value in element.attrib.items():
                    if key.lower() in ('label','hint','displayname','description') and is_candidate(value): found.add(value)
        except (ET.ParseError,OSError): pass
    if not found: raise ValueError('没有提取到可识别的英文文字。此插件可能使用压缩或专用资源，需要单独适配。')
    # Effects first, followed by familiar labels, then the remaining candidate strings.
    ordered = sorted(found,key=lambda x:(not x.startswith(('BCC ','S_')), x not in (SEED|COMMON),x.lower()))
    return {'module':row['name'],'path':row['path'],'source_sha256':digest(path),'texts':ordered,
            'sources':sources,'extracted_at':datetime.now().isoformat(timespec='seconds'),
            'note':'静态提取候选文字，可能包含未使用或非界面字符串；数量不是效果数或真实界面覆盖率。'}

def request_json(url, payload=None, headers=None):
    request = urllib.request.Request(url,data=json.dumps(payload).encode('utf-8') if payload is not None else None,
        headers={'User-Agent':'ResolvePluginManager/0.2','Accept':'application/json',**({'Content-Type':'application/json'} if payload is not None else {}),**(headers or {})})
    try:
        with urllib.request.urlopen(request,timeout=18) as response:
            return json.loads(response.read(4*1024*1024).decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'翻译服务返回 HTTP {e.code}，请检查额度、密钥或服务状态。') from None
    except (urllib.error.URLError,TimeoutError,ValueError):
        raise RuntimeError('无法连接翻译服务或响应无效，请检查网络后重试。') from None

def translate_one(text, provider, api_key='', endpoint='http://127.0.0.1:5000'):
    if provider == PROVIDERS[0]:
        result = request_json('https://api.mymemory.translated.net/get?'+urllib.parse.urlencode({'q':text,'langpair':'en|zh-CN'}))
        if str(result.get('responseStatus')) != '200' or result.get('quotaFinished'):
            raise RuntimeError('MyMemory 额度已用完或服务拒绝请求，已保存当前进度。可稍后继续或选择其他接口。')
        value = result.get('responseData',{}).get('translatedText','')
    elif provider == PROVIDERS[1]:
        result = request_json('https://translate.googleapis.com/translate_a/single?'+urllib.parse.urlencode({'client':'gtx','sl':'en','tl':'zh-CN','dt':'t','q':text}))
        value = ''.join(x[0] for x in result[0] if x and x[0])
    elif provider == PROVIDERS[2]:
        if not api_key.strip(): raise ValueError('请填写 Google Cloud API 密钥，或选择免密钥接口。')
        result = request_json('https://translation.googleapis.com/language/translate/v2',
            {'q':[text],'source':'en','target':'zh-CN','format':'text'}, {'X-Goog-Api-Key':api_key.strip()})
        value = result.get('data',{}).get('translations',[{}])[0].get('translatedText','')
    elif provider == PROVIDERS[3]:
        parsed = urllib.parse.urlparse(endpoint)
        if parsed.username or parsed.password or parsed.scheme not in ('http','https') or not parsed.hostname: raise ValueError('LibreTranslate 地址无效。')
        if parsed.scheme=='http' and parsed.hostname not in ('localhost','127.0.0.1','::1'): raise ValueError('远程翻译服务必须使用 HTTPS；HTTP 仅用于本机服务。')
        payload = {'q':text,'source':'en','target':'zh','format':'text'}
        if api_key: payload['api_key']=api_key
        value = request_json(endpoint.rstrip('/')+'/translate',payload).get('translatedText','')
    else: raise ValueError('本地词库中尚无此词条。')
    if not isinstance(value,str) or not value.strip(): raise RuntimeError('翻译接口未返回有效译文。')
    value = html.unescape(value).strip()
    if not re.search(r'[\u3400-\u9fff]',value): raise RuntimeError('接口返回的内容没有中文，已停止；已有译文已保留。')
    return value

def translate_catalog(catalog, dictionary, provider, data=DATA, api_key='', endpoint='http://127.0.0.1:5000', progress=lambda text:None, cancel=None):
    cache_path=Path(data)/'translation-cache.json'
    cache=read_json(cache_path,{})
    dictionary={**COMMON,**SEED,**cache,**dictionary}
    translations={k:dictionary[k] for k in catalog['texts'] if k in dictionary}
    pending=[k for k in catalog['texts'] if k not in translations]
    error=None
    quota_path=Path(data)/'mymemory-usage.json'; quota=read_json(quota_path,{})
    if quota.get('day')!=date.today().isoformat(): quota={'day':date.today().isoformat(),'characters':0}
    for index,text in enumerate(pending):
        if provider==PROVIDERS[-1]: break
        if cancel and cancel.is_set(): error='已停止，已有译文已保存。'; break
        try:
            if provider==PROVIDERS[0]:
                if quota['characters']+len(text)>4500: raise RuntimeError('本程序已达到 MyMemory 今日 4500 字符预算，已保存进度。')
                quota['characters']+=len(text); write_json(quota_path,quota)
            progress(f'翻译 {index+1}/{len(pending)}：{text[:65]}（已完成 {len(translations)}/{len(catalog["texts"])}）')
            translations[text]=translate_one(text,provider,api_key,endpoint)
            cache[text]=translations[text]; write_json(cache_path,cache)
            time.sleep(.25)
        except Exception as e:
            error=str(e); break
    result={**catalog,'translations':translations,'remaining':len(catalog['texts'])-len(translations),'provider':provider,'error':error}
    key=__import__('hashlib').sha256(catalog['path'].encode()).hexdigest()[:24]
    write_json(Path(data)/'catalogs'/(key+'.json'),result)
    return result

def tsv(translations):
    def escaped(s): return s.replace('\\','\\\\').replace('\t','\\t').replace('\r','\\r').replace('\n','\\n')
    return ''.join(f'{escaped(k)}\t{escaped(v)}\n' for k,v in sorted(translations.items())).encode('utf-8')

def check_pe64(path):
    with Path(path).open('rb') as f:
        if f.read(2)!=b'MZ': raise ValueError('仅支持 Windows x64 PE 格式的 OFX 模块。')
        f.seek(0x3c); offset=struct.unpack('<I',f.read(4))[0]; f.seek(offset)
        if f.read(6)!=b'PE\0\0\x64\x86': raise ValueError('仅支持 Windows x64 OFX 模块。')

def apply_adapter(row, result, data=DATA, proxy=None, process_check=resolve_running):
    if process_check(): raise RuntimeError('请先退出达芬奇，再应用界面翻译。')
    if row.get('disabled'): raise ValueError('请先恢复并启用此模块，再应用翻译。')
    path=Path(row['path']).resolve(); root=Path(row['root']).resolve()
    if not path.is_relative_to(root) or path.suffix.lower()!='.ofx': raise ValueError('模块路径无效。')
    if result.get('path')!=row['path'] or not result.get('translations'): raise ValueError('请先为所选模块提取并翻译文字。')
    check_pe64(path)
    proxy=Path(proxy) if proxy else asset_path(); check_pe64(proxy)
    saved=Path(str(path)+ORIGINAL); state_path=Path(str(path)+STATE); words=Path(str(path)+WORDS)
    state=read_json(state_path,{})
    if saved.exists():
        if not state or digest(saved)!=state.get('original_sha256') or digest(path)!=state.get('adapter_sha256'): raise RuntimeError('插件或适配层已变化，请先核对并恢复原版。')
        if digest(saved)!=result['source_sha256']: raise RuntimeError('原始模块已更新，请重新提取和翻译。')
        write_bytes_atomic(words,tsv(result['translations']))
        state['translated']=len(result['translations']); write_json(state_path,state)
        return state
    if digest(path)!=result['source_sha256']: raise RuntimeError('插件已更新，请重新提取和翻译。')
    if state_path.exists() or words.exists(): raise RuntimeError('存在未完成的翻译记录，请先恢复原版并重新扫描。')
    folder=Path(data)/'translation-backups'/uuid.uuid4().hex; folder.mkdir(parents=True)
    backup=folder/path.name; shutil.copy2(path,backup)
    if digest(backup)!=result['source_sha256']: raise RuntimeError('原版备份校验失败。')
    state={'original_sha256':digest(path),'adapter_sha256':digest(proxy),'backup':str(backup.resolve()),
           'path':str(path),'created':datetime.now().isoformat(timespec='seconds'),'translated':len(result['translations']), 'phase':'prepared'}
    write_json(folder/'record.json',state)
    write_json(state_path,state)
    staging=path.with_name(path.name+'.rpm-stage')
    if staging.exists(): raise RuntimeError('发现未完成的暂存文件，请先检查上次操作。')
    try:
        shutil.copy2(proxy,staging)
        write_bytes_atomic(words,tsv(result['translations']))
        path.rename(saved)
        try: staging.rename(path)
        except Exception:
            saved.rename(path); raise
        state['phase']='applied'; write_json(state_path,state); write_json(folder/'record.json',state)
    finally:
        if staging.exists(): staging.unlink()
    return state

def write_bytes_atomic(path,content):
    path=Path(path); temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try: temp.write_bytes(content); temp.replace(path)
    finally:
        if temp.exists(): temp.unlink()

def restore_adapter(row, process_check=resolve_running):
    if process_check(): raise RuntimeError('请先退出达芬奇，再恢复原版。')
    if row.get('disabled'): raise ValueError('请先在“备份与恢复”启用模块，再恢复翻译。')
    path=Path(row['path']).resolve(); saved=Path(str(path)+ORIGINAL); manifest=Path(str(path)+STATE)
    state=read_json(manifest,{})
    if state and state.get('phase')=='prepared' and not saved.exists() and path.exists() and digest(path)==state.get('original_sha256'):
        for suffix in (WORDS,STATE):
            sidecar=Path(str(path)+suffix)
            if sidecar.exists(): sidecar.unlink()
        return state
    if not state or not saved.is_file() or digest(saved)!=state.get('original_sha256'): raise RuntimeError('未找到可校验的原版模块。')
    if path.exists() and digest(path)!=state.get('adapter_sha256'): raise RuntimeError('当前位置已有更新或改动，已停止以避免覆盖。')
    moved=path.with_name(path.name+'.rpm-retired-'+uuid.uuid4().hex)
    if path.exists(): path.rename(moved)
    try: saved.rename(path)
    except Exception:
        if moved.exists(): moved.rename(path)
        raise
    if moved.exists(): moved.unlink()
    for suffix in (WORDS,STATE):
        file=Path(str(path)+suffix)
        if file.exists(): file.unlink()
    return state
