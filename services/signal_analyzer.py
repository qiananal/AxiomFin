# services/signal_analyzer.py
"""
买卖信号分析器
基于量价关系 + 均线系统 + MACD + RSI + 支撑阻力位
判断最佳买入点和卖出点
"""

import json
import os
import sys
import numpy as np
from datetime import datetime
from pytdx.hq import TdxHq_API

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

TDX_SERVERS = [
    {"ip": "119.147.212.81", "port": 7709},
    {"ip": "218.75.126.9", "port": 7709},
    {"ip": "124.71.223.19", "port": 7709},
]

# ── 信号强度定义 ──
SIGNAL_LEVELS = {
    "STRONG_BUY": {"label": "强烈买入", "color": "red", "desc": "多重信号共振，建议果断建仓"},
    "BUY": {"label": "建议买入", "color": "#ff6600", "desc": "技术形态良好，可分批建仓"},
    "WEAK_BUY": {"label": "关注买入", "color": "#ffaa00", "desc": "部分信号触发，可小仓位试探"},
    "HOLD": {"label": "持有观望", "color": "#888", "desc": "方向不明，建议持仓观望"},
    "WEAK_SELL": {"label": "关注卖出", "color": "#00aa00", "desc": "出现警示信号，可考虑减仓"},
    "SELL": {"label": "建议卖出", "color": "#00cc00", "desc": "技术形态转弱，建议减仓"},
    "STRONG_SELL": {"label": "强烈卖出", "color": "#00ff00", "desc": "多重见顶信号，建议清仓"},
}


def _connect_tdx():
    api = TdxHq_API()
    for node in TDX_SERVERS:
        try:
            if api.connect(node["ip"], node["port"]):
                return api
        except:
            continue
    return None


def get_kline_data(stock_code, days=120):
    """获取单只股票的日K线数据"""
    api = _connect_tdx()
    if not api:
        return None

    clean_code = stock_code.zfill(6)
    market = 1 if clean_code.startswith("6") else 0

    try:
        bars = api.get_security_bars(9, market, clean_code, 0, days)
        if not bars:
            return None
        return [
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
        return None
    finally:
        try:
            api.disconnect()
        except:
            pass


def get_realtime_quote(stock_code):
    """获取单只股票实时行情"""
    api = _connect_tdx()
    if not api:
        return None

    clean_code = stock_code.zfill(6)
    market = 1 if clean_code.startswith("6") else 0

    try:
        quotes = api.get_security_quotes([(market, clean_code)])
        if quotes and len(quotes) > 0 and quotes[0]:
            q = quotes[0]
            price = float(q.get("price", 0))
            last_close = float(q.get("last_close", 0))
            change_rate = (
                round(((price - last_close) / last_close) * 100, 2)
                if last_close > 0
                else 0.0
            )
            return {
                "price": price,
                "change_rate": change_rate,
                "volume": float(q.get("vol", 0)),
                "amount": float(q.get("amount", 0)) if q.get("amount") else 0,
                "high": float(q.get("high", 0)),
                "low": float(q.get("low", 0)),
                "open": float(q.get("open", 0)),
                "last_close": last_close,
            }
    except:
        return None
    finally:
        try:
            api.disconnect()
        except:
            pass


def calc_ma(data, period):
    """计算移动平均线"""
    if len(data) < period:
        return None
    return round(float(np.mean(data[-period:])), 2)


def calc_ema(data, period):
    """计算指数移动平均"""
    if len(data) < period:
        return None
    k = 2 / (period + 1)
    ema = data[0]
    for val in data[1:]:
        ema = val * k + ema * (1 - k)
    return round(float(ema), 2)


def calc_rsi(closes, period=14):
    """计算RSI"""
    if len(closes) < period + 1:
        return None
    deltas = np.diff(closes[-period - 1 :])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi), 1)


def calc_macd(closes):
    """计算MACD"""
    if len(closes) < 26:
        return None, None, None

    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    if ema12 is None or ema26 is None:
        return None, None, None

    dif = round(ema12 - ema26, 3)

    # 需要至少9个DIF计算DEA
    # 简化为用当前DIF推算
    # 实际用EMA of DIF
    # 这里简化：直接用当前快慢线差值
    dif_values = []
    for i in range(26, len(closes) + 1):
        e12 = calc_ema(closes[:i], 12)
        e26 = calc_ema(closes[:i], 26)
        if e12 and e26:
            dif_values.append(e12 - e26)

    if len(dif_values) >= 9:
        dea = calc_ema(dif_values, 9)
    else:
        dea = dif

    if dea is None:
        dea = dif

    macd_bar = round((dif - dea) * 2, 3)

    return round(dif, 3), round(dea, 3), macd_bar


def find_support_resistance(klines):
    """寻找支撑位和阻力位"""
    if not klines or len(klines) < 20:
        return None, None

    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]
    closes = [k["close"] for k in klines]

    # 支撑位：近20/60日最低价区域
    support_20 = min(lows[-20:])
    support_60 = min(lows[-60:]) if len(lows) >= 60 else support_20

    # 阻力位：近20/60日最高价区域
    resistance_20 = max(highs[-20:])
    resistance_60 = max(highs[-60:]) if len(highs) >= 60 else resistance_20

    current = closes[-1] if closes else 0

    return {
        "support_near": round(support_20, 2),
        "support_far": round(support_60, 2),
        "resistance_near": round(resistance_20, 2),
        "resistance_far": round(resistance_60, 2),
        "current": round(current, 2),
    }


def analyze_buy_sell_signals(stock_code, buy_price=None):
    """
    综合买卖信号分析
    
    参数:
        stock_code: 股票代码
        buy_price: 持仓成本价（可选，用于持仓诊断）
    
    返回:
        JSON 字符串
    """
    clean_code = stock_code.zfill(6)

    # 1. 获取K线数据 (120天)
    klines = get_kline_data(clean_code, days=120)
    if not klines or len(klines) < 30:
        return json.dumps(
            {"error": f"无法获取{clean_code}足够的K线数据"}, ensure_ascii=False
        )

    # 2. 获取实时行情
    quote = get_realtime_quote(clean_code)
    if not quote:
        return json.dumps(
            {"error": f"无法获取{clean_code}实时行情"}, ensure_ascii=False
        )

    closes = [k["close"] for k in klines if k["close"] > 0]
    volumes = [k["volume"] for k in klines if k["volume"] > 0]
    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]

    current_price = quote["price"]
    current_vol = quote["volume"]

    # 追加当日数据到数组
    all_closes = closes + [current_price]
    all_volumes = volumes + [current_vol]

    # ── 技术指标计算 ──
    ma5 = calc_ma(all_closes, 5)
    ma10 = calc_ma(all_closes, 10)
    ma20 = calc_ma(all_closes, 20)
    ma60 = calc_ma(all_closes, 60)

    vol_ma5 = calc_ma(all_volumes, 5)
    vol_ma20 = calc_ma(all_volumes, 20)

    rsi = calc_rsi(all_closes, 14)
    dif, dea, macd_bar = calc_macd(all_closes)

    sr_levels = find_support_resistance(klines)

    # ── 信号检测 ──
    buy_signals = []
    sell_signals = []
    buy_score = 0
    sell_score = 0

    # === 买入信号检测 ===

    # 1. 放量突破均线
    if ma20 and current_price > ma20:
        vol_ratio = current_vol / vol_ma20 if vol_ma20 and vol_ma20 > 0 else 0
        if vol_ratio >= 1.5:
            buy_signals.append(f"放量突破MA20 (量比{vol_ratio:.1f}x)")
            buy_score += 15
        elif vol_ratio >= 1.0:
            buy_signals.append(f"站上MA20 (量比{vol_ratio:.1f}x)")
            buy_score += 8

    # 2. 均线金叉
    if ma5 and ma10 and ma5 > ma10:
        # 检查是否是刚金叉（前一日MA5 < MA10）
        prev_closes_5 = all_closes[-6:-1]
        prev_closes_10 = all_closes[-11:-1] if len(all_closes) >= 11 else all_closes[:-1]
        prev_ma5 = np.mean(prev_closes_5) if len(prev_closes_5) >= 5 else None
        prev_ma10 = np.mean(prev_closes_10) if len(prev_closes_10) >= 10 else None

        if prev_ma5 and prev_ma10 and prev_ma5 <= prev_ma10:
            buy_signals.append("MA5上穿MA10金叉 ✨")
            buy_score += 12
        elif ma5 > ma10 > ma20 if (ma5 and ma10 and ma20 and ma5 > ma10 > ma20) else False:
            buy_signals.append("均线多头排列 (MA5>MA10>MA20)")
            buy_score += 8
        else:
            buy_signals.append("短期均线走强 (MA5>MA10)")
            buy_score += 4

    # 3. RSI超卖反弹
    if rsi is not None:
        if rsi < 30:
            buy_signals.append(f"RSI超卖({rsi:.1f})，反弹概率高")
            buy_score += 12
        elif rsi < 40:
            buy_signals.append(f"RSI偏弱({rsi:.1f})，关注企稳")
            buy_score += 5

    # 4. MACD金叉
    if dif is not None and dea is not None:
        if dif > dea:
            if macd_bar and macd_bar > 0:
                # 检查是否刚金叉
                prev_all_closes = all_closes[:-1]
                prev_dif, prev_dea, _ = calc_macd(prev_all_closes)
                if prev_dif and prev_dea and prev_dif <= prev_dea:
                    buy_signals.append("MACD金叉形成 ✨")
                    buy_score += 10
                else:
                    buy_signals.append("MACD多头运行")
                    buy_score += 5

    # 5. 缩量回踩支撑位
    if sr_levels and current_price <= sr_levels["support_near"] * 1.05:
        vol_ratio = current_vol / vol_ma5 if vol_ma5 and vol_ma5 > 0 else 1
        if vol_ratio < 0.8:
            buy_signals.append(f"缩量回踩支撑{sr_levels['support_near']:.2f}")
            buy_score += 10
        else:
            buy_signals.append(f"回踩支撑位{sr_levels['support_near']:.2f}附近")
            buy_score += 6

    # 6. 放量阳包阴
    if len(klines) >= 2:
        prev_close = klines[-1]["close"]
        prev_open = klines[-1]["open"]
        if prev_close < prev_open and current_price > prev_open:
            if current_vol > vol_ma5 * 1.2 if (vol_ma5 and vol_ma5 > 0) else False:
                buy_signals.append("放量阳包阴反转")
                buy_score += 12

    # === 卖出信号检测 ===

    # 1. 放量跌破均线
    if ma20 and current_price < ma20:
        vol_ratio = current_vol / vol_ma5 if vol_ma5 and vol_ma5 > 0 else 0
        if vol_ratio >= 1.5:
            sell_signals.append(f"放量跌破MA20 (量比{vol_ratio:.1f}x)")
            sell_score += 15
        elif current_price < ma10:
            sell_signals.append("跌破MA10支撑")
            sell_score += 8

    # 2. 均线死叉
    if ma5 and ma10 and ma5 < ma10:
        prev_closes_5 = all_closes[-6:-1]
        prev_closes_10 = all_closes[-11:-1] if len(all_closes) >= 11 else all_closes[:-1]
        prev_ma5 = np.mean(prev_closes_5) if len(prev_closes_5) >= 5 else None
        prev_ma10 = np.mean(prev_closes_10) if len(prev_closes_10) >= 10 else None

        if prev_ma5 and prev_ma10 and prev_ma5 >= prev_ma10:
            sell_signals.append("MA5下穿MA10死叉 ⚠️")
            sell_score += 12
        else:
            sell_signals.append("短期均线走弱 (MA5<MA10)")
            sell_score += 6

    # 3. RSI超买
    if rsi is not None:
        if rsi > 80:
            sell_signals.append(f"RSI严重超买({rsi:.1f})，回调风险高")
            sell_score += 15
        elif rsi > 70:
            sell_signals.append(f"RSI超买({rsi:.1f})，注意风险")
            sell_score += 8

    # 4. MACD死叉
    if dif is not None and dea is not None:
        if dif < dea:
            prev_all_closes = all_closes[:-1]
            prev_dif, prev_dea, _ = calc_macd(prev_all_closes)
            if prev_dif and prev_dea and prev_dif >= prev_dea:
                sell_signals.append("MACD死叉形成 ⚠️")
                sell_score += 12
            else:
                sell_signals.append("MACD空头运行")
                sell_score += 5

    # 5. 高位放量滞涨
    if sr_levels and current_price >= sr_levels["resistance_near"] * 0.95:
        if quote["change_rate"] < 2 and current_vol > (vol_ma5 * 1.5 if vol_ma5 and vol_ma5 > 0 else 0):
            sell_signals.append("高位放量滞涨，出货嫌疑")
            sell_score += 12

    # 6. 高位长上影
    if quote.get("high", 0) > 0 and quote.get("low", 0) > 0:
        upper_shadow = quote["high"] - max(quote.get("open", current_price), current_price)
        body = abs(current_price - quote.get("open", current_price))
        if body > 0 and upper_shadow / body > 1.5:
            sell_signals.append("高位长上影线")
            sell_score += 6

    # ── 综合判断 ──
    net_score = buy_score - sell_score

    if net_score >= 25:
        signal = "STRONG_BUY"
    elif net_score >= 12:
        signal = "BUY"
    elif net_score >= 5:
        signal = "WEAK_BUY"
    elif net_score >= -5:
        signal = "HOLD"
    elif net_score >= -12:
        signal = "WEAK_SELL"
    elif net_score >= -25:
        signal = "SELL"
    else:
        signal = "STRONG_SELL"

    signal_info = SIGNAL_LEVELS[signal]

    # ── 计算建议价位 ──
    suggested_buy_price = None
    suggested_sell_price = None

    # 买入建议价：支撑位附近或MA20附近
    if sr_levels:
        candidates = []
        if sr_levels["support_near"] > 0:
            candidates.append(sr_levels["support_near"] * 1.02)
        if ma20:
            candidates.append(ma20)
        if ma60:
            candidates.append(ma60)
        if candidates:
            suggested_buy_price = round(np.mean(candidates), 2)

    # 卖出建议价：阻力位附近
    if sr_levels and sr_levels["resistance_near"] > 0:
        suggested_sell_price = round(sr_levels["resistance_near"] * 0.98, 2)

    # ── 持仓诊断 (如有成本价) ──
    position_advice = None
    if buy_price and buy_price > 0:
        pnl_pct = round((current_price - buy_price) / buy_price * 100, 2)
        position_advice = {
            "cost": round(buy_price, 2),
            "current": round(current_price, 2),
            "pnl_pct": pnl_pct,
            "advice": "",
        }

        if pnl_pct <= -15 and "BUY" in signal:
            position_advice["advice"] = "深度套牢但买点信号出现，可考虑补仓摊低成本"
        elif pnl_pct <= -8:
            position_advice["advice"] = "浮亏较大，关注支撑位，企稳可补仓"
        elif pnl_pct <= -3:
            position_advice["advice"] = "轻微浮亏，持有观察"
        elif pnl_pct >= 20 and "SELL" in signal:
            position_advice["advice"] = "大幅盈利+卖出信号，建议分批止盈"
        elif pnl_pct >= 10:
            position_advice["advice"] = "盈利可观，关注阻力位，可设止盈"
        elif pnl_pct >= 3:
            position_advice["advice"] = "小幅盈利，趋势良好可持有"
        else:
            position_advice["advice"] = "盈亏平衡附近，观望为主"

    result = {
        "stock_code": clean_code,
        "current_price": round(current_price, 2),
        "change_rate": quote["change_rate"],
        "signal": signal,
        "signal_label": signal_info["label"],
        "signal_desc": signal_info["desc"],
        "net_score": net_score,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "indicators": {
            "ma5": ma5,
            "ma10": ma10,
            "ma20": ma20,
            "ma60": ma60,
            "rsi": rsi,
            "macd_dif": dif,
            "macd_dea": dea,
            "macd_bar": macd_bar,
            "vol_ma5": vol_ma5,
            "vol_ma20": vol_ma20,
        },
        "support_resistance": sr_levels,
        "suggested_buy_price": suggested_buy_price,
        "suggested_sell_price": suggested_sell_price,
        "position_advice": position_advice,
        "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    return json.dumps(result, ensure_ascii=False)


# ── 测试 ──
if __name__ == "__main__":
    import sys

    test_code = sys.argv[1] if len(sys.argv) > 1 else "002463"
    print(f"🔍 分析 {test_code} 买卖信号...\n")
    result = analyze_buy_sell_signals(test_code, buy_price=31.2)
    data = json.loads(result)
    if "error" in data:
        print(f"❌ {data['error']}")
    else:
        color_map = {
            "STRONG_BUY": "🔴", "BUY": "🟠", "WEAK_BUY": "🟡",
            "HOLD": "⚪", "WEAK_SELL": "🟢", "SELL": "🟢", "STRONG_SELL": "🟢",
        }
        emoji = color_map.get(data["signal"], "⚪")
        print(f"  {emoji} 信号: {data['signal_label']} ({data['signal_desc']})")
        print(f"  净得分: {data['net_score']} | 买分: {data['buy_score']} | 卖分: {data['sell_score']}")
        if data["buy_signals"]:
            print(f"  买点: {'; '.join(data['buy_signals'])}")
        if data["sell_signals"]:
            print(f"  卖点: {'; '.join(data['sell_signals'])}")
        if data["suggested_buy_price"]:
            print(f"  建议买入价: {data['suggested_buy_price']}")
        if data["suggested_sell_price"]:
            print(f"  建议卖出价: {data['suggested_sell_price']}")
        if data.get("position_advice"):
            pa = data["position_advice"]
            print(f"  持仓诊断: {pa['advice']} (盈亏 {pa['pnl_pct']:+.2f}%)")
