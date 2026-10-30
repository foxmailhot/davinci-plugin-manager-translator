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

class ReleaseNotReady(RuntimeError):
    pass

class ApiRateLimited(RuntimeError):
    pass

def request(url,method='GET',api=False):
    return urllib.request.Request(url,method=method,headers={'User-Agent':'ResolvePluginManager/'+VERSION,
        'Accept':'application/vnd.github+json' if api else '*/*','Cache-Control':'no-cache'})

def release_urls(tag):
    version_tuple(tag)
    base=f'https://github.com/{REPOSITORY}/releases/download/{tag}/'
    return base+RELEASE_ASSET,base+RELEASE_ASSET+'.sha256'

def checksum_value(text):
    parts=text.strip().split()
    if not parts or not re.fullmatch('[0-9a-fA-F]{64}',parts[0]): raise ValueError('更新校验文件格式无效。')
    if len(parts)>1 and parts[1].lstrip('*')!=RELEASE_ASSET: raise ValueError('校验文件中的下载包名称不匹配。')
    return parts[0].lower()

def tag_from_page(url):
    parsed=urllib.parse.urlparse(url)
    prefix=f'/{REPOSITORY}/releases/tag/'
    if parsed.scheme!='https' or parsed.netloc!='github.com' or not parsed.path.startswith(prefix):
        raise ValueError('公开发布页未返回本项目的正式版本地址。')
    tag=urllib.parse.unquote(parsed.path[len(prefix):]);version_tuple(tag)
    return tag

def check_release_page():
    """GitHub's public latest redirect is independent of the REST API quota."""
    url=f'https://github.com/{REPOSITORY}/releases/latest'
    try:
        with urllib.request.urlopen(request(url,'HEAD'),timeout=20) as response: tag=tag_from_page(response.geturl())
    except urllib.error.HTTPError as e:
        if e.code not in (405,501): raise
        # Some HTTP proxies do not implement HEAD; ordinary GET preserves the same trust checks.
        with urllib.request.urlopen(request(url),timeout=20) as response: tag=tag_from_page(response.geturl())
    if version_tuple(tag)<=version_tuple(VERSION): return None
    zip_url,sha_url=release_urls(tag)
    try:
        with urllib.request.urlopen(request(sha_url),timeout=20) as response:
            content=response.read(4097)
        if len(content)>4096: raise ValueError('更新校验文件超过大小限制。')
        expected=checksum_value(content.decode('utf-8-sig'))
    except urllib.error.HTTPError as e:
        if e.code==404: raise ReleaseNotReady('发现新版本，但下载包仍在发布中，请稍后重新检查。') from None
        raise
    return {'version':tag,'notes':'从本项目的 GitHub 正式发布页检查到新版。更新内容请查看：\n'+f'https://github.com/{REPOSITORY}/releases/tag/{tag}',
            'zip':zip_url,'sha':sha_url,'expected_sha256':expected,'source':'release-page'}

def check_api():
    try:
        with urllib.request.urlopen(request(f'https://api.github.com/repos/{REPOSITORY}/releases/latest',api=True),timeout=20) as response:
            release=json.loads(response.read(2*1024*1024))
    except urllib.error.HTTPError as e:
        if e.code==404: raise ReleaseNotReady('仓库尚无公开正式版本，或仓库暂不可访问。') from None
        headers=e.headers or {}
        if e.code in (403,429) and (e.code==429 or headers.get('X-RateLimit-Remaining')=='0' or headers.get('Retry-After')):
            raise ApiRateLimited('GitHub API 已限流。') from None
        raise
    if version_tuple(release['tag_name'])<=version_tuple(VERSION): return None
    assets={a['name']:a for a in release.get('assets',[])}
    if RELEASE_ASSET not in assets or RELEASE_ASSET+'.sha256' not in assets: raise ReleaseNotReady('新版本缺少下载包或校验文件，暂不能更新。')
    expected_zip,expected_sha=release_urls(release['tag_name'])
    if assets[RELEASE_ASSET]['browser_download_url']!=expected_zip or assets[RELEASE_ASSET+'.sha256']['browser_download_url']!=expected_sha:
        raise ValueError('更新资源地址与版本不匹配。')
    return {'version':release['tag_name'],'notes':release.get('body',''),'zip':assets[RELEASE_ASSET]['browser_download_url'],
            'sha':assets[RELEASE_ASSET+'.sha256']['browser_download_url'],'source':'api'}

def check_latest():
    errors=[]
    for check in (check_release_page,check_api):
        try:return check()
        except (urllib.error.URLError,TimeoutError,ValueError,KeyError,TypeError,RuntimeError) as e:errors.append(e)
    # Do not report "latest" when both sources failed.
    if any(isinstance(e,ReleaseNotReady) for e in errors):
        raise RuntimeError(next(str(e) for e in errors if isinstance(e,ReleaseNotReady))) from None
    if any(isinstance(e,ApiRateLimited) for e in errors):
        raise RuntimeError('公开发布页暂不可访问，备用 GitHub API 也已限流。请稍后重试，或直接打开本项目的 GitHub 发布页下载；无需填写账号密钥。') from None
    codes=[str(e.code) for e in errors if isinstance(e,urllib.error.HTTPError)]
    detail='（HTTP '+', '.join(codes)+'）' if codes else ''
    raise RuntimeError('无法从公开发布页或备用接口检查更新'+detail+'。请检查网络，或打开 GitHub 发布页手动下载。') from None

def valid_asset_url(url):
    parsed=urllib.parse.urlparse(url)
    return parsed.scheme=='https' and parsed.netloc=='github.com' and parsed.path.startswith('/'+REPOSITORY+'/releases/download/')

def download(url,path,limit):
    if not valid_asset_url(url): raise ValueError('更新地址不属于本项目的 GitHub Release。')
    req=request(url)
    try:
        with urllib.request.urlopen(req,timeout=30) as response, Path(path).open('xb') as output:
            total=0
            while True:
                chunk=response.read(1024*1024)
                if not chunk: break
                total+=len(chunk)
                if total>limit: raise ValueError('更新下载超过大小限制。')
                output.write(chunk)
    except (urllib.error.URLError,TimeoutError): raise RuntimeError('更新下载失败，请检查网络后重新检查更新。') from None

def unpack_verified(archive,checksum,destination):
    expected=checksum_value(Path(checksum).read_text(encoding='utf-8-sig'))
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
    if release.get('expected_sha256') and checksum_value(checksum.read_text(encoding='utf-8-sig'))!=release['expected_sha256']:
        raise ValueError('发布文件在检查后发生变化，请重新检查更新。')
    return unpack_verified(archive,checksum,folder/'app')

def launch_update(executable):
    import subprocess
    if sys.platform!='win32': raise RuntimeError('仅支持 Windows 更新。')
    subprocess.Popen([str(executable)],cwd=str(Path(executable).parent),creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
