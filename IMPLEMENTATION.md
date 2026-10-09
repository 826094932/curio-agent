# 选物：电子产品消费决策 Agent

当前实现使用 `ChatDeepSeek + create_agent`，模型默认 `deepseek-flash`。技术栈为 FastAPI、LangChain、MySQL、Chroma、Vue 3、JavaScript。只需要本地 MySQL 服务。

模型配置显式传入 `extra_body={"thinking": {"type": "disabled"}}`，保证结构化需求提取的指定工具调用可用。参考 [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。

## 启动

在项目根目录 `.env` 配置 DeepSeek 和 MySQL。根目录配置先加载，`backend/.env` 可覆盖；不要把 `.env.example` 中的占位值覆盖到已有密钥上。

```powershell
conda activate agent
cd D:\python\agent\backend
python -m pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

另开一个终端：

```powershell
cd D:\python\agent\frontend
npm ci
npm run dev
```

网页：<http://localhost:5173>。接口文档：<http://127.0.0.1:8000/docs>。健康检查：`/health`；依赖检查：`/ready`。健康检查不会付费调用 DeepSeek，也不会下载 Embedding 模型。

也可以在项目根目录执行 `python main.py` 启动后端。正式服务使用 `backend/app/agent/factory.py` 初始化模型。

前端通过 Vite 代理访问后端，建议统一使用 `localhost:5173`，不要在同一登录流程混用 localhost 和 127.0.0.1。Access Token 只放在前端内存中，刷新网页通过 HttpOnly Cookie 恢复登录。

## 配置

完整模板见 `backend/.env.example`。默认读取根目录现有 `DEEPSEEK_API_KEY`，不会将密钥写入源码或网页。

- `MYSQL_DSN`：`mysql+asyncmy://账号:密码@127.0.0.1:3306/product_agent`。
- `JWT_SECRET`：随机字符串，至少 32 字符。更改后现有 Access Token 失效。
- `ADMIN_EMAILS`：管理员邮箱 JSON 数组，例如 `["your-email@example.com"]`。注册该邮箱后重启后端生效；普通注册不会自动授予管理员权限。
- `CHROMA_PERSIST_DIRECTORY`：默认根目录 `data/chroma_db`，相对路径也按项目根目录解析。
- `EMBEDDING_MODEL`：默认 `BAAI/bge-small-zh-v1.5`，首次对非空库检索或导入 active 商品时下载；也可以填已下载的本地模型路径。
- `COOKIE_SECURE`：本地 HTTP 使用 false，正式 HTTPS 部署设为 true。
- `CRAWLER_DOMAINS`：允许采集的官网完整域名 JSON 数组，默认为空；只能由管理员配置。

## 已实现的主流程

1. 注册、Argon2id 密码校验、JWT 登录、Refresh Cookie 轮换、退出、用户禁用检查。
2. 用户私有会话的新建、分页读取消息、重命名、归档、恢复与逻辑删除。
3. MySQL 保存完整用户和助手消息；每轮恢复需求状态、近期消息与旧对话摘要。
4. 七个经过 Pydantic 校验的工具：商品检索、详情、评价、价格、确定性对比、读偏好、授权保存偏好。
5. Chroma 持久化语义检索与元数据过滤，MySQL 回查价格、型号和硬条件。
6. 普通聊天与真实模型 token 流式输出；取消时终止 Agent 并释放会话占用，断线后按 request_id 查询状态。
7. 请求幂等、生成前占用会话、提交时 state_version 乐观锁；工具调用日志、推荐快照、反馈。
8. 商品、价格、评价 JSON 导入、内容哈希增量索引、索引修复、官网 HTML/JSON-LD 草稿提取。
9. Vue 注册登录、私有会话栏、消息 Markdown 安全渲染、停止生成、来源和对比表、管理员导入界面。

浏览器刷新后恢复当前用户会话。会话和运行接口始终从 JWT 获取用户身份，工具闭包绑定服务端 user_id，模型不能传入其他用户 ID。

## 数据导入

初始数据库为空。项目不会把示例参数或模型记忆当作真实商品事实。`data/fixtures/*.example.json` 是明确标记的虚构格式样例，其中商品默认为 draft，不参与推荐。

先把采集并核对的真实商品整理为同样的 JSON 数组，然后导入；价格、评价必须引用已存在的商品 ID。时间字段必须带时区，金额使用十进制字符串。

```powershell
cd D:\python\agent\backend
python -m scripts.import_data products ..\data\fixtures\products.example.json
python -m scripts.import_data prices ..\data\fixtures\prices.example.json
python -m scripts.import_data reviews ..\data\fixtures\reviews.example.json
python -m scripts.rebuild_index
python -m scripts.prepare_embeddings
```

以上命令只用于说明格式；要用于真实推荐，替换来源、产品、时间、参数并设置 `status=active`。也可登录管理员账号，在网页“数据管理”导入。JSON 批次处理会返回逐条错误；成功写入 MySQL 但索引失败的记录可以再次导入修复。价格快照不会被同时间的不同内容静默覆盖。

官网提取端点 `/sources/preview` 只保存待审核草稿，不自动发布产品。当前支持静态 HTML 与 JSON-LD，严格使用管理员配置的官方域名、HTTPS、公开 IP、robots 规则，不跟随重定向。动态浏览器采集、自动价格调度是后续扩展，尚未启用。

## 核心文件

| 文件 | 用途 |
|---|---|
| `backend/app/agent/factory.py` | DeepSeek 模型与 Agent 初始化 |
| `backend/app/agent/tools.py` | 七个工具、调用次数和超时限制、审计日志 |
| `backend/app/chat/service.py` | 会话占用、执行 Agent、事务提交结果与取消恢复 |
| `backend/app/chat/memory.py` | 历史消息、长对话摘要和结构化需求提取 |
| `backend/app/db/models.py` | MySQL 表模型 |
| `backend/app/db/chroma.py` | 本地持久化索引和 BGE 向量生成 |
| `backend/app/products/scoring.py` | 五类产品的数值规格评分、硬条件判断 |
| `backend/app/ingestion/service.py` | 数据校验、幂等导入与索引修复 |
| `frontend/src/stores/chat.js` | 流式消息、历史会话与生成状态 |

模型输出不直接执行 SQL 或抓取网页。Chroma 使用自身管理的 HNSW 索引、余弦距离；当前没有 BM25 或独立 rerank。评分只覆盖已采集的数值规格，不把电池容量等同真实续航，不根据摄像头像素虚构拍摄质量。

## 运行检查

```powershell
cd D:\python\agent\backend
python -m pip check
cd ..\frontend
npm run build
```

测试与诊断文件已归档在项目外，前后端运行不依赖这些文件。后端可访问 `/health`，依赖状态可访问 `/ready`。

## 实施边界

- 当前按单个 FastAPI 进程运行。启动时恢复上次中断的 run，不可同时启动两个后端实例指向同一业务库。多 worker 部署需先实现实例租约和统一协调。
- 基础限流在内存中，重启会清空；不作为公网高强度安全防护。
- 导入接口是同步等待完成的批次 API，并非外部任务队列；大规模采集需增量分批。
- `session_contexts` 的需求字段集中放在 JSON `state`；每个快照保存结构化字段，避免为每次需求迭代增加数据库列。
- 逻辑删除会话不立即清除审计数据；账号注销与长期数据清理策略尚未实现。
- 尚无文档目标中的 200 个真实产品、1000 条评价和 50 条人工评测题。应采集真实资料后评测，不将虚构样例计入验收数据量。
- 当前源代码是 MVP 实现，简历中的性能、召回率和业务效果应以实际评测结果为准。
