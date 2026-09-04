# 27: 保持 B 站事件同步为纯 world 事实维护

**What to build:** 在架构重构中保持 `bili_event_update:{character_id}` 的 cookie、抓取、图片/文本解析、EventStore upsert 和统计行为，同时证明它只维护 world 事实，不直接触发角色回复或调用 Agent。

**Blocked by:** 03: 冻结 WorldClock 调度与九类注册基线。

**Status:** ready-for-agent

**GitHub Issue:** [#86](https://github.com/SheepLiu712/Agent-LuoTianyi/issues/86)

## Decision rule

SPEC 第 4.1、6.7、8.6 的 B 站行优先。官方动态解析、事件字段和 provider fallback 未说明时参考当前 updater/parser/fetcher、配置和测试；抓取中的 VLM/LLM 是机械结构化，不因使用模型而移入 Agent。

## Scope

- 保持仅为已配置 UID 的角色注册，每 21600 秒且启动立即执行。
- 检查/刷新 cookie，拉取未处理官方动态；有图片且 VLM 可用时用 VLM，否则按当前 LLM/规则路径解析。
- 规范化 event type/source/recurrence/personal 后 add/upsert EventStore，返回 raw/parsed/updated 计数。
- 后续 event 到期才由 17 号主动提醒形成 ProactivePromptDue；本任务不直接唤起角色。

## Acceptance criteria

- [ ] 无新动态返回零计数且不重复 upsert；相同来源/revision 重跑幂等。
- [ ] 图片、VLM 不可用和文本 fallback 路径与当前行为一致。
- [ ] cookie 无效明确失败且不写错误事件；凭据不进入日志或领域对象。
- [ ] event 角色、个人性、复发和来源字段规范化一致，缓存/查询可见。
- [ ] 任务不调用 Agent/WorldStage、不生成角色输出；只有后续提醒链消费 EventStore。
- [ ] 一个角色失败不停止其它角色或后续 6 小时周期。

## Verification

- 补/迁移 world task 回归测试，Fake cookie、feed、VLM/LLM，使用隔离 EventStore。
- 覆盖无新内容、图片/文本解析、upsert、重复、无效 cookie、多角色隔离和异常周期。
- 运行 Bili updater、EventStore、WorldClock/WorldRuntime 和 proactive 回归；真实站点另列人工验证。

## Explicit exclusions

- 不改变官方 UID、抓取频率或事件提醒产品规则。
- 不把原始 HTML、图片连接或供应商事件交给 Agent。

## Handoff

一个纯 world 同步 PR；若只补保护测试，明确无产品行为修改。
