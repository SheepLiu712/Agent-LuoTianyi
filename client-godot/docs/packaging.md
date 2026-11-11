# Windows x64 打包规范

本文是 `Agent-LuoTianyi/client-godot` 的现行打包说明，供其他对话直接复用。除标有绝对路径的命令外，以下命令默认在 `client-godot` 工程目录执行；脚本内部使用 `$PSScriptRoot` 定位工程，因此不依赖当前目录。

下文示例版本为写作时的 `0.1.6.3`；实际打包时替换为 `release.json` 中的目标版本。

## 1. 交付形态

工程有两种产物，二者使用同一份 Godot 导出目录：

| 形态 | 入口 | 产物 | 用途 |
|---|---|---|---|
| 目录版 + ZIP | `scripts/build.ps1` | `dist/agentluo-<version>/`、`artifacts/agentluo-<version>.zip` | 完整分发、回退、排查 |
| 单文件版 | `scripts/build_single.ps1` | `agentluo-<version>-single.exe` | 桌面直接运行 |

单文件版不是 Godot 的 `embed_pck`。Live2D/Cubism、`WindowsSecurity`、`PcmStreamDecoder` 等原生 DLL 不能塞进 PCK，所以单文件版采用 **C# 自解压壳**：把完整导出目录压成 `payload.zip` 嵌入 EXE，首次运行时解压到 `%LOCALAPPDATA%\AgentLuo-Single\<version>-<yyyyMMdd-HHmmss>`，再启动其中的 `agentluo.exe`。

因此：

- 单文件 EXE 内必须包含 `agentluo.exe`、`agentluo.pck`、全部插件 DLL、`licenses/`、`PREVIEW.md` 和 `release.json`。
- 不要用只含 EXE 和 PCK 的目录制作单文件版；缺 DLL 会在启动或 Live2D/音频初始化时失败。
- 单文件版首次启动需要解压，磁盘占用约为“EXE 大小 + 解压目录大小”。

## 2. 工具链与前置条件

| 依赖 | 要求 | 说明 |
|---|---|---|
| Godot | `4.7.1.stable` Windows x64 | 版本与 SHA-256 由 `scripts/common.ps1` 对照 `dependencies.lock.json` 校验 |
| 导出模板 | 同版本 Windows x64 模板 | 放在 `%APPDATA%\Godot\export_templates\4.7.1.stable\` |
| .NET Framework | 4.x | 单文件版使用 `%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe` |
| 图标 | `assets/ui/app_icon.ico` | 外层启动器图标；不能传 SVG 给 `csc` |
| PowerShell | Windows PowerShell 5.1 或 `pwsh` | 含中文的 `.ps1` 必须保存为 UTF-8 with BOM |

常用本机路径：

```powershell
$Godot = 'D:\godot\godot4.7.1\godot.exe'
$Project = 'D:\01restart\langchain\lty\Agent-LuoTianyi\client-godot'
```

`Resolve-Godot` 会检查 `--version` 是否等于锁文件中的 `engine.version_output`，并校验 GUI 可执行文件的 SHA-256。传入 `*_console.exe` 时会校验同目录的 GUI EXE。工具链不符时不会继续导出。

## 3. 版本规范

`release.json` 是版本单一来源。`build.ps1` 在导出前同步三处：

| 文件 | 字段 | 规则 |
|---|---|---|
| `release.json` | `version` | 使用输入版本，三段或四段 |
| `project.godot` | `config/version` | 与输入版本一致 |
| `export_presets.cfg` | `application/file_version`、`application/product_version` | 三段版本补 `.0`，四段版本原样 |

版本号必须匹配 `^(0|[1-9][0-9]{0,4})\.(...){2,3}$`，每段 `0..65535`，不允许前导零。示例：`0.1.6.3`、`0.1.6.3.1`。

单文件启动器的 Assembly 字段由 `scripts/build_single.ps1` 的 `Get-VersionFields` 生成：

| 输入 | `AssemblyVersion` | `AssemblyFileVersion` | `AssemblyInformationalVersion` |
|---|---|---|---|
| `0.1.6.3` | `0.1.6.3` | `0.1.6.3.0` | `0.1.6.3` |
| `0.1.6.3.1` | `0.1.6.3.1` | `0.1.6.3.1` | `0.1.6.3.1` |

三段输入时不要让 `AssemblyVersion` 变成四段；历史上 `AssemblyVersion("0.1.6.1.0")` 会触发 `CS0647`。`AssemblyFileVersion` 使用四段是预期行为。资源管理器里 `FileVersion` 可能显示为三段，因为 Windows 会省略末尾的 `.0`；以 `ProductVersion` 和 `release.json` 为准。

## 4. 目录版与 ZIP

### 4.1 命令

交互式：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1
```

自动化（推荐）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1 `
  -Version '0.1.6.3' `
  -Godot 'D:\godot\godot4.7.1\godot.exe'
```

只导出目录、不生成 ZIP：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1 `
  -Version '0.1.6.3' `
  -Godot 'D:\godot\godot4.7.1\godot.exe' `
  -Package:$false
```

### 4.2 流程与输出

`build.ps1` 依次执行：

1. 校验并同步版本字段。
2. 在 `dist/` 下创建隐藏的临时构建目录。
3. 执行 Godot `--import`。
4. 执行 `--export-release "Windows Desktop"`，导出 `agentluo.exe` 与 `agentluo.pck`。
5. 以 headless 启动导出的 EXE 3 秒，失败则终止发布。
6. 复制 `licenses/`、`PREVIEW.md`、`release.json`。
7. 生成 ZIP 并逐项校验条目数量和长度。
8. 原子移动到最终目录/ZIP；失败时清理临时目录，不发布半成品。

输出结构：

```text
dist/agentluo-<version>/
  agentluo.exe
  agentluo.pck
  <插件 DLL 和依赖文件>
  licenses/
  PREVIEW.md
  release.json
artifacts/agentluo-<version>.zip
artifacts/<step>.log
```

同版本目录或 ZIP 已存在时，脚本自动改用 `<name>-<yyyyMMdd-HHmmss>-<8位随机>`，旧包不覆盖。失败日志保留在 `artifacts/import*.log`、`export*.log`、`export-startup*.log`。

## 5. 单文件版

### 5.1 一键命令（推荐）

从现有导出目录打包：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_single.ps1 `
  -Version '0.1.6.3' `
  -BuildDirectory 'D:\01restart\langchain\lty\Agent-LuoTianyi\client-godot\dist\agentluo-0.1.6.3'
```

先重新构建目录版再打包：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_single.ps1 `
  -Version '0.1.6.3' `
  -Godot 'D:\godot\godot4.7.1\godot.exe' `
  -Build
```

默认输出到桌面；指定目录或跳过启动自检：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_single.ps1 `
  -Version '0.1.6.3' `
  -BuildDirectory '...\dist\agentluo-0.1.6.3' `
  -OutputDirectory 'D:\release' `
  -SkipRunCheck
```

参数：

| 参数 | 必填 | 说明 |
|---|---|---|
| `-Version` | 是 | 目标版本，必须与构建目录的 `release.json` 一致 |
| `-Godot` | `-Build` 时建议 | 传给 `build.ps1`；未传时使用 `GODOT_BIN` 或交互输入 |
| `-BuildDirectory` | 否 | 已有导出目录；省略时查找 `dist/agentluo-<version>` 或最新的 `dist/agentluo-<version>-*` |
| `-OutputDirectory` | 否 | 单文件 EXE 输出目录；默认桌面 |
| `-Build` | 否 | 先调用 `build.ps1` 重新导出 |
| `-SkipRunCheck` | 否 | 跳过启动自检，仅用于快速迭代或已有独立验证 |

### 5.2 脚本流程

`build_single.ps1` 依次执行：

1. 校验版本号、构建目录必需文件和 `release.json` 版本。
2. 定位 `assets/ui/app_icon.ico` 与 `csc.exe`。
3. 将整个构建目录压成 `payload.zip`，`includeBaseDirectory=false`，保证 `agentluo.exe` 位于 ZIP 根。
4. 读取 `scripts/single-launcher/Launcher.cs`，替换版本占位符，写成 UTF-8 源文件。
5. 用 `csc` 编译为 `winexe`，嵌入 `payload.zip`，并传 `/win32icon`。
6. 复制到输出目录，打印大小、版本和 SHA-256。
7. 默认执行 `--launcher-wait --headless --quit-after 3`，退出码非 0 则失败。
8. 无论成功失败，删除 `tmp/single-launcher-build-<stamp>`。

启动器行为：

- 解压目录：`%LOCALAPPDATA%\AgentLuo-Single\<version>-<yyyyMMdd-HHmmss>`。
- 有 `.ready` 且 `agentluo.exe` 存在时复用，不重复解压。
- 缺失时删除并重建该版本目录。
- `--launcher-wait` 被启动器消费，等待子进程并返回其退出码；其余参数原样转发。
- 每次构建的启动器版本带时间戳，因此不同构建使用不同解压目录。

### 5.3 手工复现

需要脱离脚本排查时，按脚本同样的步骤执行：

```powershell
$build = '...\dist\agentluo-0.1.6.3'
$work = '...\tmp\single-manual'
New-Item -ItemType Directory -Force -Path $work | Out-Null

Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory(
  $build, (Join-Path $work 'payload.zip'),
  [IO.Compression.CompressionLevel]::Optimal, $false)

# 复制 Launcher.cs，并替换四个占位符：
# __ASSEMBLY_VERSION__ / __FILE_VERSION__ / __PRODUCT_VERSION__ / __LAUNCHER_VERSION__
$source = Join-Path $work 'Launcher.cs'
$payload = Join-Path $work 'payload.zip'
$single = Join-Path $work 'agentluo-0.1.6.3-single.exe'
$icon = '...\assets\ui\app_icon.ico'
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'

& $csc /nologo /codepage:65001 /target:winexe /win32icon:$icon /out:$single `
  /resource:$payload,payload.zip `
  /r:System.Windows.Forms.dll /r:System.IO.Compression.dll /r:System.IO.Compression.FileSystem.dll $source
```

关键点：

- `/codepage:65001` 必须保留，启动器源码含中文，且脚本写出的 `.cs` 无 BOM。
- `/resource:$payload,payload.zip` 的资源名必须是 `payload.zip`，与 `Launcher.cs` 的 `GetManifestResourceStream(Payload)` 一致。
- `payload.zip` 不能多一层顶层目录，否则解压后找不到 `agentluo.exe`。
- 手工打包同样必须带 `/win32icon`。

## 6. 图标规范

图标有两个独立层面，不能混为一谈：

| 层面 | 来源 | 作用 |
|---|---|---|
| 外层单文件 EXE | `csc /win32icon:assets/ui/app_icon.ico` | 资源管理器、桌面快捷方式显示 |
| 内层 Godot EXE | `project.godot` 的 `config/windows_native_icon` 与 `export_presets.cfg` 的 `application/icon` | 运行后窗口/任务栏图标 |

规范：

- `csc` 只接受 `.ico`，不要传 `app_icon.svg`。
- 不传 `/win32icon` 时，外层 EXE 会显示 .NET 默认图标；这是“打包后图标不对”的最常见原因。
- `assets/ui/app_icon.ico` 与 `assets/ui/app_icon.svg` 是同一设计的 Windows 图标资源，当前 ICO 与旧端 `client/res/gui/icon.ico` 保持逐字节一致；除非明确改版，不要重新量化或另存。
- 替换桌面上的同名 EXE 后，Windows 可能缓存旧图标。先确认文件哈希已变化，再刷新资源管理器或换一个文件名验证。
- 如果外层图标正确、运行后窗口图标错误，检查 Godot 的两个 `application/icon` / `windows_native_icon` 配置，而不是 `csc`。

提取外层图标核验：

```powershell
Add-Type -AssemblyName System.Drawing
$exe = (Resolve-Path '...\agentluo-0.1.6.3-single.exe').Path
$icon = [System.Drawing.Icon]::ExtractAssociatedIcon($exe)
$icon.ToBitmap().Save("$env:TEMP\agentluo-single-icon.png", [System.Drawing.Imaging.ImageFormat]::Png)
Start-Process "$env:TEMP\agentluo-single-icon.png"
```

## 7. 验证清单

打包完成后至少确认：

- [ ] `release.json`、`project.godot`、`export_presets.cfg` 的版本一致。
- [ ] 目录版包含 `agentluo.exe`、`agentluo.pck`、全部 DLL、`licenses/`、`PREVIEW.md`、`release.json`。
- [ ] ZIP 能完整解压，条目数与目录文件数一致。
- [ ] 单文件 EXE 的 `FileVersion` / `ProductVersion` 与输入版本一致。
- [ ] 单文件 EXE 的资源管理器图标为 AgentLuo 图标，不是 .NET 默认图标。
- [ ] `--launcher-wait --headless --quit-after 3` 返回 0。
- [ ] 解压目录中的 `release.json` 版本与文件名一致。
- [ ] 记录 SHA-256 与文件大小，交付时一并提供。

命令：

```powershell
$exe = '...\agentluo-0.1.6.3-single.exe'
(Get-Item $exe).VersionInfo | Format-List FileVersion,ProductVersion,FileDescription,ProductName
(Get-Item $exe).Length
(Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant()
& $exe --launcher-wait --headless --quit-after 3
"exit=$LASTEXITCODE"
```

headless 启动通过只证明进程能启动并正常退出，不代替 GPU、Live2D、音频设备、DPI、真实账号和服务端验收。

打包相关门禁：

```powershell
python tests/test_build_prompt.py
python tests/test_review_documentation.py
python scripts/check_complexity.py
```

完整门禁：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check.ps1 `
  -Godot 'D:\godot\godot4.7.1\godot.exe' `
  -Python '<python.exe>'
```

## 8. 发布与旧版清理

发布顺序：

1. 先构建目录版并完成启动检查。
2. 用同一目录构建单文件版。
3. 验证版本、图标、启动、哈希。
4. 再清理旧版。

清理范围仅限构建产物和启动器解压缓存：

- 桌面旧 `agentluo-*-single.exe`
- `dist/agentluo-<old>*`
- `artifacts/agentluo-<old>*.zip` 与对应旧日志
- `%LOCALAPPDATA%\AgentLuo-Single\<old>-*`
- `tmp/single-launcher-build-*`

不可删除：

- 当前版本的 `dist/` 与 `artifacts/` 包
- `%APPDATA%\AgentLuo-Godot`（用户配置、日志、缓存）
- 源码、`assets/`、`licenses/`、`dependencies.lock.json`
- 其他对话正在使用的构建目录

安全清理示例（先确认 `$old`，再执行）：

```powershell
$old = '0.1.6.2'
Get-ChildItem 'dist' -Directory -Filter "agentluo-$old*" | Remove-Item -Recurse -Force
Get-ChildItem 'artifacts' -File -Filter "agentluo-$old*.zip" | Remove-Item -Force
Get-ChildItem (Join-Path $env:LOCALAPPDATA 'AgentLuo-Single') -Directory -Filter "$old-*" |
  Remove-Item -Recurse -Force
Get-ChildItem 'tmp' -Directory -Filter 'single-launcher-build-*' | Remove-Item -Recurse -Force
```

保留至少一个上一版本作为回退，直到新版本完成实机验收。

## 9. 已知问题与排错

| 现象 | 原因 | 处理 |
|---|---|---|
| PowerShell 报中文乱码/解析错误 | `.ps1` 被保存为 UTF-8 无 BOM，Windows PowerShell 5.1 按 GBK 读取 | 用 `New-Object Text.UTF8Encoding($true)` 写回 BOM |
| `csc` 报 `CS0647` 或版本无效 | `AssemblyVersion` 用了不合适的四段值 | 三段输入用 `assembly = <version>`、`file = <version>.0` |
| 外层 EXE 是默认 .NET 图标 | `csc` 缺少 `/win32icon` 或 ICO 路径错误 | 补 `/win32icon:<绝对路径>`，重新编译并换名验证 |
| 图标已换但桌面仍旧 | Explorer 图标缓存 | 刷新资源管理器、重启 Explorer，或复制成新文件名 |
| 启动提示“内置运行文件缺失” | `payload.zip` 资源名或嵌入参数错误 | 使用 `/resource:<zip>,payload.zip` |
| 启动后找不到 `agentluo.exe` | ZIP 多了一层目录或构建目录不完整 | 用 `includeBaseDirectory=false`，确认目录版能独立启动 |
| Godot 报告导出成功但只生成 EXE、没有 PCK | `export_presets.cfg` 的 `binary_format/embed_pck=true` | 改回 `false`；构建脚本与单文件壳都要求独立 `agentluo.pck` |
| 单文件启动退出码非 0 | 子进程启动失败/参数错误 | 去掉 `--launcher-wait` 观察窗口，或直接运行解压目录的 `agentluo.exe` |
| `csc` 报 `CS1607` 文件版本警告 | .NET 对文件版本的格式提示 | 确认三段/四段规则正确后可接受；若编译失败则修正版本字段 |
| 首次运行被 SmartScreen/杀软拦截 | 未做代码签名 | 交付 SHA-256，必要时做代码签名；不要在文档中承诺“无警告” |
| 单文件每次启动都解压 | 启动器版本含时间戳，目录不同 | 属预期；清理 `%LOCALAPPDATA%\AgentLuo-Single` 旧目录 |
| 同版本重复打包目录带后缀 | `build.ps1` 保留旧包 | 属预期；发布时使用最新目录或先归档旧包 |
| 选错版本导致单文件与目录不一致 | `-Version` 与构建目录 `release.json` 不符 | 脚本已校验并拒绝；重新构建或传入正确目录 |

### 编码与脚本约定

- 含中文的 `.ps1` 必须是 UTF-8 with BOM。`apply_patch` 默认不写 BOM，改完脚本后要显式检查前三字节是否为 `EF BB BF`。
- 不要用 `$args` 作为自定义变量名；它是 PowerShell 保留变量。
- 单文件启动器源码由脚本以 UTF-8 无 BOM 写出，因此 `csc` 命令必须带 `/codepage:65001`。
- 脚本内的临时目录只能位于工程 `tmp/` 下，删除前必须校验绝对路径仍在 `tmp/` 内。

## 10. 快速复制区

```powershell
$Project = 'D:\01restart\langchain\lty\Agent-LuoTianyi\client-godot'
$Godot = 'D:\godot\godot4.7.1\godot.exe'
$Version = '0.1.6.3'

# 1) 目录版 + ZIP
powershell -NoProfile -ExecutionPolicy Bypass -File "$Project\scripts\build.ps1" `
  -Version $Version -Godot $Godot

# 2) 单文件版（重新构建并输出到桌面）
powershell -NoProfile -ExecutionPolicy Bypass -File "$Project\scripts\build_single.ps1" `
  -Version $Version -Godot $Godot -Build

# 3) 验证
$exe = Join-Path ([Environment]::GetFolderPath('Desktop')) "agentluo-$Version-single.exe"
(Get-Item $exe).VersionInfo | Format-List FileVersion,ProductVersion
(Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant()
& $exe --launcher-wait --headless --quit-after 3
"exit=$LASTEXITCODE"
```

## 11. 相关文件

- [构建脚本](../scripts/build.ps1)
- [单文件打包脚本](../scripts/build_single.ps1)
- [公共构建函数](../scripts/common.ps1)
- [启动器模板](../scripts/single-launcher/Launcher.cs)
- [版本来源](../release.json)
- [Windows 导出预设](../export_presets.cfg)
- [应用图标](../assets/ui/app_icon.ico)
- [测试与门禁](testing.md)
