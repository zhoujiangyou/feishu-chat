<!-- AI GC START -->
# MCP 集成指南

当前项目已经支持通过 MCP 暴露服务能力。

## 一、MCP 能暴露哪些能力

当前 MCP Server 已封装这些 tools：

- `service_health`
- `create_feishu_service`
- `get_feishu_service`
- `import_text_knowledge`
- `import_feishu_document`
- `import_feishu_chat`
- `import_feishu_image`
- `search_knowledge`
- `list_knowledge_sources`
- `send_feishu_message`
- `ask_llm_question`
- `analyze_image_with_llm`
- `summarize_feishu_chat`
- `list_supported_scheduled_actions`
- `create_interval_scheduled_task`
- `list_scheduled_tasks`
- `get_scheduled_task`
- `pause_scheduled_task`
- `resume_scheduled_task`
- `delete_scheduled_task`
- `run_scheduled_task_now`

也就是说，外部 AI Agent 或 MCP Client 可以通过 MCP 来：

1. 创建飞书机器人服务实例
2. 导入和检索知识库
3. 抓取飞书文档、群聊、图片
4. 主动向飞书群组或个人发送消息
5. 直接调用 OpenAI 兼容模型做文本问答和图像理解
6. 总结飞书群聊并按需回发结果
7. 在 MCP Server 内部创建和管理定时任务

## 二、运行方式

### 1. 先启动主服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 2. 再启动 MCP Server

默认以 stdio 方式运行：

```bash
python3 -m app.mcp_server
```

或者使用安装后的脚本：

```bash
feishu-chat-service-mcp
```

如果你的环境里这个命令不可见，通常是因为用户级脚本目录还没加到 `PATH`。这时直接使用：

```bash
python3 -m app.mcp_server
```

## 三、环境变量

### 主服务地址

MCP Server 会通过 HTTP 调用主服务，因此需要知道主服务地址：

```bash
export FEISHU_CHAT_SERVICE_BASE_URL=http://127.0.0.1:8000
```

可选超时配置：

```bash
export FEISHU_CHAT_SERVICE_TIMEOUT_SECONDS=60
```

### MCP 传输方式

默认：

```bash
export FEISHU_CHAT_MCP_TRANSPORT=stdio
```

也支持：

- `sse`
- `streamable-http`

如果你想把 MCP Server 作为网络服务启动：

```bash
export FEISHU_CHAT_MCP_TRANSPORT=streamable-http
export FEISHU_CHAT_MCP_HOST=0.0.0.0
export FEISHU_CHAT_MCP_PORT=9000
python3 -m app.mcp_server
```

此时 MCP 默认地址会是：

```text
http://127.0.0.1:9000/mcp
```

### 定时任务相关环境变量

```bash
export FEISHU_CHAT_MCP_TASK_DB_PATH=/app/data/mcp_tasks.db
export FEISHU_CHAT_MCP_SCHEDULER_POLL_SECONDS=5
```

说明：

- `FEISHU_CHAT_MCP_TASK_DB_PATH`：MCP 内部定时任务使用的 SQLite 文件
- `FEISHU_CHAT_MCP_SCHEDULER_POLL_SECONDS`：调度轮询间隔

## 四、Cursor / MCP Client 配置示例

如果是 stdio 模式，可以按类似方式配置：

```json
{
  "mcpServers": {
    "feishu-chat-service": {
      "command": "python3",
      "args": ["-m", "app.mcp_server"],
      "env": {
        "FEISHU_CHAT_SERVICE_BASE_URL": "http://127.0.0.1:8000",
        "FEISHU_CHAT_MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

## 五、典型使用场景

### 1. 让 Agent 创建飞书机器人服务

调用：

- `create_feishu_service`

### 2. 让 Agent 抓群聊历史到知识库

调用：

- `import_feishu_chat`

### 3. 让 Agent 搜索知识库

调用：

- `search_knowledge`

### 4. 让 Agent 主动发消息到群或个人

调用：

- `send_feishu_message`

其中：

- 发群：`receive_id_type=chat_id`
- 发个人：`receive_id_type=open_id` 或 `user_id`

### 5. 让 Agent 调用文本问答

调用：

- `ask_llm_question`

适合这些场景：

- 让 Agent 直接调用后台配置的大模型回答问题
- 可选开启知识库检索增强

### 6. 让 Agent 调用图像理解

调用：

- `analyze_image_with_llm`

图像输入支持：

- `image_url`
- `image_base64`
- 飞书 `image_key`
- 飞书 `message_id`

### 7. 让 Agent 总结群聊

调用：

- `summarize_feishu_chat`

适合这些场景：

- 汇总某个群最近的讨论
- 做例会纪要
- 结合定时任务定期生成日报 / 周报

### 8. 让 Agent 创建定时任务

先查看支持的动作：

- `list_supported_scheduled_actions`

然后创建任务：

- `create_interval_scheduled_task`

例如：每 3600 秒往某个群发一条巡检提醒：

```json
{
  "name": "hourly-reminder",
  "service_id": "your-service-id",
  "action_type": "send_feishu_message",
  "payload": {
    "receive_id": "oc_xxx",
    "receive_id_type": "chat_id",
    "text": "定时提醒：请同步项目进度。"
  },
  "interval_seconds": 3600,
  "run_immediately": false,
  "enabled": true
}
```

### 9. 管理定时任务

- `list_scheduled_tasks`
- `get_scheduled_task`
- `pause_scheduled_task`
- `resume_scheduled_task`
- `delete_scheduled_task`
- `run_scheduled_task_now`

## 六、边界说明

MCP Server 当前是服务能力的适配层，不直接替代飞书主服务本身：

- 飞书事件回调仍然由主服务接收
- MCP 主要负责把主服务的能力提供给 Agent / AI 客户端
- 定时任务由 MCP Server 进程内部执行

这样分层的好处是：

1. 飞书对接逻辑保持稳定
2. MCP 客户端只需要理解 tools
3. 后续可以同时服务 Web API 与 MCP 两类调用方

## 七、定时任务的重要说明

定时任务是在 **MCP Server 进程内部** 调度的，因此要想让任务持续运行，MCP Server 必须保持在线。

这意味着：

- `stdio` 模式适合开发和交互式使用
- 如果你要在生产环境长期跑定时任务，建议使用：
  - `streamable-http`
  - 或 `sse`

当前仓库的 `docker-compose.yml` 已经额外提供了一个持续运行的 `feishu-chat-mcp` 服务，适合承载定时任务。
<!-- AI GC END -->
