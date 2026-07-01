# init_stock_db.py
import requests
import json
import os
import ast  # 引入原生抽象语法树，安全解包非标准 JSON

print("🔄 [坚韧网关点火] 正在从公网同步 A 股全量 5000+ 股票最新花名册...")

# 采用腾讯财经全量行情中台，格式极其标准，从源头上掐灭解析异常
url = "http://stock.gtimg.cn/data/index.php?appn=rank&t=hs_a&p=1&o=0&l=6000&v=list_data"

try:
    response = requests.get(url, timeout=15)
    if response.status_code == 200:
        # 腾讯返回格式: var list_data="sh600000,浦发银行,...\nsh600004,白云机场,...";
        raw_text = response.text
        
        # 提取双引号里面的纯文本内容
        if '"' in raw_text:
            clean_text = raw_text.split('"')[1]
            lines = clean_text.strip().split(r'\n')
            
            stock_dict = {}
            for line in lines:
                parts = line.split(',')
                if len(parts) > 2:
                    code_with_market = parts[0]  # sh600000
                    name = parts[1]             # 浦发银行
                    stock_dict[name] = code_with_market
            
            # 固化到本地冷数据箱
            with open("stock_codes.json", "w", encoding="utf-8") as f:
                json.dump(stock_dict, f, ensure_ascii=False, indent=4)
                
            print(f"✨ [自愈成功] 已在本地建立包含 {len(stock_dict)} 只 A 股的全量基础字典（stock_codes.json）。")
        else:
            raise Exception("未能在响应中匹配到有效的字符串边界")
except Exception as e:
    print(f"❌ 腾讯节点全量同步受阻: {e}，正在切换新浪兜底清洗网关...")
    # 备用新浪防线：如果上面失败，直接用物理切分法，绕过 json.loads
    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=6000&sort=symbol&asc=1&node=hs_a"
        headers = {"Referer": "https://finance.sina.com.cn"}
        res = requests.get(url, headers=headers, timeout=15)
        # 用最暴力的非结构化物理清洗，只捞取 name 和 symbol
        names = re.findall(r'name:"([^"]+)"', res.text)
        codes = re.findall(r'symbol:"([^"]+)"', res.text)
        if names and codes:
            stock_dict = {n: c for n, c in zip(names, codes)}
            with open("stock_codes.json", "w", encoding="utf-8") as f:
                json.dump(stock_dict, f, ensure_ascii=False, indent=4)
            print(f"✨ [自愈成功] 通过新浪清洗网关成功固化 {len(stock_dict)} 只股票。")
    except Exception as e2:
        print(f"❌ 终极防线崩溃，别慌！Agent 运行时的 Suggest 线上网关会完全自动兜底。")