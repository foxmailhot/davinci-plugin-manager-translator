# 达芬奇插件管理与翻译软件

Windows x64 本地 OFX 插件管理、文字翻译和可恢复的界面翻译适配工具。使用接近 DaVinci Resolve 的深灰界面，所有功能由用户手动触发。

## 使用

从本仓库 **Releases** 下载 `ResolvePluginManager-windows-x64.zip`，解压后启动 `ResolvePluginManager.exe`，无需 Python。

1. 在插件清单选中模块，点击 **一键翻译所选插件**。
2. 自动提取英文候选文字、使用内置词库和已缓存译文，再调用所选接口翻译缺失项。可以停止，已完成的译文会保留。
3. 检查预览。选择 **应用至插件（实验）**，退出达芬奇及其他宿主后安装适配层，再重启达芬奇验证。此操作需要插件目录写权限。
4. 异常时选择 **恢复原版插件**。原版模块保留在同目录，另有校验备份。

## 实际支持与限制

- 管理 Windows x64 OFX 模块；一个模块可以包含多个效果。可扫描、筛选、导出、备份禁用和恢复。
- 静态读取模块及关联 DLL 的英文候选文字，不执行插件来做提取。候选可能包含内部文字、错误提示和未使用的内容；候选翻译数量不代表真实界面覆盖率。BCC 共享库的文字可能跨多个模块。
- 实验 OFX 适配层在插件提交显示属性时翻译标签、提示、选项、分类及说明。插件 ID、参数 ID、默认值、数字及渲染入口转发给原模块，不作修改。
- **已通过模拟 OFX 宿主和测试插件验证，尚未完成真实 BCC / Sapphire 在达芬奇中的兼容性验证，不保证所有插件可用或全部汉化。** 官方升级后需要先核对原版文件再重新适配。
- 独立 Title Studio、Particle Illusion、Mocha 等窗口，以及插件自绘控件不在通用 OFX 属性适配范围内。
- 应用翻译和禁用均影响共享此模块的所有 OFX 宿主。检测 Resolve.exe 运行状态；其他宿主请自行退出。
- 软件不含 Boris FX 插件文件、商业资源、许可证或破解逻辑，不改变插件授权状态。

## 翻译接口

| 服务 | 使用条件 |
| --- | --- |
| 本地词库 | 内置通用术语及用户校对词条，无需联网 |
| MyMemory | 无需密钥，官方匿名额度 5000 字符/日；本程序设置 4500 字符/日预算，超额或服务错误保存进度 |
| Google 网页翻译 | 非官方实验端点，无服务保证，可能限流、不可达或变更；不承诺持续免费可用 |
| Google Cloud Translation | 官方 API，自备密钥及 Google Cloud 配置；有免费额度，超额可能产生费用 |
| LibreTranslate | 可连接本机或自建服务；远程服务须 HTTPS，本机允许 HTTP |

仅将提取的英文文字发送到用户选择的服务。API 密钥仅保存在当前会话内，不写入配置，不进入 GitHub。译文缓存在本机，用户校对词库优先于缓存。MyMemory 的测试接口请求也会消耗服务端额度，服务端实际额度以其自身统计为准。

参考：[MyMemory 接口](https://mymemory.translated.net/doc/spec.php)、[额度](https://mymemory.translated.net/doc/usagelimits.php)、[Google 官方价格](https://cloud.google.com/translate/pricing)、[LibreTranslate](https://docs.libretranslate.com/)。

## 手动更新

点击右上角 **检查更新**，从本仓库最新正式 GitHub Release 获取版本信息。用户确认后下载 Windows 包及 SHA-256 文件，校验成功后启动新版本；旧版本保留。使用同一 Windows 账户的新版继续读取原有设置、词库和备份。

更新采用并存版本，不覆盖旧 EXE；之后可从 `%LOCALAPPDATA%\ResolvePluginManager\updates` 启动已下载的新版本。不会在启动时自动联网检查或静默安装。检查文件用于完整性验证，当前发行版尚无代码签名。

## 开发与构建

```powershell
python -m pip install --target .tools/packaging pyinstaller==6.22.3
python -m pip install --target .tools ziglang==0.13.0
./build-resolve-manager.ps1
python -m unittest discover -s resolve_manager -p 'test_*.py' -v
python resolve_manager/release_package.py 'dist/达芬奇插件管理与翻译软件' release
```

GitHub Actions 可手动构建；推送 `vX.Y.Z` 标签后构建、测试并发布带校验文件的 Release。更新版本前请同步修改 `resolve_manager/version.py`。

原版恢复和本地数据位置详见 [使用说明](resolve_manager/使用说明.md)。OpenFX 头文件的第三方许可见 [THIRD_PARTY_NOTICES.txt](resolve_manager/THIRD_PARTY_NOTICES.txt)。本项目与 Blackmagic Design、Boris FX、Google 无隶属关系。
