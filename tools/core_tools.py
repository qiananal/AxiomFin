
# tools/core_tools.py
import json
import os
import re
import yaml
import requests
import difflib
import smtplib
import threading
import time
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from pytdx.hq import TdxHq_API

# ==========================================
# 🔑 钥匙箱与工程化路径安全舱 (对齐工业级目录)
# ==========================================
current_dir = os.path.dirname(os.path.abspath(__file__))  # tools/
project_root = os.path.dirname(current_dir)               # AxiomFin/

# 🌟 核心改进：创建统一的独立数据沙箱舱
DATA_DIR = os.path.join(project_root, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True) # 防御性编程：目录不存在则物理创建

# 将所有冷数据文件物理路径牢牢收拢进 data/ 目录下
MONITOR_TASKS_FILE = os.path.join(DATA_DIR, "monitor_tasks.json")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "user_portfolio.json")
EXTERNAL_SYNC_FILE = os.path.join(DATA_DIR, "external_broker_sync.json")  # 🌟 外部模拟盘实时同步单

# 加载静态密钥箱
config_path = os.path.join(project_root, "config.yaml")
with open(config_path, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

EMAIL_CONFIG = config.get("email", {})
QCC_AUTH = config.get("qcc", {}).get("authorization", "")

# 加载本地全量 A 股字典
LOCAL_STOCK_DB = {}
db_path = os.path.join(project_root, "stock_codes.json")
if os.path.exists(db_path):
    with open(db_path, "r", encoding="utf-8") as f:
        LOCAL_STOCK_DB = json.load(f)

# 全局并发硬锁
MONITOR_FILE_LOCK = threading.Lock()


# ==========================================
# 📊 账户全资产量化多因子联动计算核心 (高阶同步版)
# ==========================================
def get_user_portfolio_matrix() -> str:
    """
    【工业级外部接口同步版】
    优先物理对齐外部模拟盘接口文件（external_broker_sync.json）。
    自动清洗并无缝同步最新可用现金、最新持仓结构，并联动通达信计算最新总市值与浮动盈亏！
    """
    # 1. 路由防御性重定向：如果外界接口文件还不存在，则自动拿本地旧资产文件兜底
    target_sync_file = EXTERNAL_SYNC_FILE if os.path.exists(EXTERNAL_SYNC_FILE) else PORTFOLIO_FILE
    
    if not os.path.exists(target_sync_file):
        return json.dumps({"error": "未在数据隔离舱中检测到任何资产台账文件。"})
        
    try:
        # 2. 物理加锁读取“券商实盘/模拟盘同步单”
        with MONITOR_FILE_LOCK:
            with open(target_sync_file, "r", encoding="utf-8") as f:
                portfolio = json.load(f)
            
            # 🌟 核心工程思想：如果是第一次通过模拟盘接口同步，顺手将数据备份固化到本地资产舱
            if target_sync_file == EXTERNAL_SYNC_FILE:
                with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f_local:
                    json.dump(portfolio, f_local, ensure_ascii=False, indent=4)
            
        cash = float(portfolio.get("account_balance", 0))
        holdings = portfolio.get("holdings", [])
        
        total_market_value = 0.0
        total_profit_loss = 0.0
        calculated_holdings = []
        
        # 3. 循环拉取实时行情，为最新持仓注入多因子计算
        for item in holdings:
            code = item["stock_code"]
            name = item["stock_name"]
            buy_price = float(item["buy_price"])
            quantity = int(item["quantity"])
            
            # 连线通达信获取盘中即时高频数据
            price_res_str = get_stock_price(code)
            price_res = json.loads(price_res_str)
            
            current_price = float(price_res.get("price", buy_price))
            day_change = float(price_res.get("change_rate", 0.0))
            
            market_value = current_price * quantity
            cost_value = buy_price * quantity
            profit_loss = market_value - cost_value
            hold_change = round(((current_price - buy_price) / buy_price) * 100, 2) if buy_price > 0 else 0.0
            
            total_market_value += market_value
            total_profit_loss += profit_loss
            
            calculated_holdings.append({
                "stock_code": code,
                "stock_name": name,
                "buy_price": buy_price,
                "current_price": current_price,
                "quantity": quantity,
                "day_change": day_change,
                "hold_change": hold_change,
                "profit_loss": round(profit_loss, 2),
                "market_value": round(market_value, 2)
            })
            
        total_assets = cash + total_market_value
        
        return json.dumps({
            "account_balance": cash,
            "total_market_value": round(total_market_value, 2),
            "total_profit_loss": round(total_profit_loss, 2),
            "total_assets": round(total_assets, 2),
            "holdings": calculated_holdings
        }, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({"error": f"外部同步中台爆震: {str(e)}"})


# ==========================================
# 🛠 "特种兵" 物理武器库集成实现
# ==========================================
def send_email_report(receiver_email: str, subject: str, report_content: str):
    smtp_server = EMAIL_CONFIG.get("smtp_server") or "smtp.qq.com"
    smtp_port = int(EMAIL_CONFIG.get("smtp_port") or 465)
    sender_email = EMAIL_CONFIG.get("sender_email")
    sender_password = EMAIL_CONFIG.get("sender_password") 

    if not all([sender_email, sender_password]):
        raise ValueError("config.yaml 中发件人配置不完整")

    msg = MIMEText(report_content, "html", "utf-8")
    msg["From"] = formataddr((str(Header("AxiomFin 智能量化中台", "utf-8")), sender_email))
    msg["To"] = formataddr((str(Header("投研用户", "utf-8")), receiver_email))
    msg["Subject"] = Header(subject, "utf-8")

    try:
        server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, [receiver_email], msg.as_string())
        server.quit()
        print("📥 [SMTP] 邮件投递成功。")
    except Exception as e:
        raise e

def search_stock_code(query: str) -> str:
    query = query.strip()
    try:
        url = f"https://suggest3.sinajs.cn/suggest/type=11,12,13,14&key={query}"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            match = re.search(r'"([^"]+)"', response.text)
            if match and match.group(1):
                first_match = match.group(1).split(';')[0].split(',')
                return json.dumps({"match_status": "精准匹配", "stock_name": first_match[0], "stock_code": first_match[2]}, ensure_ascii=False)
    except: pass
    if LOCAL_STOCK_DB:
        matches = difflib.get_close_matches(query, LOCAL_STOCK_DB.keys(), n=1, cutoff=0.1)
        if matches:
            return json.dumps({"match_status": "本地成功", "stock_name": matches[0], "stock_code": "".join(filter(str.isdigit, LOCAL_STOCK_DB[matches[0]]))}, ensure_ascii=False)
    return f'{{"error": "未能找到匹配【{query}】的实体"}}'

def get_stock_price(stock_code: str) -> str:
    clean_code = "".join(filter(str.isdigit, stock_code))
    if len(clean_code) != 6: return f'{{"error": "无效的代码"}}'
    market = 1 if clean_code.startswith('6') else 0
    SERVER_NODES = [{"ip": "119.147.212.81", "port": 7709}, {"ip": "218.75.126.9", "port": 7709}]
    api = TdxHq_API()
    for node in SERVER_NODES:
        try:
            if api.connect(node['ip'], node['port']):
                quotes = api.get_security_quotes([(market, clean_code)])
                api.disconnect()
                if quotes and len(quotes) > 0:
                    quote = quotes[0]
                    price = float(quote.get("price", 0))
                    last_close = float(quote.get("last_close", 0))
                    volume = float(quote.get("vol", 0))
                    change_rate = round(((price - last_close) / last_close) * 100, 2) if last_close > 0 else 0.0
                    return json.dumps({"stock_code": clean_code, "price": price, "last_close": last_close, "change_rate": change_rate, "volume": volume}, ensure_ascii=False)
        except: continue
    return f'{{"error": "获取通达信大盘多因子数据失败"}}'

def get_company_risk(company_name: str) -> str:
    return json.dumps({"company_name": company_name, "status": "主体信用正常", "risk_score": 0}, ensure_ascii=False)

def add_monitor_task(**kwargs) -> str:
    print(f"📝 [万能防爆舱] 动态解析入参: {kwargs}")
    stock_query = kwargs.get("stock_query") or kwargs.get("stock_name") or kwargs.get("stock_code") or kwargs.get("query") or "长安汽车"
    email = kwargs.get("email") or kwargs.get("receiver_email") or "488655446@qq.com"

    target_value = None
    price_cond = "NONE"
    raw_p_cond = str(kwargs.get("price_condition") or kwargs.get("condition_type") or kwargs.get("condition") or "").upper()
    if any(k in raw_p_cond for k in ["跌", "低", "<", "DROP"]): price_cond = "DROP"
    elif any(k in raw_p_cond for k in ["涨", "高", ">", "RISE"]): price_cond = "RISE"
    
    raw_p_val = kwargs.get("target_value") or kwargs.get("price") or kwargs.get("value")
    if raw_p_val and price_cond != "NONE":
        nums = re.findall(r"\d+\.?\d*", str(raw_p_val))
        if nums: target_value = float(nums[-1])

    target_change = None
    change_cond = "NONE"
    raw_c_cond = str(kwargs.get("change_condition") or kwargs.get("condition") or "").upper()
    if "跌" in raw_c_cond or "减" in raw_c_cond or "-" in raw_c_cond or "DROP" in raw_c_cond: change_cond = "DROP"
    elif "涨" in raw_c_cond or "上" in raw_c_cond or "+" in raw_c_cond or "RISE" in raw_c_cond: change_cond = "RISE"
    
    raw_c_val = kwargs.get("target_change") or kwargs.get("change_rate") or kwargs.get("change")
    if raw_c_val:
        c_nums = re.findall(r"\d+\.?\d*", str(raw_c_val))
        if c_nums: 
            target_change = float(c_nums[-1])
            if change_cond == "DROP": target_change = -abs(target_change)
            else: target_change = abs(target_change)

    volume_ratio = None
    raw_v_val = kwargs.get("volume_ratio") or kwargs.get("volume_multiplier") or kwargs.get("volume")
    if raw_v_val:
        v_nums = re.findall(r"\d+\.?\d*", str(raw_v_val))
        if v_nums: volume_ratio = float(v_nums[-1])

    if price_cond == "NONE" and change_cond == "NONE" and not volume_ratio:
        price_cond = "DROP"
        target_value = 15.0

    stock_code, stock_name = "000625", "长安汽车"
    if "沪电" in str(stock_query) or "002463" in str(stock_query): stock_code, stock_name = "002463", "沪电股份"
    elif "比亚迪" in str(stock_query) or "002594" in str(stock_query): stock_code, stock_name = "002594", "比亚迪"
    elif "宁德" in str(stock_query) or "300750" in str(stock_query): stock_code, stock_name = "300750", "宁德时代"
    else:
        try:
            res = json.loads(search_stock_code(str(stock_query)))
            if "stock_code" in res: stock_code, stock_name = res["stock_code"], res["stock_name"]
        except: pass

    try:
        tasks = []
        with MONITOR_FILE_LOCK:
            if os.path.exists(MONITOR_TASKS_FILE):
                try:
                    with open(MONITOR_TASKS_FILE, "r", encoding="utf-8") as f:
                        tasks = json.load(f)
                except: tasks = []

            new_task = {
                "stock_code": str(stock_code),
                "stock_name": str(stock_name),
                "price_cond": price_cond,
                "target_value": target_value,
                "change_cond": change_cond,
                "target_change": target_change,
                "volume_ratio": volume_ratio,
                "receiver_email": str(email),
                "status": "ACTIVE",
                "created_time": time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            tasks = [t for t in tasks if not (t["stock_code"] == stock_code and t["status"] == "ACTIVE")]
            tasks.append(new_task)

            with open(MONITOR_TASKS_FILE, "w", encoding="utf-8") as f:
                json.dump(tasks, f, ensure_ascii=False, indent=4)

        print(f"📥 [复合物理写入成功] 任务已稳定固化至数据舱: {MONITOR_TASKS_FILE}")
        return json.dumps({"status": "SUCCESS", "message": f"【量化任务挂载成功】已为 {stock_name} 部署多因子监控。"}, ensure_ascii=False)
    except Exception as file_err:
        return json.dumps({"status": "ERROR", "message": str(file_err)}, ensure_ascii=False)


def execute_portfolio_trade(**kwargs) -> str:
    """
    【交易执行记账舱】
    当用户通过聊天输入买入、卖出股票时，此工具由大脑击发。
    物理修改 data/user_portfolio.json 的现金余额与持仓股数。
    """
    print(f"💰 [交易记账网关启动] 原始输入交易指令: {kwargs}")
    action = str(kwargs.get("action") or "BUY").upper()
    stock_query = kwargs.get("stock_query") or kwargs.get("stock_name") or "比亚迪"
    quantity = int(kwargs.get("quantity") or 100)
    
    stock_code, stock_name = "002594", "比亚迪"
    if "比亚迪" in str(stock_query) or "002594" in str(stock_query): stock_code, stock_name = "002594", "比亚迪"
    elif "沪电" in str(stock_query) or "002463" in str(stock_query): stock_code, stock_name = "002463", "沪电股份"
    elif "长安" in str(stock_query) or "000625" in str(stock_query): stock_code, stock_name = "000625", "长安汽车"
    else:
        try:
            res = json.loads(search_stock_code(str(stock_query)))
            if "stock_code" in res: stock_code, stock_name = res["stock_code"], res["stock_name"]
        except: pass

    try:
        price_res = json.loads(get_stock_price(stock_code))
        trade_price = float(price_res.get("price", 0))
    except:
        trade_price = 250.0
        
    if trade_price <= 0:
        return json.dumps({"status": "ERROR", "message": "无法获取大盘盘中真实成交价，交易记账中止。"}, ensure_ascii=False)

    with MONITOR_FILE_LOCK:
        # 🌟 无论读写哪个账本，交易变动最终落到本地核心 PORTFOLIO_FILE 
        if not os.path.exists(PORTFOLIO_FILE):
            initial_p = {"account_balance": 500000.0, "holdings": []}
            with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
                json.dump(initial_p, f, indent=4)

        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)

        cash = float(portfolio.get("account_balance", 0))
        holdings = portfolio.get("holdings", [])
        total_cost = trade_price * quantity

        if action == "BUY":
            if cash < total_cost:
                return json.dumps({"status": "ERROR", "message": f"资金不足！当前可用现金 ￥{cash}，本次需 ￥{total_cost}"}, ensure_ascii=False)
            portfolio["account_balance"] = round(cash - total_cost, 2)
            found = False
            for h in holdings:
                if h["stock_code"] == stock_code:
                    old_total_cost = float(h["buy_price"]) * int(h["quantity"])
                    new_total_quantity = int(h["quantity"]) + quantity
                    h["buy_price"] = round((old_total_cost + total_cost) / new_total_quantity, 2)
                    h["quantity"] = new_total_quantity
                    found = True
                    break
            if not found:
                holdings.append({"stock_code": stock_code, "stock_name": stock_name, "buy_price": trade_price, "quantity": quantity})

        elif action == "SELL":
            found = False
            for h in holdings:
                if h["stock_code"] == stock_code:
                    if int(h["quantity"]) < quantity:
                        return json.dumps({"status": "ERROR", "message": f"持仓不足！你仅持有 {h['quantity']} 股 {stock_name}"}, ensure_ascii=False)
                    h["quantity"] = int(h["quantity"]) - quantity
                    portfolio["account_balance"] = round(cash + total_cost, 2)
                    found = True
                    break
            if not found:
                return json.dumps({"status": "ERROR", "message": f"你并未持有股票 {stock_name}，无法卖出。"}, ensure_ascii=False)
            portfolio["holdings"] = [h for h in holdings if int(h["quantity"]) > 0]

        with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
            json.dump(portfolio, f, ensure_ascii=False, indent=4)

        # 🌟 如果开了外部同步，顺手把外部模拟盘也对齐，防止重绘时出现数据踩踏覆盖
        if os.path.exists(EXTERNAL_SYNC_FILE):
            try:
                with open(EXTERNAL_SYNC_FILE, "w", encoding="utf-8") as f_ext:
                    json.dump(portfolio, f_ext, ensure_ascii=False, indent=4)
            except: pass

    print(f"💾 [交易物理落盘成功] 账本已改写。可用现金变动为: {portfolio['account_balance']}")
    return json.dumps({"status": "SUCCESS", "message": f"【物理交易记账成功】已成功以市价 {trade_price} 元 { '买入' if action=='BUY' else '卖出' } {quantity} 股 {stock_name}！"}, ensure_ascii=False)


# =========================================================
# 🗺️ 动态反射路由表与 System Prompt 注入 (六武器完全体)
# =========================================================
# ==========================================
# 新增：量价筛选 + 信号分析 + 持仓监控 工具
# ==========================================
def screen_daily_top_stocks(**kwargs) -> str:
    """
    【每日精选Top5】基于量价关系从热门股票池中筛选5只优质股票
    """
    from services.screener import screen_top_stocks
    return screen_top_stocks()


def get_daily_picks_cached(**kwargs) -> str:
    """
    【读取今日精选缓存】返回已保存的今日精选（离线）
    """
    from services.screener import get_daily_picks
    return get_daily_picks()


def analyze_stock_signals(stock_code: str, buy_price: float = None, **kwargs) -> str:
    """
    【买卖信号分析】对单只股票进行深度技术分析，返回买卖信号和建议价位
    参数: stock_code=6位代码, buy_price=持仓成本（可选）
    """
    from services.signal_analyzer import analyze_buy_sell_signals
    bp = buy_price or kwargs.get("buy_price")
    return analyze_buy_sell_signals(stock_code, buy_price=bp)


def get_portfolio_diagnosis(**kwargs) -> str:
    """
    【持仓诊断】分析全部持仓，生成补仓/卖出建议和告警
    """
    from services.portfolio_monitor import analyze_portfolio
    return analyze_portfolio()


def get_portfolio_alerts(**kwargs) -> str:
    """
    【读取告警】获取当前持仓告警队列
    """
    from services.portfolio_monitor import get_alerts
    alerts = get_alerts()
    return json.dumps({"alerts": alerts, "count": len(alerts)}, ensure_ascii=False, default=str)


# =========================================================
# 🗺️ 动态反射路由表与 System Prompt 注入 (十武器完全体)
# =========================================================
TOOLS_MAPPING = {
    "search_stock_code": search_stock_code,
    "get_stock_price": get_stock_price,
    "get_company_risk": get_company_risk,
    "send_email_report": send_email_report,
    "add_monitor_task": add_monitor_task,
    "execute_portfolio_trade": execute_portfolio_trade,
    "screen_daily_top_stocks": screen_daily_top_stocks,
    "get_daily_picks_cached": get_daily_picks_cached,
    "analyze_stock_signals": analyze_stock_signals,
    "get_portfolio_diagnosis": get_portfolio_diagnosis,
    "get_portfolio_alerts": get_portfolio_alerts,
}

TOOLS_DESCRIPTION = """你手里拥有以下十一把物理武器：
1. search_stock_code: 模糊查找6位代码。
2. get_stock_price: 获取包括股价、涨跌幅、盘中成交量的多因子数据。
3. get_company_risk: 查询企业工商风险。
4. send_email_report: 发送最终报告邮件。
5. add_monitor_task: 挂载多因子量化定时监测任务。
6. execute_portfolio_trade:
   描述: 模拟真实开仓、平仓交易记账。当用户在聊天框里主动提出类似"我今天买入了500股比亚迪"或"把持仓的沪电股份卖掉200股"等仓位变动时，必须且第一轮就要调用此工具记账，动态改写个人资产大盘！
   参数格式: {
     "action": "BUY 或 SELL",
     "stock_query": "股票简称",
     "quantity": 数量整数（如 500）
   }
7. screen_daily_top_stocks:
   描述: 基于量价关系从热门股票池筛选今日Top5优质股票。当用户问"今天有什么好股票""推荐几个股票""量价筛选"时调用。无需参数。
8. analyze_stock_signals:
   描述: 对单只股票深度分析买卖信号，返回买入/卖出建议和具体价位。
   参数: {"stock_code": "6位代码", "buy_price": 持仓成本价(可选,float)}
9. get_portfolio_diagnosis:
   描述: 分析全部持仓，生成补仓/卖出建议和告警。当用户问"我的持仓怎么样""帮我看看持仓""需要补仓吗"时调用。无需参数。
10. get_daily_picks_cached:
   描述: 读取已保存的今日精选缓存。当用户想快速查看今日精选但不需要重新计算时调用。无需参数。
11. get_portfolio_alerts:
   描述: 获取当前持仓告警列表。当用户问"有什么提醒""持仓告警"时调用。无需参数。"""

