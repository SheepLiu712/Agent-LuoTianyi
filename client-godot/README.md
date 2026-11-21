# AgentLuo Godot Windows 客户端

AgentLuo 的独立 Windows x64 桌面客户端，使用 Godot 4.7.1 构建。当前源码版本为 `0.2.0.1`，版本号以 `release.json` 为准。

客户端包含 Live2D 角色、WebSocket 文字聊天、流式语音播放、本地聊天历史、私人动态、设置和日志。它尚未替换旧 Python 客户端，也不会导入旧客户端的凭据或聊天记录。

作者的个人笔记位于仓库根目录下的 `docs-godot/`、`client-godot/docs/` 和 `archive/`。这些目录已写入根 `.gitignore`，不随仓库分发。

## 环境要求

| 用途 | 要求 |
| --- | --- |
| 运行 | Windows x64 |
| 打开工程 | Godot 4.7.1 standard，版本输出必须为 `4.7.1.stable.official.a13da4feb` |
| 导出 | Godot 4.7.1 导出模板 |
| 运行构建脚本 | PowerShell 5.1 或更高版本 |
| 重建 Live2D 插件或原生扩展 | Visual Studio 2022 C++ Build Tools、Python 3.11.9、SCons 4.7.0 |
| 运行测试 | Python 3.12，并按 `tests/requirements-*.txt` 安装依赖 |
| 生成单文件 EXE | .NET Framework 4.x 的 `csc.exe` |

`dependencies.lock.json` 记录了 Godot 可执行文件、导出模板、CA 证书包、Live2D 插件、原生扩展和 SQLite 插件的版本与 SHA-256。`scripts/common.ps1` 在 PowerShell 脚本执行前会校验 Godot 的版本输出和可执行文件哈希，不匹配时直接退出。

## 打开工程

1. 安装 Godot 4.7.1 standard。
2. 在 Godot 项目管理器中导入 `client-godot/project.godot`。
3. 首次打开时等待资源导入完成，再运行主场景。

客户端数据写入 `%APPDATA%\AgentLuo-Godot`，不写入安装目录。旧 Python 客户端的数据目录保持不变，两者不共享凭据和聊天数据库；新客户端可以按用户选择只读导入旧客户端的语音和图片缓存。

## 构建 Windows 发布包

在 `client-godot` 目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

脚本参数：

| 参数 | 说明 |
| --- | --- |
| `-Version <版本>` | 指定版本号；不传时交互输入，直接回车沿用 `release.json` |
| `-Godot <exe>` | 指定 Godot 可执行文件；不传时读取 `GODOT_BIN`，仍为空则交互输入 |
| `-OutputDirectory <目录>` | 发布目录的父目录，默认 `dist` |
| `-Package:$false` | 只导出目录，不生成 ZIP |

版本号必须为三段或四段数字，每段范围 `0..65535`，不带前导零。脚本会把版本同步到以下位置：

- `release.json` 的 `version`
- `project.godot` 的 `config/version`
- `export_presets.cfg` 的 `application/file_version` 和 `application/product_version`；三段版本补 `.0`

默认产物：

- 目录：`dist/agentluo-<版本>/`
- ZIP：`artifacts/agentluo-<版本>.zip`

同版本产物已存在时，新目录和 ZIP 会追加时间戳与随机后缀，旧产物保持不变。导出先写入临时目录，全部检查通过后才移动到最终位置；失败时不会留下半成品目录。版本字段写入后，即使导出失败也会保留新版本号，便于修复后重试。

发布目录必须完整分发，包含 `agentluo.exe`、`agentluo.pck`、`release.json`、`PREVIEW.md`、`licenses/`、`windows_security.dll`、`libgd_cubism.windows.release.x86_64.dll` 和 `libgdsqlite.windows.template_release.x86_64.dll`。构建脚本会检查 `agentluo.exe`、`agentluo.pck`，并要求 `licenses/`、`PREVIEW.md`、`release.json` 存在；`verify_release_archive.py` 还会检查完整文件清单和三份 DLL。

导出完成后可以单独校验：

```powershell
python .\tests\verify_release_archive.py .\artifacts\agentluo-0.2.0.1.zip .\dist\agentluo-0.2.0.1
```

该命令检查 ZIP 条目、CRC、版本、许可文件和三份 DLL 的 SHA-256。构建脚本中的 `--headless --quit-after 3` 只验证程序能启动，不代表界面、GPU 或实机运行正常。

## 生成单文件 EXE

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_single.ps1 -Version 0.2.0.1
```

脚本读取已有的 `dist/agentluo-<版本>`，用 .NET Framework 的 `csc.exe` 把整个目录压缩进一个自解压 EXE，默认输出到桌面。首次启动时解压到 `%LOCALAPPDATA%\AgentLuo-Single\<启动器版本>`，然后运行其中的 `agentluo.exe`；用户数据仍写入 `%APPDATA%\AgentLuo-Godot`。

常用参数：

- `-Build`：先调用 `build.ps1` 生成目录。
- `-BuildDirectory <目录>`：使用指定目录，不按版本查找 `dist`。
- `-OutputDirectory <目录>`：指定输出目录。
- `-SkipRunCheck`：跳过启动检查。

## 重建 Live2D 插件

仓库已包含锁定版本的 Windows x64 插件二进制和 shader，正常构建不需要重新编译。需要重建时：

1. 检出 `dependencies.lock.json` 中 `gd_cubism.commit` 对应的源码，并初始化其 `godot-cpp` 子模块到 `gd_cubism.godot_cpp_commit`。
2. 按 gd_cubism 的说明，把 Cubism SDK 5-r.1 放入源码的 `thirdparty/`。
3. 安装 Visual Studio 2022 C++ Build Tools、Python 3.11.9 和 SCons 4.7.0。
4. 运行：

```powershell
python .\scripts\build_cubism.py --source '<gd_cubism 源码目录>'
```

脚本会拒绝有未提交改动的源码，校验两个 Git 提交号、SCons 版本和生成的 DLL 的 SHA-256。输出复制到 `addons/gd_cubism/bin/`。工具链变化后必须重新验证并更新 lock，不能直接替换二进制。

常用参数：`--jobs <数量>` 指定并行任务数，默认 8；`--console-encoding utf-8|gbk` 处理 Windows 控制台编码。

## 重建原生扩展

`native/` 下包含四个 C++ 模块，统一编译为 `addons/windows_security/bin/windows_security.dll`：

| 模块 | 作用 |
| --- | --- |
| `WindowsSecurity` | 使用 CNG RSA-OAEP/SHA256 加密密码，使用当前用户 DPAPI 保护本机密钥 |
| `WindowsInputMethod` | 查询和切换 Windows 输入法状态 |
| `PcmStreamDecoder` | 解码流式 PCM 音频，并提供波形幅度 |
| `StorageVolume` | 查询磁盘容量 |

重建步骤：

```powershell
python .\scripts\build_security.py --godot-cpp '<锁定版本的 godot-cpp 目录>'
```

`godot-cpp` 的提交号必须等于 `dependencies.lock.json` 的 `gd_cubism.godot_cpp_commit`，工作区必须干净，SCons 版本必须为 4.7.0。脚本会校验生成 DLL 的 SHA-256。

如果 MSVC 无法解析包含中文的源码路径，可以建立目录联接：

```powershell
New-Item -ItemType Junction -Path .\native\godot-cpp -Value '<真实 godot-cpp 目录>'
```

联接和编译产物不会进入 Git 或发布包。

原生加密互操作测试：

```powershell
python .\tests\run_security_interop.py --godot <Godot.exe>
```

测试需要 `cryptography` 和 `fastapi`，只在本机运行，不连接外部服务。

## TLS 信任源

客户端固定使用 `certs/ca-bundle.pem` 作为唯一的 TLS 信任源，不读取 Windows 当前用户根证书库。`project.godot` 中的 `network/tls/certificate_bundle_override` 指向该文件，`export_presets.cfg` 的 `include_filter` 必须保留 `*.pem`。

证书包的来源、快照日期、SHA-256 和刷新步骤见 [certs/README.md](certs/README.md)。

固定 CA 生效时，证书校验失败会在登录页提示“当前版本过低，请更新最新版本”；原始 mbedTLS 错误仍写入日志。

发布版只允许 HTTPS。`localhost`、`127.0.0.0/8` 和 `[::1]` 保留明文 HTTP，供本地测试使用；其他明文地址会在发送账号信息前返回 `INSECURE_SERVER`。

## 测试

四组默认回归：

```powershell
$engine = '<Godot 4.7.1 可执行文件>'
$python = '<已安装测试依赖的 python.exe>'

.\scripts\check.ps1 -Godot $engine -Python $python
.\scripts\check_accounts.ps1 -Godot $engine -Python $python
.\scripts\check_network.ps1 -Godot $engine -Python $python
.\scripts\check_features.ps1 -Godot $engine -Python $python
```

| 分组 | 内容 |
| --- | --- |
| `check` | 首次资源导入、圈复杂度检查、启动、界面与模块测试 |
| `accounts` | 原生加密互操作、账号协议、登录状态、账户页、窗口切换、依赖边界 |
| `network` | WebSocket 传输、真实聊天、语音聊天、角色触摸上报 |
| `features` | 历史、图片、设置、模型、动态和扩展接口 |

Python 静态自检：

```powershell
python .\tests\test_dependency_boundaries.py
python .\tests\test_review_documentation.py
python .\tests\test_check_gate.py
python .\tests\test_build_prompt.py
python .\tests\test_complexity_check.py
python .\scripts\check_complexity.py
```

完整命令、单脚本入口、GPU 验收和测试约定见 [tests/README.md](tests/README.md)。

CI 中的 `godot-static` 作业只运行上述 Python 静态检查，不启动 Godot，也不执行导出或 GPU 测试。

## 目录结构

| 路径 | 内容 |
| --- | --- |
| `src/application.gd` | 应用入口、页面切换、日志和窗口生命周期 |
| `src/application/` | 账号生命周期、窗口协调、界面风格 |
| `src/composition/` | 服务创建与组装 |
| `src/domain/` | 账号作用域、消息 ID、时间和服务地址等纯规则 |
| `src/network/` | HTTP、WebSocket、TLS、连通性探测和可靠发送队列 |
| `src/session/` | 账号、聊天、历史、动态、模型和设置控制器 |
| `src/storage/` | SQLite、音频与图片缓存、日志、凭据和设置 |
| `src/media/` | 图片附件、音频播放和原生解码器 |
| `src/avatar/` | Live2D 角色驱动、构图、表情和触摸反馈 |
| `src/platform/` | Windows 窗口、文件、输入、加密和运行时适配 |
| `src/ui/` | 页面、窗口、气泡、下拉框、对话框和共享控件 |
| `src/preview/` | 离线预览场景和演示数据 |
| `src/extensions/` | 预留的外观、世界和设备接口 |
| `scenes/` | Godot 场景 |
| `tests/` | Godot 测试、Python runner、依赖清单和模拟数据 |
| `scripts/` | 构建、打包、检查和复杂度脚本 |
| `native/` | C++ 原生扩展源码 |
| `addons/` | Live2D、SQLite 和原生扩展插件 |
| `assets/` | 图片、模型、图标和 shader |
| `theme/` | Godot 主题资源 |
| `certs/` | TLS CA 证书包 |
| `licenses/` | 第三方许可和素材来源 |

## 本地数据

默认根目录为 `%APPDATA%\AgentLuo-Godot`，主要子目录：

| 路径 | 内容 |
| --- | --- |
| `accounts/`、`account.cfg` | 本机账号记录和受保护凭据 |
| `history/` | 聊天与动态的 SQLite 数据 |
| `audio/` | 语音缓存 |
| `images/` | 历史图片缓存 |
| `models/` | 模型配置和受保护的 API Key |
| `reading/` | 阅读位置 |
| `logs/` | 每次启动的 JSONL 日志和元数据 |
| `window_layout.cfg` | 设置与主窗口布局 |
| `window-geometry.cfg`、`dynamics-window.cfg` | 窗口位置和尺寸 |

聊天历史由本地 SQLite 保存，用于离线显示和分页；服务端仍是历史数据的来源。语音和图片缓存按服务器和账号分别限制在 256 MiB；语音单条最多 16 MiB，图片单条最多 16 MiB。超过上限时按修改时间从旧到新删除。缓存没有按时间自动过期，仍可在“缓存与导入”页手动清理语音，并导入旧 Python 客户端中按消息 UUID 匹配的语音和图片。

## 平台边界

- 当前只实现 Windows x64。Android 和 iOS 仍缺少安全、模型、音频、窗口宿主和权限适配，桌面测试不能代替移动端验证。
- `src/extensions/` 中的外观、世界和设备接口默认返回 `NOT_IMPLEMENTED`，界面没有对应入口，不代表已经支持换装、虚拟世界或设备互联。
- 旧 Python 客户端仍可继续使用。新客户端不导入旧客户端的凭据和聊天记录，但可以只读导入其语音和图片缓存。
- 公共服务器、真实 TTS、系统 DPI、多显示器、Windows 10、集成显卡和长时间运行需要单独验收。

## 版本与发布状态

`release.json` 是版本的唯一来源，当前为 `0.2.0.1`。`dist/` 和 `artifacts/` 中存在 2026-11-18 的 `0.2.0.1` 构建，以及 2026-11-21 的带时间戳构建；这些产物都早于当前源码的最后修改，不能作为当前源码的发布证据。发布前需要重新运行 `scripts/build.ps1`。

## 相关文档

- [使用说明](PREVIEW.md)
- [测试入口](tests/README.md)
- [CA 信任源](certs/README.md)
- [第三方许可与素材来源](licenses/RESOURCES.md)
