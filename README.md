# Storewright

面向电商独立站建站与运营的本地工具集合。仓库按业务能力组织，每个工具保持独立的依赖、配置、测试和运行文档。

## 目录

```text
tools/
├── product-research/  # 选品、商品发现与市场验证
├── store-building/    # 店铺初始化、主题、内容与上架工具
└── operations/        # 日常运营、监控、分析与维护工具
shared/                # 出现稳定的跨工具复用需求后再创建共享模块
```

当前工具：

- [`tools/product-research/catalog-scout`](tools/product-research/catalog-scout)：基于 SerpApi Google Lens 的商品图片筛选与本地归档工具。

## 约定

- 一个工具一个自包含目录，不在仓库根目录共享运行时依赖。
- 配置示例、使用文档和测试跟随工具存放。
- 密钥、本地数据库、浏览器 Profile、运行产物和抓取证据不得提交。
- 只有至少两个工具存在明确且稳定的复用需求时，才提取到 `shared/`。

## StoreWright Catalog Scout

```bash
uv tool install storewright-catalog-scout
mkdir catalog-scout-workspace && cd catalog-scout-workspace
storewright-scout init
```

完整说明见 [`tools/product-research/catalog-scout/README.md`](tools/product-research/catalog-scout/README.md)。
