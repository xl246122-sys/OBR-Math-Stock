# Binance 股票 API 能力核验

核验：2026-10-31（中国时间）。

官方来源：
- https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/ws-streams/market-streams
- https://developers.binance.com/en/docs/catalog/advanced-trading-stocks-trading/api/rest-api/market-data

| 接口 | 字段/类型 | 文档频率/权限 | 实测 |
|---|---|---|---|
| price | s:string,p:string,t:int或null,mp:string | 约3秒；公开WS | VPS握手101并收到消息；开发机15秒收到5条 |
| AAPL@quote | bp/ap:string,bs/as:number,T/E:int,src:string | 至多每200ms一次；公开WS | 开发机15秒收到16条 |
| AAPL@kline_5m | 待取得真实样本确认 | 5分钟为周期，不是推送频率 | 握手成功，15秒零消息；数据能力未确认 |
| exchangeInfo | symbols、tradability、stepSize等 | X-MBX-APIKEY，无需签名 | VPS HTTP400，-2014 API-key format invalid；未提供Key |

price 源时间为 t，可为空；报价样本同时出现 T 与 E，二者语义和时钟偏差需进一步验证。首个 quote 接收时间1793376973109，T=1793376954000，相差19109ms；E=1793376973710，比接收时间晚601ms。不得把 E 与 T 混作成交时间或将网络时延算作内部算法耗时。

实际交易时段仅观察到 mp=O；其他时段 NOT_TESTED。订阅上限、长连接恢复、形成中成交量可靠性、周期结束标识、历史量能、账户费率、价格精度均未完成实证。

结论：WATCH_ONLY / DATA_INSUFFICIENT。零K线样本不能推出接口不可用，也不能确认实时量能能力。先延长采样跨越多个5分钟边界，并在服务器重复结构化测试。

证据：evidence/server-preflight.txt（VPS只读检查及原始握手短样本）；evidence/market-probe.json（开发机结构化短样本）。两者不能混为服务器性能测试。

## 续开发：服务器11分钟结构化采样

时间：2026-10-31 00:19:27至00:30:29 UTC，即中国08:19至08:30、纽约10月30日20:19至20:30。

| 流 | 连接 | 消息总数 | 结果 |
|---|---|---|---|
| price | 成功 | 220 | 持续收到价格消息；保留最后100条及关注标的有限字段 |
| AAPL@quote | 成功 | 0 | 无消息、无连接错误 |
| AAPL@kline_5m | 成功 | 0 | 无消息、无连接错误 |

保留的关注标的phase字段全部为C（共11项），与此时已过周五正常及盘后交易时段一致。不能把零quote/kline消息推断为接口故障；也不能用本次休市采样确认开市量能能力。价格消息中的symbol_count存在变化，不能以单条消息数量推断候选股票池总量或已订阅股票数。

官方字段复核：quote.T是源报价时间（可空），quote.E为服务器推送时间；kline.k包含t/ct:int、i:string、o/h/l/c/v:string、x:bool，n/vw可缺失。当前解析器仅支持5m，并严格校验ct=t+299999及x。这些K线字段仍是文档核验，不是本次真实K线样本证据。

原始结构化证据：evidence/server-market-probe.json。下一次应在有效交易时段采集多个5分钟边界，核对形成中累计量、源时间、结束标记及历史基线。继续WATCH_ONLY。

## 用户提供Key后复核（2026-10-31）

日本服务器使用提供文件中的API Key调用唯一固定GET exchangeInfo，返回HTTP200和7957个规则条目；未使用Secret或签名，未探测交易/账户端点。证据：evidence/exchange-info.json。

用户CSV去重后479个候选，474个找到规则，472个BUY_SELL；AVB/QRVO返回OFFMARKET（超出之前文档枚举，按不可开仓处理）。EA/EQR/IBUY/MPLX/PARA未找到。规则查询成功不代表Key只有只读权限；本程序通过仅实现只读端点保证用途，不声称验证过Key的账户权限设置。

常驻系统已连接price及9标的quote/kline；此时仍为休市，未确认实时成交量。规则每15分钟刷新，失败或过期会保留降级状态。
