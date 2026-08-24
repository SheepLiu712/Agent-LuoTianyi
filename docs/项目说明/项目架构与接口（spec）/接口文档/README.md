# Server 模块接口文档

本目录记录 Server 各顶层模块被其他模块调用的 interface。目录结构按照[开发守则](../../../开发进程文档/开发守则.md)中的目标架构组织，接口内容则以当前工作区代码为准。

## 阅读约定

- **当前 interface**：源码中已经存在，并且被其他顶层模块、`server_main.py` 或系统组装代码调用。
- **目标 interface**：开发守则已经确定方向，但源码尚未实现；文档必须明确标成“目标”，不能当作当前可调用方法。
- **内部实现**：仅在同一顶层模块内部使用，不在本文档中承诺稳定。
- interface 不只包括方法名，还包括调用前提、输入输出、副作用和失败方式。
- 本文档基于 2026-08-24 的当前工作区静态检查。接口变化时，修改代码的 PR 必须同步更新对应文档。

## 目标调用链

```text
外部事件
  -> Adapter
  -> stage
  -> agent_runtime.get_agent(character_id)
  -> Agent 的有限 interface
  -> Agent 内部使用 subconscious 和 capabilities
```

`SystemRuntime` 位于最外层，负责创建、连接和关闭这些模块。`domain` 提供共同的数据类型；`utils` 只提供无业务含义的通用工具。

## 模块索引

| 目标模块 | 接口文档 | 当前主要源码位置 |
| --- | --- | --- |
| `domain` | [领域对象](domain/README.md) | `server/src/domain` |
| `agent` | [Agent 表意识](agent/README.md) | `server/src/agent` |
| `subconscious` | [潜意识](subconscious/README.md) | `server/src/subconscious` |
| `capabilities` | [角色能力](capabilities/README.md) | `server/src/capabilities` |
| `agent_runtime` | [角色工厂与注册](agent_runtime/README.md) | `server/src/agent_runtime` |
| `stage` | [持续交互流程](stage/README.md) | 当前为 `server/src/chat_session` |
| Adapter | [外部协议适配](adapter/README.md) | 当前主要为 `server/src/system/user_interface` 和 `server/src/legacy` |
| `world` | [箱庭世界和周期任务](world/README.md) | `server/src/world` |
| `system` | [系统组装和基础设施](system/README.md) | `server/src/system` |
| `utils` | [通用工具](utils/README.md) | `server/src/utils` |
| `legacy` | [迁移兼容接口](legacy/README.md) | `server/src/legacy` |

守则明确约定暂不创建 `base`，因此本目录也不创建空的 `base` 接口文档。

`system` 的接口较多，另外拆分为：

- [数据库接口](system/database.md)
- [观测接口](system/observability.md)

## 当前实现与目标架构

当前代码还没有完全符合目标调用链。所有已确认差异集中记录在[当前实现与目标架构差异](当前实现与目标架构差异.md)中。阅读接口文档时应遵守以下原则：

1. 维护现有功能时，可以调用文档中标为“当前”的 interface。
2. 新功能不得继续扩大差异文件中列出的反向依赖和全局入口。
3. 迁移时先增加目标 interface 和测试，再逐个替换调用者，最后删除旧 interface。
4. 未实现的目标 interface 不能写进测试或业务代码后假定其已经存在。

## 每项 interface 的记录格式

每个模块文档用尽量少的条目回答：

- 谁在调用；
- 输入和输出；
- 调用后会发生什么；
- 失败时会怎样。

如果一个类的方法很多，文档只列出跨顶层模块使用的稳定入口；同模块内部的解析器、格式化器和私有辅助方法不作为对外承诺。
