<!-- AI GC START -->
# 本地部署逐步验收手册

这份手册用于帮助你在本地逐步验证当前项目是否可用，目标是：

1. 先验证服务本身能跑
2. 再验证 OpenAPI
3. 再验证知识库
4. 再验证 MCP
5. 最后再验证飞书回调

这样做的好处是：

- 出问题时更容易定位
- 不会把“公网回调问题”误判成“代码不行”
- 不会把“模型不兼容”误判成“飞书接入失败”

---

## 0. 验收前准备

建议你先准备好下面这些东西：

### 0.1 本地环境

- Python 3.12
- `pip`
- 可选：Docker / Docker Compose

### 0.2 大模型配置

至少准备一套可用的大模型配置：

- `llm_base_url`
- `llm_api_key`
- `llm_model`

如果你要验证图像理解，还要确保：

- 这套模型 / 网关真的支持 OpenAI 兼容 vision 输入

### 0.3 飞书配置

如果你要做飞书联调，请准备：

- `App ID`
- `App Secret`
- `Verification Token`
- `Encrypt Key`

### 0.4 公网 HTTPS（只有飞书联调才需要）

如果你只做本地 OpenAPI / MCP 验证，可以先不准备公网。

但如果你要验证飞书回调，必须有一个公网 HTTPS 地址，例如：

- `ngrok`
- `cloudflared tunnel`
- 你自己的公网服务器 + 域名 + HTTPS

---

## 1. 拉代码并确认分支

先确认你本地已经拿到最新 `main`：

```bash
git checkout main
git pull origin main
git log --oneline -n 5
```

### 预期结果

- 当前分支是 `main`
- 最近提交里能看到最新的合并提交

---

## 2. 方式一：Python 本地直接运行

如果你想最快验证，先用 Python 直接跑。

### 2.1 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2.2 安装依赖

```bash
pip install -e ".[dev]"
```

### 2.3 运行测试

```bash
python3 -m pytest
```

### 预期结果

- 所有测试通过

如果这里失败：

- 优先看 Python 版本是不是 3.12
- 看依赖是否完整安装
- 再看具体报错在哪个测试

### 2.4 启动主服务

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 2.5 健康检查

另开一个终端：

```bash
curl http://127.0.0.1:8000/health
```

### 预期结果

应该返回：

```json
{"status":"ok"}
```

---

## 3. 方式二：Docker 本地运行

如果你更想接近真实部署，可以直接走 Docker。

### 3.1 复制环境变量模板

```bash
cp .env.example .env
```

### 3.2 启动容器

```bash
docker compose up -d --build
```

### 3.3 检查服务状态

```bash
docker compose ps
docker compose logs -f feishu-chat-service
```

### 3.4 健康检查

```bash
curl http://127.0.0.1:8000/health
```

### 预期结果

- `feishu-chat-service` 正常运行
- `feishu-chat-mcp` 正常运行
- `/health` 返回 `{"status":"ok"}`

如果 Docker 起不来：

- 先看 `docker compose logs`
- 再看端口是否冲突
- 再看 `.env` 配置是否异常

---

## 4. 验证 OpenAPI 文档是否可访问

浏览器打开：

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/openapi.json`

### 预期结果

- Swagger 页面能打开
- OpenAPI JSON 正常返回

如果 `/docs` 打不开：

- 说明主服务根本没跑起来
- 先回去查第 2 步或第 3 步

---

## 5. 创建一个测试 service

这个 service 是后续所有验证的基础。

### 5.1 请求示例

在 Swagger 里或者用 curl 调：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/services \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "local-demo-bot",
    "feishu_app_id": "cli_xxx",
    "feishu_app_secret": "xxx",
    "verification_token": "verify_xxx",
    "encrypt_key": "encrypt_xxx",
    "llm_base_url": "https://your-llm-endpoint.example.com/v1",
    "llm_api_key": "sk-xxx",
    "llm_model": "gpt-4o-mini",
    "llm_system_prompt": "你是一个测试用飞书机器人助手。"
  }'
```

### 预期结果

返回里至少有：

- `service_id`
- `callback_path`

请记住这个 `service_id`，后面都要用。

---

## 6. 验证知识库基础功能

建议先不用飞书，直接验证知识库导入与检索。

### 6.1 导入一段文本

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/services/<service_id>/knowledge-base/text" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "本地测试知识",
    "content": "这个项目支持飞书机器人、知识库、MCP、图像分析和群聊总结。",
    "metadata": {
      "source": "manual-test"
    }
  }'
```

### 6.2 搜索知识库

```bash
curl "http://127.0.0.1:8000/api/v1/services/<service_id>/knowledge-base/search?query=群聊总结&limit=5"
```

### 预期结果

- 能搜到刚导入的文本

如果搜不到：

- 检查 `service_id` 是否正确
- 检查导入是否成功
- 检查 query 是否和文本内容有关联关键词

---

## 7. 验证文本问答能力

### 7.1 调用文本问答接口

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/services/<service_id>/llm/ask" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "这个项目可以做什么？",
    "use_knowledge_base": true,
    "knowledge_limit": 5
  }'
```

### 预期结果

返回中应包含：

- `answer`
- `knowledge_results`

### 如果失败

优先检查：

- `llm_base_url`
- `llm_api_key`
- `llm_model`
- 你的网关是否兼容 `/chat/completions`

---

## 8. 验证图像理解能力（URL / base64）

### 8.1 用 URL 做图像分析

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/services/<service_id>/llm/image-analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "请描述这张图片的主要内容。",
    "image_url": "https://example.com/demo.png",
    "save_analysis_to_knowledge_base": true,
    "analysis_title": "URL 图片分析测试"
  }'
```

### 预期结果

返回中应包含：

- `answer`
- `image_source`
- `saved_source`

### 如果失败

大概率是：

- 你的模型不支持 vision
- 网关不支持 OpenAI vision 消息格式
- 图片 URL 无法被模型后端访问

---

## 9. 验证文件上传图像分析

### 9.1 调用上传接口

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/services/<service_id>/llm/image-analyze/upload" \
  -F "prompt=请分析上传图片" \
  -F "file=@/path/to/your/image.png" \
  -F "save_analysis_to_knowledge_base=true" \
  -F "analysis_title=上传图片分析测试"
```

### 预期结果

返回中应包含：

- `answer`
- `image_source=upload_file`
- `saved_source`

如果失败：

- 检查上传文件路径
- 检查文件不是空文件
- 检查模型 vision 能力

---

## 10. 验证群聊总结 OpenAPI

这个步骤只有在你已经配置好飞书 app 并且 service 里的飞书配置可用时才有意义。

### 10.1 调群聊总结接口

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/services/<service_id>/feishu/chats/summarize" \
  -H "Content-Type: application/json" \
  -d '{
    "chat_id": "oc_xxx",
    "limit": 100,
    "save_summary_to_knowledge_base": true,
    "summary_title": "本地群聊总结测试"
  }'
```

### 预期结果

返回中应包含：

- `summary`
- `message_count`
- `saved_source`

如果你还配置了回发：

- `sent_result`

### 如果失败

优先检查：

- 飞书 app 权限
- 机器人是否在群里
- `chat_id` 是否有效
- 飞书消息读取权限是否开通

---

## 11. 验证 MCP 基础能力

### 11.1 启动 MCP Server（本地直跑）

```bash
export FEISHU_CHAT_SERVICE_BASE_URL=http://127.0.0.1:8000
python3 -m app.mcp_server
```

如果你是通过 Docker 启动的，可以直接使用 compose 里的 `feishu-chat-mcp`。

### 11.2 推荐先测的 MCP tools

建议按这个顺序：

1. `service_health`
2. `get_feishu_service`
3. `ask_llm_question`
4. `analyze_image_with_llm`

### 预期结果

- 主服务可被 MCP 正常调用
- 文本问答和图像分析都能返回结果

---

## 12. 验证 MCP 内部定时任务

### 12.1 推荐第一条定时任务先测发消息或群聊总结

例如创建一个定时群聊总结任务：

- `action_type = summarize_feishu_chat`

关键 payload 可以包含：

- `chat_id`
- `limit`
- `save_summary_to_knowledge_base`
- `send_to_receive_id`

### 12.2 你需要重点观察

- 任务是否成功创建
- `last_status` 是否更新
- `last_result` 是否有结果
- 是否真的写入知识库
- 是否真的把总结发到目标群

### 注意

如果你使用的是 `stdio` 模式，MCP 不是长期驻留进程，定时任务不适合这样测。

建议测定时任务时使用：

- Docker 中的 `feishu-chat-mcp`
- 或 `streamable-http` / `sse`

---

## 13. 飞书联调前置条件

只有满足下面条件，再去联调飞书：

- 主服务已通过 OpenAPI 验证
- 模型文本问答 OK
- 图像分析 OK
- 知识库检索 OK
- MCP OK（如果你要用）
- 你已经有公网 HTTPS 地址

---

## 14. 飞书回调联调步骤

### 14.1 准备公网 HTTPS 地址

例如：

- `https://your-domain.example.com`

### 14.2 创建 service

拿到：

- `service_id`

### 14.3 在飞书后台配置回调

回调地址：

```text
https://<your-domain>/api/v1/feishu/<service_id>/callback
```

同时确保飞书后台和 service 配置中的：

- `verification_token`
- `encrypt_key`

完全一致。

### 14.4 订阅事件

至少订阅：

- `im.message.receive_v1`

### 14.5 把机器人拉进群并测试

推荐按顺序发：

1. `帮助`
2. `抓取当前群 20`
3. `总结当前群 20`
4. 一条普通文本提问
5. 一张图片

### 预期结果

- 机器人正常回复帮助
- 当前群可抓取
- 当前群可总结
- 文本问答正常
- 图片自动视觉分析正常

---

## 15. 失败时如何快速定位

### 场景 A：`/health` 不通

看：

- 服务有没有启动
- 端口是否占用
- Docker 容器是否退出

### 场景 B：OpenAPI 问答失败

看：

- 模型地址 / key / model 是否正确
- 你的网关是否兼容 OpenAI `/chat/completions`

### 场景 C：图像分析失败

看：

- 模型是否支持 vision
- 上传文件是否为空
- 图片 URL 是否可访问
- 后端是否支持 `image_url` 消息格式

### 场景 D：MCP 能起但工具调不通

看：

- `FEISHU_CHAT_SERVICE_BASE_URL`
- 主服务是否已经启动
- MCP 是不是连错了地址

### 场景 E：飞书回调 accepted 但机器人没回复

看：

- 应用日志
- 飞书 token / encrypt key 是否一致
- 机器人是否在群里
- 权限是否足够

### 场景 F：群聊总结/抓取失败

看：

- `chat_id` 是否正确
- 机器人是否在该群
- 飞书消息读取权限是否开通

---

## 16. 建议的最小验收标准

如果你只是想确认“这项目能不能本地跑通”，建议至少满足下面 7 条：

- [ ] `/health` 正常
- [ ] `/docs` 正常
- [ ] `POST /api/v1/services` 正常
- [ ] 文本问答接口正常
- [ ] 图像分析接口正常
- [ ] 文本知识导入 + 搜索正常
- [ ] MCP 能连到主服务

如果你要确认“飞书主链路也通”，再追加下面 5 条：

- [ ] 飞书 challenge 验证通过
- [ ] 飞书文本消息能回复
- [ ] `抓取当前群` 可用
- [ ] `总结当前群` 可用
- [ ] 发图片后自动分析并回复

---

## 17. 建议你验证时的顺序总结

最推荐的顺序是：

1. 跑测试
2. 起主服务
3. 测 `/docs`
4. 创建 service
5. 测知识库文本导入和搜索
6. 测文本问答
7. 测图像分析
8. 起 MCP
9. 测 MCP tools
10. 最后才接飞书

不要一上来就直接测飞书回调，否则很难判断到底是：

- 网络问题
- 飞书配置问题
- 模型问题
- 代码问题

---

## 18. 最后提醒

如果你本地验证失败，不要第一时间判断“整个项目不行”。

请先明确是哪一层失败：

- 主服务没起来
- 模型不兼容
- MCP 地址不对
- 飞书打不进来
- 权限没开

建议你保留下面这些信息，出问题时一起发出来：

1. 你执行的命令
2. 服务日志
3. MCP 日志
4. 调用的接口请求体
5. 模型网关类型
6. 飞书回调配置关键字段

这样能最快定位问题。
<!-- AI GC END -->
