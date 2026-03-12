<!-- AI GC START -->
# 飞书开放平台接入指南

这份文档用于指导你把当前服务接入飞书机器人，并正确配置事件回调、权限和安全参数。

## 1. 创建飞书应用

1. 进入飞书开放平台。
2. 创建一个企业自建应用。
3. 打开机器人能力。
4. 记录以下信息：
   - `App ID`
   - `App Secret`

这两个值就是你前面需求里提到的 AK / SK。

## 2. 配置事件订阅

进入应用后台的 **事件与回调** 页面：

1. 打开事件订阅。
2. 填写请求地址：

```text
https://<your-domain>/api/v1/feishu/<service_id>/callback
```

其中：

- `<your-domain>` 是你部署服务后的公网域名
- `<service_id>` 是调用 `POST /api/v1/services` 后返回的 `service_id`

3. 配置安全信息：
   - `Verification Token`
   - `Encrypt Key`

这两个值需要和你创建服务实例时提交的值保持一致。

## 3. 订阅事件

至少订阅以下事件：

- `im.message.receive_v1`

这是当前服务监听用户消息的核心入口。

## 4. 配置应用权限

建议至少开通这些权限：

- `im:message`
- `im:message:send_as_bot`
- `im:resource`
- 文档读取相关权限（docx / wiki / drive）

如果你希望机器人抓取：

- **文档**：需要文档读取权限
- **群聊记录**：需要消息读取权限
- **图片**：需要资源读取权限

## 5. 发布并安装应用

1. 在企业内发布应用
2. 把机器人加入目标群聊
3. 确保对应用户和群聊可见该机器人

否则会出现：

- 可以收到事件，但无法正常回复消息
- 或者根本收不到目标会话中的消息

## 6. 在当前服务中创建机器人实例

调用接口：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/services \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "demo-bot",
    "feishu_app_id": "cli_xxx",
    "feishu_app_secret": "xxx",
    "verification_token": "verify_xxx",
    "encrypt_key": "encrypt_xxx",
    "llm_base_url": "https://your-llm-endpoint.example.com/v1",
    "llm_api_key": "sk-xxx",
    "llm_model": "gpt-4o-mini",
    "llm_system_prompt": "你是一个飞书协作助手。"
  }'
```

接口返回后，你会拿到：

- `service_id`
- `callback_path`

然后把这个 `callback_path` 配到飞书事件回调里。

## 7. 首次联调建议

建议按下面顺序联调：

1. 先访问服务健康检查：

```bash
curl http://127.0.0.1:8000/health
```

2. 创建服务实例
3. 在飞书后台配置回调地址
4. 发送 challenge 验证
5. 在群里 @ 机器人发送：
   - `帮助`
   - `抓取文档 <文档链接>`
   - 普通问题文本

## 8. 常见问题排查

### challenge 不通过

检查：

- 回调 URL 是否正确
- `service_id` 是否对应正确服务实例
- `verification_token` 是否一致
- 如果开启了加密，`encrypt_key` 是否一致

### 能收到消息但回复失败

检查：

- 机器人是否在目标群内
- 是否开通 `im:message:send_as_bot`
- 应用是否已经发布

### 文档抓取失败

检查：

- 应用是否具备文档读取权限
- 文档是否对该应用所在租户可访问

### 图片抓取失败

检查：

- 是否开通 `im:resource`
- `image_key` 或 `message_id` 是否有效

## 9. 推荐的验收清单

上线前至少验证以下动作：

- challenge 校验成功
- 文本消息可正常回复
- `抓取文档` 可入库
- `抓取群聊` 可入库
- 图片消息自动抓取可落库
- 普通问答能命中知识库并生成回复
<!-- AI GC END -->
