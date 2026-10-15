<script setup>
import { Clock3 } from 'lucide-vue-next'
defineProps({ metrics: { type: Object, required: true } })
const seconds = value => Number.isFinite(value) ? (value / 1000).toFixed(2) + ' 秒' : '未测得'
const value = number => number == null ? '未知' : number.toLocaleString('zh-CN')
const labels = { prepare: '准备请求', memory_load: '读取会话 / 摘要', requirements: '理解需求', agent_loop: '模型回答与工具编排', save_result: '保存结果', search_products: '商品检索', get_product_details: '商品详情', get_current_prices: '价格查询', search_reviews: '评价检索', compare_products: '商品评分', search_web: '联网补充', get_user_preference: '读取偏好', save_user_preference: '保存偏好' }
const time = text => text ? new Date(text).toLocaleString('zh-CN', { hour12: false }) : ''
</script>
<template>
  <details class="response-metrics">
    <summary><Clock3 :size="12" />首字 {{ seconds(metrics.first_token_ms) }}<span>·</span>总耗时 {{ seconds(metrics.total_ms) }}</summary>
    <div class="metrics-detail">
      <div class="metrics-meta">{{ metrics.label }} · {{ metrics.code_version }}<span>{{ time(metrics.started_at) }}</span></div>
      <div class="metrics-grid"><span>模型调用 <strong>{{ value(metrics.model_calls) }}</strong></span><span>工具调用 <strong>{{ value(metrics.tool_calls) }}</strong></span><span>输入 Token <strong>{{ value(metrics.input_tokens) }}</strong></span><span>输出 Token <strong>{{ value(metrics.output_tokens) }}</strong></span><span>模型缓存 Token <strong>{{ value(metrics.cache_read_tokens) }}</strong></span><span>引用来源 <strong>{{ value(metrics.source_count) }}</strong></span></div>
      <div v-for="(stage, index) in metrics.stages || []" :key="'stage-' + index" class="metric-row"><span>{{ labels[stage.name] || stage.name }}</span><strong>{{ seconds(stage.duration_ms) }}</strong></div>
      <div v-for="(tool, index) in metrics.tools || []" :key="'tool-' + index" class="metric-row tool-metric"><span>{{ labels[tool.name] || tool.name }}<small v-if="tool.cache_hit">缓存</small><small v-if="tool.status === 'failed'">失败</small></span><strong>{{ seconds(tool.duration_ms) }}</strong></div>
      <p class="metrics-note">后端计时；总耗时包含结果保存，模型编排阶段包含其中的工具调用。未流式输出时，首字时间可能未测得。</p>
      <p v-if="metrics.record_saved === false" class="metrics-note">本轮完整指标保存失败。</p>
    </div>
  </details>
</template>
<style scoped>
.response-metrics { margin: 11px 0 2px; color: #858585; font-size: 11px; }
summary { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; width: fit-content; cursor: pointer; list-style: none; }
summary::-webkit-details-marker { display: none; }
summary:hover { color: #333; }
.metrics-detail { margin-top: 9px; padding: 12px; border: 1px solid #e9e9e9; border-radius: 10px; max-width: 520px; background: #fafafa; }
.metrics-meta { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 4px 12px; font-size: 10px; margin-bottom: 9px; overflow-wrap: anywhere; }
.metrics-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 14px; padding-bottom: 10px; margin-bottom: 6px; border-bottom: 1px solid #e9e9e9; }
.metrics-grid span, .metric-row { display: flex; justify-content: space-between; gap: 8px; line-height: 1.7; }
strong { color: #545454; font-weight: 500; white-space: nowrap; }
.tool-metric { padding-left: 10px; color: #939393; }
small { margin-left: 6px; padding: 1px 4px; background: #eee; border-radius: 3px; font-size: 10px; }
.metrics-note { font-size: 10px; line-height: 1.6; margin: 9px 0 0; color: #969696; }
@media (max-width: 420px) { .metrics-grid { gap: 6px 10px; font-size: 10px; } }
</style>
