$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONPATH = Join-Path $PSScriptRoot '.tools/packaging'
$zigPath = Join-Path $PSScriptRoot '.tools/ziglang/zig.exe'
if (!(Test-Path -LiteralPath $zigPath)) { throw 'Install Zig 0.13.0: python -m pip install --target .tools ziglang==0.13.0' }
python resolve_manager/build_native.py --zig $zigPath
if ($LASTEXITCODE -ne 0) { throw 'OFX translation adapter build failed' }
$assetPath = Join-Path $PSScriptRoot 'resolve_manager/assets'
python -m PyInstaller --noconfirm --clean --onefile --windowed --name 'ResolvePluginManager' --add-data "$assetPath;assets" --distpath 'dist/达芬奇插件管理与翻译软件' --workpath '.tools/resolve-manager-build-v02' --specpath '.tools' 'resolve_manager/app.py'
if ($LASTEXITCODE -ne 0) { throw 'Resolve manager build failed' }
Copy-Item -LiteralPath 'resolve_manager/使用说明.md' -Destination 'dist/达芬奇插件管理与翻译软件/使用说明.md'
Copy-Item -LiteralPath 'resolve_manager/THIRD_PARTY_NOTICES.txt' -Destination 'dist/达芬奇插件管理与翻译软件/THIRD_PARTY_NOTICES.txt'
