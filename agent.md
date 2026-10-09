# 基于 LangChain 与 Chroma 的智能电子产品消费决策 Agent

> 文档版本：v1.5  
> 更新日期：2026-09-22  
> 项目定位：面向个人消费者的电子产品检索、对比、推荐与决策解释系统  
> 技术栈：Vue 3、JavaScript、HTML/CSS、FastAPI、LangChain、Chroma、MySQL、DeepSeek API、Crawl4AI
> MVP 数据策略：零电商 API，采集品牌官网公开信息并导入本地事实库

---

## 1. 项目概述

本项目实现一个可实际使用的单 Agent 智能消费决策系统。用户可以用自然语言描述预算、用途和偏好，例如：

- “预算 3000 元，推荐一台拍照好、续航强的手机。”
- “对比 AirPods Pro 和索尼降噪耳机，主要用于地铁通勤。”
- “预算 1500 元，推荐一台适合写代码的显示器。”
- “平板和轻薄本哪个更适合考研记笔记？”

系统不让大模型直接编造商品参数，而是由 Agent 调用检索、详情、价格、评价和评分工具取得证据，再由 DeepSeek 生成带依据的推荐结果。

### 1.1 核心目标

1. 支持笔记本、手机、耳机、显示器等电子产品的统一检索与推荐。
2. 将用户口语需求转换为预算、场景、硬性条件和偏好权重。
3. 使用 Chroma 完成商品及评价的本地语义检索和元数据过滤。
4. 使用 MySQL 保存精确参数、价格历史、会话、推荐结果和反馈。
5. 使用确定性评分程序完成候选商品排序，减少大模型主观打分。
6. 输出推荐理由、适用人群、缺点、价格时效和数据来源。
7. 支持服务热重启，重启 FastAPI 时不重建 Chroma 数据。
8. 支持类似主流聊天网页的多轮对话、历史会话列表、上下文继承和刷新恢复。

### 1.2 非目标

- MVP 不负责直接下单、支付或自动登录电商平台。
- MVP 不承诺秒级实时价格，价格必须附带来源和更新时间。
- MVP 不申请或依赖京东、淘宝等电商开放平台 API；价格使用可追溯的公开快照。
- 不将网页抓取、数据清洗、建库等后台任务暴露为 Agent Tool。
- 不采用多 Agent 架构；第一版使用单 Agent 加多个确定性工具。
- 不让 LLM 直接修改数据库或执行任意 SQL。

---

## 2. 总体架构

```mermaid
flowchart LR
    U[用户] --> WEB[Vue 3 Web]
    WEB --> API[FastAPI API]
    API --> A[LangChain Single Agent]
    A --> LLM[DeepSeek API]
    A --> T1[商品检索 Tool]
    A --> T2[商品详情 Tool]
    A --> T3[评价检索 Tool]
    A --> T4[价格查询 Tool]
    A --> T5[确定性对比 Tool]
    A --> T6[用户偏好 Tool]
    T1 --> V[(Chroma)]
    T3 --> V
    T2 --> M[(MySQL)]
    T4 --> M
    T5 --> M
    T6 --> M
    API --> M
    C[品牌官网公开页面] --> ETL
    R[人工校验 CSV / JSON] --> ETL
    ETL[数据导入服务] --> M
    ETL --> E[Embedding Service]
    E --> V
```

### 2.1 组件职责

| 组件 | 职责 |
|---|---|
| Vue Web | 注册登录、用户私有会话列表、流式聊天、商品推荐和对比展示 |
| FastAPI | 参数校验、鉴权、流式响应、会话管理、健康检查和管理接口 |
| LangChain Agent | 理解需求、选择工具、组织多步调用、生成最终回答 |
| DeepSeek API | 意图理解、工具选择和自然语言生成，不保存业务真值 |
| MySQL | 商品结构化数据、价格、用户、会话、运行日志和推荐记录的事实源 |
| Chroma | 商品描述、使用场景、卖点和用户评价的向量检索索引 |
| Embedding Service | 将检索文本转换为向量，默认使用 `BAAI/bge-small-zh-v1.5` |
| Crawl Service | 使用 Crawl4AI/Playwright 采集品牌官网允许公开访问的商品信息 |
| Import Service | 官网采集结果及 CSV/JSON 的校验、标准化、MySQL Upsert、向量增量更新 |

### 2.2 数据边界

**MySQL 是 Source of Truth。** 商品型号、价格、精确规格和业务记录以 MySQL 为准。

**Chroma 是可重建索引。** 它保存用于召回的文本、向量和少量过滤字段。即使 Chroma 数据丢失，也可以从 MySQL 和原始数据重新构建。

---

## 3. 技术选型

| 类别 | 选型 | 说明 |
|---|---|---|
| 前端 | Vue 3、JavaScript、HTML/CSS、Vite | SPA 页面、组件化 UI、开发服务器与构建 |
| 前端路由 | Vue Router | 登录、注册和聊天页面路由及登录守卫 |
| 前端状态 | Pinia | 当前用户、Token、会话列表和聊天状态 |
| Web 框架 | FastAPI | 异步接口、Pydantic 校验、OpenAPI 文档 |
| Agent | LangChain `create_agent` | 单 Agent 工具调用；内部基于 LangGraph 执行能力 |
| LLM | DeepSeek API | 默认使用支持 Tool Calling 的非思考模式 |
| 结构化数据库 | MySQL 8.x | 参数、价格、用户和业务日志 |
| 向量数据库 | Chroma PersistentClient | 作为 Python 库嵌入 FastAPI，数据持久化到本地目录，无需独立服务 |
| Embedding | `BAAI/bge-small-zh-v1.5` | 中文效果与本地资源占用平衡，维度 512 |
| 官网采集 | Crawl4AI、Playwright | 结构化抽取公开页面；动态页面才使用浏览器 |
| ORM | SQLAlchemy 2.x | 数据访问和事务管理 |
| 数据迁移 | Alembic | 版本化管理表结构 |
| 任务调度，可选 | APScheduler/Celery | 定时更新价格和批量重建索引 |
| 测试 | pytest、pytest-asyncio | 单元、集成和回归测试 |

### 3.1 单 Agent 的原因

当前流程围绕一个明确目标展开：理解购买需求并生成推荐。检索、查详情、查价格、评价分析和评分都是工具，不需要拆成多个拥有独立上下文的 Agent。单 Agent 更容易调试，Token 消耗更少，也便于在面试中说明每一步的可控性。

当未来出现复杂并行研究、多个电商渠道协商或独立审核角色时，再考虑 Supervisor + Sub-Agent。

---

## 4. 功能需求

### 4.1 MVP 功能

1. 自然语言需求解析。
2. 按类别、预算和硬性条件过滤商品。
3. 语义检索商品卖点及适用场景。
4. 查询候选商品精确规格和价格。
5. 检索商品评价中的优点、缺点和场景反馈。
6. 按品类评分策略生成可解释排名。
7. 输出 3 至 5 个推荐项及横向对比。
8. 保存完整消息、结构化会话状态、工具调用、推荐快照和用户反馈。
9. 支持同一 `session_id` 下的连续追问，以及历史会话查询、归档和恢复。
10. 支持长对话摘要和最近消息窗口，防止上下文无限增长。
11. 使用品牌官网公开页面和人工校验文件增量导入商品、评价与价格快照。
12. 使用 MySQL `state_version` 乐观锁和请求幂等键防止同一会话状态被并发覆盖。
13. 支持 FastAPI 热重载，MySQL 与 Chroma 数据在进程重启后保持不变。

### 4.2 第二阶段功能

- 用户长期偏好记忆。
- 商品收藏和降价提醒。
- 图片识别型号或读取商品截图。
- 外部电商 API 价格同步。
- 推荐结果离线评测和 A/B 测试。

---

## 5. Agent 状态定义

每次请求维护以下逻辑状态。状态可以存在 LangChain 运行上下文中，持久化内容写入 MySQL。

```python
from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    session_id: str
    user_id: str
    messages: list[dict[str, Any]]
    conversation_summary: str | None
    category: str | None
    budget_min: float | None
    budget_max: float | None
    use_cases: list[str]
    hard_constraints: dict[str, Any]
    soft_preferences: dict[str, float]
    candidate_product_ids: list[str]
    last_recommended_product_ids: list[str]
    evidence_ids: list[str]
    recommendation_id: str | None
```

### 5.1 需求结构化结果

```json
{
  "category": "phone",
  "budget_min": 2500,
  "budget_max": 3500,
  "use_cases": ["日常拍照", "通勤", "长续航"],
  "hard_constraints": {
    "storage_gb_gte": 256,
    "supports_nfc": true
  },
  "soft_preferences": {
    "camera": 0.4,
    "battery": 0.3,
    "performance": 0.2,
    "weight": 0.1
  }
}
```

若类别、预算或用途缺失到无法做出可靠推荐，Agent 只追问最关键的一项；能够合理检索时则直接执行，不进行多余追问。

### 5.2 多轮对话持久化

DeepSeek API 本身不替应用永久保存历史消息。每轮调用前，FastAPI 必须根据 `session_id` 从 MySQL 恢复必要上下文，并将其重新发送给模型。

一次对话使用三层记忆：

1. **原始消息：** `chat_messages` 保存用户、助手和必要的 Tool 消息，供网页完整展示和审计。
2. **结构化状态：** `session_contexts` 保存当前品类、预算、用途、硬约束、排除品牌、权重和最近推荐商品 ID。
3. **旧对话摘要：** `conversation_summary` 压缩较早对话，保留已经确认的事实和尚未解决的问题。

模型每轮实际接收的上下文为：

```text
System Prompt
+ conversation_summary
+ session_contexts 的结构化 JSON
+ 最近 10 至 20 条原始消息
+ 当前用户消息
```

原始消息始终保留在 MySQL，但不会全部发送给模型。默认在消息超过 20 条或估算上下文超过 8000 Token 时，将较早消息生成摘要；最近 10 条消息不参与压缩。

### 5.3 会话恢复规则

- 系统采用强制注册登录模式，不创建匿名会话。浏览器只保存登录凭证和当前 `session_id`，完整历史从服务端读取。
- 首次对话创建新的 `session_id`；继续对话必须携带原 `session_id`。
- 用户说“不要小米”时，更新 `excluded_brands`，保留已有预算和品类。
- 用户说“对比前两个”时，从 `last_recommended_product_ids` 解析商品，不能依靠模型猜测。
- 用户新建会话后，不继承旧会话状态；只有明确授权的长期偏好可以跨会话读取。
- 不保存或展示模型隐藏推理，只保存可见消息、结构化状态和 Tool 调用摘要。
- 同一个 `session_id` 的请求携带唯一 `request_id`；保存状态时使用 MySQL `state_version` 乐观锁。版本冲突返回 409，前端提示等待上一轮完成后重试。

---

## 6. Tool 设计规范

### 6.1 通用约束

每个 Tool 必须满足：

- 使用 Pydantic Schema 校验输入，拒绝未知或非法字段。
- 返回结构化 JSON，不返回只适合人阅读的长文本。
- 返回 `source`、`updated_at` 或证据 ID，便于最终回答引用。
- 设置超时、最大返回条数和明确的错误码。
- 不接受 SQL、Python 代码、文件路径或任意 URL 作为执行指令。
- Tool 层只执行授权业务操作，不能由模型动态决定数据库语句。
- 所有 Tool 调用写入 `tool_call_logs`，敏感字段需要脱敏。

统一响应格式：

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "request_id": "req_xxx",
    "latency_ms": 42,
    "source": "mysql|chroma|external_api",
    "updated_at": "2026-09-22T10:00:00+08:00"
  }
}
```

### 6.2 Tool 1：search_products

**用途：** 从 Chroma 召回满足语义需求和结构化条件的候选商品。

```python
class SearchProductsInput(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    category: Literal["laptop", "phone", "headphone", "monitor", "tablet"] | None = None
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    brands: list[str] = Field(default_factory=list, max_length=10)
    filters: dict[str, str | int | float | bool] = Field(default_factory=dict)
    top_k: int = Field(default=10, ge=1, le=30)
```

**检索流程：**

1. 验证类别、价格范围和过滤字段白名单。
2. 对 `query` 生成 512 维 Dense Vector。
3. 使用 Chroma `query` 执行 Dense Vector 相似度检索。
4. 使用 `where` 元数据条件过滤 `category`、`brand` 等字段。
5. 合并同一商品的多个命中文档，并按最佳距离和证据覆盖度形成候选集。
6. 返回 `product_id`、距离转换后的召回分数、命中文本和证据 ID。MVP 不引入独立 Rerank。

**返回示例：**

```json
{
  "items": [
    {
      "product_id": "phone_10023",
      "name": "示例手机 Pro",
      "category": "phone",
      "retrieval_score": 0.87,
      "matched_text": "主摄表现稳定，重度使用可维持一天……",
      "evidence_id": "pk_8a13"
    }
  ]
}
```

**说明：** 价格最终过滤应再由 MySQL 校验，因为 Chroma 中的价格可能不是最新值。

### 6.3 Tool 2：get_product_details

**用途：** 从 MySQL 获取商品的精确参数。最终回答中的参数只能来自该 Tool 或价格 Tool。

```python
class GetProductDetailsInput(BaseModel):
    product_ids: list[str] = Field(min_length=1, max_length=20)
```

**返回字段：**

- `product_id`、品牌、型号、类别、状态。
- 通用字段：发布日期、参考价、保修、来源。
- `specs`：品类专属 JSON 参数。
- `spec_version`、`updated_at`。

**错误处理：** 单个 ID 不存在时返回 `missing_product_ids`，不要让整个批次失败。

### 6.4 Tool 3：search_reviews

**用途：** 从 Chroma 检索与候选商品和关注维度相关的评价证据。

```python
class SearchReviewsInput(BaseModel):
    product_ids: list[str] = Field(min_length=1, max_length=10)
    aspects: list[str] = Field(default_factory=list, max_length=8)
    query: str | None = Field(default=None, max_length=300)
    top_k_per_product: int = Field(default=5, ge=1, le=10)
```

`aspects` 使用受控词表，例如 `camera`、`battery`、`performance`、`screen`、`noise_cancelling`、`comfort`、`after_sales`。

**返回内容：** 正向与负向评价片段、情感标签、评价时间、来源和证据 ID。结果必须保留负面证据，不能只返回好评。

### 6.5 Tool 4：get_current_prices

**用途：** 查询候选商品最近一次经过校验的价格快照和数据时效。

```python
class GetCurrentPricesInput(BaseModel):
    product_ids: list[str] = Field(min_length=1, max_length=20)
    channels: list[str] = Field(default_factory=list, max_length=10)
```

**返回字段：**

- 商品 ID、渠道、到手价、标价、优惠说明。
- 库存状态、商品 URL、抓取或更新时间。
- `is_stale`：超过配置时限时为 `true`。

MVP 采用零电商 API 方案，只从 MySQL 读取人工校验或官网公开页面采集的价格快照。Tool 必须返回 `captured_at` 和 `is_stale`，不得把快照表述为实时最低价。未来接入开放平台时也由后台同步服务更新 MySQL，不在一次 Agent 对话里临时抓取整个网站。

### 6.6 Tool 5：compare_products

**用途：** 使用确定性业务规则对候选商品进行归一化评分和排序。

```python
class CompareProductsInput(BaseModel):
    product_ids: list[str] = Field(min_length=2, max_length=10)
    category: str
    use_cases: list[str] = Field(default_factory=list, max_length=10)
    weights: dict[str, float] = Field(default_factory=dict)
```

**评分公式：**

```text
final_score = Σ(normalized_metric_i × weight_i)
              - hard_constraint_penalty
              - stale_data_penalty
```

权重总和必须在服务端归一化为 1。硬性条件不满足的商品应淘汰，而不是仅降低少量分数。

品类策略注册表：

```python
SCORING_STRATEGIES = {
    "laptop": score_laptop,
    "phone": score_phone,
    "headphone": score_headphone,
    "monitor": score_monitor,
    "tablet": score_tablet,
}
```

建议评分维度：

| 品类 | 评分维度 |
|---|---|
| laptop | CPU、GPU、内存、屏幕、续航、重量、扩展性 |
| phone | 芯片、影像、续航、充电、屏幕、系统体验 |
| headphone | 降噪、音质、佩戴、续航、延迟、编码支持 |
| monitor | 尺寸、分辨率、刷新率、面板、色域、接口、支架 |
| tablet | 芯片、屏幕、手写体验、续航、生态、重量 |

**返回内容：** 总分、各维度分数、淘汰原因、数据缺失项以及排序。LLM 只能解释这些分数，不能改写工具给出的数值。

### 6.7 Tool 6：get_user_preference

**用途：** 加载登录用户已经明确保存的长期偏好。

```python
class GetUserPreferenceInput(BaseModel):
    category: str | None = None
```

当前 `user_id` 从经过认证的 Tool Runtime Context 注入，禁止由 LLM 或客户端传入。只返回当前用户授权保存的内容，例如常用预算、品牌排除项、主要场景和维度权重。不得根据单次聊天擅自创建敏感画像。

### 6.8 Tool 7：save_user_preference

**用途：** 在用户明确要求“记住”时保存偏好。

```python
class SaveUserPreferenceInput(BaseModel):
    category: str | None = None
    preferences: dict[str, str | int | float | bool | list[str]]
    consent: bool
```

当前 `user_id` 由后端认证上下文注入。当 `consent` 不为 `true` 时拒绝保存。该 Tool 是可选功能，MVP 可以只读会话上下文。

### 6.9 不应注册为 Agent Tool 的能力

以下操作属于后台管理服务：

- 数据导入、数据清洗、Embedding 生成。
- Chroma Collection 创建、删除和全量重建。
- 数据库迁移、用户鉴权、定时更新价格。
- 任意 SQL、Shell 命令、文件读写和网页抓取。

---

## 7. Agent Workflow

```mermaid
flowchart TD
    A[收到 message 与 session_id] --> B[鉴权与输入校验]
    B --> C[载入摘要、结构化状态与最近消息]
    C --> D[LLM 提取类别、预算、场景和约束]
    D --> E{关键信息是否足够}
    E -- 否 --> F[追问一个最关键问题]
    E -- 是 --> G[search_products 召回候选]
    G --> H[get_product_details 校验规格]
    H --> I[get_current_prices 校验预算和时效]
    I --> J{候选是否足够}
    J -- 否 --> K[放宽软条件后再次检索]
    J -- 是 --> L[search_reviews 获取优缺点证据]
    K --> H
    L --> M[compare_products 确定性评分]
    M --> N[LLM 生成推荐、对比和风险说明]
    N --> O[保存助手消息、运行日志和推荐快照]
    O --> Q[更新 session_contexts 与必要的历史摘要]
    Q --> P[流式返回结果]
```

### 7.1 推荐执行规则

1. 首轮候选数建议为 10 至 20 个，进入详情阶段后保留 5 至 8 个。
2. 最终结果建议展示 3 个：首选、均衡选择和特定偏好选择。
3. 先执行硬条件过滤，再做语义排序和评分。
4. 所有价格必须包含渠道和更新时间。
5. 所有关键优缺点至少关联一个检索证据 ID。
6. 资料不足时明确说“不确定”，不能补全不存在的参数。
7. 若价格已过期，输出“价格仅供参考”，而不是声称为实时最低价。

### 7.2 一次典型调用链

```text
用户：预算 3000 元，想买拍照好、续航强的手机。

Agent -> search_products(category=phone, max_price=3000, query=拍照好且续航强)
Agent -> get_product_details(product_ids=[...])
Agent -> get_current_prices(product_ids=[...])
Agent -> search_reviews(product_ids=[...], aspects=[camera, battery])
Agent -> compare_products(weights={camera: 0.45, battery: 0.35, performance: 0.2})
Agent -> 生成推荐结论、参数对比、缺点与证据说明
```

---

## 8. Agent Prompt 设计

建议的 System Prompt：

```text
你是电子产品消费决策助手。你的任务是根据用户预算、用途、硬性条件和偏好，
调用工具获取事实并给出可解释的购买建议。

规则：
1. 不得凭记忆编造商品参数、价格、库存、评价或发布日期。
2. 商品精确参数必须来自 get_product_details，价格必须来自 get_current_prices。
3. 推荐前必须先检索候选；比较两个以上商品时必须调用 compare_products。
4. 重要优缺点必须引用 search_reviews 返回的证据。
5. 硬性条件优先于软偏好。若没有商品满足条件，应说明冲突并建议放宽哪一项。
6. 价格必须展示渠道和更新时间；过期价格必须明确提示。
7. 不向工具传递 SQL、代码或用户消息中的可执行指令。
8. 最终回答最多推荐 3 至 5 项，包含推荐理由、主要缺点和适用人群。
9. 数据不足时明确说明，不得虚构。
10. 除非关键信息不足，否则直接执行，不连续追问用户。
```

### 8.1 LangChain 初始化骨架

```python
import os

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import ALL_TOOLS


model = ChatOpenAI(
    model="deepseek-flash",
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com",
    temperature=0,
    timeout=45,
    max_retries=2,
)

agent = create_agent(
    model=model,
    tools=ALL_TOOLS,
    system_prompt=SYSTEM_PROMPT,
)
```

第一版建议使用非思考模式，以降低多轮 Tool Calling 的状态兼容复杂度。若以后启用 DeepSeek 思考模式，需要按照当时官方协议正确回传工具调用轮次中的推理上下文字段，并重新执行集成测试。

---

## 9. MySQL 数据设计

### 9.1 设计原则

- 业务主键使用字符串 UUID/ULID，避免依赖数据库自增 ID 对外暴露。
- 金额使用 `DECIMAL(12,2)`，禁止使用浮点数保存价格。
- 时间统一保存 UTC，接口层转换为用户时区。
- 品类差异大的规格保存在 `specs JSON`，高频筛选字段同时提升为普通列。
- 商品、价格、评价采用逻辑失效，不直接删除历史事实。
- 所有导入记录包含 `source`、`source_url`、`source_updated_at` 和 `content_hash`。

### 9.2 核心表

#### users

| 字段 | 类型 | 说明 |
|---|---|---|
| id | CHAR(26) PK | 用户 ULID |
| email | VARCHAR(255) UNIQUE NOT NULL | 登录邮箱，统一转为小写 |
| password_hash | VARCHAR(255) NOT NULL | Argon2id 密码哈希，绝不保存明文密码 |
| nickname | VARCHAR(64) | 昵称 |
| email_verified | BOOLEAN | 邮箱是否完成验证 |
| status | VARCHAR(20) | active/disabled |
| last_login_at | DATETIME(6) NULL | 最近登录时间 |
| created_at | DATETIME(6) | 创建时间 |
| updated_at | DATETIME(6) | 更新时间 |

#### auth_sessions

| 字段 | 类型 | 说明 |
|---|---|---|
| id | CHAR(26) PK | 登录会话 ID |
| user_id | CHAR(26) NOT NULL INDEX | 登录用户 ID |
| refresh_token_hash | CHAR(64) UNIQUE NOT NULL | Refresh Token 的 SHA-256，不保存明文 |
| user_agent | VARCHAR(512) | 登录设备信息 |
| ip_hash | CHAR(64) | 脱敏后的来源 IP 哈希 |
| expires_at | DATETIME(6) INDEX | 过期时间 |
| revoked_at | DATETIME(6) NULL | 登出或吊销时间 |
| created_at | DATETIME(6) | 创建时间 |

Access Token 使用短期 JWT，例如 15 分钟；Refresh Token 使用高熵随机值，只将哈希保存在 `auth_sessions`。用户登出、禁用账号或修改密码后吊销相关登录会话。

#### user_preferences

| 字段 | 类型 | 说明 |
|---|---|---|
| id | CHAR(26) PK | 偏好记录 ID |
| user_id | CHAR(26) NOT NULL INDEX | 用户 ID |
| category | VARCHAR(32) | 品类；空值表示通用偏好 |
| preferences | JSON | 预算、品牌排除项、用途、权重等 |
| consent_version | VARCHAR(32) | 用户授权版本 |
| created_at / updated_at | DATETIME(6) | 时间字段 |

#### categories

| 字段 | 类型 | 说明 |
|---|---|---|
| code | VARCHAR(32) PK | laptop/phone/headphone/monitor/tablet |
| name | VARCHAR(64) | 中文名称 |
| spec_schema | JSON | 允许的规格字段及类型 |
| scoring_config | JSON | 默认评分维度和权重 |
| enabled | BOOLEAN | 是否启用 |

#### products

| 字段 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(64) PK | 稳定商品 ID |
| category_code | VARCHAR(32) INDEX | 品类 |
| brand | VARCHAR(64) INDEX | 品牌 |
| model | VARCHAR(128) INDEX | 型号 |
| name | VARCHAR(255) | 展示名称 |
| release_date | DATE | 发布日期 |
| msrp | DECIMAL(12,2) | 建议零售价 |
| currency | CHAR(3) | 默认 CNY |
| summary | TEXT | 标准化商品简介 |
| specs | JSON | 品类专属规格 |
| source | VARCHAR(64) | 数据来源 |
| source_url | VARCHAR(1024) | 来源链接 |
| source_updated_at | DATETIME(6) | 来源更新时间 |
| content_hash | CHAR(64) | 参与向量构建内容的 SHA-256 |
| status | VARCHAR(20) INDEX | active/discontinued/draft |
| created_at / updated_at | DATETIME(6) | 时间字段 |

唯一约束建议为 `(category_code, brand, model)`。`specs` 必须先通过该品类的 JSON Schema 校验。

#### product_prices

| 字段 | 类型 | 说明 |
|---|---|---|
| id | CHAR(26) PK | 价格记录 ID |
| product_id | VARCHAR(64) INDEX | 商品 ID |
| channel | VARCHAR(64) INDEX | 渠道名称 |
| sku | VARCHAR(128) | 渠道 SKU |
| list_price | DECIMAL(12,2) | 标价 |
| final_price | DECIMAL(12,2) | 到手价 |
| promotion | VARCHAR(512) | 优惠说明 |
| in_stock | BOOLEAN | 是否有货 |
| product_url | VARCHAR(1024) | 商品链接 |
| captured_at | DATETIME(6) INDEX | 价格采集时间 |
| expires_at | DATETIME(6) | 价格有效期 |

保留历史价格。查询当前价时取每个 `(product_id, channel)` 最新且未失效的记录。

#### product_reviews

| 字段 | 类型 | 说明 |
|---|---|---|
| id | VARCHAR(64) PK | 评价 ID |
| product_id | VARCHAR(64) INDEX | 商品 ID |
| rating | DECIMAL(3,2) | 标准化评分 |
| title | VARCHAR(255) | 标题 |
| content | TEXT | 原始或清洗后评价 |
| aspects | JSON | 涉及维度 |
| sentiment | VARCHAR(16) INDEX | positive/neutral/negative |
| source | VARCHAR(64) | 来源 |
| source_url | VARCHAR(1024) | 来源链接 |
| reviewed_at | DATETIME(6) | 评价时间 |
| content_hash | CHAR(64) | 去重哈希 |
| created_at / updated_at | DATETIME(6) | 时间字段 |

#### chat_sessions

| 字段 | 类型 | 说明 |
|---|---|---|
| id | CHAR(26) PK | 会话 ID |
| user_id | CHAR(26) NOT NULL INDEX | 会话所有者，外键关联 users.id |
| title | VARCHAR(255) | 会话标题 |
| status | VARCHAR(20) | active/archived |
| last_message_at | DATETIME(6) INDEX | 最近消息时间，用于会话列表排序 |
| created_at / updated_at | DATETIME(6) | 时间字段 |

`chat_sessions` 建立 `(user_id, last_message_at)` 联合索引。会话列表、详情、更新和删除都必须按 `WHERE id = :session_id AND user_id = :current_user_id` 查询；只按 `session_id` 查询属于越权漏洞。

#### chat_messages

| 字段 | 类型 | 说明 |
|---|---|---|
| id | CHAR(26) PK | 消息 ID |
| session_id | CHAR(26) INDEX | 会话 ID |
| role | VARCHAR(16) | user/assistant/tool/system |
| content | JSON | 文本、工具结果摘要等 |
| tool_name | VARCHAR(64) NULL | Tool 消息对应的工具名 |
| tool_call_id | VARCHAR(128) NULL | 一次模型工具调用 ID |
| token_usage | JSON | 输入输出 Token |
| created_at | DATETIME(6) INDEX | 创建时间 |

建议建立 `(session_id, created_at)` 联合索引，网页按游标分页读取。Tool 的大体积原始结果不直接塞入 `content`，这里只保存面向上下文的裁剪摘要，完整调用审计写入 `tool_call_logs`。

#### session_contexts

| 字段 | 类型 | 说明 |
|---|---|---|
| session_id | CHAR(26) PK | 对应会话 ID |
| category | VARCHAR(32) NULL | 当前商品品类 |
| budget_min / budget_max | DECIMAL(12,2) NULL | 当前预算范围 |
| use_cases | JSON | 已确认使用场景 |
| hard_constraints | JSON | 必须满足的条件 |
| preference_weights | JSON | 当前软偏好权重 |
| excluded_brands | JSON | 当前排除品牌 |
| candidate_product_ids | JSON | 本轮候选商品 |
| last_recommended_product_ids | JSON | 最近一次展示顺序，用于解析“前两个” |
| conversation_summary | TEXT | 已压缩的早期会话摘要 |
| summarized_until_message_id | CHAR(26) NULL | 摘要覆盖到的最后一条消息 |
| state_version | INT | 乐观锁版本，避免并发覆盖 |
| updated_at | DATETIME(6) | 更新时间 |

`session_contexts` 是对话状态快照，不替代原始消息。更新用户消息、助手消息和会话状态时应使用事务；使用 `UPDATE ... WHERE session_id=:id AND state_version=:old_version` 实现乐观锁，成功后将版本加一。

#### 并发与状态策略

- MVP 固定运行单个 FastAPI 实例和单个 Uvicorn Worker，不承诺跨进程状态协调。
- 每次聊天请求生成唯一 `request_id`，`agent_runs.request_id` 建立唯一索引，重复请求直接返回已有运行状态。
- 会话状态使用 MySQL `state_version` 乐观锁；更新行数为 0 表示发生并发冲突，返回 409/`SESSION_BUSY`。
- Agent 运行进度和错误写入 `agent_runs`，客户端断线后可按 `request_id` 查询，不依赖内存状态。
- 商品、价格和会话直接查询 MySQL；MVP 不设置独立缓存层，优先保证数据一致性和部署简单。
- Access Token 保持短有效期；登出时吊销 MySQL 中的 Refresh Token，已经签发的 Access Token 最迟在到期后失效。
- 登录接口可使用单进程内存计数器做基础限流；正式多实例部署时再接入专用限流组件。

#### agent_runs

| 字段 | 类型 | 说明 |
|---|---|---|
| id | CHAR(26) PK | 一次 Agent 运行 ID |
| request_id | CHAR(26) UNIQUE | 客户端请求幂等键 |
| session_id | CHAR(26) INDEX | 会话 ID |
| user_message_id | CHAR(26) | 触发消息 |
| model | VARCHAR(64) | 模型名 |
| status | VARCHAR(20) INDEX | running/succeeded/failed |
| extracted_requirements | JSON | 结构化需求快照 |
| prompt_version | VARCHAR(32) | Prompt 版本 |
| input_tokens / output_tokens | INT | Token 用量 |
| latency_ms | INT | 总耗时 |
| error_code | VARCHAR(64) | 错误码 |
| started_at / finished_at | DATETIME(6) | 时间字段 |

#### tool_call_logs

| 字段 | 类型 | 说明 |
|---|---|---|
| id | CHAR(26) PK | 调用 ID |
| run_id | CHAR(26) INDEX | Agent Run ID |
| tool_name | VARCHAR(64) INDEX | Tool 名称 |
| arguments_redacted | JSON | 脱敏后的参数 |
| result_summary | JSON | 截断后的结果摘要 |
| status | VARCHAR(20) | succeeded/failed/timeout |
| latency_ms | INT | 耗时 |
| error_code | VARCHAR(64) | 错误码 |
| created_at | DATETIME(6) | 创建时间 |

#### recommendations

| 字段 | 类型 | 说明 |
|---|---|---|
| id | CHAR(26) PK | 推荐结果 ID |
| run_id | CHAR(26) INDEX | 对应运行 |
| user_id | CHAR(26) NOT NULL INDEX | 推荐结果所有者 |
| category | VARCHAR(32) | 品类 |
| requirements_snapshot | JSON | 当时需求 |
| answer | MEDIUMTEXT | 最终回答 |
| evidence_ids | JSON | 使用的 Chroma 证据 ID |
| price_snapshot_at | DATETIME(6) | 价格快照时间 |
| created_at | DATETIME(6) | 创建时间 |

#### recommendation_items

| 字段 | 类型 | 说明 |
|---|---|---|
| id | CHAR(26) PK | 明细 ID |
| recommendation_id | CHAR(26) INDEX | 推荐 ID |
| product_id | VARCHAR(64) INDEX | 商品 ID |
| rank_no | INT | 排名 |
| total_score | DECIMAL(6,3) | 总分 |
| dimension_scores | JSON | 各维度得分 |
| reasons | JSON | 推荐理由 |
| risks | JSON | 缺点和风险 |
| price_snapshot | JSON | 当时价格，保证可复现 |

#### feedback

| 字段 | 类型 | 说明 |
|---|---|---|
| id | CHAR(26) PK | 反馈 ID |
| recommendation_id | CHAR(26) INDEX | 推荐 ID |
| user_id | CHAR(26) NOT NULL | 反馈所有者 |
| rating | TINYINT | 1 至 5 |
| selected_product_id | VARCHAR(64) NULL | 用户最终选择 |
| comment | VARCHAR(1000) | 文本反馈 |
| created_at | DATETIME(6) | 创建时间 |

#### import_jobs

| 字段 | 类型 | 说明 |
|---|---|---|
| id | CHAR(26) PK | 导入任务 ID |
| job_type | VARCHAR(32) | product/review/price/reindex |
| source_file | VARCHAR(1024) | 数据文件或来源 |
| status | VARCHAR(20) INDEX | pending/running/succeeded/failed |
| total_count / success_count / failed_count | INT | 统计 |
| error_report | JSON | 错误摘要 |
| started_at / finished_at | DATETIME(6) | 时间字段 |

---

## 10. Chroma Collection 设计

MVP 建议拆成两个 Collection，避免商品知识与评价文本在检索分布上互相干扰。

```python
import chromadb

client = chromadb.PersistentClient(path=settings.chroma_persist_directory)
product_collection = client.get_or_create_collection(
    name=settings.chroma_product_collection,
    configuration={"hnsw": {"space": "cosine"}},
)
review_collection = client.get_or_create_collection(
    name=settings.chroma_review_collection,
    configuration={"hnsw": {"space": "cosine"}},
)
```

`PersistentClient` 会在指定目录自动加载和保存数据，不需要启动数据库服务，也不需要每次启动重新导入。

### 10.1 product_knowledge

| 字段 | Chroma 位置 | 说明 |
|---|---|---|
| id | `ids` | 稳定且唯一的文档块 ID |
| content | `documents` | 用于检索的文本 |
| dense_vector | `embeddings` | BGE 生成的 512 维向量 |
| product_id | `metadatas` | MySQL 商品 ID |
| category | `metadatas` | 品类过滤字段 |
| brand | `metadatas` | 品牌过滤字段 |
| content_type | `metadatas` | summary/spec/use_case/pros_cons |
| source_url | `metadatas` | 证据来源 |
| content_hash | `metadatas` | 增量更新判断 |
| updated_ts | `metadatas` | 更新时间戳 |

### 10.2 review_knowledge

| 字段 | Chroma 位置 | 说明 |
|---|---|---|
| id | `ids` | 稳定且唯一的评价块 ID |
| content | `documents` | 评价文本 |
| dense_vector | `embeddings` | 512 维 Dense Vector |
| review_id | `metadatas` | MySQL 评价 ID |
| product_id | `metadatas` | 商品 ID |
| category | `metadatas` | 品类 |
| aspect | `metadatas` | 评价维度 |
| sentiment | `metadatas` | 情感标签 |
| rating | `metadatas` | 评分 |
| source | `metadatas` | 来源 |
| review_ts | `metadatas` | 评价时间戳 |

### 10.3 索引与检索策略

- 使用 `chromadb.PersistentClient(path=...)`，数据库文件直接保存在项目的数据目录中。
- Collection 使用余弦距离；由 Chroma 管理本地向量索引，不在 MVP 中配置 IVF、独立向量服务或分布式节点。
- 使用 `where` 对 `category`、`brand`、`product_id` 等元数据进行过滤，再执行 Dense Vector 查询。
- 明确型号查询先由 MySQL 精确匹配；自然语言使用场景由 Chroma 语义召回。
- MVP 不使用 Sparse/BM25 混合检索和独立 Rerank，先通过离线测试验证 Top-K 召回质量。
- Chroma 只保存必要元数据，完整规格仍回查 MySQL。

推荐召回配置：

```yaml
retrieval:
  dense_top_k: 30
  final_top_k: 10
  distance: cosine
  rerank_enabled: false
  persist_directory: ./data/chroma_db
```

---

## 11. 零电商 API 数据采集与增量更新

```mermaid
flowchart LR
    A[品牌官网公开页面] --> X[Crawl4AI / Playwright]
    R[人工校验 CSV / JSON] --> B
    X --> B[字段校验]
    B --> C[型号与单位标准化]
    C --> D[去重与质量检查]
    D --> E[MySQL Upsert]
    E --> F[构造检索文本]
    F --> G[计算 content_hash]
    G --> H{内容是否变化}
    H -- 否 --> I[跳过 Embedding]
    H -- 是 --> J[生成 Embedding]
    J --> K[Chroma Upsert]
    K --> L[记录 import_jobs]
    I --> L
```

### 11.1 数据来源与采集方法

第一阶段不申请京东、淘宝等电商 API，也不在用户对话过程中临时抓取网页。后台采集任务按以下优先级获取产品信息：

1. 品牌官网公开的产品详情页、规格页和支持文档。
2. 页面中的 JSON-LD 或内嵌结构化 JSON。
3. 稳定的 CSS/XPath 字段抽取。
4. 必须执行 JavaScript 的页面才使用 Playwright。
5. 页面结构复杂时可用 DeepSeek 将已抓取文本映射到 Pydantic Schema，但模型结果必须经过类型、单位和范围校验。
6. 价格和评价不足的商品由人工校验 CSV/JSON 补齐，并保留来源 URL 和采集时间。

推荐工具分工：

| 工具 | 用途 |
|---|---|
| `httpx` | 获取静态 HTML、JSON-LD 和公开文件 |
| Crawl4AI | 异步页面采集、CSS/XPath 结构化抽取、Markdown 清洗 |
| Playwright | 处理 JavaScript 渲染、分页和必要交互 |
| Pydantic | 将不同官网字段校验并转换为统一商品 Schema |
| APScheduler | 定时执行低频增量更新；数据量增大后可换 Celery |

采集任务必须遵守目标网站的服务条款、robots 规则和访问频率限制，不绕过登录、验证码、付费墙或反爬机制。抓取失败时记录任务错误并保留旧数据，不能阻塞 Agent 查询。

### 11.2 原始数据格式

推荐保留以下目录作为可追溯输入：

```text
data/
├── raw/
│   ├── products/
│   ├── reviews/
│   └── prices/
├── normalized/
├── rejected/
└── fixtures/
```

原始文件不直接作为线上查询源。导入后 MySQL 是业务事实源，Chroma 是派生索引。

每个原始记录至少保存：`source`、`source_url`、`captured_at`、原始文件路径和 `content_hash`，以便复核字段来源。

### 11.3 幂等更新规则

| 场景 | MySQL | Chroma |
|---|---|---|
| 新商品 | Insert | Insert/Upsert 向量 |
| 描述或关键规格变化 | Update | 重新 Embedding 后 Upsert |
| 仅价格变化 | Insert 新价格记录 | 不更新 |
| 商品停售 | status=discontinued | 保留或设置过滤状态 |
| 新评价 | Insert | Insert/Upsert |
| 重复评价 | 根据 hash 跳过 | 跳过 |

`content_hash` 建议对标准化后的文本计算 SHA-256。Chroma 主键保持稳定，Upsert 时覆盖旧向量，从而避免重复数据。

### 11.4 初始数据量

适合个人开发的 MVP：

- 4 个品类。
- 每个品类 40 至 60 个商品，总计约 200 个。
- 每个商品 5 至 10 条有代表性的评价，总计约 1000 至 2000 条。
- 每件商品至少一条可验证且带采集时间的价格快照。

这个规模足以演示检索、筛选、对比、解释和增量更新，不需要先收集海量数据。

---

## 12. FastAPI 接口设计

统一前缀：`/api/v1`。除注册、登录和健康检查外，所有接口必须携带有效 Access Token。客户端不能通过请求参数指定 `user_id`，后端统一从认证上下文获取当前用户。

### 12.1 身份认证接口

| 方法与路径 | 用途 |
|---|---|
| `POST /auth/register` | 使用邮箱和密码注册用户 |
| `POST /auth/login` | 校验密码并签发 Access/Refresh Token |
| `POST /auth/refresh` | 使用 Refresh Token 换取新 Access Token |
| `POST /auth/logout` | 吊销当前登录会话 |
| `GET /users/me` | 获取当前用户基本信息 |

认证规则：

- 密码使用 Argon2id 哈希，禁止自行实现加密算法。
- Access Token 建议 15 分钟过期，Refresh Token 建议 7 至 30 天过期。
- Refresh Token 通过 `HttpOnly + Secure + SameSite=Lax` Cookie 返回，Access Token 由前端保存在内存中。
- JWT 只保存 `sub=user_id`、`jti`、签发及过期时间和必要权限，不保存密码或完整用户资料。
- 登录错误统一返回模糊提示，避免泄露邮箱是否已经注册。
- 登录、注册和刷新接口在单实例内执行基础频率限制，并记录失败次数；生产多实例部署时再接入网关限流。

### 12.2 POST /chat

```json
{
  "session_id": "01J...",
  "message": "预算 3000 元，想买拍照好、续航强的手机",
  "stream": false
}
```

服务端处理顺序：先保存用户消息，再加载 `session_contexts`、摘要和最近消息，调用 Agent 后保存助手消息并更新会话状态。任何阶段失败都要将 `agent_runs` 标记为失败，但不能删除已经收到的用户消息。

响应：

```json
{
  "request_id": "req_01J...",
  "session_id": "01J...",
  "recommendation_id": "01J...",
  "answer": "……",
  "products": [],
  "sources": [],
  "price_updated_at": "2026-09-22T10:00:00+08:00"
}
```

### 12.3 POST /chat/stream

使用 Server-Sent Events 返回：

```text
event: status   data: {"stage":"searching_products"}
event: status   data: {"stage":"comparing_products"}
event: token    data: {"text":"综合预算和拍照需求……"}
event: result   data: {"recommendation_id":"...","sources":[...]}
event: done     data: {}
```

不要把模型的隐藏推理过程发送给客户端，只发送阶段状态和最终可展示内容。

### 12.4 用户私有会话接口

| 方法与路径 | 用途 |
|---|---|
| `POST /sessions` | 新建空白会话并返回 `session_id` |
| `GET /sessions` | 按 `last_message_at` 分页返回历史会话列表 |
| `GET /sessions/{id}/messages` | 按游标分页返回完整消息历史 |
| `PATCH /sessions/{id}` | 修改标题或归档状态 |
| `DELETE /sessions/{id}` | 按数据保留策略删除会话及关联状态 |

这些接口只能操作当前登录用户自己的会话。网页首次进入时加载当前用户的会话列表；用户选择旧会话后拉取消息。发送消息时携带同一个 `session_id`，后端同时校验其所有者。刷新浏览器后仍可恢复。SSE 断线不代表对话数据丢失，客户端可以重新读取消息或根据 `request_id` 查询运行结果。

### 12.5 管理及查询接口

| 方法与路径 | 用途 |
|---|---|
| `POST /products/import` | 创建商品导入任务，需管理员权限 |
| `POST /reviews/import` | 创建评价导入任务，需管理员权限 |
| `POST /prices/import` | 导入价格快照 |
| `POST /indexes/rebuild` | 显式重建索引，禁止在启动时自动执行 |
| `GET /products/search` | 调试商品检索，不经过 Agent |
| `GET /products/{id}` | 查询商品详情 |
| `GET /recommendations/{id}` | 查询历史推荐快照 |
| `POST /feedback` | 提交推荐反馈 |
| `GET /health` | 进程存活检查 |
| `GET /ready` | 检查 MySQL、Chroma 持久化目录和必要配置是否可用 |

### 12.6 HTTP 状态码

| 状态码 | 使用场景 |
|---|---|
| 200 | 查询成功 |
| 201 | 创建会话、反馈或导入任务成功 |
| 202 | 后台导入或重建任务已接受 |
| 400 | 业务参数冲突 |
| 401/403 | 未登录或无权限 |
| 404 | 商品、当前用户会话或推荐不存在；避免暴露他人的资源是否存在 |
| 409 | 重复导入或资源状态冲突 |
| 422 | Pydantic 参数校验失败 |
| 429 | 超过限流或模型额度 |
| 503 | MySQL、Chroma 或模型服务暂不可用 |

---

## 13. 项目目录

第一版采用适合个人开发者的模块化单体结构。认证、聊天、商品和采集各自保留 `router/schema/service` 边界，但不额外创建 Repository、Celery Worker 或大量基础抽象；SQLAlchemy 查询先集中在对应模块的 `service.py` 中，出现明显复用或复杂事务后再提取 Repository。

```text
agent/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── dependencies.py
│   │   ├── errors.py
│   │   ├── agent/
│   │   │   ├── factory.py
│   │   │   ├── prompts.py
│   │   │   └── tools.py
│   │   ├── db/
│   │   │   ├── mysql.py
│   │   │   ├── chroma.py
│   │   │   └── models.py
│   │   ├── auth/
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   └── service.py
│   │   ├── chat/
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   └── memory.py
│   │   ├── products/
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   ├── service.py
│   │   │   └── scoring.py
│   │   └── ingestion/
│   │       ├── router.py
│   │       ├── crawler.py
│   │       └── service.py
│   ├── alembic/
│   ├── scripts/
│   │   ├── import_data.py
│   │   └── rebuild_index.py
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   ├── e2e/
│   │   └── evals/
│   ├── pyproject.toml
│   ├── uv.lock
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   └── index.js
│   │   ├── components/
│   │   │   ├── Sidebar.vue
│   │   │   ├── MessageList.vue
│   │   │   ├── ChatInput.vue
│   │   │   └── ProductComparison.vue
│   │   ├── views/
│   │   │   ├── LoginView.vue
│   │   │   ├── RegisterView.vue
│   │   │   └── ChatView.vue
│   │   ├── router/
│   │   │   └── index.js
│   │   ├── stores/
│   │   │   ├── auth.js
│   │   │   └── chat.js
│   │   ├── App.vue
│   │   ├── main.js
│   │   └── style.css
│   ├── tests/
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.js
│   └── .env.example
├── data/
├── README.md
└── agent.md
```

为保持结构图清晰，Python 包中的 `__init__.py` 未逐项展示，但实际创建项目时应补齐。

### 13.1 Vue 前端页面与交互

前端采用 Vue 3 Composition API，但全部使用 JavaScript，不引入 TypeScript。`index.html` 作为 Vite 入口，页面布局包含左侧用户私有会话栏和右侧聊天工作区。

| 页面/组件 | 主要职责 |
|---|---|
| `LoginView.vue` | 邮箱密码登录、错误提示和登录限流反馈 |
| `RegisterView.vue` | 注册、密码规则提示和重复邮箱处理 |
| `ChatView.vue` | 加载当前用户会话、展示消息、创建新对话 |
| `Sidebar.vue` | 当前用户的会话列表、新建、重命名和归档 |
| `MessageList.vue` | 用户/助手消息、加载状态和错误重试 |
| `ChatInput.vue` | 多行输入、发送、停止生成和禁用并发提交 |
| `ProductComparison.vue` | 商品卡片、候选维度评分、参数对比、来源和价格时效 |

Pinia Store 分工：

- `auth.js`：当前用户和内存中的 Access Token。
- `chat.js`：会话列表、当前 `session_id`、消息、分页游标、流式状态和推荐结果。

安全的浏览器鉴权方案：

- Access Token 只保存在 Pinia 内存中，页面刷新后通过 Refresh Token 换取。
- Refresh Token 由后端写入 `HttpOnly + Secure + SameSite=Lax` Cookie，JavaScript 不可读取。
- 不将 Access/Refresh Token 写入 `localStorage`。
- 前端传递 `session_id`，但不传递 `user_id`；后端根据 JWT 校验会话所有者。
- 用户登出时清空 Pinia 状态并调用 `/auth/logout` 吊销 Refresh Token。

`POST /chat/stream` 使用 `src/api/index.js` 中封装的原生 `fetch` 读取 SSE/ReadableStream，因为原生 `EventSource` 不适合携带 POST JSON 请求。该模块解析 `status`、`token`、`result`、`error` 和 `done` 事件，并通过 `AbortController` 支持“停止生成”。

助手 Markdown 在前端展示前必须使用 DOMPurify 清理，商品链接使用安全属性打开，禁止直接执行回答中的 HTML 或脚本。

### 13.2 文件职责速查

#### 后端公共文件

| 文件 | 作用 |
|---|---|
| `backend/app/main.py` | 创建 FastAPI 应用，注册路由、CORS、异常处理和生命周期事件 |
| `backend/app/config.py` | 从 `.env` 读取 MySQL、Chroma 持久化目录、DeepSeek 等配置 |
| `backend/app/dependencies.py` | 提供当前登录用户、数据库连接和权限校验等公共依赖 |
| `backend/app/errors.py` | 定义统一业务异常、错误码和 HTTP 错误响应 |

#### 数据库与基础设施

| 文件 | 作用 |
|---|---|
| `db/mysql.py` | 创建 SQLAlchemy 异步连接池和数据库 Session |
| `db/chroma.py` | 初始化 Chroma PersistentClient，管理 Collection 和向量查询 |
| `db/models.py` | 集中定义用户、登录会话、聊天、商品、价格、推荐等 MySQL 模型 |

#### 用户认证

| 文件 | 作用 |
|---|---|
| `auth/router.py` | 提供注册、登录、刷新 Token、退出和当前用户接口 |
| `auth/schemas.py` | 定义注册、登录、Token 和用户信息的请求响应格式 |
| `auth/service.py` | 实现密码哈希、JWT、Refresh Token、登录限流和用户验证 |

#### 会话与 Agent

| 文件 | 作用 |
|---|---|
| `chat/router.py` | 提供会话管理、普通聊天和流式聊天接口 |
| `chat/schemas.py` | 定义聊天请求、消息、会话和 SSE 事件格式 |
| `chat/service.py` | 编排消息保存、用户归属校验、MySQL 乐观锁、Agent 调用和结果持久化 |
| `chat/memory.py` | 加载最近消息、结构化上下文和摘要，控制发送给模型的上下文长度 |
| `agent/factory.py` | 初始化 DeepSeek 模型并创建 LangChain Agent |
| `agent/prompts.py` | 保存 System Prompt、需求提取 Prompt 和历史摘要 Prompt |
| `agent/tools.py` | 集中定义商品检索、详情、价格、评价、对比和偏好 Tool |

#### 商品与数据采集

| 文件 | 作用 |
|---|---|
| `products/router.py` | 提供商品详情、检索、推荐结果查询和用户反馈接口 |
| `products/schemas.py` | 定义商品、规格、价格和对比结果的数据格式 |
| `products/service.py` | 查询 MySQL/Chroma，完成商品过滤、详情和价格读取 |
| `products/scoring.py` | 实现不同电子产品品类的确定性评分策略 |
| `ingestion/router.py` | 提供管理员数据导入和显式重建索引接口 |
| `ingestion/crawler.py` | 使用 Crawl4AI/Playwright 采集品牌官网公开信息 |
| `ingestion/service.py` | 清洗、校验、去重并写入 MySQL 和 Chroma |

#### 脚本与测试

| 文件或目录 | 作用 |
|---|---|
| `backend/alembic/` | 保存 MySQL 表结构迁移版本 |
| `scripts/import_data.py` | 手动执行商品、评价和价格快照导入 |
| `scripts/rebuild_index.py` | 从 MySQL 重建 Chroma 向量索引 |
| `backend/tests/` | 保存单元、集成、E2E 和 Agent 评测用例 |
| `backend/pyproject.toml` | 管理 Python 依赖及测试、格式化工具配置 |
| `backend/uv.lock` | 锁定验证通过的 Python 依赖版本 |
| `backend/.env.example` | 展示后端环境变量，不包含真实密钥 |

#### Vue 前端

| 文件 | 作用 |
|---|---|
| `src/api/index.js` | 封装 API 请求、Token 刷新、统一错误和流式响应 |
| `stores/auth.js` | 保存当前用户、登录状态和内存中的 Access Token |
| `stores/chat.js` | 保存用户会话列表、当前消息、推荐结果和生成状态 |
| `LoginView.vue` | 登录页面 |
| `RegisterView.vue` | 注册页面 |
| `ChatView.vue` | 组合侧栏、消息区、输入框和商品推荐区域 |
| `Sidebar.vue` | 展示当前用户会话并支持新建、切换、重命名和归档 |
| `MessageList.vue` | 展示用户消息、助手消息和生成状态 |
| `ChatInput.vue` | 输入消息、发送请求和停止生成 |
| `ProductComparison.vue` | 展示商品参数、评分、价格、优缺点和来源对比 |
| `router/index.js` | 配置页面路由和登录守卫 |
| `App.vue` | Vue 根组件 |
| `main.js` | 初始化 Vue、Pinia 和 Router |
| `style.css` | 全局样式和响应式布局 |
| `index.html` | Vite 网页入口 |
| `package.json` | 管理 Vue 依赖和 npm 命令 |
| `package-lock.json` | 锁定前端依赖版本，保证不同环境安装一致 |
| `vite.config.js` | 配置 Vite、开发端口和后端代理 |
| `frontend/tests/` | 保存 Vue Store、组件和 API 流式解析测试 |

#### 项目根目录

| 文件或目录 | 作用 |
|---|---|
| `data/` | 保存原始、标准化、拒绝和演示数据 |
| `README.md` | 项目介绍、安装、启动和使用说明 |
| `agent.md` | 架构、数据库、Tool、Workflow 和实施约束 |

---

## 14. 配置与依赖

### 14.1 环境变量

```dotenv
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO

JWT_SECRET_KEY=replace_with_at_least_32_random_bytes
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=14

DEEPSEEK_API_KEY=replace_me
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
LLM_TIMEOUT_SECONDS=45

MYSQL_DSN=mysql+asyncmy://agent:password@127.0.0.1:3306/product_agent
CHROMA_PERSIST_DIRECTORY=./data/chroma_db
CHROMA_PRODUCT_COLLECTION=product_knowledge
CHROMA_REVIEW_COLLECTION=review_knowledge

EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_DEVICE=cpu
EMBEDDING_DIMENSION=512

PRICE_STALE_HOURS=24
MAX_AGENT_STEPS=10
MAX_TOOL_RESULT_ITEMS=30
RECENT_MESSAGE_LIMIT=20
KEEP_RECENT_MESSAGE_COUNT=10
SUMMARY_TRIGGER_TOKENS=8000

CRAWLER_USER_AGENT=ProductDecisionAgent/1.0
CRAWLER_CONCURRENCY=2
CRAWLER_REQUEST_INTERVAL_SECONDS=3

```

`.env` 不得提交 Git，仓库只保存 `.env.example`。生产环境通过 Secret Manager 或部署平台注入密钥。

### 14.2 Python 依赖

```text
fastapi
uvicorn[standard]
langchain
langchain-deepseek
langchain-huggingface
sqlalchemy[asyncio]
asyncmy
chromadb
langchain-chroma
alembic
pydantic-settings
sentence-transformers
orjson
httpx
crawl4ai
playwright
beautifulsoup4
lxml
tenacity
structlog
python-ulid
apscheduler
pyjwt
pwdlib[argon2]
email-validator
pytest
pytest-asyncio
```

开发完成后生成锁文件并固定通过测试的精确版本，不建议长期使用无版本约束的生产依赖。

### 14.3 前端环境变量与依赖

`frontend/.env.example`：

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
VITE_APP_NAME=智能电子产品消费决策助手
```

`package.json` 主要依赖：

```text
vue
vue-router
pinia
marked
dompurify
lucide-vue-next
```

开发依赖：

```text
vite
@vitejs/plugin-vue
vitest
@vue/test-utils
jsdom
eslint
```

前端统一通过 `src/api/http.js` 封装 `fetch`，处理 API Base URL、Access Token、401 自动刷新、统一错误结构和请求取消。FastAPI 开发环境只允许 Vite 地址，例如 `http://localhost:5173`，不要使用允许任意来源且携带 Cookie 的 CORS 配置。

---

## 15. 生命周期与热重启

FastAPI 使用 `lifespan` 在进程启动时：

1. 校验必要环境变量。
2. 创建 MySQL 连接池。
3. 创建 Chroma PersistentClient，并通过 `get_or_create_collection` 加载 Collection。
4. 延迟加载 Embedding 模型，或启动时预热一次。
5. 创建 Agent 单例、会话服务及 Tool 依赖。
6. 检查会话表和 `session_contexts` Migration 版本。

进程关闭时释放 MySQL连接池和模型资源。启动阶段只加载本地 Chroma 数据，**不得默认删除或重建 Collection**。

在 `backend` 目录启动后端开发服务：

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

热重启只会重建 Python 进程和 MySQL 连接池，不会删除 `CHROMA_PERSIST_DIRECTORY` 中的索引，也不会丢失 MySQL 中的历史会话。不要执行以下操作：

- 删除 `data/chroma_db` 持久化目录
- 启动时调用 `drop_collection`
- 每次启动使用 `drop_old=True`

只有 Embedding 模型、向量维度或分块规则发生不兼容变化时，才创建新版本 Collection，例如 `product_knowledge_v2`。新索引构建完成并校验后再切换别名。

---

## 16. 异常处理与稳定性

### 16.1 错误分类

| 错误类型 | 策略 |
|---|---|
| 参数校验失败 | 立即返回 422，不调用 LLM |
| DeepSeek 超时 | 最多重试 2 次，指数退避 |
| DeepSeek 限流 | 返回 429 或降级提示，不无限重试 |
| Chroma 暂不可用 | 若是明确型号查询，可降级到 MySQL；语义推荐返回 503 |
| MySQL 暂不可用 | 返回 503，禁止基于模型记忆生成参数 |
| MySQL 乐观锁冲突 | 返回 409/`SESSION_BUSY`，前端稍后重试，禁止并发覆盖状态 |
| 单个 Tool 失败 | 将结构化错误交给 Agent，允许一次替代方案 |
| 数据不足 | 返回可解释的“不足”，不生成虚假推荐 |

### 16.2 调用限制

- 单轮最多 10 个 Agent Step。
- 相同 Tool 和相同参数最多调用 2 次。
- 单个 Tool 最大结果 30 条，返回 LLM 前做字段裁剪。
- 单次请求设置总超时，例如 90 秒。
- 客户端断开流式连接时取消后续生成和不必要调用。

---

## 17. 安全设计

1. 用户输入只作为数据，不作为系统指令拼接到 Prompt。
2. 检索文档中的“忽略之前指令”等文本视为不可信内容。
3. Tool 参数通过 Schema 和白名单验证。
4. 数据库使用最小权限账号；应用账号无建库、删表权限。
5. 管理接口与聊天接口使用不同权限。
6. 日志不记录 API Key、密码、完整邮箱和未脱敏用户输入。
7. 限制消息长度、上传文件大小和请求频率。
8. 来源 URL 只允许 `http/https`，前端展示前进行转义。
9. 最终回答不得宣称“全网最低价”或“绝对最优”。
10. 对商品健康、安全或金融分期相关信息增加明确提示。
11. 所有会话和推荐查询从 JWT `sub` 获取当前用户，并在模块 Service 的数据访问逻辑中强制拼接 `user_id` 条件。
12. 客户端、LLM 和 Tool 参数均不得覆盖认证上下文中的 `user_id`。
13. 对无权访问的会话统一返回 404，不泄露该资源是否属于其他用户。
14. 密码只保存 Argon2id 哈希，Refresh Token 只保存 SHA-256 哈希；日志禁止记录任何 Token。
15. 用户注销账号时按数据保留策略删除或匿名化个人会话、偏好、推荐与反馈数据，共享商品数据不受影响。
16. Vue 输出的模型 Markdown 必须经过 DOMPurify 清理，防止存储型和反射型 XSS。
17. FastAPI 使用明确的 CORS 来源列表；Refresh Cookie 相关接口校验 `Origin`，防止跨站请求滥用。

---

## 18. 可观测性

每个请求生成 `request_id`，贯穿 FastAPI、Agent Run 和 Tool Call。

建议指标：

- API 请求量、P50/P95/P99 延迟和错误率。
- LLM 输入/输出 Token、费用估算和超时率。
- Agent 平均 Step 数、各 Tool 调用次数与失败率。
- Chroma 检索延迟、空召回率和候选覆盖率。
- 推荐生成成功率、价格过期率、数据缺失率。
- MySQL 乐观锁冲突率、重复 `request_id` 次数和 Agent 运行恢复成功率。
- 用户满意度、采纳率和反馈率。

日志建议使用 JSON 结构化输出。`agent_runs` 和 `tool_call_logs` 用于业务审计，应用日志用于排障，两者不要混为同一张表。

---

## 19. 测试与评测

### 19.1 单元测试

- 每个 Pydantic Tool Schema 的合法和非法输入。
- 各品类评分函数的边界值、缺失值和权重归一化。
- 价格过期判断、货币金额和硬性条件过滤。
- `content_hash` 幂等性和增量导入逻辑。
- `state_version` 乐观锁、`request_id` 幂等和并发冲突处理逻辑。
- 密码哈希校验、JWT 过期、Refresh Token 轮换和注销逻辑。
- 会话和推荐 Service 的数据库查询始终包含当前 `user_id`，防止 IDOR 越权访问。
- Prompt 注入文本不会变成工具参数或系统指令。
- Vue Store、路由守卫、SSE 解析、401 Token 刷新和消息状态更新。

### 19.2 集成测试

- FastAPI + MySQL：创建会话、保存消息和推荐快照。
- FastAPI + MySQL：验证同一会话并发更新时仅一个版本提交成功。
- 用户 A 无法读取、修改、继续或删除用户 B 的会话和推荐结果。
- Vue 页面刷新后能够通过 Refresh Cookie 恢复登录状态并加载当前用户会话。
- FastAPI + Chroma：写入测试向量并检索。
- Agent + 模拟 Tool：验证工具选择顺序和最大步数。
- 导入任务：重复导入不产生重复商品或向量。
- 服务重启：数据仍然存在且无需重建 Collection。
- Chroma 持久化：FastAPI 重启后无需重新生成向量即可继续检索。

### 19.3 E2E 用例

至少建立 50 条固定评测问题，覆盖：

- 明确预算和场景。
- 条件互相冲突。
- 指定两个型号对比。
- 型号拼写错误或简称。
- 没有匹配商品。
- 价格过期、规格缺失和评价不足。
- Prompt Injection 和恶意超长输入。

### 19.4 推荐质量指标

| 指标 | 含义 |
|---|---|
| Recall@K | 标准答案中的相关商品是否进入候选 |
| Constraint Pass Rate | 推荐项满足硬性条件的比例，目标 100% |
| Grounded Fact Rate | 参数和价格能被数据源支持的比例 |
| Citation Coverage | 关键优缺点带证据的比例 |
| Empty Result Handling | 无结果时是否诚实说明并提供合理放宽建议 |
| Human Preference | 人工对推荐相关性和解释性的评分 |

测试中不要只比较最终自然语言。还要断言 Tool 调用、候选 ID、过滤结果和评分结果。

---

## 20. 本地部署方案

### 20.1 资源说明

RTX 4050 可以运行本项目。DeepSeek 推理由远程 API 完成，本地 GPU 不是必要条件；`bge-small-zh-v1.5` 可直接在 CPU 上运行。Chroma、MySQL、FastAPI 的主要压力在内存和磁盘。

Windows 环境建议：

- MySQL 使用已安装的 Windows 服务。
- Chroma 通过 Python 包嵌入 FastAPI，使用 `PersistentClient` 保存到本地目录。
- Python 使用独立 Conda 环境 `agent`。
- 前端使用 Node.js LTS、Vue 3 和 Vite，开发端口默认 `5173`。
- 系统内存建议 16GB；DeepSeek 使用远程 API，本地主要资源用于 Embedding、MySQL 和开发服务。

### 20.2 启动顺序

```text
1. 启动 MySQL Windows 服务
2. 激活 Conda 环境 agent
3. 执行 Alembic Migration
4. 首次采集并导入商品、评价和价格快照
5. 校验 Chroma Collection 与文档数量
6. 启动 FastAPI；Chroma 随应用自动加载
7. 在 frontend 目录执行 npm install 和 npm run dev
8. 访问 http://localhost:5173，并通过 /docs 和 /ready 验证后端依赖
```

生产部署时先在 `frontend` 执行 `npm run build` 生成静态资源，并通过 Nginx 或静态托管服务发布；FastAPI 关闭 `--reload`。使用多个 Uvicorn Worker 前应确认 Embedding 模型内存占用，也可把 Embedding 独立为单进程服务。

---

## 21. 开发里程碑

### 阶段一：基础设施

- 创建 FastAPI 项目和配置系统。
- 连接 MySQL，并初始化 Chroma 本地持久化目录和健康检查。
- 创建 SQLAlchemy Model、Alembic Migration 和 Chroma Schema。
- 实现用户注册登录、JWT、Refresh Token 轮换和认证依赖。

### 阶段二：数据管道

- 定义商品、评价、价格 JSON Schema。
- 实现品牌官网 Crawl4AI 采集器和动态页面 Playwright 兜底采集器。
- 实现导入、标准化、去重和 MySQL Upsert。
- 实现 Embedding 与 Chroma 增量 Upsert。

### 阶段三：检索和评分

- 实现商品 Dense Vector 检索、元数据过滤和 MySQL 型号精确匹配。
- 实现评价按商品和维度检索。
- 实现五个品类的确定性评分策略。

### 阶段四：Agent 与 API

- 实现 5 个核心 Tool 和可选偏好 Tool。
- 配置 DeepSeek，完成单 Agent Workflow。
- 实现普通与 SSE 流式聊天接口。
- 实现历史会话列表、消息分页、结构化状态、长对话摘要、请求幂等和 MySQL 乐观锁。

### 阶段五：Vue 网页端

- 使用 Vue 3、JavaScript、HTML/CSS 和 Vite 实现注册与登录页面。
- 实现用户私有会话侧栏、消息列表、输入框和新建/归档会话。
- 使用 `fetch` 流解析 Agent SSE，支持阶段状态、逐步文本和停止生成。
- 实现商品卡片、参数对比、来源展示以及 Pinia 状态管理。

### 阶段六：质量保障

- 建立评测集、集成测试和 E2E 测试。
- 增加日志、指标、限流和错误降级。
- 完成 Windows/Conda 启动说明和演示数据。

---

## 22. MVP 验收标准

1. 至少支持手机、笔记本、耳机和显示器四个品类。
2. 用户必须注册登录后才能创建会话，所有会话、消息、状态、推荐和反馈均归属该用户。
3. 用户 A 即使获得用户 B 的 `session_id` 或推荐 ID，也无法访问或修改对应数据。
4. Vue 网页支持注册登录、会话列表、新建会话、历史消息恢复和流式回答。
5. 前端不使用 TypeScript，主要代码由 `.vue`、`.js`、`.html` 和 `.css` 组成。
6. 至少导入 200 个商品和 1000 条评价。
7. 自然语言查询能正确提取预算、品类、场景和硬约束。
8. 最终推荐中的型号、参数和价格均可追溯到数据库记录。
9. 对比任务必须输出确定性评分明细和主要缺点。
10. 价格展示来源、更新时间和是否过期。
11. 同一用户的同一 `session_id` 可以连续追问，刷新网页后能够恢复完整历史和当前约束。
12. 两个并发消息不会覆盖同一会话状态，MySQL 乐观锁冲突得到明确处理。
13. 服务热重启后 MySQL 和 Chroma 数据保持不变。
14. 重复导入同一数据不会产生重复记录或重复向量。
15. DeepSeek 或数据库故障时返回可解释错误，不生成虚假答案。
16. 后端、前端和集成测试全部通过，并具备一组固定回归问题。

---

## 23. 面试重点说明

### 23.1 可以重点讲的技术决策

- **事实与索引分离：** MySQL 保存精确事实，Chroma 只负责召回，避免向量库成为不可审计的业务真值。
- **单 Agent + 强类型 Tool：** 保留自然语言规划能力，同时将数据库访问和评分限制在确定性代码中。
- **双路径检索：** 型号等确定性条件由 MySQL 精确查询，使用场景和主观需求由 Chroma Dense Vector 语义召回。
- **评分与生成分离：** 程序计算排序，大模型负责解释，降低同一输入下排名漂移。
- **增量索引：** 使用稳定主键和 `content_hash`，只有影响检索的内容变化才重新生成向量。
- **结果可复现：** 推荐结果保存需求、评分、证据和价格快照，可以回放一次决策。
- **持久化会话记忆：** MySQL 保存完整消息、结构化状态与摘要，通过 `request_id` 幂等和 `state_version` 乐观锁保证单实例下的会话一致性。
- **用户级数据隔离：** 认证身份由 JWT 注入，Service 数据访问层对会话、推荐和反馈强制添加 `user_id` 条件，防止通过猜测资源 ID 越权访问。
- **可靠性控制：** 限制 Agent Step、工具参数白名单、超时重试、价格时效和来源追踪。

### 23.2 简历表述示例

**基于 LangChain 与 Chroma 的智能电子产品消费决策 Agent**

项目描述：面向手机、笔记本、耳机和显示器等品类，构建基于自然语言需求理解、语义检索、确定性评分与多轮工具调用的消费决策系统，为用户提供可追溯的商品推荐、参数对比和评价总结。

技术栈：Vue 3、JavaScript、HTML/CSS、Python、FastAPI、LangChain、DeepSeek API、Chroma、MySQL、Crawl4AI、SQLAlchemy。

- 基于 LangChain 构建单 Agent 工具调用流程，将语义检索、规格查询、价格校验、评价分析和品类评分封装为强类型 Tool，实现从口语需求到推荐结果的端到端决策。
- 设计 MySQL 业务事实库与 Chroma 本地向量索引的双存储架构，结合 Dense Vector、元数据过滤和型号精确匹配完成候选召回，并通过稳定主键与内容哈希实现幂等增量更新。
- 针对不同电子产品建立可扩展评分策略，将硬约束过滤、指标归一化和权重计算从 LLM 中剥离，提升推荐结果的一致性和可解释性。
- 保存 Agent 运行轨迹、工具调用、证据 ID 和价格快照，支持结果回放、质量评测与故障定位；通过超时重试、调用步数限制和数据时效校验降低幻觉风险。
- 设计持久化会话记忆机制，以 MySQL 保存完整消息和结构化上下文，使用摘要控制 Token 成本，并通过请求幂等与乐观锁防止多轮对话状态被并发覆盖。
- 基于 JWT、Argon2id 和 Refresh Token 轮换实现用户认证，并在数据访问层实施会话与推荐资源的用户级隔离，覆盖跨用户 IDOR 越权测试。
- 使用 Vue 3、Pinia 与原生 Fetch Stream 构建对话网页，实现注册登录、用户私有会话管理、流式生成、商品卡片和参数对比交互。

---

## 24. 风险与后续优化

| 风险 | 影响 | 应对措施 |
|---|---|---|
| 商品参数来源不一致 | 对比错误 | 建立字段标准、单位转换和来源优先级 |
| 价格更新不及时 | 推荐超预算 | 保存时间、过期标志和后台同步任务 |
| 用户评价存在偏差 | 优缺点失真 | 多来源采样、时间过滤、保留正负证据 |
| LLM 重复或错误调用 Tool | 延迟和费用增加 | 强 Schema、最大步数、重复调用检测 |
| 向量召回效果不稳定 | 漏掉相关商品 | 固定评测集、优化检索文本、Embedding 模型和 Top-K |
| 新品类字段差异大 | 代码膨胀 | Category Schema + Strategy Registry |
| 模型或 API 版本变化 | 兼容性问题 | 封装 LLM Adapter、锁定依赖并执行回归测试 |
| 同一会话并发提交 | 会话状态被覆盖 | `request_id` 唯一索引、MySQL `state_version` 乐观锁和 409 重试机制 |

---

## 25. 官方参考资料

- LangChain Agents：<https://docs.langchain.com/oss/python/langchain/agents>
- LangChain Tools：<https://docs.langchain.com/oss/python/langchain/tools>
- FastAPI：<https://fastapi.tiangolo.com/>
- DeepSeek API：<https://api-docs.deepseek.com/>
- DeepSeek Tool Calls：<https://api-docs.deepseek.com/guides/tool_calls/>
- Chroma 文档：<https://docs.trychroma.com/>
- Chroma Python Client：<https://docs.trychroma.com/reference/python/client>
- Chroma Collection 配置：<https://docs.trychroma.com/docs/collections/configure>
- LangChain Chroma 集成：<https://python.langchain.com/docs/integrations/vectorstores/chroma/>
- SQLAlchemy：<https://docs.sqlalchemy.org/>
- Alembic：<https://alembic.sqlalchemy.org/>
- Crawl4AI：<https://docs.crawl4ai.com/>
- Playwright Python：<https://playwright.dev/python/docs/library>
- Vue：<https://vuejs.org/guide/introduction.html>
- Vue Router：<https://router.vuejs.org/>
- Pinia：<https://pinia.vuejs.org/>
- Vite：<https://vite.dev/guide/>

---

## 26. 最终设计结论

第一版采用 **Vue 3 网页端 + 强制注册登录 + 单 Agent + 七个受控 Tool + MySQL 事实库 + Chroma 本地检索索引**。Agent 负责理解与编排，Tool 负责可信数据访问，评分服务负责稳定排序，LLM 负责把证据组织成用户能理解的建议。商品数据采用零电商 API 方案，通过品牌官网公开页面和人工校验文件在后台增量构建。

该结构既能在个人 RTX 4050 笔记本上完成开发和演示，也保留了以后增加品类、外部价格源、图片输入和任务调度的扩展空间。每个会话必须绑定唯一注册用户，所有用户私有数据都从认证身份进行归属过滤；多轮对话由 MySQL 永久保存，Chroma 作为可重建的本地派生索引。最重要的工程边界是：**用户数据必须隔离，参数和价格必须可验证，评分必须可复现，Chroma 数据必须可重建，Agent 权限必须受 Tool Schema 限制。**

