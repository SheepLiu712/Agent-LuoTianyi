# Citywalk Agent-Environment Interaction Loop 更新报告（2026-04-12）

## 目标与结论
本次已完成你提出的四大类改造目标：
1. 动作体系改造为 `act_here/search/goto/home`。
2. 环境改造为“同地多轮反馈 + 到达反馈 + act_here智能反馈 + 仅goto推进地点”。
3. 状态体系改造为“体力单调递减 + 饱腹度 + 心情 + LLM可读编码 + 区代码起点”。
4. 报告改造为“按地点分段 + 到达后环境反馈起始 + Agent动作/环境反馈交替完整记录”。

同时保持了严格模式：API调用失败会抛错诊断，不做静默降级。

## 一、动作体系改造
### 1) `act_here`
- 定义为非结构化动作文本（自由表达）。
- 在决策约束中要求：动作文本应包含“随便看看”或“吃xx”。
- 当前地点为餐饮场景时，会引导产出具体“吃xx”表达。

### 2) `search`
- 结构化动作，LLM只能选择有限类别。
- 类别映射到高德POI类型代码：
  - 餐厅 -> 050000
  - 咖啡甜品 -> 050300
  - 景点 -> 110000
  - 公园 -> 110101
  - 商场/购物 -> 060000
  - 文娱 -> 080000
- Runner执行 `search_nearby_pois` 后把结果写入“已搜索地点记忆”。

### 3) `goto`
- 只能前往“已搜索地点记忆”中的POI。
- 若目标不在记忆中，环境返回事件：
  - “你不知道怎么去这个地方：xxx。请先search后再goto。”
- 不推进到下一地点，保持当前状态继续循环。

### 4) `home`
- 表示结束本次逛街并回家。

## 二、环境交互循环改造
### 1) 到达新地点反馈
到达后会生成首条环境反馈（地点内日志的第一段）：
- 如果是餐饮：从POI `tag` 提取标签/特色菜信息。
- 如果有图片：从POI `photos.url` 取图，调用QWEN VLM描述。
  - 模型固定为 `qwen3-vl-plus`（可配置默认值）。
- 追加随机事件。

### 2) `act_here` 环境反馈
- `act_here` 触发环境LLM生成新的活动与随机事件。
- 返回状态变化（体力/时间/饱腹度）与下一步建议动作。
- 同一地点可重复多轮 `act_here`，不会强制换点。

### 3) 进度推进规则
- 只有 `goto` 才推进到新地点。
- `search` 只更新候选记忆，不变更地点。
- `act_here` 只在当前地点发生，不推进路线。

## 三、状态体系改造
### 1) 体力
- 体力保证单调递减：
  - `apply_adjustments` 中强制 `delta_energy` 只允许非正值生效。
  - 吃饭或环境反馈不会恢复体力。

### 2) 饱腹度
- 新增 `fullness`，默认初始值 70。
- 饱腹度范围扩展到 0~150（便于表达“过饱”）。
- 环境可对饱腹度做增减（例如吃东西增加）。

### 3) 心情
- 新增 `mood`，由体力与饱腹度派生更新。
- 低体力、过饿、过饱都会拉低心情。

### 4) LLM可读状态编码
- 新增状态编码输出，例如：
  - `体力：34/100(明显疲惫)；饱腹度：124/100(很撑)；心情：43/100(有点烦躁)；已逛时长：95分钟`
- 决策提示词已接入该编码。

## 四、起点控制改造（区代码）
- Runner支持：
  - 直接传 `start_location`，或
  - 传 `district_code`（城市区代码）。
- 传区代码时：
  - 调用高德 `/config/district` 获取区中心点。
  - 在中心附近加入随机扰动，生成起点经纬度。

## 五、报告结构改造
- 报告主标题下按“地点分段”输出。
- 每个地点包含：
  - 路径与状态变化摘要（体力/饱腹度/心情）。
  - 到达后交互日志（完整交替）：
    1. 环境反馈（到达描述）
    2. Agent动作
    3. 环境反馈
    4. Agent动作
    5. ...
  - 直到该地点离开。

## 六、配置与调用约束
### 1) 配置扩展
已加入：
- `session.initial_fullness`
- `session.initial_mood`
- `session.start_district_code`
- `search.max_action_rounds`
- `decision.environment.llm.vlm_model`（默认 `qwen3-vl-plus`）

### 2) API无静默fallback
- 决策与环境引擎默认严格模式，LLM失败抛出错误。
- 图片VLM描述失败同样抛错（便于定位问题）。

### 3) 环境变量替换来源
- 继续遵守：仅 `utils/helpers.py` 的 `load_config` 负责环境变量替换。
- citywalk配置读取仍通过 `load_citywalk_config -> load_config`。

## 七、验证结果
执行测试：
- `D:/Anaconda/envs/lty/python.exe -m pytest tests/test_citywalk_decision_engine.py tests/test_citywalk_environment_engine.py tests/test_citywalk_state_manager.py tests/test_citywalk_session_runner.py tests/test_citywalk_report_generator.py -q`

结果：
- `9 passed`

## 八、关键改动文件
- `src/plugins/citywalk/decision_engine.py`
- `src/plugins/citywalk/environment_engine.py`
- `src/plugins/citywalk/session_runner.py`
- `src/plugins/citywalk/state_manager.py`
- `src/plugins/citywalk/amap_client.py`
- `src/plugins/citywalk/types.py`
- `src/plugins/citywalk/report_generator.py`
- `src/plugins/citywalk/config.py`
- `scripts/citywalk/run_citywalk_session.py`
- `config/config.json`
