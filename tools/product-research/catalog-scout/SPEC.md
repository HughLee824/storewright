# StoreWright Catalog Scout 流式筛选规范

## 1. 目标

从若干已授权候选店铺发现商品，先使用公开列表图执行外部精确图片匹配；仅对通过筛选且类目名额未满的商品保存完整详情与图片。根据已处理商品的淘汰率动态淘汰店铺，减少 Serp、页面访问和存储消耗。

## 2. 输入

CSV 唯一必需列：

```csv
shop_url
https://authorized-shop.taobao.com/
```

允许多个店铺。空 URL 报错；重复 URL 去重。策略参数由环境或 CLI 控制，不放入 CSV。

## 3. 流程

1. 识别并规范化店铺 URL。
2. 优先机械打开完整商品列表；失败时才允许受限导航 agent 介入。
3. 发现商品 ID、URL、标题、列表图并去重。
4. 使用固定 seed 确定性打乱商品顺序。
5. 第一阶段对每件商品：
   - 下载并规范化一张列表图作为审计证据；
   - 复用 SHA-256 Vision 缓存或调用 Serp exact match；
   - 外部精确匹配则淘汰，不抓详情；
   - 局部、未映射或错误进入复核；
   - 无精确匹配则保存 `SCREENED_QUALIFIED`，不打开详情页；
   - 每次成功判定后更新店铺统计并检查提前止损。
6. 全店列表图预筛完成后，按标题关键词做确定性临时分类，每类最多预留配置数量的候选。
7. 第二阶段按受控速率处理候选详情：
   - 详情访问之间默认固定间隔 30 秒；
   - 详情主图不同则再次筛选；
   - 取得原始类目并检查配额；
   - 类目未满才保存详情 JSON、原始 HTML 和所有可验证商品图；
   - 每件商品独立提交数据库；可选正数批次上限，默认 0 表示不中途按数量暂停；
   - 登录、验证或阻断页立即暂停整个 run，不得自动重试。
8. 输出 SQLite、CSV、JSON 和离线 HTML 报告。

## 4. 确定性判定

Agent 不得参与以下决定：

- exact match 判定；
- 自身/同店/外部关系分类；
- 类目配额；
- 商品状态；
- 淘汰率与店铺决定。

自身商品、同店页面和图片 CDN 不计为外部匹配。外部页面包含完整匹配图片时商品为 `EXACT_EXTERNAL_IMAGE_MATCH`。无法映射的完整图、局部匹配和搜索错误进入 `REVIEW`。

## 5. 类目配额

默认每个规范化类目最多归档 20 件合格商品。达到配额后，同类目后续商品状态为 `SKIPPED_CATEGORY_QUOTA_REACHED`。被跳过商品保留最小审计记录，不保存完整详情资产。

## 6. 店铺止损

```text
rejection_rate = exact_count / search_success_count
```

默认参数：

- `SHOP_REJECT_RATE_THRESHOLD=0.60`
- `EARLY_STOP_MIN_SEARCHES=10`
- `EARLY_STOP_CONFIDENCE=0.90`
- `MAX_SEARCH_ERROR_RATE=0.20`
- `MAX_DETAIL_PRODUCTS_PER_BATCH=5`
- `DETAIL_PAGE_INTERVAL_SECONDS=60`
- `DETAIL_PAGE_INTERVAL_JITTER_SECONDS=15`
- `DETAIL_PAGE_MAX_PER_HOUR=20`
- `DETAIL_RISK_COOLDOWN_SECONDS=900`
- `DETAIL_RISK_MAX_COOLDOWN_SECONDS=21600`
- `PAUSE_AFTER_SCREENING=true`

成功搜索至少达到最小数量后，若淘汰率的 Wilson 置信区间下界达到阈值，店铺立即 `REJECTED`，剩余商品标记 `SKIPPED_AFTER_SHOP_REJECTED`。未提前停止时，最终实际淘汰率达到阈值也淘汰。目录截断或错误率过高进入 `REVIEW`。

## 7. 商品归档

合格商品保存：

- 商品 ID、URL、标题；
- 描述、原始类目路径、材质、属性；
- 展示价、划线价、SKU 最低/最高价、币种、规格/变体；
- 主图及可识别轮播/详情图；
- 原始 HTML、结构化 JSON；
- 图片 URL、SHA-256、pHash、尺寸和本地路径。

人工图片目录必须扁平化，并按 `main/gallery/sku/detail` 标注角色。图片候选优先来自数据源的结构化商品字段；整页 `<img>` 仅作为无结构化数据时的后备。下载失败不得残留文件，同商品内按 SHA-256 和 pHash 去重，页面 Logo、活动素材、评价图和推荐商品图不得进入人工图片目录。原始 HTML、原图和来源清单隔离保存在 `evidence/`。

`rebuild-archives` 必须能够只使用已保存 HTML 和图片离线重解析已有合格商品，不产生浏览器或 Vision 请求。

淘汰或跳过商品只保存商品身份、列表图审计证据、verdict 和外部匹配证据，不需要删除动作。

## 8. 数据与恢复

SQLite 是唯一状态事实来源。商品顺序、阶段、verdict、详情快照、图片资产、Vision 查询、证据和店铺统计必须持久化。成功 Vision 查询按 provider、规范化图片 SHA-256 和 variant 唯一缓存。`resume` 只处理未终止状态。

## 9. 通用性

核心依赖两个边界：

- `SourceAdapter`：URL 身份、HTML 解析、关系分类；
- `CatalogBackend`：列表、详情页面和图片获取。

淘宝/天猫是首个实现，不得在规则、数据库、Vision 或报告中作为唯一源硬编码。

## 10. 安全

不得绕过登录、验证码、滑块或安全验证，不得实现 stealth、代理轮换或指纹伪装。真实运行必须显式 `--confirm-authorized`。不得记录 Cookie、Authorization、API key 或服务账号内容。

公开列表图和商品图使用独立 HTTP 客户端下载，不携带浏览器登录 Cookie。一次显式授权的命令可以连续处理详情，但遇到登录、验证或阻断页必须立即停止，且不得自动重试。

## 11. 验收

- 仅含 `shop_url` 的多店 CSV 可运行和去重；
- Mock 流程覆盖合格归档、精确匹配淘汰、类目配额和提前止损；
- Mock 流程覆盖列表图全量预筛、详情批次暂停及登录重定向整 run 暂停；
- 详情主图变化可触发第二次筛选；
- crash/resume 不改变商品顺序且复用 Vision 缓存；
- 报告计数与数据库一致；
- Ruff、Pyright、pytest 和核心覆盖率门通过。
