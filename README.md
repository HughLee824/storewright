# StoreWright

StoreWright 是面向电商独立站建站与运营的本地工具集合。仓库按业务能力组织，每个工具拥有独立的依赖、配置、测试和使用文档。

当前可用工具是 [StoreWright Catalog Scout](tools/product-research/catalog-scout)：一个可审计、可恢复的商品图片筛选与本地归档 CLI。它使用 SerpApi Google Lens 检查外部精确匹配，只为通过筛选的商品保存完整详情和图片。目前支持淘宝、天猫店铺，包已发布到 [PyPI](https://pypi.org/project/storewright-catalog-scout/)。

> 仅可处理你拥有、控制或明确获授权访问的数据。工具不会绕过登录、验证码、滑块或平台风控，也不会执行购买、收藏、联系卖家或 Shopify 导入。

## 功能概览

- 从 CSV 批量读取已授权店铺，自动去重；
- 确定性打乱商品顺序，支持固定 seed 和断点恢复；
- 使用 SerpApi Google Lens 筛除存在外部精确匹配的商品；
- 按类目限制合格商品数量，并在店铺淘汰率过高时提前停止；
- 将 SQLite 检查点、CSV、JSON、HTML 报告、商品图和审计证据保存到本地；
- 支持离线 Mock 验收、报告重建和人工复核列表。

## 环境要求

| 项目 | 要求 | 用途 |
| --- | --- | --- |
| 操作系统 | macOS、Linux 或 Windows | 运行 CLI |
| Python | 3.12 或 3.13 | `uv tool` 可管理隔离的 Python 环境 |
| Chrome/Chromium | 真实任务必需 | 使用独立 Profile 保存手工登录状态 |
| SerpApi Key | 真实任务必需 | 调用 Google Lens 图片检索 |
| DeepSeek Key | 可选 | 固定商品列表 URL 无法机械打开时的导航后备 |

推荐先安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)，然后确认命令可用：

```bash
uv --version
```

## 安装

### 使用 Agent 自动安装（适合非技术用户）

仓库内置两个跨 Codex 与 Claude Code 的 Skill：

| Skill | 用途 |
| --- | --- |
| `storewright-setup` | 安装、升级、初始化、环境诊断和离线验收 |
| `storewright-scout` | 准备店铺清单、运行或恢复筛选、生成报告并解释结果 |

若本机已有 Node.js/npm，可以通过公开仓库全局安装；命令会自动检测已安装的 Agent 并让你选择：

```bash
npx skills add HughLee824/storewright \
  --skill storewright-setup \
  --skill storewright-scout \
  --global
```

同时安装到 Codex 和 Claude Code，并跳过交互确认：

```bash
npx skills add HughLee824/storewright \
  --skill storewright-setup \
  --skill storewright-scout \
  --global \
  --agent codex \
  --agent claude-code \
  --yes
```

如果已经克隆并在 StoreWright 仓库内打开 Agent，则无需安装：Codex 会从 `.agents/skills/` 自动发现，Claude Code 会从 `.claude/skills/` 自动发现。安装或打开仓库后直接调用：

```text
# Codex
使用 $storewright-setup 帮我安装并初始化 Catalog Scout，完成离线验收；需要登录、填写密钥或授权时再提醒我。

使用 $storewright-scout 帮我筛选这些已授权店铺；我不懂命令行，请你完成可以自动完成的操作，并用简单中文解释报告。

# Claude Code
/storewright-setup 帮我安装并初始化 Catalog Scout，完成离线验收；需要登录、填写密钥或授权时再提醒我。

/storewright-scout 帮我继续上次暂停的筛选任务，并告诉我哪些结果需要人工复核。
```

Agent 会完成环境检查、输入准备、CLI 操作和报告解释，不会读取密钥或未经确认执行真实店铺任务。完整 Skill 源码位于 [`.agents/skills/`](.agents/skills)。

### 方式一：从 PyPI 安装（推荐）

`uv tool` 会为 CLI 创建独立环境，不污染当前项目的 Python 依赖：

```bash
uv tool install --python 3.13 storewright-catalog-scout
storewright-scout --help
```

如果安装成功但终端找不到 `storewright-scout`，执行 `uv tool update-shell`，然后重启终端。升级或卸载：

```bash
uv tool upgrade storewright-catalog-scout
uv tool uninstall storewright-catalog-scout
```

### 方式二：从源码安装（开发者）

```bash
git clone https://github.com/HughLee824/storewright.git
cd storewright/tools/product-research/catalog-scout
uv sync
uv run storewright-scout --help
```

源码模式下，下文的 `storewright-scout` 均可替换为 `uv run storewright-scout`。开发环境的质量检查命令见[源码开发](#源码开发)。

## 快速开始

以下步骤以 PyPI 安装方式为例。所有数据库、配置和运行产物都相对于**当前工作目录**创建，因此建议为任务准备一个固定目录，并始终从该目录执行命令。

### 1. 初始化工作目录

```bash
mkdir catalog-scout-workspace
cd catalog-scout-workspace
storewright-scout init
```

`init` 会执行以下操作：

- 创建 `.env`（如果文件已存在则保留，不会覆盖）；
- 创建 `runtime/`、SQLite 数据库和专用 Chrome Profile 目录；
- 检测本机 Chrome/Chromium；
- 初始化或升级数据库结构。

初始化后的主要目录：

```text
catalog-scout-workspace/
├── .env
├── shops.csv
└── runtime/
    ├── storewright_catalog_scout.db
    ├── chrome-profile/
    └── artifacts/
```

### 2. 配置 API Key

编辑当前目录的 `.env`。真实运行至少需要一个 SerpApi Key，多个 Key 用英文逗号分隔：

```env
SERPAPI_API_KEYS=key-a,key-b,key-c

# 可选：机械导航失败时启用 DeepSeek 后备
DEEPSEEK_API_KEY=
```

如果 Chrome 未被自动识别，设置可执行文件的绝对路径：

```env
CHROME_EXECUTABLE=/absolute/path/to/chrome
```

更多限额、访问间隔和停止策略见[常用配置](#常用配置)。

### 3. 创建店铺清单

在工作目录创建 `shops.csv`。表头必须是 `shop_url`，每行填写一个已授权的淘宝或天猫店铺 URL：

```csv
shop_url
https://shop-a.taobao.com/
https://shop-b.tmall.com/
```

空 URL 会报错，重复 URL 会自动去重；店铺名称和 ID 由程序识别。

### 4. 先运行离线 Mock 验收

Mock 模式不访问店铺、不启动 Chrome、不执行真实详情限速，也不消耗 API Key，用于确认安装、配置目录、数据库和报告生成正常：

```bash
storewright-scout run \
  --shops shops.csv \
  --seed 20260718 \
  --mock-vision
```

成功后终端会输出 `run_id` 和 HTML 报告路径。报告默认位于：

```text
runtime/artifacts/<run_id>/report.html
```

### 5. 登录并诊断浏览器

真实运行前，用工具的专用 Chrome Profile 手工登录：

```bash
storewright-scout browser login
```

在打开的 Chrome 窗口完成登录后，回到终端按 Enter。登录状态保存在 `runtime/chrome-profile/`，后续真实任务会复用它；程序不会读取或打印 Cookie。

如需完整检查 CDP、Playwright 和 Browser Use 连接，请在 `browser login` 仍等待 Enter、Chrome 窗口仍打开时，在第二个终端进入同一工作目录并运行：

```bash
storewright-scout browser diagnose
```

Chrome 关闭后再执行诊断也可以检查路径、Profile、数据库和 API Key 配置，但 CDP、Playwright 和 Browser Use 会显示为未运行或未检查。

### 6. 执行真实筛选

确认 `.env` 已配置 SerpApi Key、Chrome 登录状态有效，并且 `shops.csv` 中的店铺均已获授权：

```bash
storewright-scout run \
  --shops shops.csv \
  --seed 20260718 \
  --confirm-authorized
```

`--confirm-authorized` 是真实任务的必需参数。运行时工具会启动专用 Chrome、处理商品并持续写入 SQLite 检查点；正常结束后会停止本次启动的 Chrome，并输出 `run_id` 与报告路径。

## 后续使用

将下列 `<run_id>` 替换为 `run` 输出的 UUID：

```bash
# 从已保存的检查点继续；真实任务仍需确认授权
storewright-scout resume --run-id <run_id> --confirm-authorized

# 不访问网页，重新生成 CSV、JSON 和 HTML 报告
storewright-scout report --run-id <run_id>

# 只读取已保存的 HTML，重新解析详情并整理商品归档
storewright-scout rebuild-archives --run-id <run_id>

# 查看需要人工复核或数据不足的店铺
storewright-scout review list --run-id <run_id>
```

其他常用选项：

```bash
# 关闭店铺高淘汰率提前停止策略
storewright-scout run \
  --shops shops.csv \
  --confirm-authorized \
  --no-early-stop

# 查看全部命令或某个命令的参数
storewright-scout --help
storewright-scout run --help
```

同一任务应继续使用原工作目录，因为 `.env`、SQLite 数据库、Chrome Profile 和产物路径都位于该目录。移动目录后，使用默认相对路径的旧任务将无法在新位置找到原数据库和归档。

## 常用配置

以下变量写入工作目录的 `.env`：

```env
# Google Lens 检索 Key 池
SERPAPI_API_KEYS=key-a,key-b,key-c

# 每个类目最多保存的合格商品数
MAX_QUALIFIED_PRODUCTS_PER_CATEGORY=20

# 店铺淘汰策略
SHOP_REJECT_RATE_THRESHOLD=0.60
EARLY_STOP_MIN_SEARCHES=10
EARLY_STOP_CONFIDENCE=0.90
MAX_SEARCH_ERROR_RATE=0.20

# 生产安全默认值：先暂停确认，再分批访问详情
MAX_DETAIL_PRODUCTS_PER_BATCH=5
DETAIL_PAGE_INTERVAL_SECONDS=60
DETAIL_PAGE_INTERVAL_JITTER_SECONDS=15
DETAIL_PAGE_MAX_PER_HOUR=20
DETAIL_RISK_COOLDOWN_SECONDS=900
DETAIL_RISK_MAX_COOLDOWN_SECONDS=21600
PAUSE_AFTER_SCREENING=true
```

`init` 会把以上详情保护参数写入新建的 `.env`，但不会覆盖已有文件。详情访问状态持久化在 `runtime/detail-access-state.json`；同一工作区也不允许同时运行多个 `run`、`resume` 或浏览器登录命令。

SerpApi Key 池会自动清理空项和重复项。单个 Key 出现鉴权失败、额度耗尽或限流时，程序会尝试其他 Key；全部不可用时当前查询才失败。

DeepSeek 仅作为机械导航失败时的后备，不参与逐商品判定：

```env
BROWSER_USE_PROVIDER=deepseek
BROWSER_USE_MODEL=deepseek-chat
BROWSER_USE_VISION_MODE=false
DEEPSEEK_API_KEY=your-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
```

完整配置项和算法边界见 [Catalog Scout README](tools/product-research/catalog-scout/README.md)。

## 输出说明

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
    ├── product.json
    ├── images/
    └── evidence/
```

- `report.html`：本次运行的可视化汇总；
- `products.csv`：商品状态和判定结果；
- `product.json`、`images/`：仅为通过筛选且类目未满的商品生成；
- `evidence/`：原始 HTML、图片来源和审计材料；
- SQLite：每件商品独立提交，可用于 `resume` 断点恢复。

`NO_INDEXED_MATCH_FOUND` 仅表示当前检索服务没有返回精确匹配，不证明互联网上不存在同款；图片匹配也不能证明 SKU、材质、质量或知识产权相同。

## 常见问题

### `storewright-scout: command not found`

执行 `uv tool update-shell` 后重启终端，或用 `uv tool run --from storewright-catalog-scout storewright-scout --help` 验证安装。

### `Chrome/Chromium not found`

安装 Chrome，或在 `.env` 中用 `CHROME_EXECUTABLE` 指定可执行文件的绝对路径，再运行 `storewright-scout init` 或 `storewright-scout browser diagnose`。

### `SERPAPI_API_KEYS is required`

真实运行必须在当前工作目录的 `.env` 中配置 `SERPAPI_API_KEYS`。修改后重新执行命令；Mock 模式不需要 Key。

### 页面出现登录、验证码或阻断提示

任务会进入暂停状态且不会自动处理验证。手工确认账号状态后，使用原 `run_id` 执行 `resume`。

## 源码开发

```bash
cd tools/product-research/catalog-scout
uv sync
uv run ruff check .
uv run pyright
uv run pytest --cov=storewright_catalog_scout
```

发布流程见 [RELEASING.md](tools/product-research/catalog-scout/RELEASING.md)，版本变化见 [CHANGELOG.md](tools/product-research/catalog-scout/CHANGELOG.md)。Catalog Scout 使用 [MIT License](tools/product-research/catalog-scout/LICENSE)。

## 仓库结构与约定

```text
tools/
└── product-research/
    └── catalog-scout/  # 当前已发布工具
```

- 一个工具一个自包含目录，不在仓库根目录共享运行时依赖；
- 配置示例、使用文档和测试跟随工具存放；
- 密钥、本地数据库、浏览器 Profile、运行产物和抓取证据不得提交；
- 只有至少两个工具存在明确且稳定的复用需求时，才提取到 `shared/`。
