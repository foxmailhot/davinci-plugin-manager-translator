"""Only enable native deployment for explicitly startup-tested host/plugin binaries."""
import os
from pathlib import Path
from core import digest

ADAPTER_ABI = 2
ADAPTER_MARKER = b'RPM_ADAPTER_ABI_2'
TESTED_RESOLVE_SHA256 = '7099820695195daa16940c93a8da034ccf07ad11cacbdaa1310108f1e8cb202b'
# Filled only after verification in the real host; translation/export still works otherwise.
TESTED_MODULES = {
    '130538a63318a1cbc3433a81ceeae1a1a16535ab0f3a6936ce77f602830b3c21':'BCC_OFX.ofx',
    '7ca7150ca94094528d19dcb7cef730c5ff4be31a4160af693314b9ed221525fe':'BCC_OFX_3DObjects.ofx',
    '891c457ec9a490210a9a911e5c315c1d9009f10e2de3ea2a9f51131ff19ecd63':'BCC+.ofx',
}

def ensure_compatible(row, original_sha256, proxy):
    module=TESTED_MODULES.get(original_sha256)
    if not module or Path(row['path']).name.casefold()!=module.casefold():
        raise RuntimeError('此插件版本尚未通过兼容性验证，已阻止改写 OFX。可以继续翻译和导出词库。')
    resolve=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Blackmagic Design'/'DaVinci Resolve'/'Resolve.exe'
    if not resolve.is_file() or digest(resolve)!=TESTED_RESOLVE_SHA256:
        raise RuntimeError('此达芬奇版本尚未通过兼容性验证，已阻止改写 OFX；管理和词库翻译仍可使用。')
    if ADAPTER_MARKER not in Path(proxy).read_bytes():
        raise RuntimeError('检测到旧版或不兼容的适配层模板，请升级管理器后重试。')
