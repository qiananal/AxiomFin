import yaml
import requests

print("⚡ 正在读取本地 config.yaml 安全钥匙...")
with open("config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

# 防御性编程：如果还是读成空，就就地拦截打印
if config is None:
    print("❌ 灾难！你的 config.yaml 文件在内存里读出来是空的！请检查文件是否保存或缩进是否有误！")
    exit()

# 物理拼装官方标准的请求报文
headers = {
    "Authorization": f"Bearer {config['llm']['api_key']}",
    "Content-Type": "application/json"
}
payload = {
    "model": config["llm"]["model_name"],
    "messages": [{"role": "user", "content": "你好，请确认你已经成功收到我的测试请求！"}],
    "temperature": config["llm"]["temperature"]
}

print(f"📡 正在物理撞击 DeepSeek 官方统一网关: {config['llm']['api_base']} ...")
response = requests.post(f"{config['llm']['api_base']}/chat/completions", json=payload, headers=headers)

if response.status_code == 200:
    print("\n🏆 【 连线大捷 ！】 成功收到 DeepSeek 官方通道回信 :")
    print(f"👉 {response.json()['choices'][0]['message']['content']}\n")
else:
    print(f"\n❌ 撞击失败！错误码: {response.status_code} | 详情: {response.text}")