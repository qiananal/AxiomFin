# services/agent_engine.py
import json
import os
import sys
import yaml
import requests
import copy  
from queue import Queue

current_dir = os.path.dirname(os.path.abspath(__file__))  
project_root = os.path.dirname(current_dir)               

if project_root not in sys.path:
    sys.path.insert(0, project_root)

from tools.core_tools import TOOLS_MAPPING, TOOLS_DESCRIPTION

class AxiomFinEngine:
    def __init__(self, log_queue: Queue = None):
        self.log_queue = log_queue
        
        config_path = os.path.join(project_root, "config.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        self.api_key = config["llm"]["api_key"]
        self.api_base = config["llm"]["api_base"]
        self.model_name = config["llm"]["model_name"]
        self.temperature = config["llm"]["temperature"]
        
        self.system_prompt = f"""你现在是 AxiomFin 金融投研中台的唯一主控智能体核心大脑。
你的任务是阅读用户的金融、工商分析任务，并指挥你后方的 Python 卫兵去调用外部 API 工具获取真数据。

{TOOLS_DESCRIPTION}

你必须在每一轮交互中，严格按照系统规定的结构化 JSON 格式返回你的思考、动作或最终答案。绝对不允许包含任何 Markdown 格式标记（如 ```json）。"""

        # 🌟 终极约束：把 add_monitor_task 直接写进 Schema 的枚举中，强制大模型必须调它！
        self.response_schema = {
            "type": "object",
            "properties": {
                "thought": {
                    "type": "string",
                    "description": "你当前的推导逻辑"
                },
                "status": {
                    "type": "string",
                    "enum": ["CALL_TOOL", "FINISH"],
                    "description": "状态标识。如果需要调用工具挂载监控任务或查询，必须写 'CALL_TOOL'；如果卫兵执行完工具报告成功，才能写 'FINISH'"
                },
                "action": {
                    "type": "object",
                    "properties": {
                        "tool_name": {
                            "type": "string", 
                            "enum": ["search_stock_code", "get_stock_price", "get_company_risk", "send_email_report", "add_monitor_task", "execute_portfolio_trade", "screen_daily_top_stocks", "analyze_stock_signals", "get_portfolio_diagnosis", "get_daily_picks_cached", "get_portfolio_alerts"],
                            "description": "要调用的工具名。股票推荐/量价筛选用 screen_daily_top_stocks；买卖分析用 analyze_stock_signals；持仓诊断用 get_portfolio_diagnosis；监控告警用 add_monitor_task"
                        },
                        "params": {"type": "object", "description": "工具参数"}
                    },
                    "description": "当 status 为 CALL_TOOL 时必填"
                },
                "final_answer": {
                    "type": "string",
                    "description": "当 status 为 FINISH 时，输出最终交付用户的最终文本。绝不允许假装执行了工具！"
                }
            },
            "required": ["thought", "status"]
        }

    def log(self, message: str):
        if self.log_queue is not None:
            self.log_queue.put(message)
        else:
            print(f"📡 [后台永动机] {message}")

    def invoke_llm_structured(self, messages):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "response_format": {"type": "json_object"}
        }
        response = requests.post(f"{self.api_base}/chat/completions", json=payload, headers=headers)
        if response.status_code == 200:
            return response.json()["choices"][0]['message']['content']
        else:
            raise Exception(f"DeepSeek 通道爆震！错误码: {response.status_code}")

    def run_task(self, history_messages: list):
        self.log("🏁 [AxiomFin 强类型智能体起航] 注入结构化约束钢印 Schema...")
        
        clean_history = copy.deepcopy(history_messages)
        schema_instruction = f"\n\n【🚨 死命令】：当用户提到监控、跌破、超过等定时任务时，你必须在第一轮返回 status='CALL_TOOL' 且 tool_name='add_monitor_task'！以下是 Schema 规范：\n{json.dumps(self.response_schema, ensure_ascii=False)}"
        
        messages = [{"role": "system", "content": self.system_prompt + schema_instruction}] + clean_history
        
        loop_count = 0
        max_loops = 5 
        
        while loop_count < max_loops:
            loop_count += 1
            self.log(f"🧠 【结构化自愈循环】第 {loop_count} 轮开始...")
            
            raw_response = self.invoke_llm_structured(messages)
            
            if "```" in raw_response:
                raw_response = raw_response.replace("```json", "").replace("```", "").strip()
            
            try:
                agent_decision = json.loads(raw_response)
            except Exception as pe:
                self.log(f"💥 解析异常，触发系统紧急纠偏...")
                messages.append({"role": "user", "content": "报错！请务必严格返回标准的纯 JSON 格式。"})
                continue
                
            thought = agent_decision.get("thought", "分析中...")
            status = agent_decision.get("status", "FINISH")
            
            self.log(f"💡 [Agent 内部推导思维]: {thought}")
            messages.append({"role": "assistant", "content": raw_response})
            
            if status == "FINISH":
                final_report = agent_decision.get("final_answer", "未能生成研报内容")
                return final_report
                
            elif status == "CALL_TOOL":
                action_data = agent_decision.get("action", {})
                tool_name = action_data.get("tool_name")
                params = action_data.get("params", {})
                
                self.log(f"🛡️ [强类型网关拦截] ──> 真实调度工具: 【{tool_name}】 | 参数: {params}")
                
                if tool_name in TOOLS_MAPPING:
                    tool_func = TOOLS_MAPPING[tool_name]
                    api_result_str = tool_func(**params)
                    self.log(f"📥 [Observation 外部物理接口回传真数据成功]: {api_result_str}")
                    
                    messages.append({
                        "role": "user", 
                        "content": f"Observation (工具执行成功返回的最新真数据): {api_result_str}"
                    })
                else:
                    self.log(f"❌ 警告：工具 【{tool_name}】 不存在！")
                    messages.append({"role": "user", "content": f"Observation: 错误，工具 {tool_name} 不存在。"})
            
        return "❌ 灾难！长链条推理超过最大轮次，系统强制熔断保护！"