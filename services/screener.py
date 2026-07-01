# services/screener.py
"""
量价关系股票筛选引擎
基于多维量价因子每日筛选 5 只优质股票，推送到主界面
"""

import json
import os
import sys
import time
import numpy as np
from datetime import datetime, timedelta
from pytdx.hq import TdxHq_API

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

DATA_DIR = os.path.join(project_root, "data")
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")
DAILY_PICKS_FILE = os.path.join(DATA_DIR, "daily_picks.json")

# ── 默认热门股票池（沪深300核心 + 热门概念） ──
DEFAULT_WATCHLIST = [
    # 银行保险券商
    {"code": "601398", "name": "工商银行"}, {"code": "600036", "name": "招商银行"},
    {"code": "601318", "name": "中国平安"}, {"code": "600030", "name": "中信证券"},
    {"code": "300059", "name": "东方财富"},
    # 白酒消费
    {"code": "600519", "name": "贵州茅台"}, {"code": "000858", "name": "五粮液"},
    {"code": "000568", "name": "泸州老窖"}, {"code": "600809", "name": "山西汾酒"},
    {"code": "000651", "name": "格力电器"}, {"code": "000333", "name": "美的集团"},
    {"code": "600887", "name": "伊利股份"},
    # 新能源
    {"code": "300750", "name": "宁德时代"}, {"code": "002594", "name": "比亚迪"},
    {"code": "601012", "name": "隆基绿能"}, {"code": "600438", "name": "通威股份"},
    {"code": "300274", "name": "阳光电源"}, {"code": "300014", "name": "亿纬锂能"},
    {"code": "002459", "name": "晶澳科技"},
    # 半导体科技
    {"code": "002475", "name": "立讯精密"}, {"code": "000725", "name": "京东方A"},
    {"code": "002415", "name": "海康威视"}, {"code": "300124", "name": "汇川技术"},
    {"code": "688981", "name": "中芯国际"}, {"code": "002230", "name": "科大讯飞"},
    {"code": "601138", "name": "工业富联"}, {"code": "000063", "name": "中兴通讯"},
    {"code": "002371", "name": "北方华创"}, {"code": "688012", "name": "中微公司"},
    {"code": "000977", "name": "浪潮信息"}, {"code": "603019", "name": "中科曙光"},
    {"code": "002049", "name": "紫光国微"},
    # 医药
    {"code": "600276", "name": "恒瑞医药"}, {"code": "300760", "name": "迈瑞医疗"},
    {"code": "000538", "name": "云南白药"},
    # 汽车
    {"code": "000625", "name": "长安汽车"}, {"code": "601633", "name": "长城汽车"},
    {"code": "002463", "name": "沪电股份"},
    # 电力能源
    {"code": "600900", "name": "长江电力"}, {"code": "601985", "name": "中国核电"},
    {"code": "601857", "name": "中国石油"}, {"code": "600028", "name": "中国石化"},
    # 有色
    {"code": "601899", "name": "紫金矿业"}, {"code": "600111", "name": "北方稀土"},
    # 建筑
    {"code": "601668", "name": "中国建筑"}, {"code": "601390", "name": "中国中铁"},
    {"code": "600031", "name": "三一重工"},
    # 其他热门
    {"code": "002714", "name": "牧原股份"}, {"code": "002129", "name": "TCL中环"},
    {"code": "300433", "name": "蓝思科技"}, {"code": "300782", "name": "卓胜微"},
    {"code": "603986", "name": "兆易创新"}, {"code": "600745", "name": "闻泰科技"},
    {"code": "002241", "name": "歌尔股份"}, {"code": "300408", "name": "三环集团"},
]

TDX_SERVERS = [
    {"ip": "119.147.212.81", "port": 7709},
    {"ip": "218.75.126.9", "port": 7709},
    {"ip": "124.71.223.19", "port": 7709},
]


def get_watchlist():
    """加载或初始化监视列表"""
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # 初始化默认列表
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_WATCHLIST, f, ensure_ascii=False, indent=2)
    return DEFAULT_WATCHLIST


def _connect_tdx():
    """连接通达信行情服务器（多节点热备）"""
    api = TdxHq_API()
    for node in TDX_SERVERS:
        try:
            if api.connect(node["ip"], node["port"]):
                return api
        except:
            continue
    return None


def get_kline_batch(stock_codes, days=30):
    """
    批量获取日K线数据
    返回: {code: [{open, high, low, close, volume}, ...]}
    """
    api = _connect_tdx()
    if not api:
        return {}

    result = {}
    try:
        for code in stock_codes:
            clean_code = code.zfill(6)
            market = 1 if clean_code.startswith("6") else 0
            try:
                bars = api.get_security_bars(9, market, clean_code, 0, days)
                if bars:
                    result[code] = [
                        {
                            "open": float(b.get("open", 0)),
                            "high": float(b.get("high", 0)),
                            "low": float(b.get("low", 0)),
                            "close": float(b.get("close", 0)),
                            "volume": float(b.get("vol", 0)),
                        }
                        for b in bars
                    ]
            except:
                continue
    finally:
        try:
            api.disconnect()
        except:
            pass

    return result


def get_realtime_quotes_batch(stocks):
    """
    批量获取实时行情
    stocks: [{"code": "002463", "name": "沪电股份"}, ...]
    返回: [{code, name, price, change_rate, volume, amount, high, low, open, last_close}, ...]
    """
    api = _connect_tdx()
    if not api:
        return []

    results = []
    try:
        # 分批查询 (通达信单次最多约80只)
        batch_size = 70
        for i in range(0, len(stocks), batch_size):
            batch = stocks[i : i + batch_size]
            queries = []
            for s in batch:
                code = s["code"].zfill(6)
                market = 1 if code.startswith("6") else 0
                queries.append((market, code))

            try:
                quotes = api.get_security_quotes(queries)
                if quotes:
                    for j, q in enumerate(quotes):
                        if j < len(batch) and q:
                            price = float(q.get("price", 0))
                            last_close = float(q.get("last_close", 0))
                            change_rate = (
                                round(((price - last_close) / last_close) * 100, 2)
                                if last_close > 0
                                else 0.0
                            )
                            results.append(
                                {
                                    "code": batch[j]["code"],
                                    "name": batch[j]["name"],
                                    "price": price,
                                    "change_rate": change_rate,
                                    "volume": float(q.get("vol", 0)),
                                    "amount": float(q.get("amount", 0)) if q.get("amount") else 0,
                                    "high": float(q.get("high", 0)),
                                    "low": float(q.get("low", 0)),
                                    "open": float(q.get("open", 0)),
                                    "last_close": last_close,
                                }
                            )
            except:
                continue
    finally:
        try:
            api.disconnect()
        except:
            pass

    return results


def calc_vol_price_score(quote, klines):
    """
    量价关系综合评分 (满分100)
    
    评分维度：
    1. 当日量价关系 (25分)
    2. 近期趋势 (20分)
    3. 量能结构 (20分)
    4. 突破形态 (20分)
    5. 活跃度 (15分)
    """
    score = 0.0
    reasons = []

    code = quote.get("code", "")
    price = quote.get("price", 0)
    change_rate = quote.get("change_rate", 0)
    volume = quote.get("volume", 0)
    amount = quote.get("amount", 0)
    high = quote.get("high", 0)
    low = quote.get("low", 0)
    open_price = quote.get("open", 0)
    last_close = quote.get("last_close", 0)

    if price <= 0:
        return 0, ["数据异常"]

    # ── 维度1: 当日量价关系 (25分) ──
    if change_rate > 3 and volume > 0:
        # 放量上涨：强势信号
        score += 15
        reasons.append(f"放量上涨{change_rate:+.2f}%")
        if change_rate > 5:
            score += 5
        if change_rate > 7:
            score += 3
    elif change_rate > 0:
        score += 5
        reasons.append(f"小幅上涨{change_rate:+.2f}%")
    elif change_rate < -5:
        score -= 10
        reasons.append(f"大幅下跌{change_rate:+.2f}%")
    elif change_rate < -3:
        score -= 5
    elif change_rate < 0:
        score -= 2

    # 阳线实体（收盘 > 开盘）
    if price > open_price and open_price > 0:
        body_ratio = (price - open_price) / open_price * 100
        if body_ratio > 2:
            score += 5
            reasons.append(f"实体阳线{body_ratio:.1f}%")

    # ── 维度2: 近期趋势 (20分) ──
    if klines and len(klines) >= 10:
        closes = [k["close"] for k in klines if k["close"] > 0]
        volumes = [k["volume"] for k in klines if k["volume"] > 0]

        if len(closes) >= 10:
            # 均线计算
            ma5 = np.mean(closes[-5:]) if len(closes) >= 5 else closes[-1]
            ma10 = np.mean(closes[-10:]) if len(closes) >= 10 else closes[-1]
            ma20 = np.mean(closes[-20:]) if len(closes) >= 20 else ma10

            # 均线多头排列
            if price > ma5 > ma10:
                score += 8
                reasons.append("均线多头排列")
            elif price > ma5:
                score += 4
            elif price < ma10:
                score -= 3

            # 5日涨跌幅
            if len(closes) >= 5:
                pct_5d = (closes[-1] - closes[-5]) / closes[-5] * 100
                if 3 < pct_5d < 15:
                    score += 5
                    reasons.append(f"5日涨幅{pct_5d:.1f}%温和")
                elif pct_5d >= 15:
                    score += 2  # 涨太多反而有回调风险
                    reasons.append(f"5日涨幅{pct_5d:.1f}%偏高")

            # 20日斜率
            if len(closes) >= 20:
                x = np.arange(min(len(closes), 20))
                y = np.array(closes[-20:])
                if len(y) >= 5:
                    slope = np.polyfit(x[-len(y):], y, 1)[0]
                    if slope > 0:
                        score += 3
                        reasons.append("中期趋势向上")

    # ── 维度3: 量能结构 (20分) ──
    if volumes and len(volumes) >= 5:
        avg_vol_5 = np.mean(volumes[-5:])
        avg_vol_20 = np.mean(volumes[-20:]) if len(volumes) >= 20 else avg_vol_5

        if avg_vol_5 > 0:
            vol_ratio = volume / avg_vol_5 if avg_vol_5 > 0 else 1
            if 1.5 <= vol_ratio <= 3:
                score += 12
                reasons.append(f"温和放量{vol_ratio:.1f}倍")
            elif vol_ratio > 3:
                score += 8
                reasons.append(f"大幅放量{vol_ratio:.1f}倍")
            elif 1.0 <= vol_ratio < 1.5:
                score += 4

        # 量比放大趋势
        if avg_vol_20 > 0:
            vol_trend = avg_vol_5 / avg_vol_20
            if vol_trend > 1.2:
                score += 5
                reasons.append("量能趋势放大")

    # ── 维度4: 突破形态 (20分) ──
    if klines and len(klines) >= 20:
        # 突破20日高点
        high_20 = max(k["high"] for k in klines[-20:])
        if price >= high_20 * 0.98 and volume > 0:
            score += 10
            reasons.append("逼近或突破20日高点")

        # 突破前期平台
        if len(klines) >= 10:
            high_10 = max(k["high"] for k in klines[-10:-1]) if len(klines) > 10 else high_20
            if price > high_10 and change_rate > 0:
                score += 8
                reasons.append("突破短期平台")

    # ── 维度5: 活跃度 (15分) ──
    if amount > 1e8:  # 成交额 > 1亿
        score += 3
    if amount > 5e8:
        score += 3
    if amount > 1e9:  # 成交额 > 10亿
        score += 4
        reasons.append("成交活跃超10亿")

    if volume > 100000:  # 成交量 > 10万手
        score += 2
    if volume > 500000:
        score += 3

    # 换手率估算 (总股本按平均估算)
    est_turnover = volume * 100 / 1e7
    if 3 <= est_turnover <= 15:
        score += 2
        reasons.append("换手率适中")

    return max(0, min(100, score)), reasons


def screen_top_stocks():
    """
    核心筛选函数：从监视列表中基于量价关系选出Top5
    
    返回 JSON 字符串
    """
    watchlist = get_watchlist()
    if not watchlist:
        return json.dumps({"error": "监视列表为空", "picks": []}, ensure_ascii=False)

    # 1. 批量获取实时行情
    quotes = get_realtime_quotes_batch(watchlist)
    if not quotes:
        return json.dumps({"error": "无法获取实时行情数据", "picks": []}, ensure_ascii=False)

    # 过滤有效报价
    valid_quotes = [q for q in quotes if q.get("price", 0) > 0]

    # 2. 获取K线数据（取评分前N只的K线或全部取）
    # 策略：先按当日简单指标预筛，再深度分析
    pre_screened = []
    for q in valid_quotes:
        pre_score = 0
        cr = q.get("change_rate", 0)
        vol = q.get("volume", 0)
        amt = q.get("amount", 0)
        # 放量上涨优先
        if cr > 0:
            pre_score += cr * 2  # 涨幅越大越好（但有限度）
        if vol > 100000:
            pre_score += min(vol / 100000 * 2, 10)
        if amt > 1e8:
            pre_score += min(amt / 1e8, 15)
        pre_screened.append({"quote": q, "pre_score": pre_score})

    pre_screened.sort(key=lambda x: x["pre_score"], reverse=True)

    # 取前60只做K线深度分析
    top_candidates = pre_screened[:60]
    codes_for_kline = [c["quote"]["code"] for c in top_candidates]

    klines_map = get_kline_batch(codes_for_kline, days=30)

    # 3. 综合评分
    scored = []
    for candidate in top_candidates:
        q = candidate["quote"]
        code = q["code"]
        klines = klines_map.get(code, [])
        score, reasons = calc_vol_price_score(q, klines)
        scored.append(
            {
                "code": code,
                "name": q["name"],
                "price": q["price"],
                "change_rate": q["change_rate"],
                "volume": q["volume"],
                "amount": q["amount"],
                "score": round(score, 1),
                "reasons": reasons,
                "open": q["open"],
                "high": q["high"],
                "low": q["low"],
                "last_close": q["last_close"],
            }
        )

    # 4. 排序取Top5
    scored.sort(key=lambda x: x["score"], reverse=True)
    top5 = scored[:5]

    # 5. 持久化保存
    result = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "update_date": datetime.now().strftime("%Y-%m-%d"),
        "total_scanned": len(valid_quotes),
        "picks": top5,
    }
    with open(DAILY_PICKS_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return json.dumps(result, ensure_ascii=False)


def get_daily_picks():
    """读取已保存的每日精选（离线使用）"""
    if os.path.exists(DAILY_PICKS_FILE):
        with open(DAILY_PICKS_FILE, "r", encoding="utf-8") as f:
            return json.dumps(json.load(f), ensure_ascii=False)
    return json.dumps({"error": "暂无今日精选数据，请点击刷新", "picks": []}, ensure_ascii=False)


# ── 命令行独立测试 ──
if __name__ == "__main__":
    print("🔍 开始量价筛选...")
    t0 = time.time()
    result = screen_top_stocks()
    elapsed = time.time() - t0
    print(f"✅ 筛选完成，耗时 {elapsed:.1f}s")
    data = json.loads(result)
    print(f"\n📊 扫描 {data.get('total_scanned', 0)} 只股票，Top5：\n")
    for i, pick in enumerate(data.get("picks", []), 1):
        color = "🔴" if pick["change_rate"] >= 0 else "🟢"
        print(
            f"  {i}. {pick['name']}({pick['code']}) "
            f"{color}{pick['change_rate']:+.2f}% | "
            f"量价评分: {pick['score']}/100 | "
            f"价格: {pick['price']:.2f}"
        )
        print(f"     理由: {'; '.join(pick['reasons'])}")
