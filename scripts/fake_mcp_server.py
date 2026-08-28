"""本地假 MCP server（测试页面接入用）：POST /mcp 处理 tools/list + tools/call。

启动：`python -m uvicorn fake_mcp_server:app --port 8099`
然后在「工具」页添加 MCP server：name=ext，base_url=http://127.0.0.1:8099，保存即热注册。
"""

from datetime import datetime

from fastapi import FastAPI, Request

app = FastAPI()

_TOOLS = [
    {
        "name": "weather",
        "description": "查询某个城市的天气情况",
        "inputSchema": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "城市名，如 北京"}},
            "required": ["city"],
        },
    },
    {
        "name": "quote",
        "description": "返回一句名人名言",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_time",
        "description": "返回当前服务器时间",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "translate",
        "description": "把中文短语翻译成英文",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "要翻译的中文"}},
            "required": ["text"],
        },
    },
]


@app.post("/mcp")
async def mcp(request: Request):
    body = await request.json()
    if body.get("method") == "tools/list":
        return {"jsonrpc": "2.0", "id": body.get("id"), "result": {"tools": _TOOLS}}
    if body.get("method") == "tools/call":
        name = body["params"]["name"]
        args = body["params"].get("arguments") or {}
        text = _dispatch(name, args)
        return {
            "jsonrpc": "2.0",
            "id": body.get("id"),
            "result": {"content": [{"type": "text", "text": text}]},
        }
    return {
        "jsonrpc": "2.0",
        "id": body.get("id"),
        "error": {"message": f"unknown method: {body.get('method')}"},
    }


def _dispatch(name: str, args: dict) -> str:
    if name == "weather":
        city = args.get("city", "未知")
        return f"【{city}天气】晴，25°C，微风，空气质量优。"
    if name == "quote":
        return "知识就是力量。—— 培根"
    if name == "get_time":
        return f"当前服务器时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    if name == "translate":
        return f"{args.get('text', '')} => English: '{args.get('text', '')}'"
    return f"unknown tool: {name}"
