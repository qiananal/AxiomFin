import json
import os
import sys

# Ensure the project root is on sys.path so existing modules can be imported.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover - fallback for environments without the package installed
    class FastMCP:  # type: ignore[override]
        """Minimal fallback used when the MCP package is not installed yet."""

        def __init__(self, name: str):
            self.name = name
            self.tools = {}

        def tool(self):
            def decorator(func):
                self.tools[func.__name__] = func
                return func

            return decorator

        def run(self):
            print(f"[{self.name}] MCP Server placeholder is ready. Install the mcp package to run the real server.")


mcp = FastMCP("stock-mcp-server")


@mcp.tool()
def get_stock_price(stock_code: str) -> str:
    """查询单只股票的实时价格、涨跌幅和成交量。"""
    try:
        from tools.core_tools import get_stock_price as _get_stock_price

        return _get_stock_price(stock_code)
    except Exception as exc:  # pragma: no cover - defensive fallback
        return json.dumps({"error": f"get_stock_price failed: {exc}"}, ensure_ascii=False)


@mcp.tool()
def technical_analysis(stock_code: str) -> str:
    """对单只股票进行买卖信号和技术分析。"""
    try:
        from services.signal_analyzer import analyze_buy_sell_signals

        return analyze_buy_sell_signals(stock_code)
    except Exception as exc:  # pragma: no cover - defensive fallback
        return json.dumps({"error": f"technical_analysis failed: {exc}"}, ensure_ascii=False)


@mcp.tool()
def analyze_stock(stock_code: str, buy_price: float | None = None) -> str:
    """对单只股票进行综合分析，兼容持仓成本参数。"""
    try:
        from services.signal_analyzer import analyze_buy_sell_signals

        return analyze_buy_sell_signals(stock_code, buy_price=buy_price)
    except Exception as exc:  # pragma: no cover - defensive fallback
        return json.dumps({"error": f"analyze_stock failed: {exc}"}, ensure_ascii=False)


@mcp.tool()
def capital_flow() -> str:
    """查询账户总资产、现金和持仓盈亏信息。"""
    try:
        from tools.core_tools import get_user_portfolio_matrix

        return get_user_portfolio_matrix()
    except Exception as exc:  # pragma: no cover - defensive fallback
        return json.dumps({"error": f"capital_flow failed: {exc}"}, ensure_ascii=False)


@mcp.tool()
def portfolio_diagnosis() -> str:
    """对当前持仓进行诊断并返回补仓/减仓建议。"""
    try:
        from services.portfolio_monitor import analyze_portfolio

        return analyze_portfolio()
    except Exception as exc:  # pragma: no cover - defensive fallback
        return json.dumps({"error": f"portfolio_diagnosis failed: {exc}"}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
