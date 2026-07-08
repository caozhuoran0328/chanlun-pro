# chanlun-pro 缠论分析系统完整运行顺序分析

> 本文档详细描述了 chanlun-pro 缠论分析系统从数据获取到核心计算再到最终输出的完整运行顺序。

## 目录
- [一、系统整体架构](#一系统整体架构)
- [二、核心计算流程：CL.process_klines() 完整执行顺序](#二核心计算流程-clprocess_klines-完整执行顺序)
  - [步骤 1：原始K线转换](#步骤-1原始k线转换-convert_src_klines)
  - [步骤 2：缠论K线合并](#步骤-2缠论k线合并-get_cl_lines)
  - [步骤 3：分型查找](#步骤-3分型查找-fx_processfind_fenxing)
  - [步骤 4：笔计算](#步骤-4笔计算-bi_processhandle)
  - [步骤 5：线段计算](#步骤-5线段计算-xd_processhandle)
- [三、不同使用场景的运行路径](#三不同使用场景的运行路径)
  - [场景 1：Web 图表展示 (TradingView)](#场景-1web-图表展示-tradingview)
  - [场景 2：选股 (悬瓠选股)](#场景-2选股-悬瓠选股)
  - [场景 3：告警监控](#场景-3告警监控)
  - [场景 4：命令行/回测](#场景-4命令行回测)
- [四、增量计算机制 (FileCacheDB)](#四增量计算机制-filecachedb)
  - [增量更新原理](#增量更新原理)
  - [缓存key生成](#缓存key生成)
  - [缓存清理机制](#缓存清理机制)
- [五、数据获取层架构](#五数据获取层架构)
  - [交易所抽象](#交易所抽象)
  - [支持的数据源](#支持的数据源)
  - [K线周期转换](#k线周期转换)
- [六、核心计算流程框图](#六核心计算流程框图)
- [总结](#总结)

---

## 一、系统整体架构

chanlun-pro 是一个基于缠论理论的股票技术分析系统，采用分层架构，从数据获取到核心计算再到结果展示，分为以下几个层次：

```
数据源层 (Exchange) → 原始K线转换 → 缠论核心计算 (CL.process_klines) → 结果缓存 → 前端展示 (TradingView 图表)
```

**核心模块文件：**
- 核心入口：`src/chanlun/cl.py` - CL 主类
- 接口定义：`src/chanlun/cl_interface.py` - 所有缠论对象接口定义
- 分步计算：
  - `get_src_klines.py` - 原始K线获取转换
  - `get_cl_klines.py` - 缠论K线合并
  - `get_fx.py` - 分型查找
  - `get_bi.py` - 笔计算
  - `get_xd.py` - 线段计算
- Web入口：`web/chanlun_chart/app/__init__.py` - Flask Web应用
- 数据源：`src/chanlun/exchange/exchange.py` - 交易所抽象基类，多种实现

---

## 二、核心计算流程：CL.process_klines() 完整执行顺序

### 总体步骤 (`src/chanlun/cl.py:19-34`)

```python
def process_klines(self, klines: pd.DataFrame):
    1. self.src_klines = convert_src_klines(klines)  → 原始K线转换
    2. self.cl_klines = get_cl_lines(self.src_klines) → 缠论K线合并
    3. fx_proc = FX_PROCESS() → 初始化分型处理器
    4. self.fxs = fx_proc.find_fenxing(self.cl_klines) → 查找分型
    5. bi_process = BI_Process() → 初始化笔处理器
    6. self.bis = bi_process.handle(self.fxs) → 计算笔
    7. xd_process = XD_Process() → 初始化线段处理器
    8. self.xds = xd_process.handle(self.bis) → 计算线段
    9. 初始化中枢列表（留空等待后续计算）
```

以下是每一步的详细说明：

---

### 步骤 1：原始K线转换 - `convert_src_klines()` (`src/chanlun/get_src_klines.py:14-23`)

**输入：** `pd.DataFrame` - 来自交易所的原始K线数据，包含列：`code, date, open, high, low, close, volume`

**处理过程：**
```python
for num in range(0, len(tdx_klines)):
    kline = tdx_klines.iloc[num].copy()
    # 转换为 Kline 对象（cl_interface.py 定义）
    src_kline = Kline(num, kline['date'], kline['high'], kline['low'], 
                     kline['open'], kline['close'], kline['volume'])
    ret_klines.append(src_kline)
```

**输出：** `pd.DataFrame` - 每行是 Kline 对象的属性字典

**Kline 对象属性：** (`src/chanlun/cl_interface.py:69-84`)
- `index` - K线序号
- `date` - 日期时间
- `h`/`l`/`o`/`c` - 最高、最低、开盘、收盘
- `a` - 成交量

---

### 步骤 2：缠论K线合并 - `get_cl_lines()` (`src/chanlun/get_cl_klines.py:10-89`)

**输入：** 原始K-line DataFrame `src_klines`

**核心算法：包含关系处理**

处理过程使用**状态机**方法：
1. 初始化：方向向上，取出第一根K线
2. 从第二根开始遍历每一根K线，判断当前K线与上一根保留K线的包含关系：

**包含关系判断：**
```
情况 1：当前 K 包含 上一根 K
  current_k_high >= last_k_high AND current_k_low <= last_k_low
  → 根据方向调整高低点，保留当前K线，合并之前的K线

情况 2：上一根 K 包含 当前 K
  last_k_high >= current_k_high AND last_k_low <= current_k_low  
  → 根据方向调整高低点，保留当前K线，加入合并列表

情况 3：不包含
  → 将上一根保留K线输出为 CLKline，重新开始新的合并过程
  → 根据当前K线和上一根K线的高点关系更新方向
```

**方向对包含处理的影响：**
- 向上趋势：当前K线低点 = 上一根K线低点（取低）
- 向下趋势：当前K线高点 = 上一根K线高点（取高）

**输出：** `pd.DataFrame` - 合并后的 `CLKline` 对象列表

**CLKline 对象属性：** (`src/chanlun/cl_interface.py:88-109`)
- `k_index` - 原始K索引
- `date`/`h`/`l`/`o`/`c`/`a` - 价格成交量
- `klines` - 该缠论K线包含的原始K线列表
- `index` - 缠论K线序号
- `n` - 包含的原始K线数量
- `q` - 是否有缺口
- `up_qs` - 合并时之前的趋势方向

---

### 步骤 3：分型查找 - `FX_PROCESS.find_fenxing()` (`src/chanlun/get_fx.py:18-142`)

**输入：** 合并后的缠论K线 `cl_klines`

**核心算法：三根K线判断顶底分型**

使用**状态机**顺序处理每根K线，状态定义：
- `LEFT` - 等待左边K线
- `MIDDLE` - 等待中间K线  
- `RIGHT` - 等待右边K线，确认分型
- `FREE` - 自由状态，处理新分型前的过渡
- `NEXT_LEFT`/`NEXT_MIDDLE` - 验证前一个分型未完成时的状态

**判断规则：**
- **顶分型：** 中间K线高点 > 左右两根K线高点
- **底分型：** 中间K线低点 < 左右两根K线低点

**分型状态：** (`src/chanlun/cl_interface.py:29`)
- `TOP`/`BOTTOM` - 暂定顶/底分型，未完成，还需要右边K线确认
- `VERIFY_TOP`/`VERIFY_BOTTOM` - 已验证完成的顶/底分型
- `FAILURE_TOP`/`FAILURE_BOTTOM` - 验证失败，撤销之前的暂定分型

**处理流程：**
```
1. 初始状态 = LEFT，记录left = 当前K线 → 进入MIDDLE
2. MIDDLE，记录middle = 当前K线 → 进入RIGHT
3. RIGHT 判断：
   - 如果 middle.h > left.h 且 middle.h > right.h → 顶分型成立
   - 如果 middle.l < left.l 且 middle.l < right.l → 底分型成立
   - 根据前一个分型状态决定是暂定还是验证
4. 验证成功后，添加 FX 对象到 fx_lists，清空状态，开始下一个分型查找
5. 验证失败，弹出之前的暂定分型，重新开始
```

**FX 对象属性：** (`src/chanlun/cl_interface.py:113-152`)
- `type` - 分型类型（顶/底/验证/失败）
- `k` - 分型中间K线
- `klines` - 分型包含的三根缠论K线 [left, middle, right]
- `val` - 分型值（顶是高点，底是低点）
- `index` - 序号
- `done` - 分型是否完成

**输出：** `List[FX]` - 所有找到的分型列表

---

### 步骤 4：笔计算 - `BI_Process.handle()` (`src/chanlun/get_bi.py:12-80`)

**输入：** 分型列表 `fxlist`

**核心算法：顶底相连成笔**

处理逻辑：
1. 从第一个分型开始，作为笔的起始
2. 遍历后续每一个分型：
   - 如果起始是顶分型，等待底分型 → 顶到底构成下降笔
   - 如果起始是底分型，等待顶分型 → 底到顶构成上升笔
   - 如果新分型没有突破起始分型值，更新笔的终点（延续）
3. 每找到一个完成的笔，添加到笔列表

**笔类型：** (`src/chanlun/cl_interface.py:48`)
- `UP`/`DOWN` - 普通上升/下降笔（起止分型未完成）
- `VERIFY_UP`/`VERIFY_DOWN` - 验证完成的上升/下降笔（起止分型都已验证）
- `NEW_UP`/`NEW_DOWN`/`UPDATE_UP`/`UPDATE_DOWN` - 新增/更新（用于动态增量更新）

**BI 对象属性：** (`src/chanlun/cl_interface.py:254-334`) 继承 LINE
- `start`/`end` - 起始/结束分型
- `type` - 笔类型
- `high`/`low` - 笔的高低点（根据配置取分型值或缠论K线或原始K线）
- `index` - 序号
- `mmds` - 存储买卖点
- `bcs` - 存储背驰
- `zs_type_mmds`/`zs_type_bcs` - 不同中枢类型下的买卖点和背驰

**处理更新规则：**
```python
# 起始向上笔，新高不构成新笔，直接更新终点
if start_fx.type == BOTTOM and fx.type == TOP and fx.val < start_fx.val:
    if fx.val < start_fx.val → 更新最后一笔终点
```

**输出：** `List[BI]` - 所有笔列表

---

### 步骤 5：线段计算 - `XD_Process.handle()` (`src/chanlun/get_xd.py:10-394`)

**输入：** 笔列表 `bis`

**核心算法：特征序列判断线段**

使用**状态机**处理，共 20+ 种状态，基于特征序列的分型判断线段结束。

**主要状态：** (`src/chanlun/get_xd.py:29-47`)
- `START` - 开始
- `LEFT`/`LEFT_AFTER`/`LEFT_AFTER_NORMAL` - 特征序列左部分处理
- `MIDDLE`/`MIDDLE_AFTER` - 特征序列中间部分
- `RIGHT`/`RIGHT_NORMAL`/`RIGHT_NORMAL_NORMAL` - 特征序列右部分，确认线段
- `QUEKOU_*` - 缺口相关特殊处理状态

**特征序列缺口判断：**
- 缺口：新笔的开始位置与前线段结束存在价格跳空
- 缺口情况下需要更严格的分型判断

**XD 对象属性：** (`src/chanlun/cl_interface.py:443-522`) 继承 LINE
- `start`/`end` - 起始/结束分型
- `start_line`/`end_line` - 起始/结束笔
- `type` - 线段方向 (up/down)
- `tzxls` - 特征序列列表
- `done` - 线段是否完成
- `ding_fx`/`di_fx` - 结束特征序列分型

**线段生成规则：**
1. 第一笔作为开始
2. 等待特征序列出现，根据方向处理
3. 在特征序列中找到分型，确认线段结束
4. 缺口情况下特殊处理，需要额外一根K线确认
5. 确认后添加线段到列表，重新开始下一个线段

**输出：** `List[XD]` - 所有线段列表

---

## 三、不同使用场景的运行路径

### 场景 1：Web 图表展示 (TradingView)

**完整请求流程：** (`web/chanlun_chart/app/__init__.py:250-330`)

```
用户在前端 → 请求 /tv/history
    ↓
1. 解析请求参数：symbol(market:code), resolution, from/to
    ↓
2. 获取交易所对象：ex = get_exchange(Market(market))
    ↓
3. 周期转换：frequency = resolution_maps[resolution]
    ↓
4. 查询缠论配置：cl_config = query_cl_chart_config(market, code)
    ↓
5. 判断是否开启低级别递归画图：
   - 如果开启：获取低级别K线 → 计算低级别缠论 → 转换高级别
   - 如果不开启：直接获取当前周期K线
    ↓
6. 获取K线：klines = ex.klines(code, frequency)
    ↓
7. 计算缠论：cd = web_batch_get_cl_datas(market, code, {frequency: klines}, cl_config)[0]
    ↓
8. 转换输出格式：cl_chart_data = cl_data_to_tv_chart(cd, cl_config)
    ↓
9. 返回JSON给TradingView前端画图
   包含：K线 + 分型 + 笔 + 线段 + 中枢 + 背驰 + 买卖点
```

**关键点：**
- 使用文件缓存增量计算，详见下文增量机制说明
- 支持低级别转高级别展示（enable_kchart_low_to_high）
- 所有缠论计算结果转换成TradingView可识别的坐标格式

---

### 场景 2：选股 (悬瓠选股) (`web/chanlun_chart/app/xuangu_tasks.py`)

**运行路径：**
```
用户添加选股任务 → 定时调度执行 
    ↓
遍历自选组中所有股票 → 多周期计算缠论
    ↓
根据选股规则（买卖点/背驰等）筛选 → 保存结果
    ↓
可在页面查看选股结果
```

---

### 场景 3：告警监控 (`web/chanlun_chart/app/alert_tasks.py`)

**运行路径：**
```
用户配置告警任务 → 定时（每隔N分钟）执行
    ↓
遍历监控股票 → 获取最新K线 → 更新缠论计算
    ↓
检查是否满足告警条件（指定背驰/买卖点）
    ↓
满足条件发送消息通知 → 记录告警历史
```

---

### 场景 4：命令行/回测

**运行路径：**
```python
# 1. 创建CL对象
cl = CL(code, frequency, config)
# 2. 获取K线
klines = exchange.klines(code, frequency)
# 3. 计算
cl.process_klines(klines)
# 4. 获取结果
fxs = cl.get_fxs()      # 分型
bis = cl.get_bis()      # 笔
xds = cl.get_xds()      # 线段
bi_zss = cl.get_bi_zss() # 笔中枢
xd_zss = cl.get_xd_zss() # 线段中枢
# 5. 根据结果进行策略分析回测
```

---

## 四、增量计算机制 (FileCacheDB)

**文件：** `src/chanlun/file_db.py` - `get_web_cl_data()` 方法

### 增量更新原理

系统**支持增量更新**，新K线到来不需要重新计算所有历史，只需要更新最后部分。

**增量判断步骤：** (`src/chanlun/file_db.py:108-180`)

```
1. 从缓存pickle文件加载之前计算好的CL对象
   ↓
2. 检查数据连续性：
   - 判断缓存中最后一根K线时间是否 < 新数据第一根K线时间
   - 如果不连续 → 说明数据断档，清空重新全量计算
   ↓
3. 检查价格一致性：
   - 取出缓存中倒数第二根K线，对比新数据中同日期的价格
   - 开高低收成交量任意一个不同 → 说明历史数据变动（如复权），清空重新全量计算
   ↓
4. 检查最近100根K线数量一致性：
   - 缓存中最近100根数量 ≠ 新数据中对应时间段内数量
   → 说明有丢失，清空重新计算
   ↓
5. 如果以上检查都通过 → 直接调用 cd.process_klines(新K线数据)
   - 因为新K线数据包含历史所有K线，但CL.process_klines会重新处理所有K线
   - 增量体现在：只需要获取新增K线，不需要重复网络请求
   - 缓存保存了之前计算的缠论结构，避免重复计算所有历史
```

### 缓存key生成

缓存文件名包含：
```
{market}_{code}_{frequency}_{config_md5}.pkl
```

**config_md5** 对所有影响计算的配置项计算md5，配置变化自动失效缓存重新计算。

**配置项列表：** (`src/chanlun/file_db.py:50-59`)
包括K线、分型、笔、线段、中枢、MACD、买卖点所有配置。只要配置改变，自动重新计算。

### 缓存清理机制

- 随机 5% 概率清理 7 天未访问的缓存文件，避免占用过多磁盘空间
- 代码版本更新时，如果 `cl_update_date` 变化，清空所有缓存重新计算

---

## 五、数据获取层架构

### 交易所抽象 (`src/chanlun/exchange/exchange.py:24-68`)

所有数据源实现统一 `Exchange` 抽象基类，核心接口：

```python
@abstractmethod
def klines(code, frequency, start_date, end_date, args) -> [pd.DataFrame, None]:
    """获取K线数据"""

@abstractmethod  
def ticks(codes: List[str]) -> Dict[str, Tick]:
    """获取最新Tick价格"""

@abstractmethod
def all_stocks():
    """获取所有股票列表"""

@abstractmethod  
def stock_info(code):
    """获取股票基本信息"""

@abstractmethod
def stock_owner_plate(code):
    """获取股票所属板块"""

@abstractmethod
def plate_stocks(code):
    """获取板块股票列表"""
```

### 支持的数据源

| 数据源 | 实现文件 | 市场 |
|--------|----------|------|
| 通达信 | `exchange_tdx.py` | A股 |
| 通达信期货 | `exchange_tdx_futures.py` | 国内期货 |
| 通达信外汇 | `exchange_tdx_fx.py` | 外汇 |
| 通达信港股 | `exchange_tdx_hk.py` | 港股 |
| 通达信美股 | `exchange_tdx_us.py` | 美股 |
| 富途 | `exchange_futu.py` | 多市场 |
| 同花顺iFinD QMT | `exchange_qmt.py` | A股 |
| 天勤 | `exchange_tq.py` | 期货 |
| Baostock | `exchange_baostock.py` | A股免费 |
| Binance | `exchange_binance.py` | 数字货币合约 |
| Binance 现货 | `exchange_binance_spot.py` | 数字货币现货 |
| Alpaca | `exchange_alpaca.py` | 美股 |
| IB 盈透 | `exchange_ib.py` | 美股 |
| Polygon | `exchange_polygon.py` | 美股 |
| 数据库缓存 | `exchange_db.py` | 从数据库读取 |

### K线周期转换

当需要获取高级别K线但数据源只提供低级别数据时，系统自动进行周期合并：

- **股票**：`convert_stock_kline_frequency()` - 后对齐
- **数字货币**：`convert_currency_kline_frequency()` - UTC转本地时区
- **期货**：`convert_futures_kline_frequency()` - 前对齐
- **美股**：`convert_us_kline_frequency()` - 特殊处理交易时间

支持的周期：`10s/30s/1m/2m/3m/5m/10m/15m/30m/60m/120m/3h/4h/d/w/m/y`

---

## 六、核心计算流程框图

```
┌─────────────────────────────────────────────────────────────────┐
│                    输入：原始K线DataFrame                            │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 1  convert_src_klines()                                      │
│         将原始DataFrame → List[Kline] → DataFrame                  │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2  get_cl_lines()                                            │
│         处理包含关系，合并缠论K线 → List[CLKline]                 │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3  FX_PROCESS.find_fenxing()                                │
│         状态机查找顶底分型 → List[FX]                              │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 4  BI_Process.handle()                                       │
│         顶底交替生成笔 → List[BI]                                  │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 5  XD_Process.handle()                                       │
│         特征序列状态机生成线段 → List[XD]                          │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 6  （后续计算）中枢、背驰、买卖点                            │
│         bi_zss ← 笔中枢                                             │
│         xd_zss ← 线段中枢                                           │
│         计算背驰判断 ← BC                                           │
│         标记买卖点 ← MMD                                            │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    输出：完整缠论结构对象CL                         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 总结

### 核心运行顺序总结

| 步骤 | 模块 | 输入 | 输出 | 文件 |
|------|------|------|------|------|
| 1 | 原始K线转换 | 交易所DataFrame | Kline DataFrame | `get_src_klines.py` |
| 2 | 缠论K线合并 | 原始K线 | CLKline DataFrame（处理包含关系） | `get_cl_klines.py` |
| 3 | 分型查找 | 缠论K线 | FX 分型列表 | `get_fx.py` |
| 4 | 笔计算 | 分型列表 | BI 笔列表 | `get_bi.py` |
| 5 | 线段计算 | 笔列表 | XD 线段列表 | `get_xd.py` |
| 6 | （后续）中枢背驰买卖点 | 笔/线段 | 中枢、背驰、买卖点 | （CL扩展计算） | `cl.py` |

### 增量更新关键点

1. **缓存命中条件：** 日期连续 + 价格一致 + 数量一致 → 复用缓存
2. **配置变化：** 配置md5变化 → 自动失效重新计算
3. **清理机制：** 自动清理 7 天不访问的缓存 → 节省磁盘空间

### 不同场景入口

| 场景 | 入口 | 说明 |
|------|------|------|
| Web图表 | `/tv/history` → `web_batch_get_cl_datas` → `file_cache.get_web_cl_data` | 交互式图表展示 |
| 选股 | `xuangu_tasks.run_xuangu()` | 定时扫描选股 |
| 告警 | `alert_tasks` | 实时监控告警 |
| 命令行/回测 | 直接创建 `CL` 对象调用 `process_klines()` | 回测研究 |

---

**文档生成日期：** 2026-05-18  
**基于代码版本：** https://github.com/yijixiuxin/chanlun-pro
