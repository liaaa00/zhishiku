# 内部AI问答机器人

这是一个专用内部问答系统。

## 启动

1. 在 `.env` 中填写 `OPENAI_API_KEY`（DeepSeek Key）
2. 运行：

```bash
docker compose up -d --build
```

如果你不想用 Docker，也可以直接：

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 访问

- 聊天端：http://localhost:8080/chat
- 管理端：http://localhost:8080/admin

## 管理员初始化

首次启动会根据环境变量初始化管理员账号。请在生产环境设置 `DEFAULT_ADMIN_USERNAME` 和 `DEFAULT_ADMIN_PASSWORD`，不要在页面或文档中暴露默认密码。

## DeepSeek

- 对话模型：`deepseek-chat`
- 接口地址：`https://api.deepseek.com`
- 文档检索默认使用本地哈希向量，不依赖 DeepSeek embedding

## 说明

如果你后面希望我继续把前端做得更像公司内部助手，我可以再简化 UI。
