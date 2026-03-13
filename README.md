<!-- AI GC START -->
# Feishu Chat Service

一个从 0 搭建的飞书机器人服务，目标是满足下面这些能力：

1. 与飞书机器人打通，使用飞书事件回调监听消息。
2. 用户通过飞书和机器人对话时，把任务转发给后台配置的大模型处理。
3. 支持建设并挂载知识库，回答前先做检索增强。
4. 服务创建时可指定飞书 `app_id/app_secret`（即你说的 AK/SK）。
5. 支持通过机器人命令或管理 API 抓取飞书文档、群聊记录、图片。

## 一步步拆解

### 1. 服务实例层

每一个服务实例对应一套独立配置：

- 飞书应用凭据：`app_id`、`app_secret`
- 回调校验：`verification_token`、`encrypt_key`
- 大模型配置：`llm_base_url`、`llm_api_key`、`llm_model`
- 系统提示词：`llm_system_prompt`

这样可以做到多租户：不同用户发布不同机器人服务，各自独立。

### 2. 飞书接入层

- 使用 `tenant_access_token_internal` 获取租户访问令牌
- 接收飞书事件回调
- 支持 URL challenge 校验
- 支持加密回调解密
- 处理 `im.message.receive_v1` 消息事件
- 使用消息回复接口把结果返回给飞书

### 3. 知识库层

使用 SQLite 持久化：

- `services`：服务配置
- `knowledge_sources`：知识源
- `knowledge_chunks`：分块后的文本
- `knowledge_chunks_fts`：全文检索索引
- `assets`：图片等资源文件
- `conversation_logs`：消息日志

### 4. RAG + LLM 层

消息进入后分两条路径：

- **命令路径**：抓取文档 / 群聊 / 图片并入知识库
- **问答路径**：检索知识库 -> 组装上下文 -> 调用 OpenAI 兼容模型接口 -> 回复飞书

### 5. 抓取能力

- **飞书文档**：读取 docx blocks，提取文本，分块入库
- **群聊记录**：按 chat_id 拉取历史消息，提取文本入库
- **图片**：下载图片到本地存储，并登记为知识资产

> 当前图片能力重点放在“抓取与归档”。如果后续需要图片 OCR 或多模态理解，可以在已有管道上继续扩展。

## 机器人命令

支持以下命令：

- `帮助`
- `/help`
- `抓取文档 <文档链接或 token>`
- `抓取群聊 <chat_id> [limit]`
- `抓取图片 <image_key 或 message_id>`
- `/kb doc <文档链接或 token>`
- `/kb chat <chat_id> [limit]`
- `/kb image <image_key 或 message_id>`

## 运行方式

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Docker 运行方式

```bash
cp .env.example .env
docker compose up -d --build
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

## MCP 暴露

当前项目已经支持通过 MCP 暴露服务能力。

启动主服务后，再启动 MCP Server：

```bash
python3 -m app.mcp_server
```

或者：

```bash
feishu-chat-service-mcp
```

默认通过环境变量 `FEISHU_CHAT_SERVICE_BASE_URL` 连接主服务，默认值为：

```text
http://127.0.0.1:8000
```

## 核心接口

### 1. 创建服务实例

`POST /api/v1/services`

示例请求：

```json
{
  "name": "demo-bot",
  "feishu_app_id": "cli_xxx",
  "feishu_app_secret": "xxx",
  "verification_token": "verify_xxx",
  "encrypt_key": "encrypt_xxx",
  "llm_base_url": "https://your-llm-endpoint.example.com/v1",
  "llm_api_key": "sk-xxx",
  "llm_model": "gpt-4o-mini",
  "llm_system_prompt": "你是一个飞书协作助手。"
}
```

返回中会包含：

- `service_id`
- `callback_path`

飞书事件回调地址配置成：

`https://<your-domain>/api/v1/feishu/<service_id>/callback`

### 2. 导入文本知识

`POST /api/v1/services/{service_id}/knowledge-base/text`

### 3. 导入飞书文档

`POST /api/v1/services/{service_id}/knowledge-base/feishu/document`

### 4. 导入飞书群聊记录

`POST /api/v1/services/{service_id}/knowledge-base/feishu/chat`

### 5. 导入飞书图片

`POST /api/v1/services/{service_id}/knowledge-base/feishu/image`

### 6. 触发飞书回调

`POST /api/v1/feishu/{service_id}/callback`

### 7. 主动发送飞书消息

`POST /api/v1/services/{service_id}/feishu/messages/send`

## 推荐飞书权限

至少需要关注这些权限（不同租户控制台命名可能略有差异）：

- 获取 tenant access token
- `im:message`
- `im:message:send_as_bot`
- `im:resource`
- 文档读取相关权限（docx / wiki / drive）

## 部署与飞书配置文档

- 飞书开放平台接入：`docs/feishu-open-platform.md`
- MCP 集成指南：`docs/mcp-integration.md`
- 生产部署指南：`docs/production-deployment.md`

## 当前边界说明

这版实现已经能跑通：

- 多租户服务实例
- 飞书消息回调
- 知识库导入
- 检索增强回答
- 文档 / 群聊 / 图片抓取

但仍建议后续补充：

- 更细致的飞书事件去重
- 更复杂的权限控制
- 图片 OCR 或多模态问答
- 更强的向量检索能力
- 异步任务队列

## 测试

```bash
python3 -m pytest
```
<!-- AI GC END -->
