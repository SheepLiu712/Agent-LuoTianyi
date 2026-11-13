# Linux 新实例首次部署

状态：实现草案，待非作者审查。需求来自首次使用者需要可直接执行的安装步骤，而不必理解发布目录、资源路径和 systemd 模板。

## 用户故事

1. 作为不了解项目部署结构的开发者，我希望指定安装位置即可创建所需目录和配置，以便开始安装。
2. 作为首次安装者，我希望指定维护者提供的模型目录即可完成检查、复制和权限配置，以便无需寻找 NLTK 等内部目录。
3. 作为首次安装者，我希望执行一次部署命令安装环境并连接资源路径，再执行一次命令启动后台服务，以便无需手写启动环境文件和 systemd 单元。

## 验收标准

1. 对空目录执行 init_instance.sh，创建独立的配置、数据、运行、资产、环境和发布目录，生成 JWT 密钥及部署映射。非空目录拒绝初始化，不覆盖原文件。
2. 对模型目录执行 assets，按指定提交校验文件、大小和 SHA-256；匹配后复制到实例并移除组/其他账号写权限，源文件不变。缺失、损坏或符号链接导致失败，不发布不完整资产。
3. init_instance.sh 和 assets 完成后执行 install_instance.sh，从指定提交生成发布、准备依赖、执行启动配置预检，生成普通配置、instance.env 和 current。已有数据、普通配置或 current 拒绝首次安装；环境准备失败时不切换 current、不写普通配置。
4. install_instance.sh 完成后执行 systemd，生成绑定当前账号、current 和 instance.env 的服务单元，验证后通过 sudo 安装、启用并启动。同名但内容不同或来自其他位置的单元拒绝覆盖。
5. 文件就绪、进程启动和业务健康分别报告；数据库由正常启动流程初始化。用户通过管理页面、status 和日志确认结果。
6. 原 build / plan / apply / status 升级契约保持，plan 仍阻断未经接管的旧目录，不用首次安装绕过旧库迁移和备份。

## 模块与架构

### 模块划分

- `server/scripts/deploy/init_instance.sh`、`install_instance.sh` 提供初始化与首次安装入口，调用共用的 `release/bootstrap.py` 实现。`release/cli.py` 仅注册资产、systemd 和版本管理命令，不再注册 init、install。
- 复用 `prepare_release.py` 的发布、资产、环境准备和启动预检，以及 `offline_steps.switch` 的配置、环境文件和 current 写入。
- 业务运行时继续负责新数据库初始化，不新增手写 SQL 建库流程。

调用顺序：init_instance.sh → 填写 API 密钥 → assets → install_instance.sh → systemd → 管理页面和客户端验收。

### 接口规范

所有命令从仓库以普通服务账号执行；仅安装系统服务时调用 sudo。

| 命令 | 必需参数 | 可选参数 | 结果 |
| --- | --- | --- | --- |
| init_instance.sh | `--root` | `--name 后缀`、`--port 15673` | 安装目录及密钥文件路径 |
| assets | `--root`、`--source` | `--ref HEAD` | 实例资产位置 |
| install_instance.sh | `--root` | `--ref HEAD` | 发布 ID 与管理页面地址，尚未启动 |
| systemd | `--root` | 无 | 服务名、管理页面与日志命令 |

省略 `--name` 时服务名为 `agentluo.service`，实例名为 `production`；显式 `--name test` 时服务名为 `agentluo-test.service`，实例名为 `test`。`--name` 指定后缀，不是完整重命名。已有实例不自动改名。

安装位置为不含符号链接的绝对路径，支持字母、数字、点、斜杠、横线和下划线。新目录权限 0700，凭据与记录 0600。assets 与 install_instance.sh 选择匹配版本。供应商 API 密钥由用户填写，JWT 密钥自动生成且不打印。

## 备注

### 关键技术选型

使用 Python 标准库编排，沿用 Git 提交构建、uv 锁定环境、managed systemd 模板及资产清单。测试使用真实临时文件和 Git 仓库，替代 GPU 依赖下载与系统服务操作边界。

### 非目标

不接管旧实例、不迁移用户数据、不安装 NVIDIA 驱动、不自动下载模型，不把进程启动视为完整推理验收。实际 GPU、模型调用和主机服务验收需在部署环境执行。

### 未来目标

无本次承诺之外的扩展。
