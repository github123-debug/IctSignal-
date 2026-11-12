# ICT Telegram 信号选币程序

按以下不可跳步的顺序扫描 USDT 永续合约，并在序列完整时发送 Telegram：

```text
流动性触及 -> 15M 收盘 BOS -> 回踩仍有效的 1H FVG -> Telegram
```

程序只发信号，不下单。实时扫描和历史回放共用同一套 FVG、摆动点、BOS、超时、冷却及去重逻辑。

## 已实现规则

- 只用已收盘 K 线识别 1H FVG、15M 摆动点和 BOS。
- PDH/PDL、PWH/PWL 和动态 Day High/Day Low 流动性水平。
- 左右各 2 根的严格摆动点，以及 ATR(14) 同向摆动点距离过滤。
- 每个币对独立的 `IDLE -> LIQUIDITY_TOUCHED -> BOS_CONFIRMED -> SIGNAL_FIRED` 状态机。
- 等待 BOS 16 根 15M、等待回踩 8 根 15M、信号后 5 根 15M 冷却。
- FVG、信号指纹和流动性水平三层去重，SQLite 持久化，重启不重发。
- 首次上线只建立实时基线，不把启动前的历史形态当成新信号补发。
- 默认扫描 Gate USDT 永续合约 24h 成交额前 50 名，也可固定合约。
- 支持 Gate 或 Binance 历史行情回放，不发送 Telegram。

## FVG 方向说明

交付规格中的方向公式与常见 ICT 命名相反。程序支持两种模式：

- `FVG_DEFINITION=document`：严格遵循交付规格，`C.high < A.low` 记为 Bullish/Long；这是默认值。
- `FVG_DEFINITION=classic`：常见 ICT 命名，`C.low > A.high` 记为 Bullish/Long。

上线前必须确认使用哪一种，修改 `.env` 后即可切换，其他逻辑不变。

## 安装

需要 Python 3.11 或更高版本。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install ".[dev]"
Copy-Item .env.example .env
```

## 配置

编辑 `.env`。固定扫描币对时填写：

```dotenv
MARKET_DATA_SOURCE=gate
SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT
```

自动选币时让 `SYMBOLS` 留空，并设置：

```dotenv
TOP_N=50
MIN_QUOTE_VOLUME_USDT=10000000
```

启用 Telegram：

```dotenv
TELEGRAM_ENABLED=true
TG_BOT_TOKEN=从_BotFather_取得的_token
TG_CHAT_ID=目标用户_群组或频道_ID
```

私聊场景中，接收者必须先给 Bot 发过消息。群组/频道场景中，需要先把 Bot 加入目标并赋予发消息权限。不要把真实 Token 提交到版本库。

## 使用

连接检查并执行一轮扫描：

```powershell
ict-signal live --once
```

持续扫描：

```powershell
ict-signal live
```

启动可视化监控台：

```powershell
ict-signal dashboard --host 127.0.0.1 --port 8000
```

浏览器打开 `http://127.0.0.1:8000`。监控台提供扫描状态、合约状态机、信号历史、运行日志、安全配置视图，以及扫描器启动、停止和重启控制。默认只监听本机地址，不会向局域网或公网暴露 Telegram 配置。

查看最近持久化的信号：

```powershell
ict-signal signals --limit 20
```

回放一段 UTC 历史数据：

```powershell
ict-signal replay --symbol BTCUSDT --start 2026-07-01T00:00:00Z --end 2026-07-03T00:00:00Z
```

回放只打印信号，不写入生产数据库，也不会发送 Telegram。

## 测试

```powershell
python -m pytest
```

测试覆盖 FVG 定义/回补/过期、流动性容差、ATR 摆动点、收盘 BOS、严格事件顺序、两段超时、全局冷却、日内水平冷却、消息字段以及 SQLite 重启去重。

## 部署注意

- 当前机器可直接访问 Gate 公开行情接口；Gate 数据源无需 API Key，也没有下单权限。
- Gate 自动选币包含其全部 USDT 永续合约，包括 `NVDA`、`XAU`、`SOXL` 等代币化合约。
- 当前运行机器访问 Binance 返回 HTTP 451；如切回 Binance，需使用能够合法访问该接口的网络环境。
- 一分钟扫描 50 个币对会持续访问公开行情接口。若扩大范围，应同步调整 `POLL_SECONDS` 和 `MAX_CONCURRENCY`，并观察限流响应。
- 同一根 1M K 线同时触及上下流动性时，OHLC 数据无法还原真实先后顺序；程序以距该 K 线开盘价较近的一侧作为确定性起点。若必须获得逐笔先后顺序，需要增加 WebSocket 成交流适配器。
- 所有业务时间边界使用 UTC；日志时间由部署主机时区决定。

"# IctSignal-" 
