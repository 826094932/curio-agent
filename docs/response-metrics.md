# 响应指标与优化对比

每轮普通聊天和流式聊天都会将指标保存到 MySQL `agent_runs.result.timings`，不需要新增表或迁移。回答下方展开耗时明细，可查看阶段、工具调用、Token 与来源数量；历史会话也会恢复显示。旧运行没有完整指标时不补造数据。

## 指标定义

| 指标 | 用途与边界 |
|---|---|
| `first_token_ms` | 最终回答的首个可见文本事件等待时间；工具前的临时文字被重置后重新计时。没有流式文本事件则为 null。 |
| `first_visible_token_ms` | 首次可见文本事件等待时间，可能包含随后被清除的过渡文字。 |
| `total_ms` | 后端请求处理开始到业务结果提交完成，包含会话准备、模型、工具与结果保存；不含鉴权、网络传输、浏览器绘制和最后一次指标记录写入。 |
| `answer_ready_ms` | 回答内容生成完成时的累计时间，帮助区分生成与结果保存开销。 |
| `stages` / `tools` | 会话读取、需求理解、回答编排、结果保存及各次工具调用耗时；编排阶段包含其内部工具耗时，不能相加当成总时间。 |
| `model_calls` / `model_errors` | LangChain 模型调用及失败次数，覆盖需求提取、历史摘要和最终回答；供应商内部 HTTP 重试不单独计数。 |
| `input_tokens` / `output_tokens` | 所有模型调用都返回用量时才汇总；缺失则为 null，通过 `usage_coverage` 判断覆盖率。 |
| `cache_read_tokens` | 模型明确返回的缓存输入 Token；与网页缓存是不同指标，未知时不填 0。 |
| `tool_calls` / `tool_errors` | 工具执行次数及错误数；联网额度不足等业务状态另见 `web_status`。 |
| `web_search_enabled` / `web_status` / `cache_hit` | 区分关闭联网、本地命中、网页缓存命中、真实搜索和搜索故障。 |
| `answer_characters` / `source_count` | 回答长度与证据数量，用于解释耗时差异；数量不能代替回答质量。 |
| `product_count` / `constraint_pass` | 本地推荐商品数与确定性硬约束检查；没有本地推荐卡片时 constraint_pass 为 null。 |
| 标签、代码版本、配置哈希、问题/上下文哈希 | 区分优化前后并识别可比条件；仅保存哈希，不在指标中重复记录问题、网页正文或密钥。 |
| `proxy_enabled` | 记录是否启用进程 HTTP(S) 代理，不记录代理地址或凭据；计入配置哈希，避免把网络方式变化误当作代码优化。 |

失败和取消也会记录指标，不能只统计成功请求。最终答案准确率、推荐相关性仍需固定评测集与人工评审，不能由耗时指标推断。

## 保存当前基线

默认标签为 `baseline-20261013`。正常使用若干轮后，在 backend 目录导出：

```powershell
conda activate agent
python -m scripts.export_metrics --label baseline-20261013 --output ../log/baseline-20261013
```

导出 `runs.csv`、`runs.json` 和 `summary.json`。数据保留每轮指标，并按问题、上下文、版本、模型及联网/缓存模式分组汇总成功率、P50、P95、首字等待、调用次数和 Token。省略 `--output` 时，自动保存到项目根目录 `log/<时间>-response-<标签哈希>/`。log 已加入 .gitignore。

已有快照目录会拒绝覆盖。再次导出时使用新的日期或批次目录；MySQL 中的历史运行记录继续保留。

## 后续优化

在本地 .env 设置新的 `TIMING_LABEL`，例如 `optimized-v1`，重启后用同一批问题复测，再导出对比：

```powershell
python -m scripts.export_metrics --label optimized-v1 --output ../log/optimized-v1 --baseline ../log/baseline-20261013/summary.json
```

`comparison.json` 仅自动配对相同问题、上下文、模型、配置与联网/缓存模式。减少耗时的百分比为负数。不能混用不同预算、历史上下文、冷启动/热运行或真实搜索/缓存结果来宣称优化；商品资料也应保持一致，现有离线 evaluation 可固定数据快照。

每组少于 20 次成功请求会标记 `small_sample`，少量样本的 P95 只作观察。先比较成功率及约束检查，再看耗时和 Token，避免通过减少必要检索来获得更快但更差的回答。

当前尚未加入自动商品结构化更新。后续实现时可增加该阶段的 span，并沿用相同指标记录。
