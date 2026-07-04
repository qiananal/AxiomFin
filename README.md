# AxiomFin

AxiomFin 是一个面向股票分析、技术信号识别、持仓监控以及 AI 能力接入的 Python 项目。

## 项目目标

- 提供股票筛选与技术分析能力
- 支持持仓监控与告警
- 保留原有业务逻辑，同时增加 MCP Server 入口，便于被支持 MCP 的客户端调用

## 项目结构

- app_frontend.py：Streamlit 前端主界面
- services/：股票筛选、信号分析、持仓监控等核心业务模块
- tools/：通用工具函数与账户/行情相关辅助能力
- mcp/：MCP Server 入口，用于把现有能力包装成 MCP Tool
- data/：运行时数据文件目录
- api/：保留给未来 REST API 扩展的目录
- config.yaml：项目配置文件
- requirements.txt：依赖列表

## 运行方式

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行前端

```bash
streamlit run app_frontend.py
```

### 3. 运行 MCP Server

```bash
python mcp/server.py
```

## 说明

- 本项目保持原有分析流程不变，在原有模块之外新增 MCP 适配层。
- 当前 MCP Server 主要暴露以下能力：
  - 股票价格查询
  - 技术分析
  - 综合股票分析
  - 账户/资金流信息
  - 持仓诊断

## 目录工程化说明

当前项目已经具备基础的 Python 工程化结构，主要包括：

- 按功能拆分的模块目录
- 独立的数据目录
- 统一的依赖文件
- 独立的 MCP 接入层

如果后续继续扩展，建议保持当前“业务逻辑不动、增量新增能力模块”的方式，避免重构旧代码。
