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

也就是说，外部 AI Agent 或 MCP Client 可以通过 MCP 来：

1. 创建飞书机器人服务实例
2. 导入和检索知识库
3. 抓取飞书文档、群聊、图片
4. 主动向飞书群组或个人发送消息

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

## 六、边界说明

MCP Server 当前是服务能力的适配层，不直接替代飞书主服务本身：

- 飞书事件回调仍然由主服务接收
- MCP 主要负责把主服务的能力提供给 Agent / AI 客户端

这样分层的好处是：

1. 飞书对接逻辑保持稳定
2. MCP 客户端只需要理解 tools
3. 后续可以同时服务 Web API 与 MCP 两类调用方
<!-- AI GC END -->
