# 本地 Agent 评测

针对实际 `app.chat.service.prepare/execute` 执行链评测，覆盖需求提取、工具、流式响应、多轮上下文。评测代码在本机运行，结果不上传 LangSmith；真实模型仍调用项目原有 DeepSeek API，会消耗额度。

每次运行只从现有MySQL读取商品、价格、评价和品类，复制到结果目录中的独立 `evaluation.sqlite3`。专用测试用户、会话、日志和推荐写入这份SQLite，不受网页服务重启的会话清理影响；多轮案例沿用同一测试会话。检索仍使用项目现有Chroma索引。无需启动网页或FastAPI，但必须有已初始化的MySQL、Chroma及模型配置。需要开发依赖中的 `aiosqlite`；若尚未安装，执行 `python -m pip install aiosqlite`。

在 Miniconda Prompt 中：

```bat
conda activate agent
cd /d D:\python\agent\backend
python evaluation\run.py --dry-run
python evaluation\run.py --version v1 --limit 1
python evaluation\run.py --version v1 --repeat 3
```

`--limit 1` 先跑问候案例，验证整条链能工作，再跑完整数据集。上述文件带有10个起始案例（12轮）；后续请增加实际商品、真实价格证据、工具失败和更多记忆案例。不要只靠这10个案例声称整体准确率。

结果默认在项目根目录 `log/<时间>-agent-<版本哈希>/`：

* `manifest.json`：版本、模型、包版本、事实库/Prompt/数据集哈希、评测用户ID。
* `runs.jsonl`：逐轮回答、检查项、完整工具参数、状态、工具耗时与错误、模型次数及Token。
* `results.csv`：Excel可打开，人工质量分保留空白，按rubric填写0～5分。
* `summary.json`：规则通过率、执行成功率、工具执行成功率、意外工具错误率、Schema合法率、总耗时P50/P95、首个可见文本耗时、Token覆盖率。工具执行成功率是原始统计，包含预期的授权拒绝；意外工具错误率排除案例明确允许的拒绝。规则通过要求无意外工具错误，且没有未授权的成功偏好写入。
* `comparison.json`：指定基准时生成前后差值和条件变化提示。

```bat
python evaluation\run.py --version v2 --repeat 3 --baseline ..\log\上一版目录
```

指标边界：规则通过率是配置检查项通过的比例，不等于最终回答正确率；`tool_schema_valid_rate` 只表示参数格式合法，语义参数正确需要增补规则或人工标注。执行成功表示无异常，不表示回答正确。首个可见文本可能是工具前过渡语，不是最终答案首字。总耗时包括需求提取、工具、模型和数据库提交。缺失Token记为null，不当作0。失败轮次之后的依赖追问不执行；对比时检查案例覆盖量。没有固定答案时请人工审核证据、预算、缺点、价格时效和未找到信息的表述。

可选成本估算（参数为你核实的每百万Token单价，单位自行统一）：

```bat
python evaluation\run.py --version v1 --input-price 你的输入单价 --output-price 你的输出单价
```

成本按完整输入单价估算，未应用缓存折扣；实际费用以供应商账单为准。不填写价格时成本为空。这里没有评测故障恢复或完整事实正确率，后续需要为工具故障、明确商品证据增加专门案例。

保持数据集、事实库、模型、Prompt以外的配置和重复次数稳定；变更事实库、价格时间或索引时需记录。manifest记录MySQL事实库哈希，但没有校验向量索引二进制内容。若修改模型是实验目的，比较文件会提示模型变化，这是应解释的实验条件。
