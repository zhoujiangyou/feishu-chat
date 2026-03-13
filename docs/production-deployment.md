<!-- AI GC START -->
# 生产部署指南

这份文档说明如何把当前服务部署到线上，并稳定接收飞书回调。

## 1. 部署目标

生产部署至少要满足下面几点：

1. 服务有公网 HTTPS 地址
2. `/api/v1/feishu/{service_id}/callback` 可被飞书访问
3. `data/` 目录持久化，避免 SQLite 和图片资产丢失
4. 有健康检查和重启策略

## 2. 推荐部署形态

当前项目最简单稳定的上线方式是：

- 应用容器：FastAPI + Uvicorn
- MCP 容器：承载 MCP tools 和内部定时任务
- 反向代理：Nginx / Traefik / 云负载均衡
- 数据存储：本地持久卷（当前版本使用 SQLite）

如果后续规模变大，建议把 SQLite 迁移到 PostgreSQL。

## 3. 使用 Docker Compose 部署

### 步骤 1：复制环境变量模板

```bash
cp .env.example .env
```

按实际情况修改：

- `APP_PORT`
- `PUBLIC_BASE_URL`

### 步骤 2：启动服务

```bash
docker compose up -d --build
```

这会同时启动：

- `feishu-chat-service`
- `feishu-chat-mcp`

### 步骤 3：检查健康状态

```bash
curl http://127.0.0.1:8000/health
```

## 4. 反向代理建议

飞书事件回调通常要求公网可访问，建议在服务前放一个 HTTPS 反向代理。

### Nginx 示例要点

- 把 `https://bot.example.com` 反向代理到 `http://127.0.0.1:8000`
- 保留原始 Host 和 X-Forwarded-* 头
- 给 `/api/v1/feishu/` 放开公网访问

## 5. 数据持久化

当前版本会把这些数据写入 `data/`：

- SQLite 数据库
- 抓取下来的图片文件
- MCP 定时任务数据库

因此生产环境必须持久化挂载：

```text
./data:/app/data
```

不要把容器文件系统当作长期存储。

## 6. 生产环境安全建议

### 6.1 网络安全

- 全站启用 HTTPS
- 只开放必要端口
- 如果有管理后台，再额外加鉴权

### 6.2 凭据安全

- 不要把真实 `.env` 提交到 Git
- 飞书 `App Secret`、模型 API Key 只保存在服务端
- 定期轮换高敏感密钥

### 6.3 回调安全

- 始终配置 `verification_token`
- 生产建议启用 `encrypt_key`
- 保证服务端配置与飞书控制台完全一致

## 7. 性能建议

当前版本是轻量实现，适合先上线验证业务。

如果并发提升，建议逐步做这些优化：

1. `UVICORN_WORKERS` 适当增加
2. 知识抓取改为异步任务队列
3. 检索层升级为向量数据库
4. SQLite 升级为 PostgreSQL

## 8. MCP 与定时任务说明

当前定时任务是在 MCP Server 进程内部执行的，所以生产环境里要确保 `feishu-chat-mcp` 持续运行。

推荐：

- 使用 `streamable-http` 模式部署 MCP
- 保持 `./data:/app/data` 挂载
- 通过进程管理或容器重启策略保证 MCP 服务长期存活

## 9. 发布后的操作顺序

建议按这个顺序执行：

1. 启动容器
2. 验证 `/health`
3. 调用 `POST /api/v1/services` 创建机器人服务
4. 在飞书后台配置回调地址
5. 发送 challenge 验证
6. 在群里测试命令和普通问答

## 10. 故障处理建议

### 回调大量失败

- 先查反向代理日志
- 再查容器日志
- 确认 challenge 是否过、token 是否一致

### 图片抓取失败

- 检查磁盘写权限
- 检查 `data/` 挂载是否生效
- 检查飞书资源权限

### 数据丢失

- 基本都和 `data/` 未挂载或被清理有关
- 生产环境建议定期备份 `app.db` 与图片目录
<!-- AI GC END -->
