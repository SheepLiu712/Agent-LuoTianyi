# 部署工具目录

| 位置 | 职责与入口 |
| --- | --- |
| `environment/` | 创建和安装 Python 环境。Linux 使用 `install_linux.sh` 与 uv 锁文件；Windows 使用 `install_windows.bat` 与可选 Conda 配置。 |
| `startup/` | 启动已有环境中的服务。包含 Linux / Windows 启动器、systemd 服务模板和实例环境变量示例。 |
| `release/` | 构建与检查版本。包含 build / plan / apply / status 实现、资源校验清单、数据库与资源目录迁移工具。 |
| `deploy.py` | 版本部署的统一 CLI 入口，保持原命令路径。 |
| `RESOURCE_LAYOUT.md` | 实例目录、资产、配置和数据库迁移约定。 |

从 `server/` 目录执行：

```bash
bash scripts/deploy/environment/install_linux.sh
bash scripts/deploy/startup/start_linux.sh
python scripts/deploy/deploy.py build --ref HEAD
python scripts/deploy/deploy.py --config /path/deploy.toml plan \
  --package /path/release.tar.gz --instance production --out /path/plan.json
python scripts/deploy/deploy.py apply --plan /path/plan.json --json
python scripts/deploy/deploy.py --config /path/deploy.toml status --instance production --json
python scripts/deploy/release/check_resources.py
```

安装器、启动器内部均以自身位置定位服务端根目录。Linux 依赖项目位于 `environment/`，
其本地服务端依赖相对路径为 `../../..`；修改目录时须同时调整 `pyproject.toml` 与 `uv.lock`。
数据库迁移须在停止全部写入者后进行，具体命令见 [资源布局约定](RESOURCE_LAYOUT.md)。


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
`<root>/deployments/instance.env`；首次接管和安装 systemd 单元仍需人工完成，工具不会接管任意目录。
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
