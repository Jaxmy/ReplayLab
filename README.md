# Replay Lab 本地交易练习与回测平台

Replay Lab 是一套运行在 Windows 本机的历史行情练习工具。它把手动逐根回放、模拟下单、图表指标和 Python 策略放在同一个界面里。浏览器和 VS Code 使用同一份本地服务与前端；行情、练习记录、策略文件和报告都保存在项目目录。

> 本软件只做研究和模拟，不连接券商或交易所下单。模拟结果不构成投资建议，也不保证与真实交易的成交、保证金或成本一致。

## 下载与安装

可直接下载 [main 分支源码 ZIP](https://github.com/Jaxmy/ReplayLab/archive/refs/heads/main.zip)，解压到有写入权限的文件夹，再运行 `setup.ps1` 安装依赖、生成图表资源和 VS Code 扩展安装包。如果 Releases 提供 `Replay-Lab-v0.3.1-windows-x64.zip`，其中另含预先构建的扩展包。源码和发布包均不包含个人历史行情数据库与练习记录。

需要 Windows 10/11、Python 3.12 或 3.13、Node.js 18 或更新版本（含 npm），并联网完成首次依赖安装。Node.js 用于安装图表库、构建 VS Code 扩展和解码中国指数历史数据。

在解压目录打开 PowerShell，执行一次：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
./setup.ps1
```

脚本会在项目目录创建 `.venv`，并按 `requirements-lock.txt` 安装 Python 依赖。数据更新需要联网；行情服务只监听本机 `127.0.0.1`。之后可以双击 `start-browser.cmd`，或在 VS Code 使用下文的方式启动。

也可以从源码安装：

```powershell
git clone https://github.com/Jaxmy/ReplayLab.git
cd ReplayLab
Set-ExecutionPolicy -Scope Process Bypass
./setup.ps1
```

## 启动方式

**浏览器：**双击 `start-browser.cmd`，应用会启动本地服务并打开 <http://127.0.0.1:8765/>。也可以先启动服务，再手动访问该地址。

**VS Code：**先打开项目目录，再安装 `vscode/local-replay-lab-0.3.1.vsix`。首次运行 `setup.ps1` 会安装依赖并构建这个扩展包。可在 PowerShell 执行：

```powershell
code --install-extension .\vscode\local-replay-lab-0.3.1.vsix --force
```

双击 `start-vscode.cmd` 打开项目，按 `Ctrl+Shift+P`，运行 **Replay Lab: 打开本地交易练习**。如果已打开旧版面板，先运行 **Developer: Reload Window / 开发人员: 重新加载窗口**，再重新打开面板。

两种入口共享 `http://127.0.0.1:8765` 服务。退出前保存记录；运行 `powershell -NoProfile -File .\stop.ps1` 停止由启动脚本创建的服务。关闭浏览器或面板不会删除本地文件。

## 第一次使用与手动回放

首次打开时，服务会在后台从公开数据源下载或更新行情。点开左侧“数据下载与更新”查看任务；首次完整下载可能需要一段时间。下载文件按月保存在 `data/market/`，原始归档保存在 `data/raw/`，来源和覆盖范围写入 `data/downloaded-assets.json`。网络失败时保留已下载的部分，下次启动继续尝试。

1. 在 Session/记录设置选择资产、数据基础粒度、练习起止时间和初始资金。结束时间不包含在区间内；可按资产类别随机挑选覆盖该时间段的资产。
2. 选择图表显示周期和指标。基础数据是 1 分钟时可查看 1 分钟及以上周期；基础数据是 1 小时时可查看小时及以上周期；日线可聚合成周线和月线。自定义周期示例：`7m`、`2h`。练习最多 93 天分钟数据或 100 年日线数据。
3. 在图表上左键拖动平移，使用滚轮缩放；拖动价格轴可调整纵向比例。副图与主图时间对齐。切换显示周期只改变图表聚合方式，播放和成交仍按数据基础粒度逐根推进。
4. 在图表下方输入下单金额，选择投入保证金或名义成交额、方向、杠杆和订单类型，然后点击买入或卖出。保证金模式下，名义成交额约等于保证金乘杠杆；1 倍杠杆没有额外借入资金。成交数量按下一根实际成交 K 线的价格计算并按最小单位向下取整，手续费另计。条件单可能在后续 K 线触发。
5. 在底部标签页查看持仓、策略、报告和新闻。记录会自动保存，默认名称由资产、周期和序号组成；可重命名。恢复会继续原记录，分支会建立新记录。

模拟账户采用逐仓保证金，多空可独立持仓；关闭双向持仓时，对向订单先抵消原仓位。杠杆变化只影响保证金需求，不会自动改变持仓数量。中国资产以 CNY 模拟计价，其他类别以 USD 模拟计价；指数使用合成合约，按 1 点等于 1 CNY/USD 计算，日韩指数没有使用历史汇率转换。加密货币的 USDT 按 1 USD 处理。

## 指标、策略与报告

指标菜单包含 SMA、EMA、WMA、DEMA、TEMA、HMA、布林带、唐奇安通道、肯特纳通道、VWAP、VWMA、RSI、MACD、KDJ、StochRSI、ATR、ADX/DI、CCI、Williams %R、ROC、Momentum、OBV、MFI、CMF、A/D、成交量、成交量均线、TRIX、PPO、DPO、标准差、布林带宽、%B、Aroon、CHOP、Supertrend、SAR 和一目均衡。每个指标实例可改参数、颜色和显示位置；复制后可用不同周期叠加比较。每条记录最多 30 个指标实例。无真实成交量的指数不能提供有效量能指标。

策略使用 Python。底部“策略”标签页可选择内置均线、海龟、网格和剥头皮模板，编辑真实 `.py` 文件、设置参数后启用，并按时间逐步或快速回测。最小策略示例：

```python
def on_bar(ctx, state):
    # ctx 中的 bars 只包含已经收盘的 K 线。
    if ctx.get("positions") or ctx.get("pending"):
        return []
    closes = [bar["close"] for bar in ctx["bars"]]
    if len(closes) < 20:
        return []
    fast = sum(closes[-5:]) / 5
    slow = sum(closes[-20:]) / 20
    if fast > slow:
        return [{"action": "long", "amount": 100, "amount_mode": "margin", "leverage": 2}]
    return []
```

策略返回的订单会在下一根可成交 K 线上处理。也可用 `quantity` 指定标的单位；成交金额模式用 `amount` 和 `amount_mode`。`state` 必须可以编码为 JSON。策略代码以本机 Python 进程运行，请只启用自己信任的代码；进程隔离不等同于恶意代码沙箱。

回测报告可导出 PNG、独立 HTML、JSON 和事件 CSV。图表包括净值和回撤；报告记录手续费、滑点、资金费/借贷设置及收益风险指标。夏普使用日频收益，样本不足时不计算；年化收益至少需要 30 天数据。报告文件默认保存到 `reports/`，浏览器会触发下载，VS Code 也可以选择保存位置。

## 行情来源和覆盖

|类别|资产示例|公开数据来源|可用基础粒度|
|---|---|---|---|
|加密货币现货|BTC、ETH、BNB|Binance 官方历史归档与 REST 增量|1 分钟，支持更高周期|
|加密货币永续|HYPEUSDT|Bybit 线性永续 K 线|1 分钟，上市后的可用历史|
|中国指数|上证、深证、创业板、沪深 300、中证 500、上证 50|新浪日线；Yahoo 近期分时|日线长历史；1 分钟/1 小时近期数据|
|美国指数|标普 500、纳斯达克、道琼斯、罗素 2000|Yahoo 公开图表接口|日线长历史；1 分钟/1 小时近期数据|
|日本和韩国指数|日经 225、KOSPI、KOSDAQ|Yahoo 公开图表接口|日线长历史；1 分钟/1 小时近期数据|

来源、最近更新时间和精确起止时间以本机“数据下载与更新”面板及 `data/downloaded-assets.json` 为准。公开接口可能限流或调整；分时覆盖短于日线历史时，应用分别展示，不会拿日线补造分钟 K 线。部分指数没有真实成交量。付费历史数据适配器已预留为手动导入方式；没有自动购买或调用付费数据。购买前需自行确认具体资产、指数权限、粒度和历史覆盖。

## 添加新的资产和数据源

### 使用现成 CSV 添加一项本地资产

将 CSV 放入项目目录，例如 `data/custom/my_asset.csv`，至少提供时间、`open`、`high`、`low`、`close`、`volume` 六列。时间列应统一时区；没有时区的时间由 `timezone` 指定。时间必须升序且不能重复，价格需为有限正数，最高价和最低价应覆盖该 K 线的开收盘价，成交量不能为负。

复制 `config/assets.example.json` 为 `config/assets.json`，填入一项配置：

```json
[
  {
    "adapter": "csv",
    "id": "MY_ASSET",
    "name": "我的资产",
    "category": "crypto",
    "source": "data/custom/my_asset.csv",
    "time_column": "timestamp",
    "timezone": "UTC",
    "start": "2024-01-01T00:00:00Z",
    "end": "2025-01-01T00:00:00Z",
    "base": "1m",
    "currency": "USD",
    "price_precision": 2,
    "size_precision": 6,
    "multiplier": 1,
    "lot": 0.000001,
    "year_days": 365,
    "calendar": "24/7 UTC",
    "research_only": true,
    "allow_gaps": false,
    "note": "注明数据来源和合约假设",
    "default_fee": 0.0005,
    "default_slippage": 0.0002
  }
]
```

`id` 必须唯一。`category` 可用 `crypto`、`index_cn`、`index_us`、`index_jp`、`index_kr`、`etf`、`futures` 或自定义类别；类别影响随机资产筛选和模拟计价，`index_cn` 以 CNY 计价，其余默认按 USD 计价。`base` 目前为 `1m`、`1h` 或 `1d`；更粗周期可以从基础数据聚合。源数据有正常休市间隔时设置 `allow_gaps: true`，不要在缺少成交记录时伪造 K 线。重启服务后新资产会出现在选择列表中。

### 接入自动下载或新的格式

通用数据接口位于 `app/data.py`。新适配器实现 `DataAdapter` 的 `read(start, end, warmup)` 和 `fingerprint()`，在 `PROVIDERS` 注册，并返回 UTC 时间索引的 OHLCV DataFrame。每根数据至少有 `open`、`high`、`low`、`close`、`volume` 五列；索引升序且唯一。增加自动更新器时，在 `app/market_data.py` 中把下载、时间单位转换、去重和校验分开实现，按月写入 `data/market/<asset>/<base>/YYYY-MM.parquet`。调用 `metadata(...)` 或 `register(...)` 更新 `data/downloaded-assets.json`，界面和资产选择器便能发现新数据。

对有交易日和休市缺口的市场，设置 `allow_gaps: true` 并提供真实交易日 K 线；对于 1 分钟市场，现有练习器要求连续覆盖所选区间，或由适配器正确声明交易日间隔。新类别若需要特殊合约乘数、交易日历、复权或货币换算，应在适配器中明确处理并在 `note` 写清假设。完成后检查“数据下载与更新”显示的来源、基础粒度、覆盖日期和存储路径。

新闻是可选标题事件包。JSON 数组中的事件至少有 `title`、带时区的 `known_at`；可选 `published_at`、`source`、`asset`。系统按 `known_at` 揭示事件，避免回放时提前看到尚未公开的新闻。

## 配置和文件位置

- `data/market/`：按资产、基础粒度、月份保存的 Parquet 行情。
- `data/raw/`：下载的原始 ZIP 或源文件。
- `data/downloaded-assets.json`：来源、粒度、时间覆盖、更新时间和本机存储位置。
- `config/assets.json`：用户自行添加的 CSV 资产，默认不纳入 Git。
- `sessions/`：手动练习与策略回测记录；`sessions/code/` 保存策略代码快照。
- `reports/`：导出的 PNG、HTML、JSON、CSV 报告。
- `strategies/`：可编辑 Python 策略模板。

修改手续费、滑点、初始资金和杠杆等参数时，记录会保存本次练习使用的设置。0.2 记录仍使用原记录保存的数据源和计价单位；0.1 记录与当前账户模型不兼容，原文件不会自动删除。

## 成本与模型边界

手续费、滑点、强平费、固定资金费率和借贷年利率可在新记录参数中设置；默认值是通用模拟值，不代表任一交易所费率。该引擎用于练习，不模拟真实盘口深度、部分成交、动态资金费、真实借券库存、股票 T+1、税费、分红、合约换月或全部交易所强平规则。日韩指数点值按合成美元合约处理，结果不能直接当作当地货币收益。

## 开发和许可

Python 依赖版本锁在 `requirements-lock.txt`；图表库由 `package-lock.json` 固定并在首次安装时复制到 `web/` 和 `vscode/media/`。前端资源由浏览器和 VS Code 共用。开发者可运行：

```powershell
./.venv/Scripts/python.exe -m pytest -q
npm test
node ./tests/extension-smoke.cjs
./.venv/Scripts/python.exe -m scripts.audit_v03
```

项目源码采用根目录 `LICENSE` 中的 MIT 许可。第三方组件和行情来源说明见 `THIRD_PARTY_NOTICES.md`。市场数据由各来源方提供；请遵守来源的使用和再分发条款。使用该项目即表示你了解它只产生本地模拟结果。


## v0.3.1 更新与记录管理

升级时先运行 `./stop.ps1`，更新源码后执行 `./setup.ps1`。VS Code 用户重新安装 `vscode/local-replay-lab-0.3.1.vsix`，再执行“Developer: Reload Window”；浏览器刷新页面。旧版 0.2/0.3.0 记录仍可恢复。

指标支持在开始练习前添加、复制、调整、应用；设置随新练习保存。操作会按顺序处理，侧栏和交易栏均显示进度或错误。新建失败时保留当前练习；切换资产会将无效日期调整到该资产的可用范围。

开始前可设置“练习前历史 / 基础 K 线根数”，默认 300，范围 1–5000。新练习立即展示开始时间之前已经收盘的量价与指标；回放进度和收益从选定练习时段开始，历史预览不会自动下单。若本地历史不足，会提示并显示全部可用历史；分钟、小时、日线数据均按各自基础粒度计算。切换高周期后仅聚合当前已知数据。

展开“历史记录（选择 / 批量管理）”，可勾选若干条或全选，再点击“删除已勾选”并确认永久删除。删除会移除记录 JSON、对应旧版备份，以及不再被其他记录使用的策略快照；选中的活动练习会关闭，批量回测进行中的记录须先取消任务。导出的报告单独保留在 `reports/`。此操作无法在应用内撤销。

`npm test` 使用临时合成数据与隔离服务，逐项验证浏览器 HTTP 和 VS Code 消息桥两种路径的按钮绑定、指标增删改、下单平仓、策略、批量回测、恢复、导出和批量删除。图表绘制由浏览器实测另行验证。
