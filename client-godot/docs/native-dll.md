# windows_security.dll 源码构成解析

> 本文面向会写 GDScript、懂 Godot 基本概念，但没有 PE / 逆向 / C++ 经验的项目维护者。全文的目标是让你读完之后，能独立回答五个问题：这个 DLL 里有什么、由哪些源码编译而来、Godot 如何加载它、四个类各自做什么、出问题该看哪里。
>
> **取证方式声明**：本文全部结论来自静态分析——读源码、读 PE 头、反汇编、读字符串表。**没有**动态加载 DLL、没有运行游戏、没有执行测试、没有联网核对上游。凡是需要运行才能确认的行为，本文只给出「可用第 11 节命令自行验证」的方法，不写「已验证」「实测成功」这类表述。

---

## 0. 阅读指南

### 0.1 这节回答什么

本节说明本文的边界：分析哪一个文件、为什么不分析别的文件、仓库里另外两个 DLL 是什么角色，以及推荐的阅读顺序。如果你只想快速拿到结论，直接跳到第 1 节；如果你是第一次接触 PE 格式，建议从第 2 节开始顺读。

### 0.2 分析什么、不分析什么

本文的分析对象是 `client-godot/native/` 目录下的四个 C++ 编译单元，以及它们链接产出的 `client-godot/addons/windows_security/bin/windows_security.dll`。同时覆盖 `native/SConstruct`（构建脚本）与 `scripts/build_security.py`（带门禁的构建入口）、`dependencies.lock.json` 中的 `windows_security` 段，以及 GDScript 侧对这四个类的调用面。

明确**不在**本文范围内的东西有三类。第一类是 Godot 引擎本体与 `godot-cpp` 的内部实现——本文只把它当作一个「被调用的库」来引用，不解释它怎么实现的。第二类是 `client-godot/src/` 下的全部 GDScript 业务源码，本文只在需要说明「某个原生方法被谁调用、返回字段被谁消费」时引用具体行号，不展开业务逻辑。第三类是另外两个第三方 DLL 的内部实现，只在第 9 节做表格式对照，不做逆向报告。单文件打包壳、PCK 打包细节同样不在范围内。

### 0.3 三个 DLL 的分工（一句话）

`windows_security.dll` 是本项目自有的原生扩展，把 Windows 系统能力（DPAPI 数据保护、RSA 公钥加密、键盘布局切换、磁盘容量查询、流式 PCM 解码）包装成 4 个 Godot 类供 GDScript 调用。`libgd_cubism.windows.release.x86_64.dll` 是第三方插件，提供 Live2D Cubism 模型的渲染能力。`libgdsqlite.windows.template_release.x86_64.dll` 是第三方插件，提供 SQLite 数据库访问。后两者的源码不在本仓库里，仓库中只有上游发布的编译产物，本文按哈希锁定引用。

### 0.4 推荐阅读顺序

第一遍建议只读第 1 到第 3 节，建立骨架：是什么、怎么被加载、二进制层面长什么样。第二遍读第 4 和第 5 节，逐个翻译源码，弄清每个类的职责与边界条件。第三遍按需查第 6 和第 7 节，前者是方法签名与返回字段的速查表，后者是五条业务数据流的完整链路。维护阶段读第 8 到第 11 节：怎么重建并校验哈希、有哪些安全边界与平台限制、想自己动手验证该准备哪些工具和注意哪些坑。

---

## 1. 一页看懂

### 1.1 这节回答什么

一句话定位：**这是一个 Godot 4 GDExtension 原生扩展 DLL，不是游戏逻辑 DLL**。它自己几乎不实现任何玩法逻辑，只做一件事——把 Windows 系统 API 包装成 GDScript 能调用的 4 个 Godot 类。理解这一点很重要：出问题时你面对的是「一层薄封装」，排查路径是固定的，不是「几百行 C++ 逻辑要读」。

### 1.2 总表

| 项 | 值 |
|---|---|
| 文件 | `addons/windows_security/bin/windows_security.dll` |
| 大小 | 345,600 字节 |
| SHA-256 | `037b797d14fe04de6e4ef72b5c74174f04bcf2f6089ca06c653bd8123d8b8752` |
| PE 类型 | PE32+ / x86-64（Machine `0x8664`） |
| 入口符号（导出） | `windows_security_init`，RVA `0x6cb0`，ordinal 1（**仅此一个**） |
| 注册类数量 | 4（`WindowsSecurity` / `WindowsInputMethod` / `PcmStreamDecoder` / `StorageVolume`） |
| 导入 DLL | 4 个：`bcrypt` `crypt32` `user32` `kernel32` |
| 导入函数总数 | 93（bcrypt 3 / crypt32 5 / user32 3 / kernel32 82） |
| 导出符号数 | **1** |
| 签名 | 无（`Get-AuthenticodeSignature` → `NotSigned`） |
| 源码构成 | 4 个 `.cpp`：`windows_security.cpp` `windows_input_method.cpp` `pcm_stream_decoder.cpp` `storage_volume.cpp` |

这张表里的每一行都对应本文后面某一节的证据：文件与哈希在第 3 节和第 8.5–8.6 节，PE 类型和节表在第 3.2、3.3 节，导出与导入在第 3.4、3.5 节，注册类数量与顺序在第 2.3 节和第 5.2.6 节，源码构成在第 4.2 节。

需要特别注意导出表那一行：**导出表只有一个符号**。四个类**不是**通过 PE 导出暴露的，而是在运行期通过 godot-cpp 的 `ClassDB::register_class` 注册进 Godot 的类数据库。所以「DLL 导出了四个类」是错的说法，正确说法是「DLL 导出了唯一的入口函数，入口函数在运行期注册了四个类」。这个区别在第 2.4 节展开，也是初学者最容易搞错的一点。

### 1.3 为什么必须用原生 DLL

GDScript 本身没有以下能力的等价物，只能靠系统 API 或 C++ 扩展实现。**DPAPI**（`CryptProtectData` / `CryptUnprotectData`）是 Windows 的用户级数据加密接口，绑定到当前登录用户的凭据，第三方进程拿不到密钥，Godot 没有暴露它。**RSA 公钥加密**需要 `bcrypt.dll` 与 `CRYPT32.dll` 处理 DER 结构的 PublicKeyInfo、密钥属性查询与 OAEP 填充，GDScript 既没有 BLOB 类型也没有 ASN.1 解析能力。**键盘布局切换**（`LoadKeyboardLayoutW` / `ActivateKeyboardLayout`）和 IME 开关不是一回事——Godot 的 `DisplayServer` 只暴露 IME 激活与否，不暴露具体键盘布局句柄（HKL），而密码框需要强制切到纯 ASCII 布局。**磁盘容量查询**（`GetDiskFreeSpaceExW`）拿的是卷级容量，`DirAccess` 只能逐目录累加文件大小，拿不到「整个盘剩多少」。**流式 PCM 解码**如果用 GDScript 逐样本做位运算与归一化，在 24 kHz 双通道的长语音上开销明显。

### 1.4 一条最短主线

```text
GDScript: ClassDB.class_exists("WindowsSecurity")
  -> Godot 读 .gdextension -> LoadLibrary("windows_security.dll")
  -> 解析并调用 windows_security_init (RVA 0x6cb0)
  -> initialize_security() -> ClassDB::register_class x 4
  -> GDScript 侧 class_exists() 返回 true，instantiate() 拿到 RefCounted
```

---

## 2. 从 Godot 到 C++ 的加载链路

### 2.1 这节回答什么

这一节回答「DLL 里的类是怎么变成 GDScript 里能 `class_exists` 的类的」。结论：靠 `.gdextension` 里声明的 `entry_symbol`，引擎加载 DLL 后调用这一个导出函数，函数内部再把四个类注册进 ClassDB。全过程只有一次跨语言调用点（`windows_security_init`），其余全是运行期的类注册。

### 2.2 `.gdextension` 逐字段

`addons/windows_security/windows_security.gdextension:1-7` 全文：

```ini
[configuration]
entry_symbol = "windows_security_init"
compatibility_minimum = "4.3"
reloadable = false

[libraries]
windows.x86_64 = "res://addons/windows_security/bin/windows_security.dll"
```

| 字段 | 值 | 含义 |
|---|---|---|
| `entry_symbol` | `windows_security_init` | 引擎加载 DLL 后唯一会调用的导出符号 |
| `compatibility_minimum` | `4.3` | 最低兼容 Godot 版本 |
| `reloadable` | `false` | 不参与编辑器热重载 |
| `libraries` 键 | `windows.x86_64` | 平台/架构标识，**只有 Windows x64 一项** |
| `libraries` 值 | `res://addons/windows_security/bin/windows_security.dll` | 开发态库路径 |

这些字段逐个说清楚。`entry_symbol` 是 Godot 与 GDExtension 的唯一契约点：引擎在 `LoadLibrary` 成功之后，用这个名字去 PE 导出表里找函数地址，找不到就直接放弃加载，所以这个名字必须与 `extern "C" GDE_EXPORT` 导出的函数名完全一致。`compatibility_minimum = "4.3"` 表示这个扩展要求 Godot 4.3 或更高版本；本项目的锁文件记录引擎为 4.7.1，满足要求。`reloadable = false` 表示这个库不参与编辑器的脚本热重载机制（与之相对的是 `reloadable = true` 的库，编辑器在编译脚本变更后会尝试重新加载 DLL）。`[libraries]` 段用「平台.架构」作为键，Godot 会按当前运行平台挑选匹配的条目；这里只有 `windows.x86_64` 一条，意味着**这个扩展在 macOS、Linux、Android 上根本不会被尝试加载**。

### 2.3 加载时序（源码明确写的）

```text
Godot 扫描 .gdextension
  |- LoadLibrary("windows_security.dll")
  |- GetProcAddress("windows_security_init")        <- PE 导出表的唯一符号
       |- GDExtensionBinding::InitObject(address, library, initialization)
            |- register_initializer(initialize_security)      <- native/windows_security.cpp:140
            |- register_terminator(terminate_security)        <- native/windows_security.cpp:141
            |- set_minimum_library_initialization_level(MODULE_INITIALIZATION_LEVEL_SCENE)  <- :142
            |- init()
                 |- 引擎回调 initialize_security(level)
                      |- level == MODULE_INITIALIZATION_LEVEL_SCENE
                           |- ClassDB::register_class<WindowsSecurity>()       <- :131
                              ClassDB::register_class<WindowsInputMethod>()  <- :132
                              ClassDB::register_class<PcmStreamDecoder>()     <- :133
                              ClassDB::register_class<StorageVolume>()        <- :134
```

对应源码 `native/windows_security.cpp:129-136`：

```cpp
void initialize_security(ModuleInitializationLevel level) {
    if (level == MODULE_INITIALIZATION_LEVEL_SCENE) {
        ClassDB::register_class<WindowsSecurity>();
        ClassDB::register_class<WindowsInputMethod>();
        ClassDB::register_class<PcmStreamDecoder>();
        ClassDB::register_class<StorageVolume>();
    }
}
```

对应源码 `native/windows_security.cpp:138-146`：

```cpp
extern "C" GDExtensionBool GDE_EXPORT windows_security_init(
        GDExtensionInterfaceGetProcAddress address, GDExtensionClassLibraryPtr library,
        GDExtensionInitialization *initialization) {
    GDExtensionBinding::InitObject init(address, library, initialization);
    init.register_initializer(initialize_security);
    init.register_terminator(terminate_security);
    init.set_minimum_library_initialization_level(MODULE_INITIALIZATION_LEVEL_SCENE);
    return init.init();
}
```

`windows_security_init` 做的事情只有四件：构造 `GDExtensionBinding::InitObject`（它拿到引擎传入的接口函数表与类库指针）、把 `initialize_security` 注册为初始化回调、把 `terminate_security` 注册为卸载回调、把最低初始化级别设成 `MODULE_INITIALIZATION_LEVEL_SCENE`，最后调用 `init.init()`。`init.init()` 内部会回调引擎提供的初始化函数，引擎随后以 `MODULE_INITIALIZATION_LEVEL_SCENE` 这个级别调用我们注册的 `initialize_security`，四个 `ClassDB::register_class` 就在这里执行。注册顺序是固定的：先 `WindowsSecurity`，再 `WindowsInputMethod`，再 `PcmStreamDecoder`，最后 `StorageVolume`。

二进制静态证据与源码一致：`windows_security_init` 位于 RVA `0x6cb0`，`initialize_security` 位于 RVA `0x6750`，后者内部恰好有 4 次注册调用，顺序与源码逐条对应。也就是说，**这个 DLL 里没有第二个入口、没有隐藏的注册路径**，四个类就是这四个。

### 2.4 为什么导出表只有一个符号

Godot 的类不是靠 PE 导出暴露的。godot-cpp 提供 `ClassDB::register_class<T>()` 模板函数，把 C++ 类登记到引擎的类数据库；登记完成后，引擎内部就知道了这个类的实例工厂、虚函数表、属性列表和绑定方法。此后 GDScript 里 `ClassDB.class_exists("WindowsSecurity")` 返回 `true`，`ClassDB.instantiate("WindowsSecurity")` 能拿到实例，`WindowsSecurity.new()` 也能用。

所以「导出表只有一个符号」与「DLL 提供了 4 个类、12 个绑定方法」这两件事毫不矛盾。前者说的是 **DLL 与操作系统之间**的契约（操作系统只需要一个入口），后者说的是 **DLL 与 Godot 运行时之间**的契约（通过 ClassDB 完成，完全不经过 PE 导出表）。同样的形态也出现在仓库另外两个 DLL 上：`libgd_cubism` 只导出 `gd_cubism_library_init`，`libgdsqlite` 只导出 `sqlite_library_init`。这是 godot-cpp 项目的标准交付形态，见到「只有一个导出符号」不必惊慌。

### 2.5 `reloadable = false` 的含义与后果

| 项 | 说明 |
|---|---|
| 源码依据 | `addons/windows_security/windows_security.gdextension:4` |
| 语义 | 该库不参与编辑器热重载 |
| 后果 | **推断**：重建 DLL 后必须重启编辑器 / 游戏进程，新的 DLL 才会被加载 |

`reloadable = false` 的直接语义是「这个库不参与热重载」。由此推出「改完 DLL 必须重启宿主进程」这一步，属于 GDExtension 语义的推断——仓库内没有任何明文说明这句话，但它与 Windows 的 DLL 加载模型一致：已加载的模块在进程生命周期内不会因为磁盘上的文件变化而自动替换。因此当你重建了 DLL 发现行为没变时，先确认自己重启了编辑器或游戏进程。

### 2.6 DLL 在发行包里的位置

| 环境 | 路径 |
|---|---|
| 开发态 | `res://addons/windows_security/bin/windows_security.dll` |
| 导出包（目录版） | EXE 同级根目录，例如 `dist/agentluo-0.1.8.6/windows_security.dll` |

原生 DLL 不能塞进 PCK，这是 Godot 导出机制决定的（GDExtension 是可执行文件级别的依赖，不是资源）。`docs/packaging.md:16` 对此有明确表述：单文件版不是 `embed_pck`，而是 C# 自解压壳，把完整导出目录压成 `payload.zip` 嵌入 EXE，首次运行时解压到 `%LOCALAPPDATA%\AgentLuo-Single\<version>-<timestamp>` 再启动。`export_presets.cfg:33` 也确认了 `embed_pck=false`，PCK 是独立的。因此分发时必须带上 DLL——`docs/packaging.md:20-21` 还专门警告「不要用只含 EXE 和 PCK 的目录制作单文件版；缺 DLL 会在启动或 Live2D/音频初始化时失败」。

---

## 3. 二进制解剖（先看骨架）

### 3.1 这节回答什么

这一节把 DLL 当成一个 PE 文件来读：头部字段说明它由什么工具链生成，节表说明代码和数据分别放在哪里，导入表说明它依赖哪些系统能力，导出表说明操作系统只能看到哪个入口，调试目录和 RTTI 说明还能从二进制里恢复出哪些源码信息。读完这一节，你应该能拿着 `objdump` 的输出对照本文，而不是把 DLL 当黑盒。

本节所有 RVA 都相对于 `ImageBase = 0x180000000`，因此 `VA = RVA + 0x180000000`。文件偏移（file offset）只用于在十六进制编辑器里定位字符串；RVA 用于在反汇编里定位代码。两者不能混用。

### 3.2 PE 头：一句话结论

这是一个 **MSVC 14.44 生成的 x64 PE32+ DLL，未加壳、未签名、静态链接 CRT、带 ASLR/DEP/GS、没有 CFG**。它只有一个导出函数，功能全部通过运行期 ClassDB 注册暴露。

| 字段 | 值 | 说明 |
|---|---|---|
| Machine | `0x8664` | AMD64 |
| Magic | `0x20B` | PE32+（64 位） |
| LinkerVersion | `14.44` | MSVC 14.44 工具链 |
| TimeDateStamp | `1794356886` | UTC 2026-11-11 00:28:06；本地时间 08:28:06 |
| Characteristics | `0x2022` | 可执行 + 大地址 + DLL |
| ImageBase | `0x180000000` | 64 位 DLL 的默认基址 |
| AddressOfEntryPoint | `0x233e0` | CRT 启动入口，不是导出函数 |
| SizeOfImage | `0x5b000` | 映射后总大小 |
| SizeOfHeaders | `0x400` | 头部大小 |
| Subsystem | `2` | Windows GUI |
| DllCharacteristics | `0x160` | HighEntropyVA + DYNAMIC_BASE + NX_COMPAT；无 CFG |
| CheckSum | `0` | MSVC 默认不填，正常 |
| SectionAlignment / FileAlignment | `0x1000` / `0x200` | 标准值 |

数据目录里有几个值得记住的非空项：

| 目录 | RVA / 大小 | 含义 |
|---|---|---|
| Export | `0x504d0` / `0x60` | 只有 1 个导出 |
| Import | `0x50530` / `0x64` | 4 个 DLL，93 个函数 |
| Exception | `0x56000` / `0x2e5c` | 989 条 x64 unwind 记录 |
| Base Relocation | `0x5a000` / `0x91c` | 支持 ASLR 重定位 |
| Debug | `0x4b9e0` / `0x1c` | 只有 1 条 ILTCG，无 CodeView |
| TLS | `0x4bb80` / `0x28` | CRT 的线程局部存储回调 |
| Load Config | `0x4b8a0` / `0x140` | GS cookie、CFG 指针 |
| IAT | `0x3b000` / `0x308` | 导入地址表 |
| Security | 0 / 0 | 无 Authenticode 签名 |
| Resource | 0 / 0 | 无 `.rsrc`，没有版本资源 |
| Delay Import | 0 / 0 | 没有延迟导入 |

### 3.3 节表：六个节各自装什么

| 节 | RVA | 虚拟大小 | 文件偏移 | 文件大小 | 熵 | 用途 |
|---|---|---|---|---|---|---|
| `.text` | `0x1000` | `0x39127` | `0x400` | `0x39200` | 6.351 | 全部代码，含静态 CRT 与 godot-cpp |
| `.rdata` | `0x3b000` | `0x15fe0` | `0x39600` | `0x16000` | 5.265 | 只读数据、导入/导出表、IAT、RTTI、字符串 |
| `.data` | `0x51000` | `0x4b2c` | `0x4f600` | `0x1400` | 3.394 | 可写全局数据、GS cookie、键盘布局缓存 |
| `.pdata` | `0x56000` | `0x2e5c` | `0x50a00` | `0x3000` | 5.423 | x64 异常/unwind 元数据，989 条 |
| `.fptable` | `0x59000` | `0x100` | `0x53a00` | `0x200` | 0.000 | 全零，用途未定性（见第 13 节） |
| `.reloc` | `0x5a000` | `0x91c` | `0x53c00` | `0xa00` | 5.254 | 基址重定位，1110 条 |

三个判断：

1. **没有高熵节**。最高熵是 `.text` 的 6.351，远低于加壳/压缩程序常见的 7.5 以上；也没有自修改代码迹象。结论：未加壳、未压缩。
2. **没有独立 `.rsrc`**。所以 `Get-Item ... | Select VersionInfo` 看到的所有版本字段都是空的；这是正常现象，不代表文件损坏。版本信息由外层 EXE/安装包负责，不在这个 DLL 里。
3. **没有独立 `.tls` 节**。TLS 目录指向 `.rdata`，回调是 CRT 的 `_tls_callback`，不是应用逻辑。

### 3.4 导入表：它到底调用了哪些系统能力

共 **4 个 DLL、93 个函数、没有 delay import**：

| DLL | 函数数 | 关键函数 | 用途 |
|---|---:|---|---|
| `bcrypt.dll` | 3 | `BCryptGetProperty`、`BCryptEncrypt`、`BCryptDestroyKey` | CNG RSA 公钥属性查询与 OAEP 加密 |
| `CRYPT32.dll` | 5 | `CryptStringToBinaryA`、`CryptDecodeObjectEx`、`CryptImportPublicKeyInfoEx2`、`CryptProtectData`、`CryptUnprotectData` | PEM/DER 解析、导入公钥、DPAPI |
| `USER32.dll` | 3 | `LoadKeyboardLayoutW`、`GetKeyboardLayout`、`ActivateKeyboardLayout` | 键盘布局切换 |
| `KERNEL32.dll` | 82 | `GetDiskFreeSpaceExW`、`GetLastError`、`GetCurrentThreadId`、CRT 所需的堆/锁/TLS 函数 | 磁盘容量、错误码、线程、静态 CRT |

安全排查的结论比“有哪些导入”更重要：**没有** `wininet`、`winhttp`、`ws2_32`、`urlmon`、`advapi32`、`shell32`、`ole32`、`netapi32`、`ntdll`、`dbghelp`，也没有 `vcruntime140.dll` / `msvcp140.dll` / `ucrtbase.dll`。这说明：

- 这个 DLL 不发起网络请求；
- 不读写注册表（没有 `advapi32`，就没有 `Reg*`）；
- 不创建进程、不调用 `ShellExecute`；
- C/C++ 运行库是静态链接进 DLL 的，不依赖 VC++ Redistributable（按当前构建参数）。

`kernel32` 里的 `CreateFileW`、`WriteFile` 等函数来自静态 CRT 的文件/控制台支持，调用点集中在 CRT 初始化与 `_fsopen`/`_open` 路径；本文分析的四个业务函数没有调用它们。`IsDebuggerPresent` 也只出现在 CRT 的调试报告/abort 路径，不是应用层反调试。

### 3.5 导出表：为什么只有一个符号

| 符号 | Ordinal | RVA | VA |
|---|---:|---|---|
| `windows_security_init` | 1 | `0x6cb0` | `0x180006cb0` |

导出表只有 1 个函数、1 个名字、没有 forwarder、没有 ordinal-only 导出。旁证 `windows_security.exp`（851 字节）也只列出 `windows_security_init`；`windows_security.lib`（1958 字节）是导入库，不是静态库，里面是 `__imp_windows_security_init` 和 `windows_security_NULL_THUNK_DATA` 这类给调用方链接用的桩。

这不是“功能少”，而是 GDExtension 的标准形态：操作系统只需要一个入口，类和方法由 Godot 运行期注册。第 2.4 节已经解释过这一点；同样的形态也出现在另外两个第三方 DLL 上（见第 9 节）。

### 3.6 调试信息：没有 PDB，但有构建指纹

Debug Directory 只有 **1 条**记录，类型是 **13（`IMAGE_DEBUG_TYPE_ILTCG`）**，不是 CodeView（类型 2）。因此：

- DLL 内**没有 PDB 路径、没有 RSDS GUID、没有 Age**；
- 不能用 `dumpbin /pdbpath` 之类的方法找回 PDB；
- 无法从二进制判断某个 PDB 是否匹配。

那条 type=13 的 988 字节负载不是随机哈希，而是增量链接的段名清单，例如 `.text$di`、`.text$mn`、`.idata$5`、`.CRT$XCA`、`.CRT$XCU` 等。结合 `.text` 里 29 个 6 字节 IAT thunk，可以高置信推断：**这次链接启用了增量链接（`/INCREMENTAL` 或 `/LTCG:incremental`）**。这不是加壳或篡改迹象。

构建机信息泄露在 `.exp` 而不是 DLL 里：`.exp` 含有 `VS\2022\BuildTools\VC\Tools\MSVC\14.44.35207\bin\HostX64\x64\link.exe` 和 `cwd=...\client-godot\native`。没有泄露 `C:\Users\<用户名>` 一类用户目录。

### 3.7 RTTI：从二进制反推类名与方法签名

`.rdata` 里有 35 条 MSVC type descriptor（`.?AV...`），其中和本项目直接相关的有 5 条类名：

| 文件偏移 | RVA | 名字 | 命名空间 |
|---|---|---|---|
| `0x503d0` | `0x51dd0` | `.?AVRefCounted@godot@@` | `godot` |
| `0x50428` | `0x51e28` | `.?AVPcmStreamDecoder@godot@@` | `godot` |
| `0x50458` | `0x51e58` | `.?AVStorageVolume@@` | 全局 |
| `0x50480` | `0x51e80` | `.?AVWindowsInputMethod@godot@@` | `godot` |
| `0x504b0` | `0x51eb0` | `.?AVWindowsSecurity@@` | 全局 |

更值钱的是 `MethodBindTR` / `MethodBindTRC` 的 type descriptor：模板参数把“类、返回类型、参数类型、是否 const”全部写进了名字。可以直接还原出 12 个绑定方法的签名：

| 类 | 还原签名 | 对应方法 |
|---|---|---|
| `WindowsSecurity` | `Dictionary(String const&, String const&) const` | `encrypt_password` |
| `WindowsSecurity` | `Dictionary(PackedByteArray const&, PackedByteArray const&) const` | `protect_secret` 与 `unprotect_secret` 共用 |
| `WindowsInputMethod` | `Dictionary(bool)` | `set_english` |
| `WindowsInputMethod` | `int64_t() const` | `get_layout` |
| `PcmStreamDecoder` | `Dictionary(PackedByteArray const&)` | `append` |
| `PcmStreamDecoder` | `Dictionary()` | `finish` |
| `PcmStreamDecoder` | `Dictionary() const` | `get_status` |
| `PcmStreamDecoder` | `PackedVector2Array(int)` | `read_frames` |
| `PcmStreamDecoder` | `double(int64_t) const` | `get_amplitude` |
| `PcmStreamDecoder` | `PackedFloat32Array(int) const` | `get_waveform` |
| `StorageVolume` | `Dictionary(String const&) const` | `query` |

注意两个容易写反的地方：`read_frames` 返回 `PackedVector2Array`（非 const 方法），`get_waveform` 返回 `PackedFloat32Array`（const 方法）。以源码 `native/pcm_stream_decoder.h:40-42` 为准。

没有找到 RTTI Complete Object Locator，也没有找到指向 COL 的 vftable 首项。这通常意味着构建时关闭了 RTTI 生成（`/GR-`），所以**不能仅凭二进制证明继承关系**；`WindowsSecurity : RefCounted` 这类结论来自源码和注册期引用的基类名串，属于“多路一致但没有 COL 直证”的推断。

### 3.8 字符串地图：三种字符串，三种读法

| 类别 | 例子 | 文件偏移 | 读法 |
|---|---|---|---|
| 源文件路径 | `pcm_stream_decoder.h`、`storage_volume.h`、`windows_input_method.h`、`windows_security.cpp` | `0x39ca0`、`0x39d70`、`0x39e40`、`0x39ff8` | 证明哪些翻译单元参与编译；前三者带绝对路径，最后一个带相对路径 |
| 错误码 | `INVALID_KEY`、`PROTECT_FAILED`、`INVALID_WAV`、`BUFFER_LIMIT` | `0x39f48`、`0x39f38`、`0x3a500`、`0x3a510` | 与源码里的字符串常量一一对应 |
| 方法名/字典键 | `encrypt_password`、`read_frames`、`total_bytes`、`queued_frames` | `0x3a058`、`0x3a448`、`0x3a6e0`、`0x3a4c0` | 与 `_bind_methods()` 和 GDScript 侧字段对应 |
| 宽字符串 | `AgentLuo`、`KeyLength`、`SHA256`、`00000409` | `0x39f08`、`0x39f70`、`0x39f88`、`0x3a378` | 分别用于 DPAPI 描述、BCrypt 属性名、OAEP 算法名、键盘布局 ID |

读字符串时有两个坑：

1. **串池复用**。`PROTECT_FAILED` 的地址 `0x39f22` 指向 `UNPROTECT_FAILED` 字符串的内部，不是独立字符串；`enabled` 在全文里只以 `_enabled`（`0x3a33f`）存在，代码引用的是 `+1` 地址。看到“偏移对不上”先怀疑串池，不要怀疑分析错了。
2. **UTF-16 宽字符串**。`AgentLuo`、`00000409` 等是 UTF-16LE，用普通 `strings` 看不到，要加 `-el`。`00000409` 的原始字节是 `30 00 30 00 30 00 30 00 30 00 34 00 30 00 39 00 00 00`。

### 3.9 安全缓解与签名

| 项 | 状态 | 证据 |
|---|---|---|
| ASLR | 开 | `DllCharacteristics` 的 `DYNAMIC_BASE (0x40)` |
| High-Entropy VA | 开 | `0x20` |
| DEP/NX | 开 | `NX_COMPAT (0x100)` |
| GS 栈保护 | 开 | LoadConfig 的 `SecurityCookie = 0x1800510c0`，函数序言可见 cookie 校验 |
| CFG | 关 | 没有 `GUARD_CF (0x4000)`，`GuardCFFunctionTable = 0` |
| SEH | x64 表格化异常 | `.pdata` 989 条，没有 `NO_SEH` |
| Authenticode 签名 | 无 | `Get-AuthenticodeSignature` 返回 `NotSigned`，Security Directory 为空 |
| 加载权限 | 普通用户 | 没有 `NO_ISOLATION`/`APPCONTAINER` 限制；DPAPI 使用当前用户域 |

“无签名”是事实，不是漏洞本身；它意味着分发时无法用系统级签名校验来源，需要靠仓库哈希锁和发布流程保证完整性。`dependencies.lock.json` 里的 SHA-256 正是起这个作用。

### 3.10 地址速查表

| 名称 | RVA | 说明 |
|---|---:|---|
| `windows_security_init` | `0x6cb0` | 唯一导出入口 |
| `initialize_security` | `0x6750` | 4 次 `register_class` |
| `WindowsSecurity::encrypt_password` | `0x53f0` | RSA 加密入口 |
| 公钥导入 helper | `0x6270` | PEM→DER→PublicKeyInfo→CNG key |
| 密钥长度查询 / 加密主体 | `0x5520` / `0x55e4` | 同一逻辑函数的两段 |
| `protect_secret` / `unprotect_secret` | `0x67a0` / `0x6bb0` | 共同 helper `0x5200` |
| `WindowsInputMethod::set_english` | `0x7860` | 键盘布局切换 |
| `StorageVolume::query` | `0xb420` | `GetDiskFreeSpaceExW` 在 `0xb553` |
| PCM 8 MiB 上限 | `0x8b05` 处立即数 `0x800000` | 单次 `append` 上限 |
| PCM 帧队列上限 | `0x91fb` / `0x941d` 处立即数 `0x1000000` | 约 128 MiB / `sizeof(Vector2)` |

下一节开始进入源码：先看四个翻译单元如何组织，再逐文件读。

---

## 4. 源码构成总览

### 4.1 这节回答什么

这一节回答“DLL 的源码到底由哪些文件组成、为什么是这四个文件、它们之间怎么包含、为什么一个 DLL 里能同时出现四种完全不同的能力”。先把地图画出来，第 5 节再逐个文件精读。

### 4.2 四个翻译单元

`native/SConstruct:8` 明确列出四个 `.cpp`：

```python
binary = env.SharedLibrary("../addons/windows_security/bin/windows_security.dll",
    ["windows_security.cpp", "windows_input_method.cpp", "pcm_stream_decoder.cpp", "storage_volume.cpp"])
```

| 文件 | 行数 | 类 | 命名空间 | 职责 | 直接依赖的系统 API |
|---|---:|---|---|---|---|
| `windows_security.cpp` | 146 | `WindowsSecurity` | 全局 | 入口函数、类注册、DPAPI、RSA-OAEP | `bcrypt`、`crypt32` |
| `windows_input_method.cpp` | 55 | `WindowsInputMethod` | `godot` | 当前线程键盘布局切换与恢复 | `user32` |
| `pcm_stream_decoder.cpp` | 234 | `PcmStreamDecoder` | `godot` | 流式 WAV/PCM 解析、归一化、RMS 波形 | 无（纯算法） |
| `storage_volume.cpp` | 51 | `StorageVolume` | 全局 | 卷级总容量/可用容量查询 | `kernel32`（Windows）/ `statvfs`（Unix） |

三个头文件：

- `windows_input_method.h`（18 行）：声明 `godot::WindowsInputMethod`；
- `pcm_stream_decoder.h`（44 行）：声明 `godot::PcmStreamDecoder` 的成员、状态机和私有方法；
- `storage_volume.h`（11 行）：声明全局 `StorageVolume`。

`WindowsSecurity` 没有独立头文件，类定义直接写在 `windows_security.cpp` 里。这是有意的：它只在这个翻译单元内使用，不需要被其他 `.cpp` 包含。

### 4.3 包含关系与编译边界

```text
windows_security.cpp
  ├─ godot_cpp/classes/ref_counted.hpp
  ├─ godot_cpp/core/class_db.hpp
  ├─ godot_cpp/godot.hpp
  ├─ godot_cpp/variant/{dictionary,packed_byte_array}.hpp
  ├─ <windows.h> <bcrypt.h> <wincrypt.h>
  ├─ "pcm_stream_decoder.h"
  ├─ "storage_volume.h"
  └─ "windows_input_method.h"          <- 三个头文件在这里汇合

windows_input_method.cpp
  ├─ "windows_input_method.h"
  ├─ godot_cpp/core/class_db.hpp
  ├─ godot_cpp/variant/dictionary.hpp
  └─ <windows.h>

pcm_stream_decoder.cpp
  ├─ "pcm_stream_decoder.h"
  ├─ godot_cpp/core/class_db.hpp
  └─ <algorithm> <cmath> <cstring>

storage_volume.cpp
  ├─ "storage_volume.h"
  ├─ godot_cpp/core/class_db.hpp
  └─ <windows.h> 或 <sys/statvfs.h>（编译期二选一）
```

这说明 `windows_security.cpp` 是**聚合点**：它既定义自己的类，又包含另外三个头文件，并在 `initialize_security()` 中把四个类一起注册。另外三个 `.cpp` 只负责实现各自的类，不互相包含。这样编译单元之间没有循环依赖，新增一个能力时只需要“加一对 `.h/.cpp` + 在入口里多注册一行”。

### 4.4 `GDCLASS`、`_bind_methods` 与 12 个绑定方法

四个类都使用同一套 godot-cpp 宏：

```cpp
class WindowsSecurity : public RefCounted {
    GDCLASS(WindowsSecurity, RefCounted);
protected:
    static void _bind_methods();
public:
    // ...
};
```

`GDCLASS(子类, 基类)` 做两件事：给类生成 Godot 需要的类型信息，并声明 `_bind_methods()` 这个静态钩子。`ClassDB::register_class<T>()` 在运行期调用它，把类登记进 Godot 的类数据库；`_bind_methods()` 里的 `ClassDB::bind_method(D_METHOD("名字", "参数名"), &T::函数)` 则把 C++ 成员函数包装成 GDScript 可调用的方法。

四个类合计 **12 个绑定方法**：

| 类 | 方法数 | 方法 |
|---|---:|---|
| `WindowsSecurity` | 3 | `encrypt_password`、`protect_secret`、`unprotect_secret` |
| `WindowsInputMethod` | 2 | `set_english`、`get_layout` |
| `PcmStreamDecoder` | 6 | `append`、`finish`、`get_status`、`read_frames`、`get_amplitude`、`get_waveform` |
| `StorageVolume` | 1 | `query` |

`D_METHOD` 的第二个及后续参数是 **GDScript 侧看到的参数名**，不是 C++ 参数名。例如 `D_METHOD("encrypt_password", "public_key_pem", "password")` 让 GDScript 可以用 `encrypt_password(public_key_pem = ..., password = ...)` 这种命名参数调用。绑定的参数名会作为字符串留在 `.rdata` 里（`public_key_pem`、`password`、`cipher`、`max_count`、`buckets` 等），这也是第 3.8 节能从二进制反推方法名和参数名的原因。

### 4.5 四种返回契约，不要混用

这个 DLL 没有统一所有方法的返回结构，而是按业务需要分成了四类。读 GDScript 调用方时，先确认它面对的是哪一种。

| 类 | 成功标志 | 数据字段 | 错误字段 | 备注 |
|---|---|---|---|---|
| `WindowsSecurity` | `ok == true` | `data: PackedByteArray` | `error: String`、`native_code: int` | 还带 `stage: "native_code"` |
| `WindowsInputMethod` | `ok == true` | 无 | `error: String`、`native_code: int` | 只有状态，没有数据 |
| `PcmStreamDecoder` | `ok == true` | 由具体方法返回 | `code: String` | 用 `code` 不是 `error`；状态字典字段固定 |
| `StorageVolume` | 字段 `>= 0` | `total_bytes`、`free_bytes` | 用 `-1` 表示不可用 | 没有 `ok`/`error` |

两个 `result()` helper 也不一样：

- `windows_security.cpp:18-25` 的 `result(error, data, native_code)` 会写入 `ok/error/data/stage/native_code`；
- `windows_input_method.cpp:13-20` 的 `result(ok, error, native_code)` 不写 `data`。

`PcmStreamDecoder::get_status()`（`pcm_stream_decoder.cpp:22-33`）则手工拼九个字段：`ok`、`code`、`sample_rate`、`channels`、`bits`、`queued_frames`、`decoded_frames`、`input_bytes`、`finished`。

### 4.6 RAII：三个小结构解决三个资源问题

`windows_security.cpp` 的匿名命名空间里有三个 RAII 结构，都是“离开作用域自动清理”，这是 C++ 侧避免密钥/明文残留的核心：

| 结构 | 行号 | 清理动作 | 解决的问题 |
|---|---:|---|---|
| `KeyHandle` | 27 | `BCryptDestroyKey` | CNG 密钥句柄泄漏 |
| `LocalBuffer` | 31 | `SecureZeroMemory` + `LocalFree` | DPAPI 输出缓冲残留与泄漏 |
| `PasswordBytes` | 40 | `SecureZeroMemory` | UTF-8 明文密码在堆上残留 |

这三个结构都没有拷贝构造/赋值（隐式删除或未使用），生命周期严格绑定到函数栈。读这段代码时，只要盯住“构造后谁负责析构”，就不会被 `goto` 式的错误分支绕晕。

### 4.7 命名空间与链接性

| 类 | 声明位置 | 二进制 type descriptor | 结论 |
|---|---|---|---|
| `WindowsSecurity` | `windows_security.cpp:109`，全局 | `.?AVWindowsSecurity@@` | 全局命名空间 |
| `WindowsInputMethod` | `windows_input_method.h:7`，`namespace godot` | `.?AVWindowsInputMethod@godot@@` | `godot` 命名空间 |
| `PcmStreamDecoder` | `pcm_stream_decoder.h:10`，`namespace godot` | `.?AVPcmStreamDecoder@godot@@` | `godot` 命名空间 |
| `StorageVolume` | `storage_volume.h:5`，全局 | `.?AVStorageVolume@@` | 全局命名空间 |

命名空间不统一不影响 Godot 注册：`ClassDB::register_class<T>()` 用的是 C++ 类型，不依赖命名空间；GDScript 侧看到的类名只由 `GDCLASS` 的第一个参数决定。但读源码时要知道这个差异，否则在头文件里找不到 `WindowsSecurity` 的声明会误以为漏文件。

### 4.8 从一个 DLL 到四个类的映射证据

二进制里能同时找到四组独立证据，证明这四个 `.cpp` 确实编进了同一个 DLL：

1. 四个类名 type descriptor（第 3.7 节）；
2. `initialize_security`（RVA `0x6750`）里连续 4 次注册调用；
3. 四段各自的 `_bind_methods`（RVA `0x47c0`、`0x6d10`、`0x7fc0`、`0xad50`）；
4. 四个源文件路径字符串（`windows_security.cpp`、`pcm_stream_decoder.h`、`storage_volume.h`、`windows_input_method.h`）。

这四条互相独立，任何一条单独看都只是线索，合起来才能确定“一个 DLL = 四个翻译单元 + 一次注册”。这也是读其他 GDExtension DLL 的通用方法：先找导出入口，再找注册调用，再找类名和 `_bind_methods`，最后用字符串路径确认源码文件。

---

## 5. 逐文件精读

### 5.1 这节回答什么

这一节按文件逐个读，重点不是把每一行翻译成中文，而是回答三个问题：这个文件对外承诺什么、内部怎么实现、哪些边界条件会让它失败。读完你应该能判断“某个错误码是谁返回的、某个上限写在哪里、改代码时会不会破坏契约”。

### 5.2 `windows_security.cpp`：入口、DPAPI 与 RSA

#### 5.2.1 文件结构

```text
includes
  -> 匿名命名空间
       result()            统一返回字典
       KeyHandle           CNG 密钥 RAII
       LocalBuffer         DPAPI 缓冲 RAII
       PasswordBytes       明文 RAII
       dpapi()             DPAPI 加/解密
       import_key()        PEM -> DER -> PublicKeyInfo -> CNG key
       encrypt_with_key()  BCryptGetProperty + BCryptEncrypt
  -> class WindowsSecurity
       _bind_methods()
       encrypt_password()
       protect_secret()
       unprotect_secret()
  -> initialize_security()
  -> windows_security_init()
```

#### 5.2.2 `dpapi()`：当前用户的本地加密

`dpapi(plain, scope, decrypt)` 在 `windows_security.cpp:46-59`。输入校验在 46-48 行：

- 输入不能为空；
- 加密输入上限 65,536 字节，解密输入上限 131,072 字节；
- `scope` 不能为空，上限 65,536 字节；
- 任一不满足返回 `INVALID_INPUT`。

`scope` 被当作 DPAPI 的 **entropy**（第二份密钥材料），所以“同一个 Windows 用户 + 不同 scope”解不开彼此的密文。测试 `tests/test_windows_security.gd:42-43` 用错误 scope 验证了这一点。

加密调用 `CryptProtectData`，描述串是 `L"AgentLuo"`，标志位 `CRYPTPROTECT_UI_FORBIDDEN`；解密调用 `CryptUnprotectData`，同样禁止 UI。失败返回 `PROTECT_FAILED` / `UNPROTECT_FAILED`，并把 `GetLastError()` 放进 `native_code`。

为什么禁止 UI？因为这是后台凭据存储，不能弹 Windows 的密码/确认框；一旦需要交互，调用会直接失败，由上层决定是否降级。

#### 5.2.3 `import_key()`：PEM 到 CNG 公钥

`import_key(pem, key)` 在 `windows_security.cpp:61-80`，步骤是：

1. `pem.utf8()`，长度超过 16,384 字符直接 `INVALID_KEY`；
2. `CryptStringToBinaryA(..., CRYPT_STRING_BASE64HEADER, ...)` 把 PEM 的 Base64 正文解码成 DER；
3. `CryptDecodeObjectEx(X509_ASN_ENCODING, X509_PUBLIC_KEY_INFO, ...)` 解析 `SubjectPublicKeyInfo`；
4. 检查 `info->Algorithm.pszObjId == szOID_RSA_RSA`（字符串 `1.2.840.113549.1.1.1`），不是 RSA 就拒绝；
5. `CryptImportPublicKeyInfoEx2` 导入成 `BCRYPT_KEY_HANDLE`；
6. 释放 `info`，失败时把 `GetLastError()` 放进 `native_code`。

这里只接受**公钥**，不接受私钥；私钥永远不会进入客户端。PEM 头可以是 `BEGIN PUBLIC KEY` 这类标准 Base64 header，函数不解析私钥块。

#### 5.2.4 `encrypt_with_key()`：RSA-OAEP-SHA256

`encrypt_with_key(key, password)` 在 `windows_security.cpp:82-107`：

1. `BCryptGetProperty(key, BCRYPT_KEY_LENGTH, ...)` 读密钥位数；
2. 只接受 2048–8192 位；超出返回 `INVALID_KEY`；
3. 明文长度上限是 `bits / 8 - 2 * 32 - 2`，即密钥字节数减去 OAEP-SHA256 的 66 字节开销；超出返回 `INVALID_INPUT`；
4. 第一次 `BCryptEncrypt(..., nullptr, 0, &required, BCRYPT_PAD_OAEP)` 只查询输出长度；
5. `PackedByteArray cipher` 按 `required` 扩容；
6. 第二次 `BCryptEncrypt` 真正写入密文；
7. 把 `required` 截断回实际长度，返回 `data`。

`BCRYPT_OAEP_PADDING_INFO{ pszAlgId = BCRYPT_SHA256_ALGORITHM }` 是 `windows_security.cpp:91` 的局部结构；二进制里能看到 `L"SHA256"` 和输出缓冲减 `0x42`（66）两条独立证据。`BCRYPT_PAD_OAEP` 的立即数 8 本身没有被直接观察到，属于高置信推断（见第 13 节）。

为什么是 OAEP 而不是 PKCS#1 v1.5？因为服务端解密函数按 OAEP-SHA256 实现，客户端必须匹配；测试 `tests/run_security_interop.py` 会用服务端的 `decrypt_password` 反向验证密文。

#### 5.2.5 三个公开方法

| 方法 | 行号 | 行为 | 主要错误码 |
|---|---:|---|---|
| `encrypt_password(pem, password)` | 118-124 | 校验 PEM 非空且不超过 16 KiB → `import_key` → `encrypt_with_key` | `INVALID_KEY`、`INVALID_INPUT`、`ENCRYPTION_FAILED` |
| `protect_secret(plain, scope)` | 125 | `dpapi(plain, scope, false)` | `INVALID_INPUT`、`PROTECT_FAILED` |
| `unprotect_secret(cipher, scope)` | 126 | `dpapi(cipher, scope, true)` | `INVALID_INPUT`、`UNPROTECT_FAILED` |

`protect_secret` / `unprotect_secret` 只有一行，真正的逻辑都在 `dpapi()`；这种“薄方法 + 厚 helper”的结构让错误码只有一处来源，便于测试断言。

#### 5.2.6 注册与入口

`initialize_security()` 在 129-136 行，只有 `MODULE_INITIALIZATION_LEVEL_SCENE` 时才注册四个类；`terminate_security()` 是空函数。`windows_security_init()` 在 138-146 行，四步：构造 `InitObject`、注册初始化/卸载回调、设置最低初始化级别、调用 `init()`。

注册顺序固定为 `WindowsSecurity` → `WindowsInputMethod` → `PcmStreamDecoder` → `StorageVolume`。二进制 `0x6750` 的四个 call 与源码逐条对应，没有第二套注册路径。

### 5.3 `windows_input_method.cpp`：线程级键盘布局

#### 5.3.1 为什么需要它

Godot 的 `DisplayServer` 能开关 IME，但不能指定“当前线程用哪个键盘布局（HKL）”。中文输入法在密码框里自动切回中文，是实际会遇到的问题；这个类用 Win32 的 `LoadKeyboardLayoutW` / `ActivateKeyboardLayout` 强制切到 US 英语布局（`00000409`），离开密码框时再恢复。

#### 5.3.2 状态与线程亲和性

文件级静态变量在 `windows_input_method.cpp:10-11`：

```cpp
HKL saved_layout = nullptr;
DWORD saved_thread = 0;
```

这两个变量记录“进入英文模式前，当前线程原本的布局”。`set_english(false)` 只有在 `saved_layout != nullptr` 且 `saved_thread == GetCurrentThreadId()` 时才恢复（30-37 行）。为什么检查线程？因为 HKL 是线程级状态，跨线程恢复别人的布局是错误行为；Godot 主线程通常不变，但显式检查更安全。

#### 5.3.3 两个方向

`set_english(true)`（28-51 行）：

1. 取当前线程 ID；
2. 如果还没保存过布局，`GetKeyboardLayout(thread)` 保存，并记下线程 ID；
3. `LoadKeyboardLayoutW(L"00000409", 0)` 加载/获取英语布局；
4. 如果当前已经是英语，直接成功；
5. 否则 `ActivateKeyboardLayout(english, 0)`，失败返回 `ACTIVATE_FAILED`。

`set_english(false)`（30-37 行）：

1. 没有保存过，或保存的线程不是当前线程 → 直接返回成功（不动作）；
2. 否则 `ActivateKeyboardLayout(saved_layout, 0)`；
3. 清空保存状态；失败返回 `ACTIVATE_FAILED`。

`get_layout()`（53-55 行）把 `GetKeyboardLayout(GetCurrentThreadId())` 的 HKL 指针强转成 `int64_t`。测试断言英文模式下的值是 `0x04090409`：低字 `0x0409` 是美国英语，高字 `0x0409` 是布局 ID；这个常量只在测试里出现，生产代码不硬编码它。

#### 5.3.4 调用时机

GDScript 侧在 `src/ui/account_view.gd` 里使用：进入密码/确认密码框时 `set_english(true)`，离开时 `set_english(false)`，每次非 Tab 按键前再强制一次（219-235 行），离开页面时恢复（106-107 行）。原生类本身不判断“现在是不是密码框”，它只执行开关；业务判断全部在上层。

### 5.4 `pcm_stream_decoder.cpp`：一个流式 WAV 状态机

这是四个文件里最复杂的一个，234 行，承担“服务端边下发 WAV 分片、客户端边解码边播放”的核心。

#### 5.4.1 成员与状态机

`pcm_stream_decoder.h:10-33` 的私有成员：

| 成员 | 作用 |
|---|---|
| `Phase phase` | `RIFF` → `CHUNKS` → `DATA` → `TAIL` |
| `std::vector<uint8_t> pending` | 还没消费的输入字节 |
| `std::vector<Vector2> frames` | 解码后的立体声帧队列 |
| `std::vector<float> amplitudes` | 每个 RMS 窗口一个幅度值 |
| `read_offset` | 队列里已读位置 |
| `decoded` / `input` / `header_bytes` / `data_left` | 计数与剩余数据 |
| `rate` / `channels` / `bits` / `format` / `alignment` | WAV 格式 |
| `window_frames` / `energy_frames` / `energy` | RMS 窗口与能量累加 |
| `ended` / `unbounded_data` / `code` | 结束标志、无界 data、错误码 |

状态机的转移：

```text
RIFF --(读到 "RIFF....WAVE")--> CHUNKS
CHUNKS --(读到 fmt )--> CHUNKS（解析格式，继续找 data）
CHUNKS --(读到 data)--> DATA
DATA --(data_left 归零)--> TAIL
TAIL --(忽略剩余字节)--> TAIL
```

`data` 的 size 字段如果等于 `0xffffffff`，视为“无界流”（服务端不知道总长度），此时 `unbounded_data = true`，直到 `finish()` 才结束。

#### 5.4.2 四个硬上限

| 常量 | 位置 | 值 | 作用 |
|---|---|---:|---|
| 单次 `append` | `pcm_stream_decoder.cpp:93` | 8 MiB | 防止一次传入超大块 |
| 头部累计 | `pcm_stream_decoder.cpp:9` | 1 MiB | 防止 `fmt `/其他 chunk 无限膨胀 |
| 帧队列 | `pcm_stream_decoder.cpp:8` | 128 MiB / `sizeof(Vector2)` = 16,777,216 帧 | 防止未读数据压垮内存 |
| 总时长 | `pcm_stream_decoder.cpp:60` | `rate * 1800` 帧 | 30 分钟上限 |

超过任一上限都返回 `BUFFER_LIMIT`，并调用 `fail()` 清空 `pending`/`frames`/`amplitudes`。`fail()`（36-44 行）是“粘性失败”：一旦设置 `code`，后续 `append` 直接返回状态，不再尝试解码。

#### 5.4.3 格式支持

`validate_format()`（167-173 行）只接受：

- 1–2 声道；
- 采样率 8,000–192,000 Hz；
- PCM（format 1）8/16/24/32 位；
- IEEE float（format 3）32 位。

`WAVE_FORMAT_EXTENSIBLE`（`0xfffe`）通过 `parse_subtype()`（154-165 行）处理：它要求 `fmt ` 至少 40 字节、扩展长度至少 22、`bits` 与子格式一致，并且**完整校验 14 字节 GUID 后缀**，而不是只看第一个 word。校验通过后，`format` 被替换成真正的子格式（1 或 3）。这是防“伪造扩展头绕过格式检查”的关键。

`parse_format()`（46-56 行）还校验 `alignment == channels * bits / 8` 和 `byte_rate == rate * alignment`；不一致返回 `INVALID_WAV`。只允许第一个 `fmt ` chunk，重复出现直接拒绝。

#### 5.4.4 采样归一化

`decode_sample()`（175-187 行）：

| 格式 | 归一化 |
|---|---|
| 8 位无符号 PCM | `(int(byte) - 128) / 128.0` |
| 16 位 PCM | `int16 / 32768.0` |
| 24 位 PCM | 三字节小端拼成有符号 24 位，再 `/ 8388608.0` |
| 32 位 PCM | `int32 / 2147483648.0` |
| 32 位 float | 直接 `memcpy`，并检查 `std::isfinite` |

`decode()`（58-84 行）按 `alignment` 取整帧，单声道复制到第二声道，累加平方能量；每 `window_frames = max(1, rate / 100)` 帧（约 10 ms）输出一个 RMS 幅度到 `amplitudes`。

#### 5.4.5 读取与波形

| 方法 | 行号 | 行为 |
|---|---:|---|
| `read_frames(max_count)` | 113-122 | 从 `frames` 取最多 `max_count` 帧，返回 `PackedVector2Array`；读空后清空 vector |
| `get_amplitude(index)` | 124-129 | 返回该帧所属 RMS 窗口的幅度；越界或失败返回 0 |
| `get_waveform(buckets)` | 131-147 | 仅在 `ended` 且无错误时，把全部 RMS 窗口按桶取峰值，返回 `PackedFloat32Array` |

`get_waveform` 的 `buckets` 限制在 1–128，默认 24（`_bind_methods` 里的 `DEFVAL(24)`）。未 `finish` 时返回空数组，这是测试 `tests/test_pcm_decoder.gd:120` 断言的行为。

#### 5.4.6 错误码

| 错误码 | 触发条件 | 位置 |
|---|---|---|
| `INVALID_WAV` | 缺 `RIFF/WAVE`、`fmt ` 不合法、alignment/byte rate 不一致、float 非有限 | 47、52、178、201、210 |
| `UNSUPPORTED_FORMAT` | 声道/采样率/位深/编码不支持，或扩展 GUID 不匹配 | 160、170 |
| `BUFFER_LIMIT` | 单次 8 MiB、头部 1 MiB、队列/时长超限 | 61、93、211、217 |
| `TRUNCATED_AUDIO` | `finish()` 时仍停在 RIFF/CHUNKS、仍有 pending、或 data 未读完 | 107 |
| `EMPTY_AUDIO` | `finish()` 时没有任何解码帧 | 108 |
| `STREAM_FINISHED` | 已结束后再 `append` | 89-91 |

### 5.5 `storage_volume.cpp`：卷级容量

#### 5.5.1 返回契约

`query(path)`（44-50 行）先填 `total_bytes = -1`、`free_bytes = -1`；空路径直接返回。成功时改写两个非负值，失败保留 `-1`。上层 `src/storage/godot_storage_service.gd:54-68` 只采纳 `>= 0` 的字段，因此 `-1` 会自然降级成“容量不可用”。

#### 5.5.2 Windows 与 Unix

`query_capacity()`（19-38 行）用编译期分支：

- Windows：`GetDiskFreeSpaceExW(path.utf16(), &available, &total, &free)`，只使用 `available` 和 `total`，忽略 `free`；`valid_capacity(total, available)` 要求 `total > 0`、`total <= INT64_MAX`、`available <= total`。
- Unix/macOS：`statvfs(path.utf8(), &info)`，用 `f_bavail * f_frsize` 算可用、`f_blocks * f_frsize` 算总量，并做乘法溢出检查。

虽然 `StorageVolume` 本身有 Unix 分支，但整个 DLL 的另外两个编译单元无条件包含 `windows.h`，所以当前产物仍然是 Windows x64 专用。Unix 分支是为未来移植保留的，不是“现在就能在 Linux 上编译”。

### 5.6 四个文件如何合成一个 DLL

| 源码要素 | 二进制证据 | 结论 |
|---|---|---|
| 4 个 `.cpp` 同一产物 | 4 个类名 type descriptor + 4 次注册调用 + 4 个 `_bind_methods` | 同一 DLL |
| `windows_security.cpp` 是入口 | 唯一导出 `windows_security_init` 在 `0x6cb0` | 入口确定 |
| 三个头文件被聚合 | 字符串里同时出现 4 个源文件路径 | 编译单元齐全 |
| 只有一个 DLL | SConstruct 只调用一次 `SharedLibrary` | 不存在“每个类一个 DLL” |

下一节把这四个类放回 GDScript 的调用现场：谁实例化、谁传参、谁消费返回字段。

---

## 6. 四个类的 GDScript 契约

### 6.1 这节回答什么

这一节是速查表：每个类在 GDScript 里长什么样、参数是什么、返回字段怎么读、缺 DLL 时会发生什么。第 7 节再用五条业务数据流把这些方法串起来。

### 6.2 `WindowsSecurity`

实例化方式：`ClassDB.instantiate("WindowsSecurity")`。类本身无状态，每次调用新建实例没有副作用。

| 方法 | 参数 | 成功返回 | 失败返回 | 生产调用点 |
|---|---|---|---|---|
| `encrypt_password` | `public_key_pem: String`, `password: String` | `ok=true`，`data` 为 RSA 密文 | `error` = `INVALID_KEY` / `INVALID_INPUT` / `ENCRYPTION_FAILED`，`data` 为空 | `src/platform/windows_password_encryption.gd:6`；`src/network/account_api.gd:148` |
| `protect_secret` | `plain: PackedByteArray`, `scope: PackedByteArray` | `ok=true`，`data` 为 DPAPI blob | `INVALID_INPUT` / `PROTECT_FAILED` | `src/platform/windows_secret_protection.gd:12`；`src/storage/credential_store.gd:24`；`src/storage/model_store.gd:70` |
| `unprotect_secret` | `cipher: PackedByteArray`, `scope: PackedByteArray` | `ok=true`，`data` 为明文 | `INVALID_INPUT` / `UNPROTECT_FAILED` | `src/platform/windows_secret_protection.gd:20`；`src/storage/credential_store.gd:70`；`src/storage/model_store.gd:59` |

所有返回都带 `stage = "native_code"` 和 `native_code`（Win32/NTSTATUS 错误码）。这是测试 `tests/test_windows_security.gd:35,84,90` 明确断言的契约；上层可以据此区分“原生失败”和“GDScript 适配器失败”。

### 6.3 `WindowsInputMethod`

实例化方式：`ClassDB.instantiate("WindowsInputMethod")`。底层 `saved_layout`/`saved_thread` 是文件级静态变量，因此**多个实例共享同一份保存状态**；实际使用中只创建一个控制器。

| 方法 | 参数 | 返回 | 调用点 |
|---|---|---|---|
| `set_english` | `enabled: bool` | `{ok, error, stage, native_code}` | `src/ui/account_view.gd:219-235`；`src/ui/account_view.gd:106-107` |
| `get_layout` | 无 | `int`（HKL 指针值） | 仅测试 `tests/test_windows_security.gd:76-80` |

生产代码不直接调用 `get_layout`；它只在测试里用来断言“切到英文后是 `0x04090409`、恢复后回到原值”。

### 6.4 `PcmStreamDecoder`

实例化方式：`ClassDB.instantiate("PcmStreamDecoder")`，通常由 `src/platform/native_decoder_factory.gd:32-33` 包进 `Decoder` 适配器。**每个音频流必须独立实例**，因为它保存了 `pending`、`frames`、`phase` 等流式状态；不能复用同一个实例处理两条并发语音。

| 方法 | 参数 | 返回 | 用途 |
|---|---|---|---|
| `append` | `bytes: PackedByteArray` | 状态字典 | 追加一个 WAV 分片 |
| `finish` | 无 | 状态字典 | 声明流结束，校验截断/空音频 |
| `get_status` | 无 | 状态字典 | 查询格式、队列、已解码帧、是否结束 |
| `read_frames` | `max_count: int` | `PackedVector2Array` | 取已解码的立体声帧喂给 `AudioStreamGenerator` |
| `get_amplitude` | `frame_index: int` | `float` | 取某帧的 RMS 幅度，驱动口型 |
| `get_waveform` | `buckets: int = 24` | `PackedFloat32Array` | 流结束后取整段波形，写缓存/UI |

状态字典固定九个字段：

```text
ok, code, sample_rate, channels, bits,
queued_frames, decoded_frames, input_bytes, finished
```

注意失败字段叫 `code`，不是 `error`；`append` 失败后错误是粘性的，后续调用直接返回同一个状态。

### 6.5 `StorageVolume`

实例化方式：`ClassDB.instantiate("StorageVolume")`，在 `src/storage/godot_storage_service.gd:10-11` 创建一次并复用。

| 方法 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `query` | `path: String` | `{total_bytes, free_bytes}` | 两者都是 `int64`；失败或空路径为 `-1` |

调用点 `src/storage/godot_storage_service.gd:57-61` 会先 `ProjectSettings.globalize_path(path)`，再传入原生；只采纳 `>= 0` 的字段，`total_bytes == 0` 归一为 `-1`。

### 6.6 缺失 DLL 时的降级

| 缺失的类 | GDScript 行为 | 文件:行 |
|---|---|---|
| `WindowsSecurity` | `protect_secret`/`unprotect_secret` 返回 `SECURITY_UNAVAILABLE`；`encrypt_password` 退回基类，返回 `ENCRYPTION_UNAVAILABLE`；启动时直接显示“账号与聊天功能暂不可用” | `src/platform/windows_secret_protection.gd:7-19`；`src/platform/windows_password_encryption.gd:3-6`；`src/application.gd:86-90,160-167` |
| `PcmStreamDecoder` | 工厂返回 `null`；播放侧映射为 `DECODER_UNAVAILABLE`；离线导入退回 GDScript 的 `Wav` 解析 | `src/platform/native_decoder_factory.gd:31-33`；`src/media/reply_audio.gd:457-462`；`src/storage/audio_import.gd:100-119` |
| `StorageVolume` | `_volume` 保持 `null`，目录字节仍可统计，但容量字段为 `-1`，`code = CAPACITY_UNAVAILABLE` | `src/storage/godot_storage_service.gd:10-11,54-68,94-100` |
| `WindowsInputMethod` | `create_ime_controller()` 返回 `null`；只跳过键盘布局切换，仍会调用 `DisplayServer.window_set_ime_active` | `src/platform/godot_input_service.gd:15-17`；`src/ui/account_view.gd:219-227` |

`NOT_IMPLEMENTED` 不属于这四个类的降级码；它属于 `src/extensions/` 下的占位接口（换装、箱庭、设备互联），不要混为一谈。

### 6.7 生命周期与线程

- `WindowsSecurity`：无状态，随用随建；DPAPI 绑定当前 Windows 用户，换用户/换机后旧密文解不开是预期行为。
- `WindowsInputMethod`：状态是文件级静态变量，绑定“保存时的线程”；跨线程恢复不会生效。Godot 主线程调用即可。
- `PcmStreamDecoder`：有状态，必须一流一实例；`read_frames` 消费队列，`get_amplitude` 只读不消费。
- `StorageVolume`：无状态，可复用；路径必须传绝对路径（上层已 `globalize_path`）。

---

## 7. 五条业务数据流

### 7.1 这节回答什么

这一节回答“这些原生方法在真实业务里什么时候被调用、参数从哪来、返回值被谁消费”。每条流都从 GDScript 入口开始，到最终落盘/展示/播放结束。看懂这五条，排查问题时就能判断“是原生返回错、适配器映射错，还是上层没用对字段”。

### 7.2 登录密码：PEM → RSA-OAEP → Base64

```text
登录页收集 username/password
  -> AccountSession.perform()
  -> AccountApi._perform()
  -> GET /auth/public_key 取 PEM
  -> WindowsSecurity.encrypt_password(pem, password)
  -> base64(encrypted.data) 写回 payload["password"]
  -> POST /auth/login
```

关键点：

- PEM **每次操作重新获取**，不做本地缓存（`src/network/account_api.gd:139-152`）。
- 加密成功后先把明文 `payload[password_field] = ""`，再写 Base64 密文，避免明文留在请求字典里（`account_api.gd:148-151`）。
- 失败统一映射为客户端错误 `ENCRYPTION_ERROR`；原生返回的 `error` 只用于诊断，不直接展示给用户。
- `auto_login` 走 token，不加密密码（`account_api.gd:70-75`）。

### 7.3 本地令牌与 API Key：DPAPI + scope

令牌：

```text
scope = sha256(JSON([规范化服务器地址, 用户名]))
  -> WindowsSecurity.protect_secret(token_utf8, scope_utf8)
  -> user://accounts/<scope>.bin（先写 .tmp 再 rename）
```

读取时反向：`unprotect_secret(cipher, scope_utf8)`；文件不存在返回 `NOT_FOUND`，文件超过 131072 字节视为不可用，解密失败返回 `UNAVAILABLE`。对应 `src/storage/credential_store.gd:14-27,29-49,56-79`。

API Key 的 scope 不同：`src/storage/model_store.gd:15-18` 用 `JSON([base, username])`，实际 entropy 是 `scope + "/" + type_id`，所以同一账号下不同模型供应商的 Key 不能互相解密。保存失败且不允许明文时返回 `PLAINTEXT_CONFIRMATION_REQUIRED`；允许明文才写 `api_key_plain`（`model_store.gd:59-76`）。

为什么 scope 要包含服务器和用户名？因为 DPAPI 只保证“同一 Windows 用户”，不保证“同一账号”；scope 把密文绑定到具体账号/服务器，防止 A 账号的令牌被 B 账号页面误读。

### 7.4 语音：分片 → 状态机 → 帧 → 播放/波形/缓存

```text
服务端回复事件 payload.audio (Base64)
  -> ChatSession._receive_reply()
  -> ReplyAudio.append_reply_audio(id, encoded, final, ...)
  -> base64 解码 + 往返校验
  -> PcmStreamDecoder.append(bytes)
  -> 若 final: PcmStreamDecoder.finish()
  -> PcmStreamDecoder.get_waveform() 写缓存 manifest
  -> AudioStreamGenerator + read_frames() 播放
  -> get_amplitude(heard) 驱动口型
```

关键点：

- 每个回复流一个 decoder；`append` 失败用 `status.code` 记录，不抛异常。
- 已停止的流仍会接收并解码，只是立即 `read_frames(queued_frames)` 丢弃，避免缓存写入被中断（`reply_audio.gd:369-370`）。
- `finish()` 成功才提交缓存；`finish()` 失败（截断/空音频）不提交。
- 播放采样率来自 `get_status().sample_rate`，不是硬编码；`AudioStreamGenerator.buffer_length = 0.25`。
- 波形来自原生 RMS（`amplitudes`），不是重新扫描 PCM；缓存 manifest 里保存 `waveform`，重放时不需要再解码。
- 离线导入 `src/storage/audio_import.gd:100-119` 也是 `append` → `finish` → `get_waveform`，并额外校验 `input_bytes == 文件大小`、`decoded_frames > 0`、采样率/时长范围。

### 7.5 存储容量：卷级总量 + 目录占用

```text
设置页查询应用根目录 / 语音缓存目录
  -> GodotStorageService.query_directory(path)
  -> globalize_path(path)
  -> StorageVolume.query(absolute) 取 total/free
  -> DirAccess 递归统计目录 bytes/files
  -> UI 显示容量环 + “整盘 ...”
```

`StorageVolume` 只回答“这个卷总共多少、还剩多少”，不回答“这个目录占多少”；目录占用由 GDScript 的 `_measure()` 递归统计（`godot_storage_service.gd:69-92`）。如果原生容量不可用，UI 显示“容量数据暂不可用”“整盘 --”，而不是伪造 0。

### 7.6 输入法：进入密码框切英文，离开恢复

```text
密码/确认密码框 focus_entered / focus_exited
  -> AccountView._queue_ime_sync()
  -> _sync_ime()
  -> _set_ime_active(active)
       -> DisplayServer.window_set_ime_active(active)
       -> WindowsInputMethod.set_english(not active)
```

进入密码框：`active=false` → `set_english(true)`；离开：`set_english(false)`。每次非 Tab 按键前再强制一次，防止 TSF 输入法自行切回中文（`account_view.gd:230-235`）。离开页面时恢复原布局（`account_view.gd:106-107`）。

### 7.7 一张总图

```text
                    ┌──────────────────────────────┐
                    │        GDScript 业务层        │
                    │ account / chat / storage / ui │
                    └──────────────┬───────────────┘
                                   │ ClassDB.instantiate
                    ┌──────────────▼───────────────┐
                    │   WindowsSecurity (3 methods) │  RSA / DPAPI
                    │   WindowsInputMethod (2)      │  键盘布局
                    │   PcmStreamDecoder (6)        │  WAV 流解码
                    │   StorageVolume (1)           │  卷容量
                    └──────────────┬───────────────┘
                                   │ Win32 / CNG / DPAPI
                    ┌──────────────▼───────────────┐
                    │ bcrypt / crypt32 / user32    │
                    │ kernel32（含静态 CRT）        │
                    └──────────────────────────────┘
```

下一节离开运行时，讲怎么从源码重建出这个 DLL，以及为什么哈希锁是构建的一部分。

---

## 8. 构建与可复现

### 8.1 这节回答什么

这一节回答“这个 DLL 是怎么从四个 `.cpp` 编出来的、为什么必须锁定 godot-cpp 和 SCons 版本、构建脚本在哪些地方会拒绝执行、重建后怎么确认产物没变”。如果你要改原生代码，这一节是操作手册；如果你只是读代码，也可以从构建参数反推编译器的行为。

### 8.2 `SConstruct` 逐行

`native/SConstruct` 只有 8 行有效内容：

```python
from pathlib import Path

cpp = Path(ARGUMENTS["godot_cpp"]).absolute()
env = SConscript(str(cpp / "SConstruct"))
env.Append(LIBS=["bcrypt", "crypt32", "user32"])
env.Append(CPPDEFINES=["WIN32_LEAN_AND_MEAN", "NOMINMAX"])
env.Append(CXXFLAGS=["/utf-8"])
binary = env.SharedLibrary("../addons/windows_security/bin/windows_security.dll",
    ["windows_security.cpp", "windows_input_method.cpp", "pcm_stream_decoder.cpp", "storage_volume.cpp"])
Default(binary)
```

| 行 | 作用 | 为什么需要 |
|---:|---|---|
| 3 | 取 `godot_cpp` 参数并转绝对路径 | 复用 godot-cpp 的 SConstruct，必须指向一个完整 checkout |
| 4 | 加载 godot-cpp 的构建环境 | 继承 include 路径、编译选项、静态 CRT 默认值 |
| 5 | 链接 `bcrypt`、`crypt32`、`user32` | CNG、DPAPI/PEM、键盘布局 |
| 6 | 定义 `WIN32_LEAN_AND_MEAN`、`NOMINMAX` | 减少 `windows.h` 污染，避免 `min/max` 宏与 C++ 标准库冲突 |
| 7 | `/utf-8` | 源码/字符串里有中文，MSVC 默认按本地代码页会乱码 |
| 8 | 一次 `SharedLibrary` 产出单 DLL | 四个 `.cpp` 全部编进同一个产物 |

注意 `LIBS` 里有 `user32`，但 `dependencies.lock.json` 的 `system_libraries` 只写了 `bcrypt`、`crypt32`。这是锁文件的遗漏，不是构建错误；第 8.5 节会再提。

### 8.3 `build_security.py` 的五道门禁

`scripts/build_security.py` 不是简单的 `scons` 包装，它在构建前后做了五件事：

| 门禁 | 行号 | 行为 | 失败后果 |
|---|---:|---|---|
| native 源码干净 | 17-21 | `git status --porcelain --untracked-files=all -- native addons/windows_security` 必须为空 | 拒绝构建，防止“源码和二进制对不上” |
| godot-cpp 干净 | 26-27 | 同一命令检查 godot-cpp checkout | 拒绝构建 |
| godot-cpp commit 匹配 | 28-30 | `git rev-parse HEAD` 必须等于 lock 里的 `godot_cpp_commit` | 拒绝构建 |
| SCons 版本匹配 | 31-33 | `SCons.__version__` 必须等于 `4.7.0` | 拒绝构建 |
| 产物 SHA-256 匹配 | 44-51 | 构建后计算哈希，必须等于 `binary_sha256` | 抛错，不静默接受新二进制 |

两个细节值得注意：

1. **godot-cpp commit 复用了 `gd_cubism` 段**（`build_security.py:29` 读的是 `lock["gd_cubism"]["godot_cpp_commit"]`），不是 `windows_security` 专属字段。这是锁文件结构的历史耦合；当前两个扩展共用同一个 godot-cpp commit，所以能工作，但改锁时要知道这一点。
2. **Python 版本不校验**。脚本打印 `sys.version`，但只比较 SCons 版本；`native_build.python = 3.11.9` 是文档性约束，不是硬门禁。

脚本还在 `35` 行打了一个 OEM 编码补丁：把 `encodings.oem.oem_decode` 替换成 UTF-8 解码，避免 MSVC 响应文件里的中文路径在 Windows OEM 代码页下解析失败。这个补丁只影响本进程，不修改系统。

### 8.4 工具链与静态 CRT

| 项 | 值 | 来源 |
|---|---|---|
| Godot | 4.7.1 standard / x86_64 | `dependencies.lock.json:4-10` |
| godot-cpp commit | `fbbf9ec4efd8f1055d00edb8d926eef8ba4c2cce` | `dependencies.lock.json:26` |
| MSVC | 14.44.35207（family 14.3） | lock + `LinkerVersion 14.44` + `.exp` 的 link.exe 路径 |
| Python | 3.11.9 | lock（脚本不硬校验） |
| SCons | 4.7.0 | lock（脚本硬校验） |
| 目标 | `platform=windows arch=x86_64 target=template_release` | `build_security.py:37` |

静态 CRT 的结论来自三条证据：导入表没有 `vcruntime140.dll`/`msvcp140.dll`/`ucrtbase.dll`；`.text` 里有 `_tls_callback`、`RtlUnwindEx`、`GetStartupInfoW` 等 CRT 符号；锁定的 godot-cpp checkout 中 `tools/windows.py` 的 `use_static_cpp` 默认 `True`，MSVC 下走 `/MT`。`build_security.py` 只传 `platform/arch/target/godot_cpp` 和 `-j8`，没有覆盖 `use_static_cpp`，所以当前产物按默认 `/MT` 构建，不依赖 VC++ Redistributable。

如果你手工传 `use_static_cpp=false`，就会变成 `/MD`，需要 VC++ 运行库；此时 README 里“不需要额外运行时 DLL”这句话就不再成立。读构建结论时一定要带上“按当前默认参数”这个前提。

### 8.5 锁文件字段与已知不一致

`dependencies.lock.json` 的 `windows_security` 段：

```json
"windows_security": {
  "binary_sha256": "037b797d14fe04de6e4ef72b5c74174f04bcf2f6089ca06c653bd8123d8b8752",
  "source": "native/windows_security.cpp",
  "input_method_sources": ["native/windows_input_method.h", "native/windows_input_method.cpp"],
  "audio_sources": ["native/pcm_stream_decoder.h", "native/pcm_stream_decoder.cpp"],
  "storage_sources": ["native/storage_volume.h", "native/storage_volume.cpp"],
  "system_libraries": ["bcrypt", "crypt32"],
  "msvc_version": "14.44.35207"
}
```

**已知不一致**：`system_libraries` 只列 `bcrypt`、`crypt32`，但 `native/SConstruct:5` 还链接了 `user32`。这是一个文档/锁文件遗漏，不影响二进制行为；如果以后要按锁文件重建依赖清单，应把 `user32` 补上。

另外，`source` 只写了 `native/windows_security.cpp`，另外三个文件放在 `input_method_sources`/`audio_sources`/`storage_sources` 里。读锁文件时要四个字段一起看，不能只看 `source` 就以为 DLL 只有一个源文件。

### 8.6 重建与验证命令

在 `Agent-LuoTianyi` 目录下执行（路径按你的实际 godot-cpp checkout 替换）：

```powershell
cd D:\01restart\langchain\lty\Agent-LuoTianyi
python client-godot\scripts\build_security.py --godot-cpp 'D:\path\to\godot-cpp'
```

构建成功后脚本会打印：

```text
Build toolchain: python=3.11.x scons=4.7.0 godot_cpp=fbbf9ec4...
WindowsSecurity SHA256: 037b797d14fe04de6e4ef72b5c74174f04bcf2f6089ca06c653bd8123d8b8752
```

独立核对哈希：

```powershell
$dll = 'D:\01restart\langchain\lty\Agent-LuoTianyi\client-godot\addons\windows_security\bin\windows_security.dll'
Get-FileHash $dll -Algorithm SHA256 | Format-List
```

核对发行包副本：

```powershell
$pkg = 'D:\01restart\langchain\lty\Agent-LuoTianyi\client-godot\dist\agentluo-0.1.8.6\windows_security.dll'
Get-FileHash $pkg -Algorithm SHA256 | Format-List
```

跑原生相关测试（需要 Godot 可执行文件）：

```powershell
& $env:GODOT_BIN --headless --path client-godot --script res://tests/test_windows_security.gd
& $env:GODOT_BIN --headless --path client-godot --script res://tests/test_pcm_decoder.gd
```

跑 RSA/DPAPI 互操作（需要 Python 的 `cryptography`、`fastapi`）：

```powershell
python client-godot\tests\run_security_interop.py --godot $env:GODOT_BIN
```

这些命令来自仓库脚本与 README；本文**没有实际执行**它们，测试覆盖结论来自测试源码的断言，不是运行结果。

### 8.7 为什么哈希锁是构建的一部分

普通项目只锁依赖版本，这个项目还锁二进制哈希。原因很实际：DLL 没有 Authenticode 签名，无法靠系统验证来源；一旦有人用旧源码、不同编译器或不同 CRT 参数重建，行为可能变化但版本号不变。`build_security.py` 在构建后强制比较 SHA-256，等于把“构建可复现”变成硬门禁——只要源码、工具链、参数任一变化，哈希就会变，脚本就会拒绝，迫使维护者显式更新锁文件并重新验证。

这也是为什么第 3 节要记录 TimeDateStamp、LinkerVersion、Rich header 这些“看起来没用”的字段：它们是构建指纹，能在哈希之外告诉你这个 DLL 是不是同一工具链产物。

---

## 9. 另外两个 DLL：同目录，不同来源

### 9.1 这节回答什么

`client-godot` 里还有两个 GDExtension DLL：`libgd_cubism`（Live2D）和 `libgdsqlite`（SQLite）。它们和 `windows_security.dll` 放在同一个导出目录，加载机制相同，但源码构成完全不同：一个是项目自有的薄封装，两个是上游项目的完整插件。这一节用对照表说明差异，不展开成第三份逆向报告。

### 9.2 三文件对照

| 项 | `windows_security.dll` | `libgd_cubism.windows.release.x86_64.dll` | `libgdsqlite.windows.template_release.x86_64.dll` |
|---|---|---|---|
| 大小 | 345,600 B | 885,248 B | 3,393,024 B |
| SHA-256 | `037b797d...b8752` | `6260d821...09a2` | `ba79b9bb...fedb` |
| 来源 | 本项目 `native/` | 上游 `gd_cubism` 0.9.1 | 上游 `godot-sqlite` 4.9 |
| 工具链 | MSVC 14.44 | MSVC 14.44 + LTCG | MinGW-w64 / GNU ld |
| CRT | 静态 `/MT` | 静态 | UCRT 动态 |
| 导出符号 | `windows_security_init` | `gd_cubism_library_init` | `sqlite_library_init` |
| 导入 DLL | 4 个 | 仅 `KERNEL32.dll` | 13 个（KERNEL32 + 12 个 UCRT） |
| 调试信息 | 无 PDB，仅 ILTCG | 无 PDB | 无 PDB |
| 签名 | 无 | 无 | 无 |
| 作用 | 加密/输入法/音频/容量 | Live2D 模型渲染 | SQLite 数据库 |

三者的 SHA-256 都与 `dependencies.lock.json` 逐字节一致；这说明仓库分发的是锁定产物，不是本地随手重编的版本。

### 9.3 `libgd_cubism`：把 Cubism Core 静态链进去

关键事实：

- 只有 1 个导出 `gd_cubism_library_init`（RVA `0x252B0`），与 `gd_cubism.gdextension` 的 `entry_symbol` 对上。
- 导入表只有 `KERNEL32.dll` 的 86 个函数；**没有** `Live2DCubismCore.dll`、`vcruntime140.dll`、`msvcp140.dll`。说明 Cubism Core 与 C++ 运行库都被静态链进这个 DLL。
- 字符串里有 `CubismRenderer@Rendering@Framework@Cubism@Live2D`、`csmReviveMocInPlace`、`csmHasMocConsistency`、`CSM_MOC_VERSION_50`，以及 `model3.json` 的全套键（`FileReferences`、`Groups`、`Layout`、`HitAreas`、`Textures`、`Physics`、`DisplayInfo`、`Expressions`、`Motions`、`UserData`、`Sound`）。
- 有 POGO/ILTCG 调试记录，但没有 CodeView/PDB。
- 类名要用 `GDCubismUserModel`（Godot 类）和内部的 `CubismRenderer`；**不存在** `CubismModel` 这个 Godot 类。

Cubism SDK 的精确 Core 版本没有直接取证；`CSM_MOC_VERSION_50` 与 lock 的 `5-r.1` 自洽，但只能说明是 5.x 系列，不能钉死到某个补丁号。

### 9.4 `libgdsqlite`：MinGW 构建、SQLite 静态链入

关键事实：

- 只有 1 个导出 `sqlite_library_init`（RVA `0x12DC0`）；sqlite3 的 C API 一个都不导出。
- 导入 13 个 DLL、194 个函数：`KERNEL32` 101 个 + 12 个 `api-ms-win-crt-*`（含 `-private`）。这是 **UCRT 动态链接**，不是 MSVC 静态 CRT；但也不需要 VC++ Redistributable。
- 链接器版本 2.46、独立的 `.edata/.idata/.bss/.xdata` 节、libstdc++ 错误串，说明是 **MinGW-w64/GNU ld** 构建，不是 MSVC。
- 字符串里有 SQLite `3.51.0`、`THREADSAFE=1`、`MUTEX_W32`、`SYSTEM_MALLOC`、`TEMP_STORE=1`、`MAX_VARIABLE_NUMBER=32766`、`DEFAULT_SYNCHRONOUS=2`。
- 没有 `sqlite3.dll` 导入，说明 SQLite 被静态编进插件。
- 没有 PDB、没有签名、没有版本资源。

`gdsqlite.gdextension` 写 `compatibility_minimum = "4.7"`，而 `gd_cubism` 写 `4.3`；本项目引擎是 4.7.1，两者都满足。如果换到 4.3–4.6，`libgdsqlite` 会被拒绝加载，`libgd_cubism` 不会。

### 9.5 release 与 debug 的差异

`libgdsqlite` 同时提供 release 和 debug 两个 DLL。两者导入集合完全相同，但 debug 的 `.rdata` 更大，独有 godot-cpp `gen\src\classes\*.cpp` 路径和 `Condition "..." is true.` 断言串；release 没有。这说明差异主要来自 `NDEBUG`/`DEV_ENABLED` 与断言代码，不是两套不同实现。

### 9.6 为什么“源码构成”完全不同

| 类型 | 例子 | 源码形态 | 读法 |
|---|---|---|---|
| 自有薄封装 | `windows_security.dll` | 4 个 `.cpp`，共 486 行，直接调 Win32/CNG | 逐函数读，重点是边界与错误码 |
| 上游完整插件 | `libgd_cubism`、`libgdsqlite` | 仓库只放编译产物，源码在上游仓库 | 不用读全部源码；看 `entry_symbol`、类名、版本字符串、依赖即可 |
| 引擎/框架 | `godot-cpp` | 通过 `SConstruct` 静态链入 | 只在排查 ABI/内存问题时看 |

所以“这个 DLL 的源码构成”对不同 DLL 有不同答案：`windows_security.dll` 的源码就在 `native/`；另外两个的源码不在本仓库，本文只能给出二进制指纹与上游版本，不能假装读过它们的全部源码。

---

## 10. 安全与边界

### 10.1 这节回答什么

这一节回答“这个 DLL 的攻击面有多大、它做了哪些防御、还有哪些没做、换平台/换用户/缺文件时会怎样”。这不是安全审计报告，而是维护者需要知道的边界；结论全部基于静态证据。

### 10.2 攻击面：只接收 GDScript 传入的字节和字符串

四个类的输入只有三类：

- 字符串：PEM、密码、磁盘路径；
- 字节数组：明文、DPAPI 密文、WAV 分片；
- 布尔/整数：`enabled`、`max_count`、`frame_index`、`buckets`。

它不监听端口、不发起网络、不读注册表、不创建进程、不主动写文件。缓存文件、日志、下载都由 GDScript 侧负责；原生 DLL 只做“给定输入 → 返回结果”的纯函数式处理（`WindowsInputMethod` 的静态布局状态是唯一例外）。

这意味着主要的攻击面是**恶意/畸形输入**，而不是“DLL 自己联网外传数据”。导入表里没有网络/注册表/进程 API，是这一结论最硬的证据。

### 10.3 已有的防御

| 防御 | 位置 | 作用 |
|---|---|---|
| PEM 长度上限 16 KiB | `windows_security.cpp:63` | 防止超大 Base64 解码耗尽内存 |
| DPAPI 输入上限 64/128 KiB、scope 64 KiB | `windows_security.cpp:46-48` | 限制 blob 大小 |
| RSA 位数 2048–8192 | `windows_security.cpp:86-89` | 拒绝过弱/异常密钥 |
| OAEP-SHA256 与明文长度扣减 66 字节 | `windows_security.cpp:90-92` | 避免填充溢出，匹配服务端 |
| `CRYPTPROTECT_UI_FORBIDDEN` | `windows_security.cpp:52-55` | 后台调用不弹 UI |
| 明文/密钥缓冲清零 | `KeyHandle`、`LocalBuffer`、`PasswordBytes` | 减少内存残留 |
| WAV 8 MiB/1 MiB/128 MiB/1800s 四重上限 | `pcm_stream_decoder.cpp:8-9,60,93` | 防内存/时长耗尽 |
| 扩展 GUID 全量校验 | `pcm_stream_decoder.cpp:154-165` | 防伪造 `WAVE_FORMAT_EXTENSIBLE` 绕过格式检查 |
| 失败即清空缓冲 | `pcm_stream_decoder.cpp:36-44` | 错误后不保留半成品数据 |
| `isfinite` 检查 float 样本 | `pcm_stream_decoder.cpp:178` | 拒绝 NaN/Inf |
| 容量值溢出/大小关系校验 | `storage_volume.cpp:14-17` | 防 `available > total` 或乘法溢出 |
| 线程亲和性检查 | `windows_input_method.cpp:30-37` | 不跨线程恢复别人的布局 |

### 10.4 没做的部分

| 项 | 现状 | 影响 |
|---|---|---|
| Authenticode 签名 | 无 | 系统无法验证发布者；靠仓库哈希锁与发布流程 |
| CFG | 关闭 | 间接调用目标不受 Control Flow Guard 保护 |
| PDB | 无 | 崩溃转储只能靠 RVA/反汇编定位，不能直接映射源码行 |
| 第三方许可声明 | 两个第三方 DLL 内无 license/copyright 串 | 合规义务落在仓库 `licenses/`；Live2D Cubism 是商业授权，分发前要确认 |
| 动态验证 | 本次未做 | 运行期行为（DPAPI 描述串、OAEP 旗标、返回字典）需按第 8.6 节命令自行验证 |

“无签名 + 无 PDB + 无 CFG”不等于“不安全”，但意味着出了问题时的取证成本更高：你需要保留构建产物哈希、用 RVA 对照本文、按第 11 节的方法反汇编。

### 10.5 平台边界

| 平台 | 现状 | 依据 |
|---|---|---|
| Windows x64 | 支持 | `.gdextension` 只有 `windows.x86_64` |
| Windows arm64 | 不支持 | 没有对应库条目 |
| macOS / Linux | 不支持 | `.gdextension` 无条目；`windows_security.cpp`/`windows_input_method.cpp` 无条件包含 `windows.h` |
| Android / iOS | 不支持 | 无预设、无库条目；README 明确说移动端后端尚未实现 |

`StorageVolume` 有 Unix 分支，但它只是“这个类本身可移植”，不代表整 DLL 可移植。要支持 Linux/macOS，至少需要把 DPAPI/RSA/键盘布局拆成平台实现，并新增库条目。

### 10.6 版本与文档漂移

这是读仓库时容易踩的坑，不属于 DLL 本身的问题：

- `release.json:1`、`project.godot:14`、`export_presets.cfg:48-49`、`dist/agentluo-0.1.8.6/release.json` 都是 `0.1.8.6`；
- `client-godot/README.md:3,136,142`、`docs/README.md:3`、`PREVIEW.md:3` 仍写 `0.1.8.2`；
- `Agent-LuoTianyi/docs/代码地图.md:19` 仍称“当前 dev 尚无 Godot 源码目录”，与已存在的 `client-godot` 矛盾；该文件也没有把 `client-godot` 列进入口表。

本文只提醒，不修改这些文件。判断当前版本时以 `release.json` 为准，不以 README 的叙述为准。

### 10.7 常见故障的定位顺序

| 现象 | 先查什么 | 再看什么 |
|---|---|---|
| 启动提示“账号与聊天功能暂不可用” | `ClassDB.class_exists("WindowsSecurity")` 是否为 false | DLL 是否在 EXE 同级、`.gdextension` 是否被导出、是否缺 VC++ 依赖 |
| 登录报 `ENCRYPTION_ERROR` | 原生返回的 `error`/`native_code` | PEM 是否为空/非 RSA、密码是否超过 `bits/8-66`、服务端公钥是否有效 |
| 令牌读不出来 | scope 是否与保存时一致 | 是否换了 Windows 用户/机器、密文是否被截断/篡改、文件是否超过 131072 字节 |
| 语音没声音/波形为空 | `get_status().code` | 是否 `finish`、WAV 是否截断/格式不支持、`read_frames` 是否被消费 |
| 容量显示 `--` | `StorageVolume.query` 是否返回 `-1` | 路径是否绝对、卷是否可访问、`free <= total` 是否成立 |
| 密码框仍输入中文 | `WindowsInputMethod` 是否加载 | `set_english(true)` 的 `ok`/`error`、当前线程是否变化 |

---

## 11. 自己动手读：工具、命令、坑

### 11.1 这节回答什么

这一节给一套最小工具链和可复现命令，让你不依赖本文也能独立验证结论。最后给一个 30 分钟检查清单，适合第一次接手这个 DLL 时走一遍。

### 11.2 工具表

| 工具 | 用途 | 本环境路径/获取方式 |
|---|---|---|
| PowerShell | 哈希、签名、版本信息、文件枚举 | 系统自带 |
| `objdump` | PE 头、节表、导入/导出、反汇编 | `C:\x86_64-14.2.0-release-win32-seh-ucrt-rt_v12-rev1\mingw64\bin\objdump.exe` |
| `strings` | ASCII/UTF-16 字符串与偏移 | 同目录 `strings.exe` |
| Python | 熵计算、PE 解析、脚本化交叉核对 | `D:\anaconda\python.exe` |
| `pefile`（可选） | 解析 Rich header、数据目录、导入表 | `python -m pip install pefile` |
| `capstone`（可选） | 反汇编与 xref 脚本 | `python -m pip install capstone` |
| Godot 4.7.1 | 跑测试/加载扩展 | `$env:GODOT_BIN` |

没有 `dumpbin` 不影响分析；`objdump` 能覆盖大部分 PE 读取需求。`sigcheck` 也不是必需，`Get-AuthenticodeSignature` 足够判断有无签名。

### 11.3 六条核心命令

```powershell
$dll = 'D:\01restart\langchain\lty\Agent-LuoTianyi\client-godot\addons\windows_security\bin\windows_security.dll'
$objdump = 'C:\x86_64-14.2.0-release-win32-seh-ucrt-rt_v12-rev1\mingw64\bin\objdump.exe'
$strings = 'C:\x86_64-14.2.0-release-win32-seh-ucrt-rt_v12-rev1\mingw64\bin\strings.exe'

# 1. 哈希与签名
Get-FileHash $dll -Algorithm SHA256
Get-AuthenticodeSignature $dll

# 2. PE 头、数据目录、导入/导出
& $objdump -p $dll

# 3. 节表
& $objdump -h $dll

# 4. 反汇编某个函数（RVA + ImageBase）
& $objdump -d -M intel --start-address=0x180005200 --stop-address=0x180005430 $dll

# 5. ASCII 字符串与文件偏移
& $strings -a -t x $dll | Select-String 'INVALID_KEY|BUFFER_LIMIT|read_frames'

# 6. UTF-16 宽字符串
& $strings -a -t x -el $dll | Select-String 'AgentLuo|KeyLength|00000409'
```

### 11.4 四个必须知道的坑

#### 坑一：导入调用经过 IAT thunk，直接 grep 函数名会 0 命中

`.text` 中散布着 29 个 6 字节 thunk（例如 `0x21a38`、`0x21a3e`、`0x21a44`），形如：

```text
180021a38: ff 25 ba 98 01 00   jmp QWORD PTR [rip+0x198ba]   # 0x18003b2f8  BCryptGetProperty
180021a3e: ff 25 ac 98 01 00   jmp QWORD PTR [rip+0x198ac]   # 0x18003b2f0  BCryptEncrypt
```

业务函数用 `call 0x180005200` 这种相对调用进入 thunk，再由 thunk 跳 IAT。`objdump | Select-String 'BCrypt'` 只会在导入表段命中，不会在反汇编正文命中，于是容易误判“导入了但没调用”。正确做法是先看 thunk，再把 `call` 目标折算回导入名。

#### 坑二：没有 CodeView，就没有 PDB 路径

Debug Directory 只有 type=13 ILTCG。不要花时间在 DLL 里找 `RSDS`、GUID、Age；找不到是正常的。要定位 PDB，只能从构建机/CI 产物或 `.exp` 的构建路径侧推。

#### 坑三：字符串池复用，偏移可能指向另一个串的内部

`PROTECT_FAILED` 的实际地址是 `0x39f22`，落在 `UNPROTECT_FAILED`（`0x39f20`）内部；`enabled` 只以 `_enabled`（`0x3a33f`）存在，代码引用 `+1`。看到字符串偏移和预期不一致，先怀疑 MSVC `/GF` 串池，不要怀疑自己的反汇编。

#### 坑四：导出表只有入口，不代表功能只有一个

导出表只有 `windows_security_init`，但 DLL 里有 4 个类、12 个方法。判断功能要看：

1. `entry_symbol` 指向的入口；
2. 入口里的 `register_class` 调用；
3. 每个类的 `_bind_methods`；
4. RTTI 的 `MethodBindTR/TRC` 签名；
5. `.gdextension` 与 GDScript 调用点。

只看导出表会得出“这个 DLL 只有一个函数”的错误结论。

### 11.5 30 分钟检查清单

| 时间 | 动作 | 预期结果 |
|---|---|---|
| 0–3 分钟 | `Get-FileHash` + 对照 lock | 哈希一致 |
| 3–6 分钟 | `objdump -p` 看导出与导入 | 1 个导出、4 个导入 DLL |
| 6–9 分钟 | `objdump -h` 看节表 | 6 个节，无高熵节 |
| 9–12 分钟 | `Get-AuthenticodeSignature` | `NotSigned` |
| 12–16 分钟 | `strings` 找源文件、错误码、方法名 | 四个源文件、关键错误码齐全 |
| 16–20 分钟 | 反汇编 `windows_security_init` | 4 步 InitObject 调用 |
| 20–24 分钟 | 反汇编 `initialize_security` | 4 次注册，顺序正确 |
| 24–30 分钟 | 对照 `SConstruct`、`build_security.py`、lock | 四个源文件、链接库、工具链一致 |

### 11.6 这套方法如何迁移到其他 GDExtension

1. 先读 `.gdextension`，拿 `entry_symbol` 和平台库路径；
2. `objdump -p` 确认导出表里真有这个符号；
3. 反汇编入口，找 `register_initializer` / `register_class`；
4. 用类名和 `_bind_methods` 找方法绑定；
5. 用 RTTI 的 `MethodBindTR/TRC` 还原方法签名；
6. 用字符串找源文件路径和错误码；
7. 最后才去看导入表，判断它依赖哪些系统能力。

顺序反过来（先看导入表）容易被静态 CRT 的 80 多个 kernel32 函数淹没，抓不到重点。

---

## 12. 术语表

| 术语 | 解释 |
|---|---|
| PE / PE32+ | Windows 可执行文件格式；PE32+ 是 64 位变体 |
| RVA / VA | 相对虚拟地址 / 虚拟地址；本 DLL `VA = RVA + 0x180000000` |
| Section / 节 | PE 里的代码/数据分区，如 `.text`、`.rdata` |
| IAT | 导入地址表，存放外部 DLL 函数地址 |
| Thunk | 一小段跳转桩，这里指 6 字节的 `jmp [rip+disp]` |
| RTTI | C++ 运行期类型信息，包含 type descriptor、vftable、COL |
| Type descriptor | RTTI 里的类型名字符串，形如 `.?AVWindowsSecurity@@` |
| COL | Complete Object Locator，把 vftable 关联到类型信息 |
| PDB | 程序数据库，调试符号文件 |
| ILTCG | Incremental Link Time Code Generation 的调试记录类型（type 13） |
| CRT | C/C++ 运行库；`/MT` 静态、`/MD` 动态 |
| GDExtension | Godot 4 的原生扩展机制，通过 `.gdextension` 描述 |
| ClassDB | Godot 的类数据库，`register_class`/`instantiate` 都走它 |
| GDCLASS | godot-cpp 宏，声明类的 Godot 类型信息与 `_bind_methods` |
| RefCounted | Godot 的引用计数基类；GDScript 侧看到的是引用对象 |
| DPAPI | Windows 数据保护 API，绑定当前用户 |
| CNG | Windows Cryptography Next Generation，`bcrypt.dll` 那套 API |
| OAEP | RSA 的一种填充方案；这里用 SHA-256 |
| RMS | 均方根，音频响度的一种度量 |
| WAVE_FORMAT_EXTENSIBLE | WAV 的扩展格式头，用 GUID 指定子格式 |
| Entropy / scope | 本文里指 DPAPI 的第二份密钥材料，绑定账号/服务器 |
| Authenticode | Windows 的代码签名机制 |
| CFG | Control Flow Guard，控制流保护 |
| GS | MSVC 的栈缓冲区保护（stack cookie） |

---

## 13. 附录

### 13.1 源码索引

| 文件:行 | 内容 |
|---|---|
| `native/windows_security.cpp:18` | `result()` 统一返回字典 |
| `native/windows_security.cpp:27` | `KeyHandle` RAII |
| `native/windows_security.cpp:31` | `LocalBuffer` RAII |
| `native/windows_security.cpp:40` | `PasswordBytes` RAII |
| `native/windows_security.cpp:46` | `dpapi()` |
| `native/windows_security.cpp:61` | `import_key()` |
| `native/windows_security.cpp:82` | `encrypt_with_key()` |
| `native/windows_security.cpp:109` | `WindowsSecurity` 类 |
| `native/windows_security.cpp:112` | `_bind_methods()` |
| `native/windows_security.cpp:118` | `encrypt_password()` |
| `native/windows_security.cpp:125` | `protect_secret()` |
| `native/windows_security.cpp:126` | `unprotect_secret()` |
| `native/windows_security.cpp:129` | `initialize_security()` |
| `native/windows_security.cpp:138` | `windows_security_init()` |
| `native/pcm_stream_decoder.h:10` | `PcmStreamDecoder` 类 |
| `native/pcm_stream_decoder.h:12` | `Phase` 状态机 |
| `native/pcm_stream_decoder.cpp:8` | `QUEUE_FRAMES` |
| `native/pcm_stream_decoder.cpp:9` | `HEADER_LIMIT` |
| `native/pcm_stream_decoder.cpp:14` | `_bind_methods()` |
| `native/pcm_stream_decoder.cpp:22` | `get_status()` |
| `native/pcm_stream_decoder.cpp:36` | `fail()` |
| `native/pcm_stream_decoder.cpp:46` | `parse_format()` |
| `native/pcm_stream_decoder.cpp:58` | `decode()` |
| `native/pcm_stream_decoder.cpp:86` | `append()` |
| `native/pcm_stream_decoder.cpp:105` | `finish()` |
| `native/pcm_stream_decoder.cpp:113` | `read_frames()` |
| `native/pcm_stream_decoder.cpp:124` | `get_amplitude()` |
| `native/pcm_stream_decoder.cpp:131` | `get_waveform()` |
| `native/pcm_stream_decoder.cpp:154` | `parse_subtype()` |
| `native/pcm_stream_decoder.cpp:167` | `validate_format()` |
| `native/pcm_stream_decoder.cpp:175` | `decode_sample()` |
| `native/pcm_stream_decoder.cpp:199` | `consume_riff()` |
| `native/pcm_stream_decoder.cpp:206` | `consume_chunk()` |
| `native/pcm_stream_decoder.cpp:224` | `consume_data()` |
| `native/windows_input_method.cpp:10` | 静态布局状态 |
| `native/windows_input_method.cpp:28` | `set_english()` |
| `native/windows_input_method.cpp:53` | `get_layout()` |
| `native/storage_volume.cpp:14` | `valid_capacity()` |
| `native/storage_volume.cpp:23` | `GetDiskFreeSpaceExW` |
| `native/storage_volume.cpp:44` | `query()` |
| `native/SConstruct:5` | 链接 `bcrypt/crypt32/user32` |
| `native/SConstruct:8` | 四个源文件产出单 DLL |
| `addons/windows_security/windows_security.gdextension:2` | `entry_symbol` |
| `scripts/build_security.py:17` | native 源码 clean 检查 |
| `scripts/build_security.py:28` | godot-cpp commit 检查 |
| `scripts/build_security.py:31` | SCons 版本检查 |
| `scripts/build_security.py:44` | 产物哈希检查 |

### 13.2 未决问题

| 问题 | 现状 | 建议 |
|---|---|---|
| `.fptable` 节全零、用途不明 | 标准 MSVC 不产生该名字的节；可能是工具链/链接后处理 | 查 SConstruct 是否传自定义 `/SECTION`，或对比其他构建产物 |
| `BCRYPT_PAD_OAEP` 立即数未直接观察 | 由 `L"SHA256"` 与 `0x42` 扣减推断 | 在 `0x55e4` 追踪第 10 个参数 `dwFlags` 的来源 |
| `PcmStreamDecoder::append` 入口未由符号确认 | 通过 `_bind_methods` 绑定顺序与实现块推定 | 分析 `_bind_methods` 的绑定顺序，或动态断点确认 |
| RIFF 状态机未逐字节核对 | 已确认错误码出口与常量，未逐块验证 `RIFF/WAVE/fmt /data` 比较 | 用合成 WAV 做动态单步 |
| 继承关系无 COL 直证 | 源码明确 `: RefCounted`，二进制缺 COL | 结合源码与注册期基类名串，结论足够 |
| Cubism Core 精确版本 | 只有 `CSM_MOC_VERSION_50` 与 lock `5-r.1` | 反汇编 `csmGetVersion` 或从 Godot 侧读属性 |
| SQLite 是否定义 `SQLITE_OMIT_LOAD_EXTENSION` | 只有 “Extension loading cannot be enabled/disabled.” 字符串 | 查上游构建脚本或动态调用 `enable_load_extension` |
| 全部结论未做动态验证 | 本文是静态分析 | 按第 8.6 节命令跑测试/互操作 |

### 13.3 如果只想记三件事

1. **它是什么**：`windows_security.dll` 是一个 Godot 4 GDExtension，四个 `.cpp` 编成一个 DLL，只导出 `windows_security_init`，运行期注册 `WindowsSecurity`、`WindowsInputMethod`、`PcmStreamDecoder`、`StorageVolume` 四个类。
2. **它做什么**：RSA-OAEP 加密登录密码，DPAPI 保护本地令牌/API Key，流式解码服务端 WAV 并输出帧/RMS 波形，查询卷容量，切换键盘布局。没有网络、注册表、进程创建。
3. **怎么维护**：改完 `native/` 后用 `build_security.py` 重建，必须过 git-clean、godot-cpp commit、SCons 版本、SHA-256 四道门禁；DLL 没有签名/PDB，排查靠 RVA + 本文源码索引 + 第 11 节命令。

---

**文档边界**：本文只分析 `windows_security.dll` 及其源码、构建、GDScript 调用面，并对两个第三方 DLL 做对照；不分析 Godot 引擎内部、不分析全部 GDScript 业务逻辑、不构成安全审计。所有二进制结论来自静态分析，运行期行为请按第 8.6 节自行验证。
