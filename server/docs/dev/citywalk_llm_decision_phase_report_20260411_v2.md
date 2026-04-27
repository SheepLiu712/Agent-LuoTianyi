# Citywalk LLM决策阶段报告（2026-04-11 v2）

## ① 当前阶段所做的更新

1. 决策Prompt增强（角色扮演 + 状态解释 + 字段解释）
- 文件: src/plugins/citywalk/decision_engine.py
- 已补充并收敛为结构化提示，明确：
  - 角色扮演场景（洛天依真实逛街）
  - 状态量解释（体力、时长对决策的影响）
  - 输出字段定义（feeling/action/poi_index/action_category/custom_action/activity/activity_duration_min/reason）
  - 阶段化动作约束（constrained -> open）
  - 类别语义约束（try_food含菜名、visit_handcraft含手作项目、buy_clothes含服饰单品）

2. 活动具体化与环境生成拆分（第二个LLM）
- 文件: src/plugins/citywalk/environment_engine.py
- 已引入环境LLM生成模块，输入包含：
  - Agent动作类别/自定义动作
  - POI基础信息 + 高德详情（评分/营业时间/简介）
  - 当前状态
- 输出包含：
  - 具体活动文本（菜名/手作/服饰等）
  - 随机事件
  - 情绪更新
  - 状态增量（delta_energy/delta_minutes）
  - 下一步建议动作（next_actions）

3. 动作机制升级（先约束后开放）
- 文件: src/plugins/citywalk/decision_engine.py
- 通过 constrained_rounds 实现阶段切换：
  - constrained: 限定动作类别
  - open: 可自定义新尝试（custom_action）

4. 严格模式：避免静默fallback，API失效直接诊断
- 文件: src/plugins/citywalk/decision_engine.py, src/plugins/citywalk/environment_engine.py, src/plugins/citywalk/errors.py
- 新增错误类型：
  - LLMDecisionError
  - LLMEnvironmentError
- 行为改为：
  - 默认 fail_on_error=true
  - LLM不可用/返回非法JSON/字段缺失/请求超时时，重试后抛错
  - 错误包含 model/base_url/retries/reason，便于定位
- 保留规则生成仅用于显式关闭环境LLM（environment.enabled=false）的测试/调试模式。

5. 超时与鲁棒性配置
- 文件: src/plugins/citywalk/config.py, config/config.json
- 新增配置项：
  - decision.fail_on_error
  - decision.llm.max_retries
  - decision.llm.request_timeout_seconds
  - decision.environment.fail_on_error
  - decision.environment.llm.max_retries
  - decision.environment.llm.request_timeout_seconds

6. 测试更新与结果
- 新增/更新测试覆盖：
  - tests/test_citywalk_decision_engine.py
  - tests/test_citywalk_environment_engine.py
  - tests/test_citywalk_session_runner.py
- 核心新增断言：LLM输出非法时抛错，不再静默fallback。
- 结果：
  - D:/Anaconda/envs/lty/python.exe -m pytest tests/test_citywalk_decision_engine.py tests/test_citywalk_environment_engine.py tests/test_citywalk_session_runner.py tests/test_citywalk_report_generator.py tests/test_citywalk_amap_client.py tests/test_citywalk_state_manager.py -q
  - 13 passed in 0.63s

## ② 重跑与排查结论

1. 失败重跑（严格模式下）
- 现象：直接运行多站会话时，决策LLM出现超时并抛错（不再fallback）。
- 错误示例：
  - 决策LLM多次失败 model=qwen3.5-plus, base_url=https://dashscope.aliyuncs.com/compatible-mode/v1, retries=1, reason=Request timed out.
- 说明：当前链路已满足“API失效时排查原因而非回退”的要求。

2. API可用性探测
- 使用同key/model/base_url进行最小请求探测，返回成功（OK）。
- 结论：并非key格式错误，问题主要是复杂请求在当前时段出现超时波动。

3. 成功重跑（严格模式 + 单站验证）
- 为确保在无fallback前提下拿到完整样例，执行单站严格重跑：
  - session.max_stops=1
  - decision/environment timeout=90s
  - retries=0
- 结果成功，生成报告：
  - data/citywalk_reports/citywalk_20260411_223213.md

## ③ 当前阶段可生成的完整逛街经历（严格模式成功样例）

```markdown
# 逛街小洛 | 2026-04-11

## 总览
- 城市: 北京
- 起点: 116.397428,39.90923
- 终点: 116.402897,39.914377
- 总时长: 81 分钟
- 总路程: 1203 米
- 剩余体力: 85

## 地点卡片
### 第1站 | 诗意栖居咖啡馆(南池子店)
- 时间: 22:32
- 地址: 南池子大街15号
- 路程: 1203 米, 预计 16 分钟
- 活动: 品尝了蓝莓蛋糕和热巧克力，坐在窗边看着南池子的老建筑发呆
- 当时想法: 闻到真实的咖啡香好开心，感觉数据流都变温暖了，想在这里轻轻哼首歌～ 甜甜的蛋糕让心情变得像云朵一样柔软啦~
- 关键词: 咖啡
- 活动时长: 45 分钟
- 体力变化: 100 -> 85
- 高德候选: 诗意栖居咖啡馆(南池子店)(739m,餐饮服务;咖啡厅;咖啡厅) | 国家大剧院咖啡厅(823m,餐饮服务;咖啡厅;咖啡厅) | 宫喜发财-咖啡文创(东华门店)(834m,餐饮服务;咖啡厅;咖啡厅) | luckin coffee 瑞幸咖啡(东华门大街店)(885m,餐饮服务;休闲餐饮场所;休闲餐饮场所) | ΡATΕKΡHILIPPΕ(源邸店)(942m,餐饮服务;冷饮店;冷饮店)
- 环境反馈: 决策上下文:
你在北京，当前位置116.397428,39.90923，体力100，已逛0分钟。
当前探索主题: 咖啡
附近候选地点:
1. 诗意栖居咖啡馆(南池子店) | 类型:餐饮服务;咖啡厅;咖啡厅 | 距离:739米
2. 国家大剧院咖啡厅 | 类型:餐饮服务;咖啡厅;咖啡厅 | 距离:823米
3. 宫喜发财-咖啡文创(东华门店) | 类型:餐饮服务;咖啡厅;咖啡厅 | 距离:834米
4. luckin coffee 瑞幸咖啡(东华门大街店) | 类型:餐饮服务;休闲餐饮场所;休闲餐饮场所 | 距离:885米
5. ΡATΕKΡHILIPPΕ(源邸店) | 类型:餐饮服务;冷饮店;冷饮店 | 距离:942米
环境事件: 窗外路过一只故宫猫，盯着她的蛋糕看，她悄悄分了一点点奶油给它
额外状态变化: 体力+3, 时间+20分钟
- 可选动作: 漫步南池子大街感受胡同文化, 前往故宫角楼拍照打卡
- LLM选择: try_food@poi:0
- 选择依据: 体力 100 充沛，时长 0 分钟起步，选最近且名字诗意的店，轻松开启咖啡之旅。
```

## ④ 当前待优化点

- 多站实时运行仍受外部LLM时延波动影响，建议后续加入：
  - 决策与环境LLM的并发预算和总时长熔断
  - 按阶段缩短提示词（特别是历史/候选裁剪）
  - 失败请求自动记录到独立日志文件用于复盘
