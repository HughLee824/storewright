# StoreWright Catalog Scout

[![PyPI](https://img.shields.io/pypi/v/storewright-catalog-scout)](https://pypi.org/project/storewright-catalog-scout/)
[![Python](https://img.shields.io/pypi/pyversions/storewright-catalog-scout)](https://pypi.org/project/storewright-catalog-scout/)
[![License](https://img.shields.io/pypi/l/storewright-catalog-scout)](https://opensource.org/license/mit)

StoreWright Catalog Scout 是面向已授权店铺数据的商品图片筛选与本地归档工具。它先用商品列表图调用 SerpApi Google Lens 精确匹配，再决定是否读取并保存完整商品详情；按类目最多保留指定数量的合格商品，并在店铺淘汰率显著过高时提前停止，减少 API、页面访问和存储消耗。

淘宝/天猫是首个数据源。编排、图片检索、判定、数据库和报告均通过通用接口实现，不把淘宝写死为唯一来源。

> 工具不会绕过登录、验证码、滑块或平台风控，不包含 stealth、代理轮换或指纹伪装。真实任务只可用于你拥有、控制或明确获授权访问的数据。SerpApi 会收到公开商品图片 URL；仅在机械导航失败时，页面状态才可能发送给配置的 Browser Use/DeepSeek 模型。

## 工作流

```text
shops.csv
  → 发现并确定性打乱商品
  → 列表图 Serp 精确匹配
      → 外部精确匹配：淘汰，只保留最小审计证据
      → 无精确匹配：保存 screened_qualified，不立即打开详情
  → 每次成功判断后更新店铺淘汰率
  → Wilson 下界超过阈值：提前淘汰店铺并停止剩余处理
  → 全店列表图预筛完成后，按标题临时分类并限制候选数
  → 候选详情页固定间隔 30 秒，每件完成后立即持久化检查点
      → 详情主图变化：再次 Serp
      → 类目未满：保存完整详情和可识别商品图
      → 登录/验证/阻断页：立即 paused，不自动重试
```

核心决策全部是确定性规则。DeepSeek 只在固定商品列表 URL 无法直接打开时作为导航后备，不参与逐商品判定。

## 安装

包已发布到 [PyPI](https://pypi.org/project/storewright-catalog-scout/)。需要本机 Chrome。推荐使用 `uv tool` 安装；`uv` 会为命令创建隔离环境，并在需要时安装兼容的 Python。

```bash
uv tool install storewright-catalog-scout
storewright-scout --help

mkdir catalog-scout-workspace
cd catalog-scout-workspace
storewright-scout init
```

`init` 会创建当前工作目录下的 `.env`、SQLite 数据库和运行目录，不会覆盖已有 `.env`。填写至少一个 SerpApi Key 后即可运行。升级使用：

```bash
uv tool upgrade storewright-catalog-scout
```

## 输入 CSV

`shops.csv` 只需要一个字段，可提供多个店铺：

```csv
shop_url
https://shop-a.taobao.com/
https://shop-b.tmall.com/
```

空 URL 会报错，重复 URL 会去重。店铺名称和 ID 自动识别。

## 配置

关键配置：

```env
SERPAPI_API_KEYS=key-a,key-b,key-c

MAX_POOL_SIZE=2000
MAX_QUALIFIED_PRODUCTS_PER_CATEGORY=20
SHOP_REJECT_RATE_THRESHOLD=0.60
EARLY_STOP_MIN_SEARCHES=10
EARLY_STOP_CONFIDENCE=0.90
MAX_SEARCH_ERROR_RATE=0.20
MAX_DETAIL_PRODUCTS_PER_BATCH=0  # 0 表示本次命令不中途按数量暂停
DETAIL_PAGE_INTERVAL_SECONDS=30
PAUSE_AFTER_SCREENING=false
```

每次 SerpApi 查询都会随机排列 Key 池并选择一个 Key。若该 Key 鉴权失败、额度耗尽或触发限流，程序会自动尝试池内其他 Key；仅当全部 Key 均不可用时，当前查询才失败。配置中的空项和重复 Key 会自动清理。

淘汰率只使用成功判定作为分母：

```text
精确匹配淘汰数 / 成功图片检索数
```

至少成功搜索 10 件后才允许提前淘汰。默认使用 90% Wilson 置信区间，下界达到 60% 才停止；最终完成时实际淘汰率达到 60% 也会淘汰店铺。检索错误率超过 20% 或商品发现被安全上限截断时进入人工复核。

### DeepSeek 导航后备

```env
BROWSER_USE_PROVIDER=deepseek
BROWSER_USE_MODEL=deepseek-chat
BROWSER_USE_VISION_MODE=false
DEEPSEEK_API_KEY=your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

程序优先通过 SourceAdapter 生成商品列表 URL，并用 Playwright 直接打开和机械验证。只有失败时才调用 Browser Use + DeepSeek。

## 运行

先在专用 Chrome Profile 手工登录并诊断：

```bash
storewright-scout browser login
storewright-scout browser diagnose
```

完全离线 Mock E2E：

```bash
storewright-scout run \
  --shops shops.csv \
  --seed 20260718 \
  --mock-vision \
  --confirm-authorized
```

真实运行：

```bash
storewright-scout run \
  --shops shops.csv \
  --seed 20260718 \
  --confirm-authorized
```

恢复与报告：

```bash
storewright-scout resume --run-id <uuid> --confirm-authorized
storewright-scout report --run-id <uuid>
storewright-scout rebuild-archives --run-id <uuid>
storewright-scout review list --run-id <uuid>
```

`rebuild-archives` 只读取已保存的 HTML，离线补齐结构化价格、属性和 SKU，重建扁平图片目录，不启动浏览器或调用 SerpApi。

成功的查询按 `(provider, normalized_image_sha256, variant)` 缓存；相同图片不会重复消耗 SerpApi。处理顺序由运行 seed 和店铺 canonical key 决定，恢复后保持不变。

一次已授权的 `run/resume` 默认连续处理剩余详情，不要求每 5 件重新授权。每件商品独立提交 SQLite，因此仍可从任意检查点恢复。只有显式配置正数 `MAX_DETAIL_PRODUCTS_PER_BATCH`、检测到登录/验证/阻断页或发生真实错误时才暂停；程序不会尝试处理安全验证。

## 本地输出

```text
runtime/artifacts/<run_id>/
├── shops.csv
├── products.csv
├── summary.json
├── report.html
├── vision/
└── shops/<shop_key>/products/<item_id>/
    ├── screening-listing/
    ├── screening-detail/
    ├── product.json       # 仅合格且类目未满的商品
    ├── images/            # 001-main.jpg、002-gallery.jpg、003-sku.jpg ...
    └── evidence/
        ├── raw.html
        ├── image-sources.json
        └── original-images/
```

`images/` 只包含按结构化来源筛选、SHA-256/pHash 去重且通过尺寸校验的商品图，不创建逐图子目录。原始页面和图片来源信息放在 `evidence/`，避免干扰人工挑图。

被淘汰商品保留商品 ID、URL、列表图和 Serp 证据，不保存完整详情资产，因此不需要删除文件。商品状态包括：

- `qualified`
- `screened_qualified`
- `rejected`
- `review`
- `skipped_category_quota_reached`
- `skipped_after_shop_rejected`

## 判定边界

- 自身商品、同店页面和图片 CDN 不作为外部精确匹配。
- 外部页面完整图片匹配会淘汰商品。
- 无法映射到外部页面的完整图、局部匹配和搜索错误进入复核。
- `NO_INDEXED_MATCH_FOUND` 只表示当前 provider 没有返回精确匹配，不证明互联网不存在同款。
- 图片匹配不证明 SKU、材质、质量或知识产权相同。

## 扩展其他平台

新增数据源时实现 `SourceAdapter` 与 `CatalogBackend`：

- 店铺和商品 URL 识别；
- 商品列表入口与 DOM 提取；
- 商品详情结构化解析；
- 自身商品/同店/外部 URL 关系分类；
- 页面和图片获取。

Serp provider、规则引擎、类目配额、店铺止损、SQLite 与报告无需依赖淘宝。

## 源码开发

```bash
git clone https://github.com/HughLee824/storewright.git
cd storewright/tools/product-research/catalog-scout
uv sync
```

## 质量检查

```bash
uv run ruff check .
uv run pyright
uv run pytest --cov=storewright_catalog_scout
```

发布流程见 [`RELEASING.md`](https://github.com/HughLee824/storewright/blob/main/tools/product-research/catalog-scout/RELEASING.md)，版本变化见 [`CHANGELOG.md`](https://github.com/HughLee824/storewright/blob/main/tools/product-research/catalog-scout/CHANGELOG.md)。本项目使用 [MIT License](https://github.com/HughLee824/storewright/blob/main/tools/product-research/catalog-scout/LICENSE)。

## 已知限制

- 列表图与详情主图不同会多使用一次 Serp 查询。
- 所有列表图预筛先完成，详情页只按受控速率访问；公开图片下载使用独立 HTTP 客户端，不携带浏览器 Cookie。
- 类目通常在详情页才能可靠获得，因此部分已通过预筛的商品仍需轻量读取详情后才能判断类目名额。
- 页面可识别字段会随平台模板变化；原始 HTML 和结构化数据会随合格商品一起保存，便于重新解析。
- 达到 `MAX_POOL_SIZE` 会标记目录不完整并进入复核，不会声称覆盖全店。
- 不执行购买、收藏、联系卖家或 Shopify 导入。
