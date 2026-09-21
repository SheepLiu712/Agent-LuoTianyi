# Godot 0.1.3 登录与气泡

- 目标：白色QQ式登录页、账号历史与独立记住/自动登录、自适应文字及图片气泡，交付Windows x64 0.1.3。
- PRD：[Godot客户端](../需求说明（PRD）/Godot-Windows客户端.md)。
- 总体设计：[客户端总体设计](../../项目说明/项目架构与接口（spec）/Godot客户端总体设计.md)。
- interface：[0.1.3契约](../../项目说明/项目架构与接口（spec）/接口文档/client_godot/release-013.md)。
- 状态：进行中，仅本地提交。

## 已完成

### 2026-09-21 登录存储接口

- SPEC 79e0abb；Red 39fb04e实际因五个登录存储能力缺失而失败；Green为本记录提交。StorageService增加profile原子读写和受保护令牌存取/删除，Godot实现复用CredentialStore，磁盘查询不变。
- test_login_storage与原test_storage_service通过：新安装、原子写回、加密令牌、账号/服务器隔离、损坏文件不覆写、不可写路径及不可用基类均验证。JSON数字按值检查，不将引擎解析的浮点数字误判为字段丢失。
- 作者自审：平台API仅在存储实现类，未新增明文降级或修改服务端；原热重载DLL差异未纳入。
