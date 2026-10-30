"""User-triggered GitHub Release updater. New versions run side by side with the current EXE."""
import hashlib
import json
import os
import re
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from core import DATA
from version import VERSION, REPOSITORY, RELEASE_ASSET

def version_tuple(value):
    if not re.fullmatch(r'v?\d+\.\d+\.\d+',value): raise ValueError('版本格式无效。')
    return tuple(int(x) for x in value.lstrip('v').split('.'))

def check_latest():
    request=urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/releases/latest',headers={'Accept':'application/vnd.github+json','User-Agent':'ResolvePluginManager/'+VERSION})
    try:
        with urllib.request.urlopen(request,timeout=20) as response: release=json.loads(response.read(2*1024*1024))
    except urllib.error.HTTPError as e:
        if e.code==404: raise RuntimeError('仓库尚无公开正式版本，或仓库暂不可访问。可在 GitHub 页面查看发布状态。') from None
        raise RuntimeError(f'GitHub 返回 HTTP {e.code}，请稍后再试。') from None
    except (urllib.error.URLError,TimeoutError,ValueError): raise RuntimeError('无法连接 GitHub，请检查网络后重试。') from None
    if version_tuple(release['tag_name'])<=version_tuple(VERSION): return None
    assets={a['name']:a for a in release.get('assets',[])}
    if RELEASE_ASSET not in assets or RELEASE_ASSET+'.sha256' not in assets: raise RuntimeError('新版本缺少下载包或校验文件，暂不能更新。')
    return {'version':release['tag_name'],'notes':release.get('body',''),'zip':assets[RELEASE_ASSET]['browser_download_url'],
            'sha':assets[RELEASE_ASSET+'.sha256']['browser_download_url']}

def valid_asset_url(url):
    parsed=urllib.parse.urlparse(url)
    return parsed.scheme=='https' and parsed.netloc=='github.com' and parsed.path.startswith('/'+REPOSITORY+'/releases/download/')

def download(url,path,limit):
    if not valid_asset_url(url): raise ValueError('更新地址不属于本项目的 GitHub Release。')
    request=urllib.request.Request(url,headers={'User-Agent':'ResolvePluginManager/'+VERSION})
    try:
        with urllib.request.urlopen(request,timeout=30) as response, Path(path).open('xb') as output:
            total=0
            while True:
                chunk=response.read(1024*1024)
                if not chunk: break
                total+=len(chunk)
                if total>limit: raise ValueError('更新下载超过大小限制。')
                output.write(chunk)
    except (urllib.error.URLError,TimeoutError): raise RuntimeError('更新下载失败，请检查网络后重新检查更新。') from None

def unpack_verified(archive,checksum,destination):
    expected=Path(checksum).read_text(encoding='utf-8-sig').split()[0].lower()
    if not re.fullmatch('[0-9a-f]{64}',expected): raise ValueError('更新校验文件格式无效。')
    actual=hashlib.sha256(Path(archive).read_bytes()).hexdigest()
    if actual!=expected: raise ValueError('更新包 SHA-256 校验失败，已停止。')
    destination=Path(destination).resolve()
    with zipfile.ZipFile(archive) as package:
        infos=package.infolist()
        if len(infos)>100 or sum(i.file_size for i in infos)>300*1024*1024: raise ValueError('更新包内容超出限制。')
        names=set()
        for info in infos:
            raw=info.filename.replace('\\','/'); name=PurePosixPath(raw)
            if name.is_absolute() or '..' in name.parts or ':' in raw or stat.S_ISLNK(info.external_attr>>16): raise ValueError('更新包包含不安全路径。')
            target=(destination/str(name)).resolve()
            if not target.is_relative_to(destination): raise ValueError('更新包路径越界。')
            if raw.casefold() in names: raise ValueError('更新包包含重复文件。')
            names.add(raw.casefold())
        executable=destination/'ResolvePluginManager.exe'
        if 'resolvepluginmanager.exe' not in names: raise ValueError('更新包缺少主程序。')
        if destination.exists(): raise FileExistsError('更新目标目录已存在。')
        destination.mkdir(parents=True)
        package.extractall(destination)
    return executable

def stage_update(release,data=DATA):
    version_tuple(release['version'])
    folder=Path(data)/'updates'/(release['version']+'-'+uuid.uuid4().hex[:8]); folder.mkdir(parents=True)
    archive=folder/'update.zip'; checksum=folder/'update.sha256'
    download(release['zip'],archive,150*1024*1024); download(release['sha'],checksum,4096)
    return unpack_verified(archive,checksum,folder/'app')

def launch_update(executable):
    import subprocess
    if sys.platform!='win32': raise RuntimeError('仅支持 Windows 更新。')
    subprocess.Popen([str(executable)],cwd=str(Path(executable).parent),creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
