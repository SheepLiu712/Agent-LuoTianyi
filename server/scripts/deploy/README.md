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

部署配置文件例子如下：
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

`assets` 从指定 Git 提交的资产清单核验源文件，复制到实例后移除组和其他账号写权限，不修改源目录；符号链接和损坏文件被拒绝。`assets` 与 `install_instance.sh` 都默认 `--ref HEAD`，指定版本时需使用同一 ref。

`install_instance.sh` 为首次安装入口：构建发布包，复用发布准备、依赖安装和启动预检，再生成普通配置、`instance.env` 与 `current`。它不要求已有数据库和 systemd 单元，不启动服务，也不宣称业务健康。已有 `current`、普通配置或数据会阻断，不能用于接管旧实例或升级；环境准备失败时不会切换 `current`。依赖下载中断留下的环境目录需先检查，现有环境校验不会原地修补损坏依赖。

`systemd` 生成并验证 managed 单元，以 sudo 安装、重载 systemd、启用并启动服务。同名但内容或位置不同的单元会被拒绝，不会覆盖其他服务。数据库由正常服务初始化路径创建；启动后通过管理页面和 `status` 确认业务运行时健康。

## 版本更新

本节适用于已按独立实例方式部署并由 systemd 管理的服务。更新沿用原安装目录、用户数据和密钥，不再执行 `init_instance.sh`、`install_instance.sh` 或重新创建服务。

使用外部配置/数据或自定义环境文件的实例，先阅读[外部路径与链接部署](#外部路径与链接部署)。

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

**3. 执行更新。** 此步骤会停服。以服务所属账号运行；系统级服务需预先配置下文所述的非交互 sudo 启停权限，首次安装时交互输入过 sudo 密码不代表该权限已配置。

```bash
python3 scripts/deploy/deploy.py apply --plan "$PLAN_FILE" --json
```

**4. 确认结果**
```bash
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
| 直接使用测试服务原有配置和数据 | `AGENTLUO_CONFIG_DIR`、`AGENTLUO_DATA_DIR` 指向原目录 | 先停止原服务及其他写入者，再运行自己的代码；使用同一运行锁目录 |

直接引用配置和数据会写入原目录，包括管理配置、凭据、业务记录和可能的数据库迁移，并不是只读浏览。两个服务不能同时写同一套数据；同一主机使用相同 `AGENTLUO_RUNTIME_DIR` 并通过统一启动器启动，可共用 `server.lock` 防止误启动。跨主机或其他维护工具的写入者仍须人工停止。

> 注意：模型目录至少要允许运行账号读取文件、进入目录。NLTK 等第三方库还会检查所有权和写权限；不能通过开放组/其他账号写权限来解决加载失败。若共享账号条件不满足库的安全要求，应使用当前账号持有的、通过清单校验的资产副本。模型库可能产生缓存，是否可完全只读挂载须经过实际推理验证。

### 前台运行

先按[源码环境安装步骤](../../README.md#linux-源码环境)在自己的仓库创建 `.venv`；在导出下面的共享路径之前完成安装。示例假定仓库位于 `$HOME/Agent-LuoTianyi/server`，测试实例位于 `/srv/agentluo-test`。请换成实际位置和资产版本，并先停止使用原配置及数据的测试服务。

创建一个`instance.env`文件，指定需要修改的路径：
```
AGENTLUO_CONFIG_DIR="/path/to/your/config"
AGENTLUO_DATA_DIR="/path/to/your/data"
AGENTLUO_RUNTIME_DIR="/path/to/your/runtime"
AGENTLUO_ASSET_DIR="/path/to/your/assets"
AGENTLUO_RESOURCE_DIR="/path/to/your/resources"
AGENTLUO_PYTHON="path/to/your/python"
```

然后在启动之前配置一个实例文件路径的环境变量再运行：
```bash
cd "$HOME/Agent-LuoTianyi/server"
AGENTLUO_INSTANCE_ENV="path/to/your/instance.env"
bash scripts/deploy/startup/start_linux.sh --check-startup
bash scripts/deploy/startup/start_linux.sh
```

其中，`config`指配置文件，`data`指数据文件，`runtime`指运行时文件（日志等），`assets`指模型资源，`resources`指人设、Prompt、管理页面等随代码发布的小资源。

注意：
1. 当需要复用测试实例的数据时，建议同时复用`runtime`，使得`server.lock`也被复用，避免误启动。
2. 监听端口取共享配置中的 `is_debug` 与 `server.debug_port/production_port`；不要为改变自己服务的端口而误改仍供他人使用的共享配置。
3. `--check-startup` 仅检查启动配置，不代表模型推理通过。

#### 小技巧1：不创建`instance.env`
直接在终端设置环境变量也是可行的：
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

#### 小技巧2：通过软链接共用模型
若希望通过 home 下的链接访问模型，可将上述 `AGENTLUO_ASSET_DIR` 改为以下链接位置，其他设置不变：

```bash
ln -s /srv/agentluo-test/assets/production-baseline-20261110 "$HOME/agentluo-shared-models"
export AGENTLUO_ASSET_DIR="$HOME/agentluo-shared-models"
```

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

## 版本化资源

`release/resources.lock.json` 列出运行所需的小资源（Prompt、当前人设、预制语音、管理页面和源码内算法数据），记录路径、大小与 SHA-256。新增或修改这些资源时，必须同时审查并更新清单。预制语音来自现有生产使用的清单及音频，不包含账号数据。

学歌分段 Prompt 位于 `res/agent/prompts/song_segmentation_prompt.json`，可通过 `world.auto_song_learner.prompt_file` 指定；自动流水线显式将该文件传给子进程。这份 Prompt 随代码资源发布。

`release/assets.lock.json` 记录现有模型资产基线 `production-baseline-20261110`，包含模型、词典、模型配套配置与参考音频，不包含压缩安装包、QQ 凭据、歌曲库或用户数据。这个文件不会下载资产，也不把模型提交进 Git。发布包可引用该资产版本。

```bash
python scripts/deploy/release/check_resources.py
python scripts/deploy/release/check_resources.py --assets-root /path/to/assets
```

缺文件、大小或哈希不符时检查失败。第三方模型库可能另有首次初始化缓存行为，本次校验不等于已完成所有 GPU 工作负载的只读挂载验证。资产应先离线准备完整，再进行实际推理验收。

### 数据库版本与迁移

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
