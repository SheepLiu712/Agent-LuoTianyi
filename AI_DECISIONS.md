# AI 决策记录

## 2026-11-17 #402：由当前页面显式拥有 Qt 默认提交按钮

**待定问题**：登录输入框的 Return/Enter 应触发登录，而非低频入口；还需决定低频按钮获得焦点时以及切换注册页后的默认动作归属。

**背景约束**：维护者已授权非人在回路，在固定 `ee718b21536e410ce5e4073b068f03b9bfcd68dc` 基线上仅修改登录对话框、其测试和本记录。保留 Esc 防误退出、显式关闭、鼠标与焦点按钮 Space、登录及注册原校验，不混入 #376 异步网络或未合并 #359 协议。原有 17 个测试不得删除或弱化。实现后须经 Oracle gate 才能提交，不推送或写 GitHub。

**调研参考**：通过 Context7 核对 Qt 官方 Qt for Python 文档，采用框架自己的默认按钮机制，不另造键盘分发逻辑。

- [QPushButton default / autoDefault](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QPushButton.html)：默认按钮处理 Return/Enter；聚焦的 auto-default 按钮可以抢占默认按钮；一个对话框只有一个默认按钮；焦点按钮仍可用 Space 激活。
- [QTabWidget currentChanged](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QTabWidget.html)：页面索引改变发出通知，可在所有按钮完成父子装配后初始化并随切页更新默认按钮。
- [QSignalSpy](https://doc.qt.io/qtforpython-6/PySide6/QtTest/QSignalSpy.html) 与 [QTest](https://doc.qt.io/qtforpython-6/PySide6/QtTest/QTest.html)：真实发送按键/点击，观测 clicked、accepted、finished，而非把 isDefault/autoDefault 内部属性当验收。
- [Issue #402](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/402)：本轮复核为 open、bug / should be solved，正文的输入框误开重置与离屏复现均落在本修复范围；无评论。UI/UX 技能的初次检索只得到通用提交反馈与网页键盘导航，未据此扩展 UI；具体桌面策略以 Qt 官方语义为准。

**候选方案**
1. **原生显式默认策略**：所有顶层表单按钮关闭 autoDefault；初始化与 currentChanged 时将当前页主提交按钮设为 default、另一页取消 default。低频按钮保留鼠标与 Space，不再因焦点改变 Return/Enter 的主动作。
2. **只设登录按钮 default**：代码最少，但不处理聚焦 auto-default 的抢占，也不处理注册页、隐藏页与历史默认状态。
3. **硬拦 Enter 或逐输入框接 returnPressed**：可直接调用提交，但硬拦全部 Enter 会误走登录；逐框连接会新增重复入口，并可能与 QDialog 原生默认处理叠加，需要额外处理焦点、注册及子窗口边界。

**选择**：方案 1。登录页 Return/Enter 统一由登录主提交处理；注册页由注册主提交处理。次要按钮的有焦点激活保留 Space 与鼠标。

**选择理由**：只增加 11 行运行代码，使用 Qt 原生行为、无新依赖、无认证/数据改动。需要在布局装配完成后初始化，因为无 QDialog 父级时的 setDefault 不足以建立对话框级默认。显式切页管理配合关闭 autoDefault，也避免主按钮先获得焦点时残留的隐藏页默认状态。

**未选原因**
- 方案 2：真实 QTest 已证实，仅设登录 default 后仍有 4 个聚焦低频按钮场景误激活；加入按页 default、但主按钮仍保留 autoDefault 时，有 16 个“主按钮焦点历史→注册成功返回登录”场景在登录输入框按键未激活登录。不是仅凭内部属性推测。
- 方案 3：超出本次小范围默认策略；绕过原生提交路径易破坏注册、空表单校验和子对话框，且引入不必要的分发分支。不存在为本缺陷拦截全部 Enter 的需要。

**验证方式**：在 `client` 目录使用指定解释器执行：

```powershell
& 'C:\Users\Administrator\.conda\envs\agent\python.exe' -c 'import os; os.environ["QT_QPA_PLATFORM"] = "offscreen"; import pytest; raise SystemExit(pytest.main(["tests/test_login_dialog.py", "-q", "--tb=short", "-p", "no:cacheprovider"]))'
```

本轮实际环境：Python 3.10.21、PySide6 / Qt 6.11.0、pytest 9.0.3；解释器为 `C:\Users\Administrator\.conda\envs\agent\python.exe`，实际导入源码为当前 `issue-402` 工作树的 `client/src/gui/login_dialog.py`。CI 固定 PySide6 6.9.2，未安装/切换共享依赖，本轮结果不冒充该版本或远端 CI 证据。

| 阶段 | 真实结果 | 观测依据 |
| --- | --- | --- |
| 改动前既有基线 | 17 passed | 原 Esc、关闭、登录、注册和子窗口测试原样运行 |
| 输入框 Return/Enter 红灯 | 4 failed, 17 passed | 用户名/密码 × 两键：reset clicked=1，login clicked=0 |
| 完成装配后显式登录 default | 21 passed | 原 17 + 输入框 4 个场景 |
| 聚焦低频按钮红灯 | 4 failed, 21 passed | reset/server × 两键：次要 clicked=1 |
| 低频按钮关闭 autoDefault | 25 passed | 聚焦次要按钮的 Enter 改由登录处理 |
| 注册/切页红灯 | 16 failed, 25 passed | 4 个注册框 × 两键 × 两条切页路径，注册主提交未激活 |
| 增加按页 default 管理 | 41 passed | 注册正确提交，成功回登录后仍能键盘登录 |
| 空表单与显式入口安全网 | 61 passed | 实际 QMessageBox 文案；鼠标/Space 打开正确子窗口，返回后仍能键盘登录 |
| 主按钮焦点历史红灯 | 16 failed, 61 passed | 先聚焦主按钮再切页/提交，返回登录后主动作缺失 |
| 所有顶层按钮关闭 autoDefault | 77 passed | 旧 17 原保证全部保留；新增 60 个参数化场景全部通过 |

运行代码不拦截 Return/Enter，不修改原 Esc 处理；测试通过真实事件和信号观察动作及对话框结果。网络与凭据仅在已有注入边界隔离，不调用真实账号服务。新增测试通过 black 26.5.1 / ruff 0.14.10 的定向检查；运行文件原有 QHBoxLayout 未使用导入 F401 在 HEAD 与当前各 1 项，未混入无关清理。全量离线 CI 由独立 verifier 统一调度，打包版、人工窗口/真实服务登录、PySide6 6.9.2 尚未验证。

**风险与回滚**：低频按钮不再以 Return/Enter 显式激活，使用 Space 或鼠标；这是为稳定主动作做出的有意选择。关闭 autoDefault 可能改变平台样式预留的默认按钮边框空间，离屏测试不证明打包版视觉。若交互不符预期，可独立回退本原子修改（当前页 default 管理、四个 autoDefault 设置及对应新增测试）；无数据迁移、配置或服务端变更。Oracle gate 前保留未提交 diff，不自行 merge/rebase/push。
