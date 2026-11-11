# 运行资源迁移

新环境的歌曲目录为 `data/singing/<角色>`，知识库为 `data/knowledge`。旧环境仍可使用原配置中的显式路径；不要直接用仓库配置覆盖实例配置。

迁移前停止全部服务、手动启动进程和数据维护工具。使用原部署目录执行：

```bash
python scripts/deploy/release/migrate_resource_layout.py --server-root /path/to/server
python scripts/deploy/release/migrate_resource_layout.py --server-root /path/to/server --apply --offline
```

工具复制歌曲与知识库，原文件不删除；在所有复制成功后原子替换配置，并保留 `config.before-resource-layout.json`。已有目标或备份会导致拒绝执行。锁只覆盖遵循现有启动约定的进程，`--offline` 不是自动停服。复制数据库必须在所有写入者停止后执行。

旧 QQ 凭据仅在新路径不存在时复制到 `config/qq_music_credential.json`，不覆盖现有凭据。外部绝对路径和自定义路径不改写，需要单独迁移。失败后的清理仅删除本次创建的目标。迁移后若已经启动并产生新数据，不能仅恢复旧配置作为数据回滚。

学歌流水线使用 `.runtime/song_learner` 作为工作目录，输出歌曲仍按配置写入歌曲库。可以通过 `world.auto_song_learner.work_dir` 指定独立目录。

## 独立实例路径

启动前可设置 `AGENTLUO_CONFIG_DIR`、`AGENTLUO_RESOURCE_DIR`、`AGENTLUO_ASSET_DIR`、`AGENTLUO_DATA_DIR`、`AGENTLUO_RUNTIME_DIR`。默认分别为源码根目录的 `config`、`res`、`res`、`data`、`.runtime`；相对环境变量值以源码根目录为基准，不以调用终端目录为基准。

`res/tts` 和 `res/song_learner` 解析到资产目录，其余 `res` 路径解析到发布资源目录。实例配置中的相对路径保留原文，仅在加载时解析为绝对路径；显式绝对路径不改写。路径字段不能通过 `data/../` 等方式逃离所属根目录。自定义绝对路径需要操作者自行保证隔离。

Python 入口在 `.runtime` 中运行，以容纳第三方临时文件；管理页面和模型仍通过明确的路径读取。日志写入 `.runtime/logs`，学歌子进程写入 `.runtime/song_learner`。密钥、管理员认证和配置备份留在所选配置目录。每个实例必须有独立的配置、数据、运行目录；只读资源可共享。

## 版本化资源

`release/resources.lock.json` 列出运行所需的小资源（Prompt、当前人设、预制语音、管理页面和源码内算法数据），记录路径、大小与 SHA-256。新增或修改这些资源时，必须同时审查并更新清单。预制语音来自现有生产使用的清单及音频，不包含账号数据。

学歌分段 Prompt 已移入 `res/agent/prompts/song_segmentation_prompt.json`，可通过 `world.auto_song_learner.prompt_file` 指定；自动流水线显式将该文件传给子进程。模型目录不再承担这份 Prompt 的发布。

`release/assets.lock.json` 记录现有模型资产基线 `production-baseline-20261110`，包含模型、词典、模型配套配置与参考音频，不包含压缩安装包、QQ 凭据、歌曲库或用户数据。这个文件不会下载资产，也不把模型提交进 Git。发布包可引用该资产版本。

```bash
python scripts/deploy/release/check_resources.py
python scripts/deploy/release/check_resources.py --assets-root /path/to/assets
```

缺文件、大小或哈希不符时检查失败。第三方模型库可能另有首次初始化缓存行为，本次校验不等于已完成所有 GPU 工作负载的只读挂载验证。资产应先离线准备完整，再进行实际推理验收。

## 统一启动

Linux 使用 `bash scripts/deploy/startup/start_linux.sh`，Windows 使用现有启动脚本，也可以直接执行 `python server_main.py`。所有入口由 `prepare_startup` 加载当前实例的 `secrets.local.env`，再解析配置；AdminShell 复用同一个 SecretStore，避免移除密钥时恢复已被删除的文件值。业务密钥仍由现有运行时校验负责，不额外硬编码特定模型供应商。

Linux 启动器的 `AGENTLUO_PYTHON` 可指定解释器，默认当前发布目录的 `.venv/bin/python`。安装器和启动器使用同一实例运行目录的 `server.lock`。不同实例的虚拟环境应独立维护；更新依赖前停止使用该环境的所有实例。systemd 示例中的 `@INSTANCE_ENV_FILE@` 替换为该实例的环境文件路径，格式参考 `startup/instance.env.example`；该文件不是 shell 脚本。

```bash
bash scripts/deploy/startup/start_linux.sh --check-startup
python server_main.py --check-startup
```

检查只验证配置解析及监听模式/端口，不启动 HTTP、数据库或模型；不会打印密钥值。它不替代 `check_resources.py`、业务配置校验或 GPU 推理测试。

`start_production.sh` 仅为旧运维命令提供兼容入口，不再使用本机独有的 `production_main.py`。首次切换前停止旧服务，按原实例配置核对密钥与锁位置；本系列改动不迁移线上文件，也不替换生产的 TTS 或通话行为补丁。

### 部署计划预检

`deploy.py --config /path/deploy.toml plan --package release.tar.gz --instance production --out plan.json --json`
只读取实例，计划文件必须在实例目录外且不能覆盖已有文件。返回 2 表示配置或输出错误，3 表示预检阻断。
计划列出发布目录、`assets/<asset-version>`、`environments/<environment-id>` 的复用或准备需求。
已有文件逐项检查大小与 SHA-256；环境检查解释器版本、锁定依赖、PyTorch 和 `pip check`，
并要求环境目录的 `environment.json` 与发布清单的 `environment` 一致。缺少环境时列为准备，禁止移动旧虚拟环境。
缺少模型资产来源、已有文件损坏、首次接管未声明迁移方案均阻断。
build 从指定提交的 `config/config.json.template` 生成发布包的 `config/config.json`，普通配置随版本覆盖。
仅替换实例的 `config.json` 文件，不能替换整个 config 目录；`secrets.local.env`、`admin_auth.json`、
`admin_setup_token.txt`、第三方凭据与 Cookie 保持独立。发布模板的凭据字段必须使用 `$ENV_NAME` 引用。
plan 不要求 config schema；若旧配置仍含内联凭据或覆盖后数据库路径改变，则阻断并要求先处理。
plan 检查发布空间，apply 在停服前再次检查备份容量、服务权限、计划有效性与实例写入锁。


### 数据库 schema 与迁移

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

首次接管的目录调整仍需明确处理。plan 固定列出 schema、systemd、健康接口、运行时与管理页面验收。
当前不提供自动版本回退；迁移失败保留备份、保持停服，修补后前进。恢复备份必须先确认没有需要保留的新写入。
apply 按计划协调停服、备份与迁移；status 只读查询实际状态，调用和首次接管要求见 [部署工具说明](README.md)。
