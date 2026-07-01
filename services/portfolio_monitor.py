# services/portfolio_monitor.py
"""
持仓监控模块
对已持仓股票进行实时分析监控，判断补仓或卖出时机，触发提醒
"""

import json
import os
import sys
import time
import threading
from datetime import datetime
from pytdx.hq import TdxHq_API

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from services.signal_analyzer import analyze_buy_sell_signals

DATA_DIR = os.path.join(project_root, "data")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "user_portfolio.json")
EXTERNAL_SYNC_FILE = os.path.join(DATA_DIR, "external_broker_sync.json")
ALERTS_FILE = os.path.join(DATA_DIR, "portfolio_alerts.json")

TDX_SERVERS = [
    {"ip": "119.147.212.81", "port": 7709},
    {"ip": "218.75.126.9", "port": 7709},
]

# 全局告警队列（界面实时消费）
alert_queue = []
alert_lock = threading.Lock()


def _connect_tdx():
    api = TdxHq_API()
    for node in TDX_SERVERS:
        try:
            if api.connect(node["ip"], node["port"]):
                return api
        except:
            continue
    return None


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
            return {
                "price": price,
                "change_rate": round(((price - last_close) / last_close) * 100, 2) if last_close > 0 else 0,
                "volume": float(q.get("vol", 0)),
                "amount": float(q.get("amount", 0)) if q.get("amount") else 0,
            }
    except:
        return None
    finally:
        try:
            api.disconnect()
        except:
            pass


def load_portfolio():
    """加载持仓数据"""
    target = EXTERNAL_SYNC_FILE if os.path.exists(EXTERNAL_SYNC_FILE) else PORTFOLIO_FILE
    if not os.path.exists(target):
        return None
    with open(target, "r", encoding="utf-8") as f:
        return json.load(f)


def save_alerts(alerts):
    """保存告警记录"""
    with open(ALERTS_FILE, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)


def load_alerts():
    """加载历史告警"""
    if not os.path.exists(ALERTS_FILE):
        return []
    with open(ALERTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def get_alerts():
    """获取当前告警队列"""
    with alert_lock:
        alerts = list(alert_queue)
    return alerts


def clear_alerts():
    """清空告警"""
    with alert_lock:
        alert_queue.clear()


def analyze_portfolio():
    """
    分析全部持仓，生成诊断建议和告警
    
    返回 JSON 字符串
    """
    portfolio = load_portfolio()
    if not portfolio:
        return json.dumps(
            {"error": "未找到持仓数据", "holdings": [], "alerts": [], "summary": ""},
            ensure_ascii=False,
        )

    holdings = portfolio.get("holdings", [])
    cash = float(portfolio.get("account_balance", 0))

    if not holdings:
        return json.dumps(
            {
                "account_balance": cash,
                "holdings": [],
                "alerts": [],
                "summary": "当前无持仓",
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
        )

    analyzed = []
    alerts = []

    for h in holdings:
        code = h["stock_code"]
        name = h["stock_name"]
        buy_price = float(h["buy_price"])
        quantity = int(h["quantity"])

        # 获取实时行情
        quote = get_realtime_quote(code)
        if not quote:
            analyzed.append(
                {
                    "code": code,
                    "name": name,
                    "buy_price": buy_price,
                    "quantity": quantity,
                    "current_price": None,
                    "error": "无法获取实时行情",
                }
            )
            continue

        current_price = quote["price"]
        pnl = (current_price - buy_price) * quantity
        pnl_pct = round((current_price - buy_price) / buy_price * 100, 2) if buy_price > 0 else 0

        # 调用信号分析器
        try:
            signal_str = analyze_buy_sell_signals(code, buy_price=buy_price)
            signal_data = json.loads(signal_str)
        except:
            signal_data = {"signal": "HOLD", "signal_label": "分析异常"}

        # ── 补仓/卖出决策逻辑 ──
        advice = ""
        alert_type = None  # ADD / SELL / WARNING
        alert_level = 0  # 0=无, 1=提示, 2=重要, 3=紧急

        net_score = signal_data.get("net_score", 0)
        position_advice = signal_data.get("position_advice", {})

        # 补仓判断
        if pnl_pct <= -10 and "BUY" in signal_data.get("signal", ""):
            advice = "🔴 建议补仓：深度浮亏但技术面出现买入信号，补仓可有效摊薄成本"
            alert_type = "ADD"
            alert_level = 3
        elif pnl_pct <= -5 and signal_data.get("signal") in ("STRONG_BUY", "BUY"):
            advice = "🟠 可考虑补仓：浮亏中+强烈买入信号，适量补仓"
            alert_type = "ADD"
            alert_level = 2
        elif pnl_pct <= -3 and signal_data.get("signal") == "STRONG_BUY":
            advice = "🟡 关注补仓机会：轻微浮亏+买入信号共振"
            alert_type = "ADD"
            alert_level = 1

        # 卖出判断
        if pnl_pct >= 15 and "SELL" in signal_data.get("signal", ""):
            advice = "🟢 强烈建议卖出：大幅盈利+卖出信号共振，建议分批止盈锁定利润"
            alert_type = "SELL"
            alert_level = 3
        elif pnl_pct >= 8 and signal_data.get("signal") in ("STRONG_SELL", "SELL"):
            advice = "🟢 建议减仓：盈利可观+技术面转弱，建议减仓"
            alert_type = "SELL"
            alert_level = 2
        elif pnl_pct >= 3 and signal_data.get("signal") == "STRONG_SELL":
            advice = "🟢 关注卖出：有盈利+强烈卖出信号，可部分止盈"
            alert_type = "SELL"
            alert_level = 1
        elif pnl_pct <= -20:
            advice = "⚠️ 深度套牢超20%，不建议盲目割肉，关注反弹机会"
            alert_type = "WARNING"
            alert_level = 2

        # 无明确方向
        if not advice:
            advice = position_advice.get("advice", "继续持有，等待方向明确")

        item = {
            "code": code,
            "name": name,
            "buy_price": round(buy_price, 2),
            "quantity": quantity,
            "current_price": round(current_price, 2),
            "change_rate": quote["change_rate"],
            "pnl": round(pnl, 2),
            "pnl_pct": pnl_pct,
            "market_value": round(current_price * quantity, 2),
            "signal": signal_data.get("signal", "HOLD"),
            "signal_label": signal_data.get("signal_label", "观望"),
            "net_score": net_score,
            "buy_signals": signal_data.get("buy_signals", []),
            "sell_signals": signal_data.get("sell_signals", []),
            "suggested_buy": signal_data.get("suggested_buy_price"),
            "suggested_sell": signal_data.get("suggested_sell_price"),
            "advice": advice,
            "alert_type": alert_type,
            "alert_level": alert_level,
        }
        analyzed.append(item)

        if alert_type and alert_level >= 2:
            alerts.append(item)

    # 写入告警文件
    if alerts:
        old_alerts = load_alerts()
        # 合并去重
        for a in alerts:
            exists = any(
                o["code"] == a["code"]
                and o["alert_type"] == a["alert_type"]
                and o.get("update_time", "").startswith(datetime.now().strftime("%Y-%m-%d"))
                for o in old_alerts
            )
            if not exists:
                a["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                old_alerts.append(a)
        save_alerts(old_alerts)

        # 推送实时告警
        with alert_lock:
            for a in alerts:
                alert_queue.append(a)
            # 保持最近50条
            if len(alert_queue) > 50:
                alert_queue[:] = alert_queue[-50:]

    # 生成汇总
    total_market_value = sum(h.get("market_value", 0) for h in analyzed if h.get("market_value"))
    total_pnl = sum(h.get("pnl", 0) for h in analyzed if h.get("pnl"))

    summary_parts = []
    add_count = sum(1 for h in analyzed if h.get("alert_type") == "ADD" and h.get("alert_level", 0) >= 2)
    sell_count = sum(1 for h in analyzed if h.get("alert_type") == "SELL" and h.get("alert_level", 0) >= 2)
    warn_count = sum(1 for h in analyzed if h.get("alert_type") == "WARNING")

    if add_count:
        summary_parts.append(f"{add_count}只建议补仓")
    if sell_count:
        summary_parts.append(f"{sell_count}只建议卖出")
    if warn_count:
        summary_parts.append(f"{warn_count}只需关注")

    summary = "；".join(summary_parts) if summary_parts else "持仓正常，无需操作"

    result = {
        "account_balance": cash,
        "total_market_value": round(total_market_value, 2),
        "total_pnl": round(total_pnl, 2),
        "holdings": analyzed,
        "alerts": alerts,
        "summary": summary,
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    return json.dumps(result, ensure_ascii=False)


def generate_alert_email(alerts):
    """生成告警邮件HTML"""
    if not alerts:
        return None

    level_emoji = {3: "🚨", 2: "⚠️", 1: "💡"}
    type_labels = {"ADD": "补仓建议", "SELL": "卖出建议", "WARNING": "风险提示"}

    rows = ""
    for a in alerts:
        lvl = a.get("alert_level", 1)
        atype = a.get("alert_type", "WARNING")
        emoji = level_emoji.get(lvl, "💡")
        label = type_labels.get(atype, "提示")

        pnl_color = "#cc0000" if (a.get("pnl_pct", 0) or 0) >= 0 else "#00aa00"
        rows += f"""
        <tr>
            <td style="padding:10px; border-bottom:1px solid #eee;">
                <b>{emoji} {label}</b><br>
                <span style="font-size:14px;">{a['name']}({a['code']})</span>
            </td>
            <td style="padding:10px; border-bottom:1px solid #eee;">
                现价: <b>{a['current_price']}</b><br>
                成本: {a['buy_price']}
            </td>
            <td style="padding:10px; border-bottom:1px solid #eee; color:{pnl_color};">
                盈亏: <b>{a['pnl_pct']:+.2f}%</b><br>
                ¥{a['pnl']:+,.2f}
            </td>
            <td style="padding:10px; border-bottom:1px solid #eee; font-size:13px;">
                {a['advice']}
            </td>
        </tr>"""

    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 650px;">
        <h2 style="color: #cc0000; border-bottom: 2px solid #cc0000; padding-bottom: 10px;">
            👑 AxiomFin 持仓监控告警
        </h2>
        <p style="color: #666;">时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <table style="width:100%; border-collapse:collapse; margin-top:15px;">
            <thead>
                <tr style="background:#f5f5f5;">
                    <th style="padding:10px; text-align:left;">股票</th>
                    <th style="padding:10px; text-align:left;">现价/成本</th>
                    <th style="padding:10px; text-align:left;">盈亏</th>
                    <th style="padding:10px; text-align:left;">建议</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        <p style="margin-top:20px; color:#999; font-size:12px;">
            AxiomFin 量化中台 · 自动持仓监控
        </p>
    </div>"""


# ── 测试 ──
if __name__ == "__main__":
    print("🔍 持仓分析中...\n")
    result = analyze_portfolio()
    data = json.loads(result)
    if "error" in data:
        print(f"❌ {data['error']}")
    else:
        print(f"💰 现金: ¥{data.get('account_balance', 0):,.2f}")
        print(f"📊 总市值: ¥{data.get('total_market_value', 0):,.2f}")
        print(f"📈 总盈亏: ¥{data.get('total_pnl', 0):+,.2f}")
        print(f"\n{'─'*60}")
        for h in data.get("holdings", []):
            color = "🔴" if (h.get("pnl_pct", 0) or 0) >= 0 else "🟢"
            print(f"\n{color} {h['name']}({h['code']})")
            print(f"  持仓: {h['quantity']}股 | 成本: {h['buy_price']} | 现价: {h.get('current_price', 'N/A')}")
            print(f"  盈亏: {h.get('pnl_pct', 0):+.2f}% (¥{h.get('pnl', 0):+,.2f})")
            print(f"  信号: {h.get('signal_label', 'N/A')} (得分: {h.get('net_score', 0)})")
            print(f"  建议: {h.get('advice', 'N/A')}")
        if data.get("alerts"):
            print(f"\n⚠️ 告警 ({len(data['alerts'])}条):")
            for a in data["alerts"]:
                print(f"  - {a['name']}: {a['advice']}")
        print(f"\n📋 汇总: {data.get('summary', 'N/A')}")
