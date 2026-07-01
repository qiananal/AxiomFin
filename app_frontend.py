# app_frontend.py  v2.0
# AxiomFin 金融自动化多因子中台 —— 量价精选 + 买卖信号 + 持仓监控
import streamlit as st
import sys
import os
import threading
import time
import json
from datetime import datetime
from queue import Queue, Empty

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from tools.core_tools import (
    MONITOR_TASKS_FILE, PORTFOLIO_FILE, MONITOR_FILE_LOCK,
    get_stock_price, send_email_report, get_user_portfolio_matrix,
)

# ── 页面配置 ──
st.set_page_config(
    page_title="AxiomFin | 金融自动化多因子中台",
    page_icon="👑",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ──
st.markdown("""
<style>
.main .block-container { padding-top: 1rem; }
.report-box { padding: 18px; background-color: #f0f2f6; border-radius: 10px; border-left: 5px solid #0066cc; margin: 10px 0; }
.log-line { font-family: 'Courier New', monospace; color: #555; margin: 3px 0; font-size: 13px; }
.task-card { padding: 10px; background: #f9f9f9; border-radius: 6px; margin: 6px 0; border: 1px solid #ddd; }
.pick-card {
    padding: 14px; border-radius: 10px; margin: 8px 0;
    border-left: 5px solid #ff6600; background: linear-gradient(135deg, #fff8f0, #fff);
}
.pick-card .rank { font-size: 28px; font-weight: bold; color: #ff6600; }
.pick-card .name { font-size: 16px; font-weight: bold; }
.pick-card .score { font-size: 20px; font-weight: bold; color: #0066cc; }
.alert-card {
    padding: 12px; border-radius: 8px; margin: 6px 0;
    border-left: 4px solid #cc0000; background: #fff5f5;
}
.alert-card.sell { border-left-color: #00aa00; background: #f5fff5; }
.alert-card.add { border-left-color: #cc0000; background: #fff5f5; }
.alert-card.warn { border-left-color: #ffaa00; background: #fffdf5; }
.holding-row { padding: 8px 12px; border-radius: 6px; margin: 4px 0; background: #fafafa; border: 1px solid #eee; }
.signal-strong-buy { color: #cc0000; font-weight: bold; }
.signal-buy { color: #ff6600; font-weight: bold; }
.signal-hold { color: #888; }
.signal-sell { color: #00aa00; font-weight: bold; }
.signal-strong-sell { color: #008800; font-weight: bold; }
.refresh-hint { font-size: 11px; color: #999; text-align: right; margin-top: 4px; }
.section-title {
    font-size: 18px; font-weight: bold; padding: 8px 0;
    border-bottom: 2px solid #0066cc; margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)

# ── 单例守护 ──
if not hasattr(st, "_cron_daemon_initialized"):
    st._cron_daemon_initialized = False
if not hasattr(st, "_portfolio_monitor_initialized"):
    st._portfolio_monitor_initialized = False
if "daily_picks_data" not in st.session_state:
    st.session_state.daily_picks_data = None
if "portfolio_diag_data" not in st.session_state:
    st.session_state.portfolio_diag_data = None
if "portfolio_alerts" not in st.session_state:
    st.session_state.portfolio_alerts = []


# ============================================================
# 后台线程1: 原有多因子巡检守护
# ============================================================
def cron_scheduler_loop():
    while True:
        if os.path.exists(MONITOR_TASKS_FILE):
            tasks = []
            with MONITOR_FILE_LOCK:
                try:
                    with open(MONITOR_TASKS_FILE, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:
                            tasks = json.loads(content)
                except:
                    tasks = []

            if not tasks:
                time.sleep(60)
                continue

            updated_tasks = []
            triggered_any = False

            for task in tasks:
                if task.get("status") != "ACTIVE":
                    updated_tasks.append(task)
                    continue

                code = task["stock_code"]
                name = task["stock_name"]
                email = task["receiver_email"]

                p_cond, target_p = task.get("price_cond", "NONE"), task.get("target_value")
                c_cond, target_c = task.get("change_cond", "NONE"), task.get("target_change")
                v_ratio = task.get("volume_ratio")

                try:
                    price_res_str = get_stock_price(code)
                    price_res = json.loads(price_res_str)
                    if "error" in price_res or float(price_res.get("price", 0)) <= 0:
                        updated_tasks.append(task)
                        continue

                    current_price = float(price_res["price"])
                    current_change = float(price_res["change_rate"])
                    current_vol = float(price_res["volume"])

                    p_triggered = True if p_cond == "NONE" else False
                    if p_cond == "DROP" and current_price <= float(target_p or 0):
                        p_triggered = True
                    if p_cond == "RISE" and current_price >= float(target_p or 0):
                        p_triggered = True

                    c_triggered = True if c_cond == "NONE" else False
                    if c_cond == "DROP" and current_change <= float(target_c or 0):
                        c_triggered = True
                    if c_cond == "RISE" and current_change >= float(target_c or 0):
                        c_triggered = True

                    v_triggered = True if not v_ratio else False
                    if v_ratio:
                        if current_vol >= (45000.0 * float(v_ratio)):
                            v_triggered = True

                    if p_triggered and c_triggered and v_triggered:
                        task["status"] = "TRIGGERED"
                        triggered_any = True

                        cond_rows = ""
                        if p_cond != "NONE":
                            cond_rows += f"<tr><td><b>现价预警线</b></td><td>{'跌破' if p_cond == 'DROP' else '突破'} {target_p} 元 (当前 {current_price})</td></tr>"
                        if c_cond != "NONE":
                            cond_rows += f"<tr><td><b>涨跌幅限制</b></td><td>{'下穿' if c_cond == 'DROP' else '上攻'} {target_c}% (当前 {current_change}%)</td></tr>"
                        if v_ratio:
                            cond_rows += f"<tr><td><b>成交量爆量</b></td><td>超基准 {v_ratio} 倍 ({current_vol} 手)</td></tr>"

                        email_report = f"""
                        <div style="font-family:Arial,sans-serif;padding:15px;border:2px solid #ffaa00;border-radius:8px;">
                            <h2 style="color:#cc0000;border-bottom:2px solid #cc0000;padding-bottom:8px;">👑 AxiomFin 多因子联合共振警报</h2>
                            <table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;background:#fafafa;">
                                {cond_rows}
                            </table>
                        </div>
                        """
                        try:
                            send_email_report(
                                receiver_email=email,
                                subject=f"⚠️【AxiomFin多因子共振】{name}",
                                report_content=email_report,
                            )
                        except:
                            pass
                except Exception as e:
                    print(f"巡检异常: {e}")

                updated_tasks.append(task)

            if triggered_any:
                with MONITOR_FILE_LOCK:
                    try:
                        with open(MONITOR_TASKS_FILE, "w", encoding="utf-8") as f:
                            json.dump(updated_tasks, f, ensure_ascii=False, indent=4)
                    except:
                        pass

        time.sleep(60)


# ============================================================
# 后台线程2: 持仓监控 + 每日精选
# ============================================================
def portfolio_monitor_loop():
    """每5分钟执行持仓诊断 + 每30分钟刷新每日精选"""
    last_screen_time = 0
    last_diag_time = 0

    while True:
        now = time.time()

        # 每日精选: 每30分钟刷新（交易时段内）
        if now - last_screen_time >= 1800:
            try:
                from services.screener import screen_top_stocks
                result = json.loads(screen_top_stocks())
                st.session_state.daily_picks_data = result
                last_screen_time = now
                print(f"📊 [每日精选] 已刷新 Top5，扫描 {result.get('total_scanned', 0)} 只")
            except Exception as e:
                print(f"每日精选刷新失败: {e}")

        # 持仓诊断: 每5分钟
        if now - last_diag_time >= 300:
            try:
                from services.portfolio_monitor import analyze_portfolio, get_alerts
                diag = json.loads(analyze_portfolio())
                st.session_state.portfolio_diag_data = diag
                alerts = get_alerts()
                st.session_state.portfolio_alerts = alerts

                # 如果有紧急告警，发邮件
                urgent = [a for a in alerts if a.get("alert_level", 0) >= 2]
                if urgent:
                    from services.portfolio_monitor import generate_alert_email
                    html = generate_alert_email(urgent)
                    if html:
                        try:
                            send_email_report(
                                receiver_email="488655446@qq.com",
                                subject=f"🚨 AxiomFin 持仓告警 ({len(urgent)}条)",
                                report_content=html,
                            )
                        except:
                            pass

                last_diag_time = now
            except Exception as e:
                print(f"持仓诊断失败: {e}")

        time.sleep(30)


# ============================================================
# 🗃️ 左侧 Sidebar
# ============================================================
with st.sidebar:
    st.title("⚙️ AxiomFin 核心控制台")

    # ── 资产看板 ──
    st.divider()
    st.header("👑 VIP 实时全资产大盘")

    matrix_res = json.loads(get_user_portfolio_matrix())

    if "error" not in matrix_res:
        p_loss = matrix_res["total_profit_loss"]
        loss_color = "🔴" if p_loss >= 0 else "🟢"

        st.metric(label="💼 账户总资产", value=f"¥{matrix_res['total_assets']:,.0f}")

        col1, col2 = st.columns(2)
        col1.metric(label="💴 现金", value=f"¥{matrix_res['account_balance']:,.0f}")
        col2.metric(label=f"{loss_color} 持仓盈亏", value=f"¥{p_loss:+,.0f}")

        st.write("**持仓明细：**")
        for h in matrix_res["holdings"]:
            c_color = "color:red;" if h["profit_loss"] >= 0 else "color:green;"
            st.markdown(f"""
            <div style='padding:10px;background:#f0f2f6;border-radius:6px;margin:4px 0;border-left:4px solid #ffaa00;'>
                <b>{h['stock_name']} ({h['stock_code']})</b><br>
                <span style='font-size:12px;color:#666;'>{h['quantity']}股 | 成本:{h['buy_price']}</span><br>
                <span style='font-size:13px;'>现价: <b>{h['current_price']}</b> ({h['day_change']:+.2f}%)</span><br>
                <span style='font-size:13px;{c_color}'>盈亏: <b>{h['profit_loss']:+,.0f}</b> ({h['hold_change']:+.2f}%)</span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("💡 未检测到持仓数据。在 data/ 目录创建 user_portfolio.json 即可联动。")

    # ── 监控任务面板 ──
    st.divider()
    st.subheader("🤖 多因子监控面板")

    if os.path.exists(MONITOR_TASKS_FILE):
        try:
            with open(MONITOR_TASKS_FILE, "r", encoding="utf-8") as f:
                current_tasks = json.load(f)
            for t in current_tasks:
                status_map = {"ACTIVE": "🟢 巡检中", "TRIGGERED": "🔴 已触发"}
                st.markdown(f"""
                <div class='task-card'>
                    <b>{t['stock_name']} ({t['stock_code']})</b><br>
                    状态: {status_map.get(t['status'], '未知')}
                </div>
                """, unsafe_allow_html=True)
        except:
            pass
    else:
        st.write("暂无活跃任务")

    # ── 持仓告警面板 ──
    st.divider()
    st.subheader("🔔 持仓实时告警")

    alerts = st.session_state.portfolio_alerts
    if alerts:
        level_emoji = {3: "🚨", 2: "⚠️", 1: "💡"}
        type_labels = {"ADD": "补仓", "SELL": "卖出", "WARNING": "注意"}
        for a in alerts[:5]:
            lvl = a.get("alert_level", 1)
            cls = "add" if a.get("alert_type") == "ADD" else ("sell" if a.get("alert_type") == "SELL" else "warn")
            emoji = level_emoji.get(lvl, "💡")
            label = type_labels.get(a.get("alert_type"), "提示")
            st.markdown(f"""
            <div class='alert-card {cls}'>
                <b>{emoji} {a['name']}</b> — {label}<br>
                <small>{a.get('advice', '')}</small>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.write("暂无告警")

    # ── 系统控制 ──
    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🗑️ 清空监控任务", use_container_width=True):
            if os.path.exists(MONITOR_TASKS_FILE):
                os.remove(MONITOR_TASKS_FILE)
            st.session_state.messages = []
            st.success("已重置！")
            st.rerun()
    with col_b:
        if st.button("🔄 立即诊断", use_container_width=True):
            with st.spinner("分析中..."):
                try:
                    from services.portfolio_monitor import analyze_portfolio
                    diag = json.loads(analyze_portfolio())
                    st.session_state.portfolio_diag_data = diag
                    st.success("诊断完成！")
                    st.rerun()
                except Exception as e:
                    st.error(f"失败: {e}")


# ============================================================
# 🏛️ 主界面
# ============================================================
st.title("👑 AxiomFin 金融自动化多因子中台")
st.caption("量价精选 + 买卖信号 + 持仓监控 | DeepSeek 智能体驱动")

# ── Tab 切换 ──
tab1, tab2, tab3, tab4 = st.tabs(["📊 每日精选 Top5", "📈 买卖信号分析", "💼 持仓诊断", "💬 智能投研助手"])

# ============================================================
# Tab 1: 每日精选 Top5
# ============================================================
with tab1:
    col_title, col_btn = st.columns([4, 1])
    with col_title:
        st.markdown('<div class="section-title">🔍 量价关系每日精选</div>', unsafe_allow_html=True)
    with col_btn:
        refresh_btn = st.button("🔄 立即刷新精选", use_container_width=True, key="refresh_picks")

    picks_data = st.session_state.daily_picks_data

    if refresh_btn or not picks_data:
        with st.spinner("🔍 正在扫描全市场热门股票，基于量价关系多因子打分..."):
            try:
                from services.screener import screen_top_stocks
                picks_data = json.loads(screen_top_stocks())
                st.session_state.daily_picks_data = picks_data
            except Exception as e:
                st.error(f"筛选失败: {e}")
                picks_data = {"error": str(e), "picks": []}

    if picks_data and picks_data.get("picks"):
        update_time = picks_data.get("update_time", "未知")
        total = picks_data.get("total_scanned", 0)
        st.caption(f"📅 更新时间: {update_time} | 扫描范围: {total} 只热门股 | 评分维度: 量价关系·趋势·量能结构·突破形态·活跃度")

        cols = st.columns(5)
        for i, pick in enumerate(picks_data["picks"]):
            with cols[i]:
                change_color = "#cc0000" if pick["change_rate"] >= 0 else "#00aa00"
                change_bg = "#fff0f0" if pick["change_rate"] >= 0 else "#f0fff0"

                # 信号标签
                score = pick["score"]
                if score >= 75:
                    grade = "⭐ 强烈推荐"
                elif score >= 60:
                    grade = "👍 值得关注"
                else:
                    grade = "👀 观察"

                st.markdown(f"""
                <div style='padding:12px;border-radius:10px;margin:4px 0;
                            border:2px solid #ff6600;background:linear-gradient(180deg,#fff8f0,#fff);text-align:center;'>
                    <div style='font-size:11px;color:#999;'>#{i+1} {grade}</div>
                    <div style='font-size:15px;font-weight:bold;margin:4px 0;'>{pick['name']}</div>
                    <div style='font-size:11px;color:#888;'>{pick['code']}</div>
                    <div style='font-size:20px;font-weight:bold;margin:6px 0;'>{pick['price']:.2f}</div>
                    <div style='font-size:14px;font-weight:bold;color:{change_color};background:{change_bg};
                                padding:4px 8px;border-radius:4px;display:inline-block;'>
                        {pick['change_rate']:+.2f}%
                    </div>
                    <div style='font-size:22px;font-weight:bold;color:#0066cc;margin:8px 0;'>
                        {pick['score']}<span style='font-size:12px;'>/100</span>
                    </div>
                    <div style='font-size:10px;color:#666;text-align:left;margin-top:6px;'>
                        {'; '.join(pick['reasons'][:3])}
                    </div>
                    <div style='font-size:10px;color:#aaa;margin-top:4px;'>
                        量:{pick['volume']:.0f}手 | 额:{pick['amount']/1e8:.1f}亿
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("📡 暂无精选数据，点击「立即刷新精选」开始扫描。首次加载可能需要10-30秒。")


# ============================================================
# Tab 2: 买卖信号分析
# ============================================================
with tab2:
    st.markdown('<div class="section-title">📈 单股买卖信号深度分析</div>', unsafe_allow_html=True)

    col_code, col_price, col_go = st.columns([2, 1, 1])
    with col_code:
        analyze_code = st.text_input("股票代码", placeholder="例如: 002463", key="sig_code")
    with col_price:
        analyze_cost = st.number_input("持仓成本（可选）", value=0.0, step=0.01, key="sig_cost")
    with col_go:
        st.write("")
        st.write("")
        analyze_btn = st.button("🔍 开始分析", use_container_width=True, key="sig_btn")

    if analyze_btn and analyze_code:
        with st.spinner(f"🧠 正在深度分析 {analyze_code} 的量价关系与技术指标..."):
            try:
                from services.signal_analyzer import analyze_buy_sell_signals
                cost = analyze_cost if analyze_cost > 0 else None
                result = json.loads(analyze_buy_sell_signals(analyze_code, buy_price=cost))
            except Exception as e:
                st.error(f"分析失败: {e}")
                result = {"error": str(e)}

        if "error" in result:
            st.error(result["error"])
        else:
            # 信号大卡片
            sig = result["signal"]
            sig_class = f"signal-{sig.lower().replace('_', '-')}"
            sig_colors = {
                "STRONG_BUY": ("#cc0000", "#fff0f0"),
                "BUY": ("#ff6600", "#fff8f0"),
                "WEAK_BUY": ("#ffaa00", "#fffdf5"),
                "HOLD": ("#888", "#f5f5f5"),
                "WEAK_SELL": ("#00aa00", "#f5fff5"),
                "SELL": ("#00cc00", "#f0fff0"),
                "STRONG_SELL": ("#008800", "#e0ffe0"),
            }
            c, bg = sig_colors.get(sig, ("#888", "#f5f5f5"))
            emoji_map = {"STRONG_BUY": "🔴", "BUY": "🟠", "WEAK_BUY": "🟡", "HOLD": "⚪", "WEAK_SELL": "🟢", "SELL": "🟢", "STRONG_SELL": "🟢"}

            st.markdown(f"""
            <div style='padding:20px;border-radius:12px;margin:10px 0;background:{bg};border:2px solid {c};'>
                <div style='display:flex;align-items:center;gap:15px;'>
                    <div style='font-size:48px;'>{emoji_map.get(sig, '⚪')}</div>
                    <div>
                        <div style='font-size:24px;font-weight:bold;color:{c};'>{result['signal_label']}</div>
                        <div style='color:#666;'>{result['signal_desc']}</div>
                        <div style='margin-top:6px;font-size:13px;color:#888;'>
                            当前价: <b>{result['current_price']:.2f}</b> |
                            涨跌: <b style='color:{"#cc0000" if result["change_rate"]>=0 else "#00aa00"};'>{result['change_rate']:+.2f}%</b> |
                            净得分: <b>{result['net_score']}</b>
                        </div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # 详细指标
            col_left, col_right = st.columns(2)

            with col_left:
                st.markdown("#### 📈 买入信号")
                if result.get("buy_signals"):
                    for s in result["buy_signals"]:
                        st.markdown(f"- {s}")
                else:
                    st.write("暂无买入信号")
                st.markdown("#### 📉 卖出信号")
                if result.get("sell_signals"):
                    for s in result["sell_signals"]:
                        st.markdown(f"- {s}")
                else:
                    st.write("暂无卖出信号")

            with col_right:
                st.markdown("#### 📊 技术指标")
                ind = result.get("indicators", {})
                st.write(f"- MA5: {ind.get('ma5') or '—'} | MA10: {ind.get('ma10') or '—'}")
                st.write(f"- MA20: {ind.get('ma20') or '—'} | MA60: {ind.get('ma60') or '—'}")
                st.write(f"- RSI(14): {ind.get('rsi') or '—'}")
                st.write(f"- MACD: DIF={ind.get('macd_dif') or '—'} DEA={ind.get('macd_dea') or '—'} BAR={ind.get('macd_bar') or '—'}")

                sr = result.get("support_resistance")
                if sr:
                    st.write(f"- 近支撑: {sr.get('support_near')} | 远支撑: {sr.get('support_far')}")
                    st.write(f"- 近阻力: {sr.get('resistance_near')} | 远阻力: {sr.get('resistance_far')}")

                st.markdown("#### 💰 建议价位")
                if result.get("suggested_buy_price"):
                    st.markdown(f"🔴 **建议买入价: ¥{result['suggested_buy_price']:.2f}**")
                if result.get("suggested_sell_price"):
                    st.markdown(f"🟢 **建议卖出价: ¥{result['suggested_sell_price']:.2f}**")

            # 持仓诊断
            pa = result.get("position_advice")
            if pa:
                st.divider()
                st.markdown("#### 💼 持仓诊断")
                c_pnl = "#cc0000" if pa["pnl_pct"] >= 0 else "#00aa00"
                st.markdown(f"""
                | 成本价 | 现价 | 盈亏比例 | 建议 |
                |--------|------|----------|------|
                | {pa['cost']:.2f} | {pa['current']:.2f} | <span style='color:{c_pnl}'>{pa['pnl_pct']:+.2f}%</span> | {pa['advice']} |
                """, unsafe_allow_html=True)


# ============================================================
# Tab 3: 持仓诊断
# ============================================================
with tab3:
    col_t, col_b = st.columns([4, 1])
    with col_t:
        st.markdown('<div class="section-title">💼 持仓综合诊断与操作建议</div>', unsafe_allow_html=True)
    with col_b:
        diag_btn = st.button("🔄 刷新诊断", use_container_width=True, key="diag_refresh")

    diag = st.session_state.portfolio_diag_data

    if diag_btn or not diag:
        with st.spinner("📡 正在拉取实时行情并深度分析全部持仓..."):
            try:
                from services.portfolio_monitor import analyze_portfolio
                diag = json.loads(analyze_portfolio())
                st.session_state.portfolio_diag_data = diag
            except Exception as e:
                st.error(f"诊断失败: {e}")
                diag = {"error": str(e), "holdings": []}

    if diag and not diag.get("error"):
        update_t = diag.get("update_time", "")
        st.caption(f"📅 更新时间: {update_t}")

        # 汇总指标
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("💴 现金", f"¥{diag.get('account_balance', 0):,.0f}")
        col2.metric("📊 总市值", f"¥{diag.get('total_market_value', 0):,.0f}")
        pnl = diag.get("total_pnl", 0)
        col3.metric("📈 总盈亏", f"¥{pnl:+,.0f}", delta=f"{pnl:+,.0f}" if pnl != 0 else None)
        col4.metric("📋 综合建议", diag.get("summary", "—"))

        # 持仓列表
        st.divider()
        st.write("**逐股诊断：**")
        holdings = diag.get("holdings", [])
        if holdings:
            for h in holdings:
                if h.get("error"):
                    st.warning(f"⚠️ {h['name']}({h['code']}): {h['error']}")
                    continue

                pnl_color = "red" if h["pnl_pct"] >= 0 else "green"
                pnl_bg = "#fff0f0" if h["pnl_pct"] >= 0 else "#f0fff0"

                sig = h.get("signal", "HOLD")
                sig_class = f"signal-{sig.lower().replace('_', '-')}"
                sig_colors = {
                    "STRONG_BUY": "#cc0000", "BUY": "#ff6600", "WEAK_BUY": "#ffaa00",
                    "HOLD": "#888", "WEAK_SELL": "#00aa00", "SELL": "#00cc00", "STRONG_SELL": "#008800",
                }
                s_color = sig_colors.get(sig, "#888")

                alert_html = ""
                if h.get("alert_type"):
                    a_emoji = {"ADD": "🔴", "SELL": "🟢", "WARNING": "⚠️"}.get(h["alert_type"], "")
                    alert_html = f'<span style="font-size:18px;">{a_emoji}</span>'

                with st.container():
                    st.markdown(f"""
                    <div style='padding:12px;border-radius:8px;margin:8px 0;background:#fafafa;border:1px solid #ddd;border-left:4px solid {s_color};'>
                        <div style='display:flex;justify-content:space-between;align-items:center;'>
                            <div>
                                <b style='font-size:16px;'>{h['name']}</b>
                                <span style='color:#888;font-size:13px;margin-left:10px;'>{h['code']}</span>
                                <span style='color:{s_color};font-weight:bold;margin-left:10px;font-size:14px;'>{alert_html} {h.get('signal_label', '—')}</span>
                            </div>
                            <div style='text-align:right;'>
                                <div style='font-size:20px;font-weight:bold;'>{h.get('current_price', '—'):.2f}</div>
                                <div style='font-size:12px;color:{"#cc0000" if h["change_rate"]>=0 else "#00aa00"};'>{h['change_rate']:+.2f}%</div>
                            </div>
                        </div>
                        <div style='display:flex;justify-content:space-between;margin-top:10px;font-size:13px;color:#555;'>
                            <div>
                                持仓: {h['quantity']}股 | 成本: {h['buy_price']} | 市值: ¥{h.get('market_value', 0):,.0f}
                            </div>
                            <div style='color:{pnl_color};font-weight:bold;background:{pnl_bg};padding:2px 10px;border-radius:4px;'>
                                盈亏: {h['pnl_pct']:+.2f}% (¥{h['pnl']:+,.0f})
                            </div>
                        </div>
                        <div style='margin-top:8px;padding:8px;background:#fff;border-radius:4px;font-size:13px;'>
                            <b>建议:</b> {h.get('advice', '—')}<br>
                            <span style='color:#888;font-size:11px;'>
                                买分:{h.get('buy_signals', []) and len(h.get('buy_signals',[])) or 0}个 |
                                卖分:{h.get('sell_signals', []) and len(h.get('sell_signals',[])) or 0}个
                                {f" | 建议买入:{h.get('suggested_buy')}" if h.get('suggested_buy') else ""}
                                {f" | 建议卖出:{h.get('suggested_sell')}" if h.get('suggested_sell') else ""}
                            </span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("📭 当前无持仓。通过聊天框进行模拟交易即可自动建仓。")
    else:
        st.info("📡 暂无诊断数据。点击「刷新诊断」开始分析。")


# ============================================================
# Tab 4: 智能投研助手（原聊天界面）
# ============================================================
with tab4:
    st.caption("基于 DeepSeek 大脑 | 支持 24 小时后台多因子多线程定时监控与物理共振预警")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if user_query := st.chat_input(
        "输入投研指令（如：帮我分析002463的买卖点 / 今日精选 / 持仓诊断 / 监控沪电股份跌幅超5%）..."
    ):
        with st.chat_message("user"):
            st.markdown(user_query)
        st.session_state.messages.append({"role": "user", "content": user_query})

        with st.chat_message("assistant"):
            log_queue = Queue()
            with st.status("🧠 AxiomFin 智能体中台推理中...", expanded=True) as status:
                container = {"final_report": None, "error": None}
                recent_context = st.session_state.messages[-6:]

                def worker_task():
                    try:
                        from services.agent_engine import AxiomFinEngine
                        engine = AxiomFinEngine(log_queue=log_queue)
                        container["final_report"] = engine.run_task(recent_context)
                    except Exception as e:
                        container["error"] = str(e)
                    finally:
                        log_queue.put("__DONE__")

                threading.Thread(target=worker_task, daemon=True).start()

                log_placeholder = st.container()
                while True:
                    try:
                        log_msg = log_queue.get(timeout=0.1)
                        if log_msg == "__DONE__":
                            break
                        log_placeholder.markdown(
                            f"<div class='log-line'>{log_msg}</div>",
                            unsafe_allow_html=True,
                        )
                    except Empty:
                        continue

                if container["error"]:
                    status.update(label="💥 引擎故障！", state="error")
                    final_report = f"❌ 详情: {container['error']}"
                else:
                    status.update(label="🏆 推理完成！", state="complete", expanded=False)
                    final_report = container["final_report"]

            st.subheader("📊 最终交付结果")
            st.markdown(f"<div class='report-box'>{final_report}</div>", unsafe_allow_html=True)
            st.session_state.messages.append({"role": "assistant", "content": final_report})
            st.rerun()


# ============================================================
# 🔥 后台守护线程点火
# ============================================================
if not st._cron_daemon_initialized:
    st._cron_daemon_initialized = True
    print("🔥 [中台] 多因子巡检守护线程点火...")
    threading.Thread(target=cron_scheduler_loop, name="AxiomFin-Cron-Daemon", daemon=True).start()
    print("⚡ [中台] 巡检线程就绪！")

if not st._portfolio_monitor_initialized:
    st._portfolio_monitor_initialized = True
    print("🔥 [中台] 持仓监控+每日精选守护线程点火...")
    threading.Thread(target=portfolio_monitor_loop, name="AxiomFin-Portfolio-Monitor", daemon=True).start()
    print("⚡ [中台] 持仓监控线程就绪！")
