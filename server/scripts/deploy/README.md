# 部署工具目录

| 位置 | 职责与入口 |
| --- | --- |
| `environment/` | 创建和安装 Python 环境。Linux 使用 `install_linux.sh` 与 uv 锁文件；Windows 使用 `install_windows.bat` 与可选 Conda 配置。 |
| `startup/` | 启动已有环境中的服务，主要用于源码目录内运行。包含 Linux / Windows 启动器、systemd 服务模板和实例环境变量示例。 |
| `release/` | 首次部署及版本管理，`bootstrap.py` 提供 目录初始化、首次安装功能，资产迁移和校验功能`assets` 注册为服务`systemd`共嗯。构建与检查版本，包含 build / plan / apply / status 实现、资源校验清单、数据库与资源目录迁移工具。 |
| `init_instance.sh`、`install_instance.sh` | 初始化空实例、首次安装；参数由脚本传给共用 Python 实现。 |
| `deploy.py` | 版本构建、更新、状态查询及资产/systemd 管理。 |

## 首次部署

面向新用户的完整步骤见 [服务端 README](../../README.md#linux-首次部署)。在仓库的 `server/` 目录以普通账号执行：

```bash
bash scripts/deploy/init_instance.sh --root "$HOME/agentluo-production"
# 填写输出的 secrets.local.env 中的 API 密钥，再继续。
python3 scripts/deploy/deploy.py assets --root "$HOME/agentluo-production" --source /path/to/models
bash scripts/deploy/install_instance.sh --root "$HOME/agentluo-production"
python3 scripts/deploy/deploy.py systemd --root "$HOME/agentluo-production"
```

`init_instance.sh` 仅接受新目录或空目录，自动创建独立配置、数据、运行、资产、环境与发布目录，生成 JWT 密钥和 `deployments/deploy.toml`。默认服务名 `agentluo.service`、部署配置中的实例名 `production`、端口 `15673`。`--name` 是添加在 `agentluo` 后的后缀，不是完整服务名：`--name test` 会生成 `agentluo-test.service`，对应实例名为 `test`；显式 `--name production` 则生成 `agentluo-production.service`。端口通过 `--port` 修改。目录必须由服务账号持有，不使用 sudo 执行部署 CLI。

`assets` 从指定 Git 提交的资产清单核验源文件，复制到实例后移除组和其他账号写权限，不修改源目录；符号链接和损坏文件被拒绝。`assets` 与 `install_instance.sh` 都默认 `--ref HEAD`，指定版本时需使用同一 ref。

`install_instance.sh` 为首次安装入口：构建发布包，复用发布准备、依赖安装和启动预检，再生成普通配置、`instance.env` 与 `current`。它不要求已有数据库和 systemd 单元，不启动服务，也不宣称业务健康。已有 `current`、普通配置或数据会阻断，不能用于接管旧实例或升级；环境准备失败时不会切换 `current`。依赖下载中断留下的环境目录需先检查，现有环境校验不会原地修补损坏依赖。

`systemd` 生成并验证 managed 单元，以 sudo 安装、重载 systemd、启用并启动服务。同名但内容或位置不同的单元会被拒绝，不会覆盖其他服务。数据库由正常服务初始化路径创建；启动后通过管理页面和 `status` 确认业务运行时健康。

## 版本更新

本节适用于已按独立实例方式部署并由 systemd 管理的服务。更新沿用原安装目录、用户数据和密钥，不再执行 `init_instance.sh`、`install_instance.sh` 或重新创建服务。使用外部配置/数据或自定义环境文件的实例，先阅读[外部路径与链接部署](#外部路径与链接部署)。

**1. 获取目标代码并构建。** 在仓库中获取要发布的提交或标签，从 `server/` 执行。下例更新到本地 `HEAD`；也可将其换成已获取的标签。build 仅读取 Git 提交，未提交的改动不会发布。

```bash
INSTALL_DIR="$HOME/agentluo-production"
UPDATE_DIR="$HOME/agentluo-updates"
mkdir -p "$UPDATE_DIR"
python3 scripts/deploy/deploy.py build --ref HEAD --output-dir "$UPDATE_DIR/packages"
```

其中`UPDATE_DIR`是存放计划文件的目录，由于plan需要对计划文件和当前运行实例中的文件进行比较，它们不能是同一个目录。

`build` 会生成发布包 `agentluo-<commit>.tar.gz`，并在 `packages/` 下生成清单文件 `agentluo-<commit>.json`，包含该版本的模型资源、配置和数据库迁移信息。

**2. 检查更新计划。** 将 `PACKAGE` 改为上一条命令输出的发布包绝对路径。默认实例名是 `production`，创建时使用过 `--name` 的应换成对应名称；旧实例使用自己的部署配置路径。

```bash
PACKAGE="/absolute/path/from/build/agentluo-<commit>.tar.gz"
PLAN_FILE="$UPDATE_DIR/plan-$(date +%Y%m%d-%H%M%S).json"
python3 scripts/deploy/deploy.py --config "$INSTALL_DIR/deployments/deploy.toml" plan \
  --package "$PACKAGE" --instance production --out "$PLAN_FILE"
```

计划必须在实例外，不能覆盖已有文件。确认输出 `executable: true` 后继续；如有阻断，按输出修复并生成新计划。新版本需要不同模型资源时，先按该版本清单准备资产，在部署配置中填写 `asset_source`，或使用与目标版本相同的 `assets --ref` 导入；模型不会自动下载。目标提交须包含当前部署工具所需的发布文件。

**3. 执行更新并确认结果。** 此步骤会停服。以服务所属账号运行；系统级服务需预先配置下文所述的非交互 sudo 启停权限，首次安装时交互输入过 sudo 密码不代表该权限已配置。

```bash
python3 scripts/deploy/deploy.py apply --plan "$PLAN_FILE" --json
python3 scripts/deploy/deploy.py --config "$INSTALL_DIR/deployments/deploy.toml" status \
  --instance production --json
```

检查 `status` 的 `healthy` 为真，再通过客户端发送消息、试听回复。`apply` 会备份配置和迁移涉及的数据库，保留实例密钥与第三方凭据；普通 `config.json` 由发布模板覆盖，因此需要保留的普通配置改动应纳入目标版本模板。配置或凭据在计划生成后变化，需重新生成计划。失败后的备份位置和恢复方式见下文 [apply 与 status](#apply-与-status)。

安装器、启动器内部均以自身位置定位服务端根目录。Linux 依赖项目位于 `environment/`，
其本地服务端依赖相对路径为 `../../..`；修改目录时须同时调整 `pyproject.toml` 与 `uv.lock`。
数据库迁移须在停止全部写入者后进行，具体命令见 [数据库版本与迁移](#数据库版本与迁移)。


## 外部路径与链接部署

运行时支持代码、模型、配置和数据位于不同目录，也支持这些目录通过符号链接指向实际位置。例如，开发者在自己的 home 目录中运行代码，使用同一主机上测试服务的模型和数据。路径必须能由当前账号访问；远程服务器上的路径须先挂载到本机，不能直接填写 HTTP 或 SSH 地址。

### 选择共享范围

| 需求 | 设置方式 | 使用条件 |
| --- | --- | --- |
| 只复用模型 | `AGENTLUO_ASSET_DIR` 指向已有资产目录或链接 | 配置、数据和运行目录保持自己的实例路径；资产须匹配代码版本 |
| 使用测试配置和数据副本，两个服务同时运行 | 配置、数据使用一致性快照的副本，模型仍可共享 | 独立运行目录和监听端口；检查配置内显式绝对路径，避免仍指回原数据 |
| 直接使用测试服务原有配置和数据 | `AGENTLUO_CONFIG_DIR`、`AGENTLUO_DATA_DIR` 指向原目录 | 先停止原服务及其他写入者，再运行自己的代码；使用同一运行锁目录 |

直接引用配置和数据会写入原目录，包括管理配置、凭据、业务记录和可能的数据库迁移，并不是只读浏览。切换代码运行前应备份并确认数据库版本兼容。两个服务不能同时写同一套数据；同一主机使用相同 `AGENTLUO_RUNTIME_DIR` 并通过统一启动器启动，可共用 `server.lock` 防止误启动。跨主机或其他维护工具的写入者仍须人工停止。

模型目录至少要允许运行账号读取文件、进入目录。NLTK 等第三方库还会检查所有权和写权限；不能通过开放组/其他账号写权限来解决加载失败。若共享账号条件不满足库的安全要求，应使用当前账号持有的、通过清单校验的资产副本。模型库可能产生缓存，是否可完全只读挂载须经过实际推理验证。

### 前台运行：直接设置路径，无需 instance.env

先按[源码环境安装步骤](../../README.md#linux-源码环境)在自己的仓库创建 `.venv`；在导出下面的共享路径之前完成安装。示例假定仓库位于 `$HOME/Agent-LuoTianyi/server`，测试实例位于 `/srv/agentluo-test`。请换成实际位置和资产版本，并先停止使用原配置及数据的测试服务。

```bash
cd "$HOME/Agent-LuoTianyi/server"
TEST_INSTANCE="/srv/agentluo-test"
export AGENTLUO_CONFIG_DIR="$TEST_INSTANCE/config"
export AGENTLUO_DATA_DIR="$TEST_INSTANCE/data"
export AGENTLUO_RUNTIME_DIR="$TEST_INSTANCE/.runtime"
export AGENTLUO_ASSET_DIR="$TEST_INSTANCE/assets/production-baseline-20261110"
export AGENTLUO_RESOURCE_DIR="$PWD/res"
export AGENTLUO_PYTHON="$PWD/.venv/bin/python"
export PLAYWRIGHT_BROWSERS_PATH="$PWD/.runtime/browsers"

bash scripts/deploy/startup/start_linux.sh --check-startup
bash scripts/deploy/startup/start_linux.sh
```

该例复用原实例的运行锁，Python 环境和浏览器仍使用自己的安装结果。监听端口取共享配置中的 `is_debug` 与 `server.debug_port/production_port`；不要为改变自己服务的端口而误改仍供他人使用的共享配置。`--check-startup` 仅检查启动配置，不代表模型推理通过。

若希望通过 home 下的链接访问模型，可将上述 `AGENTLUO_ASSET_DIR` 改为以下链接位置，其他设置不变：

```bash
ln -s /srv/agentluo-test/assets/production-baseline-20261110 "$HOME/agentluo-shared-models"
export AGENTLUO_ASSET_DIR="$HOME/agentluo-shared-models"
```

运行时会解析目录链接，无需把模型复制进代码仓库。`AGENTLUO_RESOURCE_DIR` 表示人设、Prompt、管理页面等随代码发布的小资源，通常保留为自己的代码版本的 `res/`；它与大型模型的 `AGENTLUO_ASSET_DIR` 是不同的设置。完整映射见[独立实例路径](#独立实例路径)。

### systemd 运行：保存自定义 instance.env

需要长期后台运行时，将前台示例的路径保存到自己维护的环境文件，例如 `/home/alice/agentluo-dev/instance.env`。创建其父目录，目录权限设为 `700`、文件设为 `600`。以下内容中的用户名与路径都要改成实际值：

```ini
AGENTLUO_CONFIG_DIR=/srv/agentluo-test/config
AGENTLUO_DATA_DIR=/srv/agentluo-test/data
AGENTLUO_RUNTIME_DIR=/srv/agentluo-test/.runtime
AGENTLUO_ASSET_DIR=/home/alice/agentluo-shared-models
AGENTLUO_RESOURCE_DIR=/home/alice/Agent-LuoTianyi/server/res
AGENTLUO_PYTHON=/home/alice/Agent-LuoTianyi/server/.venv/bin/python
PLAYWRIGHT_BROWSERS_PATH=/home/alice/Agent-LuoTianyi/server/.runtime/browsers
SERVER_HOST=127.0.0.1
```

这是 systemd 的 `EnvironmentFile`，写绝对路径，不写 `export`，不使用 `$HOME`、`$TEST_INSTANCE` 或 `~` 展开；路径包含空格时将值用双引号包围。环境文件负责定位目录，模型密钥仍从所选配置目录的 `secrets.local.env` 加载。版本化实例通过 `current` 启动时，会自动读取该实例的 `deployments/instance.env`；源码目录启动默认沿用终端环境变量。也可用 `AGENTLUO_INSTANCE_ENV=/absolute/path/instance.env bash scripts/deploy/startup/start_linux.sh` 显式指定文件，或将该变量设为空来禁用自动加载。启动器用 Bash source 加载文件，因此显式指定的文件必须来自可信操作者且兼容 Bash 赋值语法；上面的简单绝对路径示例可直接使用，任意 systemd 环境文件不一定兼容。自动加载或显式文件中的设置优先于同名终端环境变量。

使用[自定义服务模板](startup/agentluo.service.example)，把 `@SERVICE_USER@`、`@SERVICE_HOME@`、`@SERVER_DIR@`、`@INSTANCE_ENV_FILE@` 分别换成服务账号、账号主目录、自己的 `server/` 路径和上述环境文件绝对路径。保存为独立服务名（如 `agentluo-dev.service`），验证后安装：

```bash
systemd-analyze verify /path/to/agentluo-dev.service
sudo install -m 644 /path/to/agentluo-dev.service /etc/systemd/system/agentluo-dev.service
sudo systemctl daemon-reload
sudo systemctl start agentluo-dev.service
systemctl status agentluo-dev.service --no-pager
```

共享原数据时，不要同时启用原服务和开发服务的开机自启。以后编辑环境文件后重启自己的服务即可生效；修改服务单元还需先执行 `systemctl daemon-reload`。

### 与自动部署脚本的边界

上面的外部路径方式由运行时和启动器支持。当前 `assets` / `install_instance.sh` 的一键流程采用实例内资产副本，会拒绝资产符号链接；`apply` 要求配置、数据和运行目录在实例内，不能把这些目录链接到外部后继续升级。`apply` 还会重写 `deployments/instance.env`，因此手改该文件不能作为持久外部路径配置。

使用外部路径时维护独立环境文件和自定义服务单元，不使用 `deploy.py systemd` 生成 managed 服务，也不对该布局执行 `apply`。更新自己的代码或 Python 环境前先停止自己的服务，保留自定义路径，按目标版本安装依赖并重新启动；涉及原数据时仍遵守单一写入者和迁移兼容要求。需要自动备份、迁移、切换的版本升级时，使用独立实例布局及上文的版本更新流程。

## apply 与 status

`apply` 只接收计划，不另接受目标实例或发布包覆盖参数。计划绑定原部署配置的绝对路径、包哈希、
实例真实目录、当前发布、配置文件状态和数据库版本；schema 1 的旧计划需要重新生成。
业务行写入不使计划失效，配置或凭据变化会要求重新 plan。

部署配置示例（端口由各实例决定）：

```toml
[instances.production]
root = "/data/projects/agentluo-production"
service = "agentluo.service"
service_scope = "system" # 也支持 user；须使用对应的 systemd 用户管理器
health_url = "http://127.0.0.1:15673/admin/api/health"
admin_url = "http://127.0.0.1:15673/admin"
is_debug = false
startup_timeout_seconds = 180
# 目标资产版本不存在时，可从已完整校验的本机目录准备；不自动下载模型。
# asset_source = "/data/model-baseline"
```

执行前，实例必须已采用 `releases/`、`current`、`config/`、`data/`、`.runtime/` 布局，
并将服务配置为 [managed systemd 模板](startup/agentluo-managed.service.example)。
其中 `WorkingDirectory` 和启动器绑定本实例 `current`，`EnvironmentFile` 绑定
`<root>/deployments/instance.env`。全新实例由上文首次部署命令创建；接管既有目录仍需先完成迁移，工具不会接管任意目录。
以服务所属用户运行部署。系统级服务的非 root 用户需要对该服务 `systemctl --no-ask-password stop/start`
的非交互 sudo 权限；工具在停服前检查。默认检查同用户进程的 `/proc` 文件描述符以排除其他写入者。
若主机存在不可读的系统会话进程，可以设置 `writer_check = "sudo-helper"`，由管理员将
`release/check_writers.py` 安装为 root 所有、普通用户不可写的 `/usr/local/libexec/agentluo-check-writers`，
并仅授权 `sudo -n /usr/local/libexec/agentluo-check-writers --root <实例绝对路径>` 及其 `--check-only` 形式。
检查器只读扫描所有用户进程，不读取业务内容；运行锁文件本身不作为业务写入证据。禁止直接 sudo 执行用户可改写的源码。

在线阶段只新建缺失的发布、资产和 Python 环境。新环境用 uv 按锁安装依赖，不绑定某个发布的 editable 源码；
Chromium 也安装在该环境的 browsers/ 中，不改写旧环境的浏览器缓存；系统库仍由环境安装阶段预先提供。
已验证环境只复用，不原地安装。启动配置预检使用临时配置、数据和运行目录，不初始化生产业务写入者。
停服后取得运行锁、排除残留写入进程，再备份配置与迁移涉及的 SQLite 数据库，迁移并校验 schema。
随后仅替换普通配置，写入本实例的模式和监听端口（取 health_url 的端口），保留凭据文件；
原子切换 current 后启动服务，验证实际进程版本、systemd、健康接口、运行时 running 和管理页面。

记录位于 `deployments/operations/<id>/`，备份位于 `deployments/backups/<id>/`。
只有验收通过才更新 `deployments/current.json`；`latest.json` 保存最近操作阶段与结果。
相同成功计划在服务健康且配置未变化时再次执行，返回 unchanged，不重复停服。
在线准备失败保持旧服务运行；停服后的失败尝试保持服务停止，保留记录与备份，不自动恢复旧数据库。
若停止失败，结果会明确提示人工检查实际进程状态。

中断或停服后的失败操作会阻断后续 apply。先根据 operation.json 检查数据库版本、备份和实际服务，
完成必要的人工恢复后，才可在对应 operation.json 标记 `recovery_acknowledged: true`，重新生成计划。
标记仅表示操作者已处理恢复，不会自动回滚、续跑或重放迁移。

`status` 不修改实例：分别返回 current 指向的发布、PID 实际运行发布、发布文件校验、服务状态、
HTTP/运行时健康、最近成功记录和最近操作。查询完成的退出码 0 不代表服务健康，自动化应读取 `healthy`。
无法访问 systemd 或接口时报告 unknown / 不健康，不将历史部署成功视为当前正常运行。

## 独立实例路径

启动前可设置 `AGENTLUO_CONFIG_DIR`、`AGENTLUO_RESOURCE_DIR`、`AGENTLUO_ASSET_DIR`、`AGENTLUO_DATA_DIR`、`AGENTLUO_RUNTIME_DIR`。默认分别为源码根目录的 `config`、`res`、`res`、`data`、`.runtime`；相对环境变量值以源码根目录为基准，不以调用终端目录为基准。

`res/tts` 和 `res/song_learner` 解析到资产目录，其余 `res` 路径解析到发布资源目录。实例配置中的相对路径保留原文，仅在加载时解析为绝对路径；显式绝对路径不改写。路径字段不能通过 `data/../` 等方式逃离所属根目录。自定义绝对路径需要操作者自行保证隔离。

Python 入口在 `.runtime` 中运行，以容纳第三方临时文件；管理页面和模型仍通过明确的路径读取。日志写入 `.runtime/logs`，学歌子进程写入 `.runtime/song_learner`。密钥、管理员认证和配置备份留在所选配置目录。并行运行的实例必须使用独立的配置、数据、运行目录；模型资源可在满足读取和第三方库校验条件时共享。开发代码接替已停止的测试服务运行时，可显式复用其配置、数据和运行锁目录；操作示例和自动部署边界见[外部路径与链接部署](#外部路径与链接部署)。

## 版本化资源

`release/resources.lock.json` 列出运行所需的小资源（Prompt、当前人设、预制语音、管理页面和源码内算法数据），记录路径、大小与 SHA-256。新增或修改这些资源时，必须同时审查并更新清单。预制语音来自现有生产使用的清单及音频，不包含账号数据。

学歌分段 Prompt 位于 `res/agent/prompts/song_segmentation_prompt.json`，可通过 `world.auto_song_learner.prompt_file` 指定；自动流水线显式将该文件传给子进程。这份 Prompt 随代码资源发布。

`release/assets.lock.json` 记录现有模型资产基线 `production-baseline-20261110`，包含模型、词典、模型配套配置与参考音频，不包含压缩安装包、QQ 凭据、歌曲库或用户数据。这个文件不会下载资产，也不把模型提交进 Git。发布包可引用该资产版本。

```bash
python scripts/deploy/release/check_resources.py
python scripts/deploy/release/check_resources.py --assets-root /path/to/assets
```

缺文件、大小或哈希不符时检查失败。第三方模型库可能另有首次初始化缓存行为，本次校验不等于已完成所有 GPU 工作负载的只读挂载验证。资产应先离线准备完整，再进行实际推理验收。

## 启动与预检约定

启动入口先加载所选配置目录中的 `secrets.local.env`，再解析配置。源码环境默认使用 `.venv/bin/python`，可通过 `AGENTLUO_PYTHON` 指定其他解释器；版本化部署由实例环境文件指定解释器。启动器的环境文件加载规则见[外部路径与链接部署](#外部路径与链接部署)。

安装器与启动器使用同一运行目录的 `server.lock`；更新 Python 环境前停止使用该环境的服务。`--check-startup` 只检查配置解析、监听模式和端口，不启动 HTTP、数据库或模型，不替代资源校验和实际推理验收。

部署计划还核对发布文件与资产的大小和 SHA-256、Python 与锁定依赖、PyTorch、依赖一致性及 `environment.json`。缺少环境时准备新环境，不移动旧虚拟环境。缺少模型来源或文件损坏时阻断；预检退出码 2 表示参数/输出错误，3 表示阻断。发布配置的凭据字段须使用 `$ENV_NAME` 引用；内联凭据或更新后数据库路径变化须先处理。停服前还会复核备份容量、服务权限、计划有效性和实例锁。

## 数据库版本与迁移

主库与歌曲知识库分别使用 SQLite `PRAGMA user_version`，当前目标均为 1，0 表示历史未标记库。
`src/utils/database_schema.json` 保存版本 1 所需的表、列与类型；启动和 plan 都检查版本，
版本匹配时还核验这些结构并执行 SQLite quick_check。数据库结构变更时必须维护契约并提供对应迁移。

新库初始化成功后标记版本 1；历史库沿用已有迁移逻辑，迁移前通过 SQLite backup API 留下一致性备份，
验证结构后才标记版本。备份权限为 0600，保留在原数据库旁的 `.schema-0-backup-*` 文件，不自动清理。
未知或更高版本、版本 1 但结构损坏的库会在初始化写入前拒绝，不通过重建或清空数据库解决。

plan 从发布声明和实例实际版本生成迁移清单，不执行迁移；数据库缺失也会阻断，避免误用空库。
当前提供 0→1 的离线迁移入口，必须停止所有写入进程后使用对应发布环境执行：

```bash
python scripts/deploy/release/migrate_database.py --kind main --database /absolute/data/database/luotianyi.db
python scripts/deploy/release/migrate_database.py --kind songs --database /absolute/data/knowledge/knowledge_db.db
```

plan 固定列出 schema、systemd、健康接口、运行时与管理页面验收。
当前不提供自动版本回退；迁移失败保留备份、保持停服，修补后前进。恢复备份必须先确认没有需要保留的新写入。
apply 按计划协调停服、备份与迁移；status 只读查询实际状态，执行要求见 [apply 与 status](#apply-与-status)。
