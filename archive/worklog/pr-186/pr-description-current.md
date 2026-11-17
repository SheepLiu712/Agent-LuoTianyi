# PR #186 描述（当前 head 修正稿）

> 供更新远端 PR 描述使用。当前 head 以推送后的提交为准；验证结果以对应提交上的实际运行记录为准。

## 目的

为桌面用户新增独立的 Godot 4.7.1 Windows x64 客户端，提供 Live2D 虚拟形象、WebSocket 聊天、流式 PCM 语音、SQLite 本地历史、动态社区、四域日志与打包体系。不修改服务端、旧 Python 客户端、CLI 或 App 的业务代码。

## 改动范围

- 新增 `client-godot/`：Godot 客户端源码、场景、测试、构建与打包脚本。
- 新增 `archive/worklog/pr-186/`：历次审查整改记录。
- 新增 `docs/服务端接口-*.md` 与 `docs/服务端接口文档.md`：客户端使用的服务端接口说明。
- 根 `.gitignore`：追加 godot-sqlite 预编译库白名单与本机 ETL 诊断产物忽略规则。
- `docs-godot/` 是作者本地个人笔记，已从 Git 索引移除并加入 `.gitignore`，不属于本 PR 交付内容。

## 版本

- `release.json`、`project.godot`、`export_presets.cfg` 与客户端文档统一为 `0.2.0.0`。
- 0.2.0.0 发布包尚未重新构建；发布前需执行 `scripts/build.ps1`。

## 验证

- `scripts/check.ps1`：通过；包含复杂度门禁与 `connectivity-probe`。
- `scripts/check_accounts.ps1`：通过；依赖边界 9/9。
- `scripts/check_network.ps1`：4/4。
- `scripts/check_features.ps1`：通过；慢用例使用独立超时，不降低断言。
- `test_dependency_boundaries.py`：9/9。
- `test_review_documentation.py`：5/5。
- `test_check_gate.py`：6/6。
- `test_build_prompt.py`：4/4。
- `test_complexity_check.py`：39 项，38 通过、1 跳过（环境无 PowerShell 7 专项）。

未覆盖：GPU/视觉、真实公网服务、Windows 10、系统 DPI、多屏、release EXE/PCK/ZIP 打包实验。相关结果不能从离线回归推断通过。

已知限制：本地历史 scope 仍由 server+username 生成。公开接口当前没有清空历史或同名注销重注册路径；若生产存在手工删号流程，需由服务端返回 `user_uuid` 后另行迁移 scope，不能只靠客户端猜测。
