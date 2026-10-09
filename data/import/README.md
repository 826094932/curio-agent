# 官网资料导入包

核对日期：2026-09-23（Asia/Shanghai）。商品规格只填写官网明确公开且能对应当前条目的字段，未公开内容保持缺失，不由模型补全。

## 文件

- `apple-products.json`：iPhone、iPad、MacBook Air、Apple Watch、AirPods 各一条。
- `apple-prices.json`：官网能明确对应到所选基础配置的价格；MacBook Air 价格未稳定展示，因此未录入。
- `xiaomi-products.json`：手机、平板、笔记本、手表、耳机各一条。
- `xiaomi-prices.json`：小米中国大陆官网明确展示的起售配置价格。

## 导入顺序

先导入商品，再导入价格：

```powershell
cd D:\python\agent\backend
python -m scripts.import_data products ..\data\import\apple-products.json
python -m scripts.import_data products ..\data\import\xiaomi-products.json
python -m scripts.import_data prices ..\data\import\apple-prices.json
python -m scripts.import_data prices ..\data\import\xiaomi-prices.json
```

也可以在网页“数据管理”中依次选择“商品”和“价格快照”上传对应文件。

## 数据边界

- 价格是采集时快照，默认 24 小时后标记为过期，导入前应再次打开 `product_url` 核对。
- 小米不同地区的型号和配置可能不同。手机、平板、手表、耳机规格来自 `mi.com` 官方区域或全球规格页，价格来自小米中国大陆官网。
- REDMI Book Pro 16 2026 的大陆官网静态页面未暴露完整配置组合，因此仅录入已确认字段。
- `smartwatch` 是本次新增的品类，评分仅覆盖续航、重量、峰值亮度和存储等已采集数值，不代表健康功能或整体质量。
