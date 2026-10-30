from __future__ import annotations
import hashlib
import json
import os
import shutil
import stat
import uuid
from datetime import datetime
from pathlib import Path

SUFFIX = '.disabled-by-resolve-manager'
DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ResolvePluginManager'
SEED = {'BCC 3D Objects': 'BCC 三维对象', 'BCC Art Looks': 'BCC 艺术风格',
        'BCC Extruded EPS': 'BCC EPS 挤出', 'BCC Extruded Spline': 'BCC 样条挤出',
        'BCC Extruded Text': 'BCC 文字挤出', 'BCC Layer Deformer': 'BCC 图层变形',
        'BCC Title Studio': 'BCC 标题工作室', 'BCC Type On Text': 'BCC 文字逐字显现',
        "BCC Artist\'s Poster": 'BCC 艺术海报', 'BCC Bump Map': 'BCC 凹凸贴图',
        'BCC Cartoon Look': 'BCC 卡通风格', 'BCC Charcoal Sketch': 'BCC 炭笔素描',
        'Brightness': '亮度', 'Contrast': '对比度', 'Saturation': '饱和度',
        'Amount': '强度', 'Radius': '半径', 'Threshold': '阈值', 'Blend': '混合',
        'Opacity': '不透明度', 'Scale': '缩放', 'Rotation': '旋转'}

def read_json(path, fallback):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return fallback

def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)

def default_roots():
    paths = [Path(os.environ.get('CommonProgramFiles', r'C:\Program Files\Common Files')) / 'OFX' / 'Plugins']
    paths += [Path(p.strip()) for p in os.environ.get('OFX_PLUGIN_PATH', '').split(os.pathsep) if p.strip()]
    return list(dict.fromkeys(str(p.resolve()) for p in paths))

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def scan(roots):
    rows, errors, seen = [], [], set()
    def walk_error(e):
        errors.append(str(e))
    for root in roots:
        root = Path(root).resolve()
        if not root.is_dir():
            errors.append(f'目录不存在：{root}')
            continue
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
            safe_dirs = []
            for d in dirs:
                try:
                    info = (Path(directory) / d).lstat()
                    if not stat.S_ISLNK(info.st_mode) and not (getattr(info, 'st_file_attributes', 0) & 0x400):
                        safe_dirs.append(d)
                except OSError as e:
                    errors.append(str(e))
            dirs[:] = safe_dirs
            for name in files:
                disabled = name.lower().endswith('.ofx' + SUFFIX)
                if not (name.lower().endswith('.ofx') or disabled):
                    continue
                path = Path(directory) / name
                try:
                    resolved = path.resolve()
                    key = str(resolved).lower()
                    if key in seen or path.is_symlink() or not resolved.is_relative_to(root):
                        continue
                    seen.add(key)
                    bundle = next((p for p in path.parents if p.name.lower().endswith('.ofx.bundle')), path.parent)
                    rel = path.relative_to(root)
                    vendor = 'Boris FX' if 'boris' in str(path).lower() else (rel.parts[0] if len(rel.parts) > 1 else '未识别')
                    rows.append(dict(name=name.removesuffix(SUFFIX), vendor=vendor, path=str(path),
                                     bundle=str(bundle), root=str(root), disabled=disabled,
                                     size=path.stat().st_size, modified=datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec='seconds')))
                except OSError as e:
                    errors.append(str(e))
    return sorted(rows, key=lambda x: x['path'].lower()), errors

def resolve_running():
    import subprocess
    result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Resolve.exe', '/FO', 'CSV', '/NH'],
                            capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('无法检查达芬奇进程，已取消操作。')
    return b'resolve.exe' in result.stdout.lower()

def disable(row, data=DATA, process_check=resolve_running):
    if process_check():
        raise RuntimeError('请先退出达芬奇，再禁用插件。')
    path = Path(row['path'])
    root = Path(row['root']).resolve()
    if path.is_symlink() or path.suffix.lower() != '.ofx' or not path.resolve().is_relative_to(root):
        raise ValueError('插件路径无效，请重新扫描。')
    target = path.with_name(path.name + SUFFIX)
    if target.exists():
        raise FileExistsError('已存在禁用文件，请重新扫描。')
    token = uuid.uuid4().hex
    folder = Path(data) / 'backups' / token
    folder.mkdir(parents=True)
    backup = folder / path.name
    shutil.copy2(path, backup)
    sha = digest(backup)
    if digest(path) != sha:
        raise RuntimeError('备份校验失败，原插件未改动。')
    record = dict(id=token, original=str(path.resolve()), disabled=str(target.absolute()),
                  backup=str(backup.resolve()), sha256=sha, state='prepared',
                  created=datetime.now().isoformat(timespec='seconds'))
    manifest = folder / 'record.json'
    write_json(manifest, record)
    # Rename only the module, preserving the bundle's shared resources and DLL paths.
    path.rename(target)
    record['state'] = 'disabled'
    write_json(manifest, record)
    return record

def records(data=DATA):
    return [(p, read_json(p, {})) for p in sorted((Path(data) / 'backups').glob('*/record.json'))]

def restore(manifest, data=DATA, process_check=resolve_running):
    if process_check():
        raise RuntimeError('请先退出达芬奇，再恢复插件。')
    manifest = Path(manifest).resolve()
    if not manifest.is_relative_to((Path(data) / 'backups').resolve()):
        raise ValueError('备份记录不在管理器目录内。')
    rec = read_json(manifest, {})
    original, disabled, backup = (Path(rec[k]) for k in ('original', 'disabled', 'backup'))
    if str(disabled) != str(original) + SUFFIX or original.suffix.lower() != '.ofx':
        raise ValueError('备份记录路径无效。')
    if not backup.resolve().is_relative_to(manifest.parent) or digest(backup) != rec['sha256']:
        raise RuntimeError('备份校验失败，无法恢复。')
    if original.exists():
        raise FileExistsError('原位置已有插件文件，已停止以避免覆盖。')
    if disabled.exists():
        if digest(disabled) != rec['sha256']:
            raise RuntimeError('禁用文件已发生变化，已停止以避免覆盖更新。')
        disabled.rename(original)
    else:
        original.parent.mkdir(parents=True, exist_ok=True)
        staging = original.with_name(original.name + '.restore-' + uuid.uuid4().hex)
        try:
            shutil.copy2(backup, staging)
            if digest(staging) != rec['sha256']:
                raise RuntimeError('恢复副本校验失败。')
            # Windows rename refuses an existing target, including files created after the check.
            staging.rename(original)
        finally:
            if staging.exists():
                staging.unlink()
    rec['state'] = 'restored'
    rec['restored'] = datetime.now().isoformat(timespec='seconds')
    write_json(manifest, rec)
    return rec

def validate_dictionary(value):
    if not isinstance(value, dict) or not all(isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip() for k, v in value.items()):
        raise ValueError('词库格式应为 {"英文原文": "中文译文"}，原文和译文均不能为空。')
    return value
