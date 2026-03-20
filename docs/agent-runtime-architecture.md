<!-- AI GC START -->
# 闭环自主 Agent 架构设计

本文档用于把“类似 Claude Code / OpenClaw 的闭环自主 Agent”设计直接落到当前仓库的上下文中，作为后续实现 `Agent Runtime`、会话持久化、多步规划与工具执行闭环的基线说明。

## 一、目标

希望系统在接收到一个目标后，可以：

1. 理解用户目标，而不是只做单轮问答。
2. 结合当前知识库内容判断是否已有足够上下文。
3. 在知识不足时，选择合适的 MCP / Service API 能力补足上下文。
4. 进行多步规划、执行、观察、校验，而不是一次性输出结果。
5. 在完成任务后输出结果，并把关键执行产物沉淀回知识库。

对应的目标闭环如下：

```text
目标输入
  -> 检索知识
  -> 规划下一步
  -> 调工具执行
  -> 读取结果
  -> 判断是否完成
  -> 未完成则继续下一轮
  -> 完成后输出结果并沉淀记忆
```

## 二、当前仓库现状

当前仓库已经具备做 Agent 的主要基础设施：

- `app/services/knowledge_base.py`
  - 文本知识导入
  - 飞书文档 / 群聊 / 图片导入
  - 本地知识检索
- `app/services/llm.py`
  - OpenAI 兼容文本问答
  - 图像理解
- `app/services/service_api.py`
  - 对主服务 HTTP API 的统一封装
- `app/mcp_server.py`
  - 把主服务能力以 MCP tools 暴露给外部 Agent / MCP Client
- `app/services/mcp_scheduler.py`
  - 定时任务创建、执行与管理
- `app/services/bot.py`
  - 当前消息入口
  - 命令处理
  - 检索增强问答

也就是说，仓库已经具备：

- 知识层
- 工具层
- 模型层
- 调度层
- API 层

当前缺少的是：

> 一个把“目标 -> 规划 -> 工具执行 -> 校验 -> 记忆更新 -> 下一轮”串起来的 Agent Runtime。

## 三、建议新增的核心层

建议在当前仓库中新增 `app/agent/` 目录，作为自主执行编排层：

```text
app/agent/
  __init__.py
  runtime.py
  planner.py
  verifier.py
  memory.py
  tool_bridge.py
  policy.py
  session_store.py
  prompts.py
  types.py
  exceptions.py
```

各模块职责如下：

- `runtime.py`
  - Agent 主循环
  - 控制 step、状态流转、终止条件
- `planner.py`
  - 结合目标、知识、历史 observation 决定下一步动作
- `verifier.py`
  - 判断某一步是否成功
  - 判断目标是否完成
- `memory.py`
  - 管理 working memory
  - 检索知识
  - 写入 episode summary
- `tool_bridge.py`
  - 统一封装工具调用
  - 第一版建议走 `service_api.py`
- `policy.py`
  - 控制高风险工具是否允许自动执行
- `session_store.py`
  - 会话持久化
  - 步骤日志持久化
- `prompts.py`
  - 统一管理 planner / verifier 提示词
- `types.py`
  - Agent 内部数据结构定义
- `exceptions.py`
  - Agent 子系统专用异常

## 四、运行闭环设计

建议 Runtime 使用如下执行循环：

```text
创建 Session
  -> 读取 / 初始化 Working Memory
  -> 结合 goal 检索知识库
  -> Planner 选择下一步动作
  -> Tool Bridge 执行
  -> Verifier 判断结果
  -> 更新 Session / Step Logs / Working Memory
  -> 若未完成则继续下一轮
  -> 完成后输出 final answer
  -> 写入 episode summary
```

其中每轮只允许做一件事：

- 调一个工具
- 或直接结束
- 或等待用户补充信息

不建议第一版让模型一次性规划并执行完整流程，这会让失败恢复与重规划变得困难。

## 五、建议的数据结构

### 1. AgentSession

Agent 会话需要可持久化，建议至少包含：

- `id`
- `service_id`
- `goal`
- `status`
- `step_count`
- `max_steps`
- `context`
- `constraints`
- `policy_config`
- `current_plan`
- `working_memory`
- `final_answer`
- `failure_reason`
- `created_at`
- `updated_at`

### 2. AgentStepLog

每一轮执行都要留痕，建议记录：

- `session_id`
- `step_index`
- `plan_decision`
- `observation`
- `verification`
- `created_at`

### 3. Observation

工具调用后的结果统一标准化为 observation：

- `tool_name`
- `arguments`
- `success`
- `result`
- `error`
- `summary`

## 六、数据库设计建议

当前仓库的持久化风格集中在 `app/db.py`，因此建议继续沿用同一方式，在 `init_db()` 中新增：

### `agent_sessions`

用于保存当前 Agent 会话状态。

建议字段：

- `id`
- `service_id`
- `goal`
- `status`
- `step_count`
- `max_steps`
- `context_json`
- `constraints_json`
- `policy_config_json`
- `current_plan_json`
- `working_memory_json`
- `final_answer`
- `failure_reason`
- `created_at`
- `updated_at`

### `agent_step_logs`

用于保存每一轮执行日志。

建议字段：

- `id`
- `session_id`
- `step_index`
- `plan_decision_json`
- `observation_json`
- `verification_json`
- `created_at`

## 七、状态机设计

### 1. Session 状态

建议支持：

- `created`
- `running`
- `waiting_input`
- `completed`
- `failed`
- `cancelled`
- `paused`

### 2. 执行流转

```text
created
  -> running
  -> waiting_input
  -> completed
  -> failed
  -> cancelled
  -> paused
```

### 3. 终止条件

第一版必须显式限制：

- `max_steps`
- `timeout_seconds`
- `max_tool_calls`
- `max_same_action_retries`

防止 Agent 因空结果或错误重试而进入死循环。

## 八、Planner 设计

Planner 负责“当前这一轮下一步做什么”，而不是直接产生最终答案。

建议输入包括：

- 当前目标 `goal`
- 上下文 `context`
- 当前计划 `current_plan`
- Working Memory
- 最近若干条 Observation
- 检索到的知识片段
- 可用工具列表
- 当前约束与策略

建议输出严格 JSON，动作限定为：

- `tool_call`
- `finish`
- `ask_user`
- `wait`
- `fail`

第一版建议：

- 使用 `OpenAICompatibleLLM`
- 增加一个更通用的 `chat_completion_text(...)` 接口
- 让 planner 输出 JSON 字符串并解析

## 九、Verifier 设计

Verifier 是闭环的关键，避免系统“调了工具但并没有真的完成任务”。

第一版建议以规则校验为主：

- 工具是否调用成功
- 是否返回关键字段
- 是否真的产生所需副作用

例如：

- `import_feishu_chat` 成功并不代表目标完成
- `summarize_feishu_chat` 成功但还没发送，不算完成
- `send_feishu_message` 成功且用户目标包含“发送结果”，才可以判定完成

后续可补充基于 LLM 的语义校验。

## 十、Memory 设计

建议把记忆分为三层：

### 1. Working Memory

本次任务中间状态，例如：

- 最新导入的 chat source id
- 最新摘要文本
- 是否已经发消息
- 上一步工具结果

### 2. Long-term Memory

即当前已有知识库：

- 文档
- 群聊记录
- 图片分析
- 总结结果
- 任务产物

### 3. Episodic Memory

任务完成后把整次执行摘要写回知识库，例如：

- 用户目标
- 实际执行的步骤
- 结果与失败点

这样后续 Agent 可把历史任务经验也作为检索对象。

## 十一、Tool Bridge 设计

建议第一版 Tool Bridge 优先走 `app/services/service_api.py`，而不是在服务内部再引入一层 MCP client。

原因：

1. 当前 `service_api.py` 已经把主服务能力封装好了。
2. 内部 Runtime 走 HTTP API 能保持调用边界清晰。
3. 测试时更容易使用 fake client 做隔离。

第一版建议支持这些工具：

- `search_knowledge`
- `list_knowledge_sources`
- `import_feishu_chat`
- `import_feishu_document`
- `import_feishu_image`
- `ask_llm_question`
- `summarize_feishu_chat`
- `send_feishu_message`

后续如需统一外部 MCP Agent 与内部 Runtime，可把 Tool Bridge 抽象为双通道：

- Local API executor
- MCP executor

## 十二、策略与安全边界

建议给工具分风险等级：

### 读操作

- `search_knowledge`
- `list_knowledge_sources`
- `ask_llm_question`

### 写操作

- `import_feishu_chat`
- `import_feishu_document`
- `import_feishu_image`
- `import_text_knowledge`

### 有副作用操作

- `send_feishu_message`
- 定时任务创建 / 删除 / 恢复

建议第一版默认策略：

- 读操作：自动允许
- 写知识库：自动允许
- 发送消息：需要显式打开 `allow_send_feishu_message`
- 定时任务管理：默认禁止直接自动执行

## 十三、API 接入设计

建议在 `app/main.py` 增加以下接口：

- `POST /api/v1/services/{service_id}/agent/run`
- `GET /api/v1/services/{service_id}/agent/sessions/{session_id}`
- `GET /api/v1/services/{service_id}/agent/sessions/{session_id}/logs`
- `POST /api/v1/services/{service_id}/agent/sessions/{session_id}/resume`
- `POST /api/v1/services/{service_id}/agent/sessions/{session_id}/cancel`

第一版建议先做同步执行：

- 请求进入后直接运行若干 step
- 到达完成 / 失败 / 等待输入后返回

后续再演进到后台任务 / 异步 worker。

## 十四、与现有文件的映射关系

### 新增文件

```text
app/agent/
  __init__.py
  runtime.py
  planner.py
  verifier.py
  memory.py
  tool_bridge.py
  policy.py
  session_store.py
  prompts.py
  types.py
  exceptions.py
```

### 需要修改的现有文件

- `app/db.py`
  - 增加 `agent_sessions` / `agent_step_logs`
- `app/schemas.py`
  - 增加 Agent API request / response 模型
- `app/main.py`
  - 增加 Agent API 路由
- `app/services/llm.py`
  - 建议补一个通用 chat completion 文本接口
- `app/services/bot.py`
  - 第二阶段再接入 agent mode

## 十五、推荐实现顺序

建议按下面顺序落地：

1. `app/agent/types.py`
2. `app/agent/exceptions.py`
3. `app/db.py`
4. `app/agent/session_store.py`
5. `app/agent/tool_bridge.py`
6. `app/agent/memory.py`
7. `app/services/llm.py` 增强
8. `app/agent/planner.py`
9. `app/agent/verifier.py`
10. `app/agent/runtime.py`
11. `app/schemas.py`
12. `app/main.py`
13. 测试
14. 第二阶段再接 `app/services/bot.py`

## 十六、第一版 MVP 范围建议

为了尽快闭环，第一版建议只覆盖下面几类任务：

### 1. 知识增强问答

示例：

- “结合当前知识库，说明系统有哪些 MCP 能力”

### 2. 先补数据再回答

示例：

- “总结一下昨天项目群的风险”

### 3. 总结后执行动作

示例：

- “总结当前群的讨论结果，并发到项目群”

### 4. 文档导入与知识沉淀

示例：

- “抓取这篇文档并整理关键结论入库”

## 十七、测试建议

建议新增这些测试：

- `tests/test_agent_runtime.py`
- `tests/test_agent_api.py`
- `tests/test_agent_tool_bridge.py`
- `tests/test_agent_verifier.py`
- `tests/test_agent_resume.py`

优先覆盖：

- session 创建 / 更新 / 恢复
- planner 输出 `finish` / `tool_call`
- tool bridge 路由
- verifier 规则判断
- API 正常返回

## 十八、当前设计边界

这份设计稿是当前仓库上的第一版落地方案，边界如下：

1. 第一版优先单 Agent，而不是多 Agent 协同。
2. 第一版优先同步请求内闭环，而不是后台异步任务系统。
3. 第一版优先规则校验，再逐步引入语义 verifier。
4. 第一版优先使用现有 Service API 做工具桥，再考虑 MCP 双通道统一。
5. 第一版优先最小侵入，不直接重写现有 `bot.py`。

## 十九、结论

对于当前仓库，最合理的演进方式不是推翻已有知识库、MCP 和问答逻辑，而是在其上新增一层 `Agent Runtime`：

- 复用现有知识库
- 复用现有 Service API
- 复用现有 MCP tool 语义
- 补上会话状态、规划、验证和执行闭环

这样可以把当前项目从“带知识库和 MCP 的飞书机器人服务”升级为“支持目标驱动、自主规划和多步执行的闭环 Agent 服务”。
<!-- AI GC END -->
