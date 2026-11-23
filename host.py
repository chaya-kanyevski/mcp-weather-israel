"""Host – צ'אט בטרמינל שמחבר בין המשתמש, ה-LLM וה-MCP Servers.

זרימה: קלט משתמש → LLM (עם רשימת כל ה-Tools) → אם המודל ביקש Tool – מריצים דרך
ה-Client המתאים ומחזירים לו את התוצאה → חוזרים עד שהמודל עונה בטקסט.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

from client import MCPClient

load_dotenv()
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # עברית תקינה בטרמינל של Windows

# ← כאן מחברים MCP Servers נוספים
MCP_SERVERS = ["weather_USA.py", "weather_Israel.py"]

MAX_TOOL_ROUNDS = 10

SYSTEM_PROMPT = """You are a helpful weather assistant. Always answer in the user's language.
Never guess a forecast from memory – always use the tools.

For a location in ISRAEL, call these tools IN ORDER, one after another:
1. open_weather_forecast_israel
2. enter_weather_forecast_city_israel (city name in Hebrew)
3. select_weather_forecast_city_israel
4. get_weather_forecast_page_content
Then answer the user's exact question based only on the page content, briefly and clearly
(for example: temperatures, chance of rain, and what to wear).
If a step returns an ERROR, tell the user what failed instead of inventing data.

For a location in the USA, use get_forecast (latitude/longitude) or get_alerts (2-letter state code).
"""


class Host:
    def __init__(self) -> None:
        self.llm = OpenAI(api_key=os.environ["LLM_API_KEY"],
                          base_url=os.getenv("LLM_BASE_URL") or None)
        self.model = os.getenv("LLM_MODEL", "gemini-2.0-flash")
        self.clients: list[MCPClient] = []
        self.tool_owner: dict[str, MCPClient] = {}  # שם Tool → ה-Client שלו
        self.tools_spec: list[dict] = []
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    async def connect(self) -> None:
        for server in MCP_SERVERS:
            client = MCPClient()
            tools = await client.connect_to_server(server)
            self.clients.append(client)
            for t in tools:
                self.tool_owner[t.name] = client
                # המרה מתיאור MCP לפורמט function-calling של ה-LLM
                self.tools_spec.append({
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema or {"type": "object", "properties": {}},
                    },
                })
            print(f"🔌 {client.name}: {', '.join(t.name for t in tools)}")

    async def ask(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        for _ in range(MAX_TOOL_ROUNDS):
            resp = self.llm.chat.completions.create(
                model=self.model, messages=self.messages,
                tools=self.tools_spec, temperature=0,
            )
            msg = resp.choices[0].message
            if not msg.tool_calls:
                self.messages.append({"role": "assistant", "content": msg.content or ""})
                return msg.content or ""

            self.messages.append({
                "role": "assistant", "content": msg.content or "",
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.function.name,
                                             "arguments": tc.function.arguments}}
                               for tc in msg.tool_calls],
            })
            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments or "{}")
                print(f"   🔧 {name}({json.dumps(args, ensure_ascii=False)})")
                client = self.tool_owner.get(name)
                try:
                    result = await client.call_tool(name, args) if client else f"ERROR: unknown tool {name}"
                except Exception as e:
                    result = f"ERROR: {e}"
                preview = result.replace("\n", " ")[:120]
                print(f"      ↳ {preview}{'…' if len(result) > 120 else ''}")
                self.messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        return "הגעתי למספר המרבי של קריאות לכלים בלי תשובה סופית."

    async def chat_loop(self) -> None:
        print("\n💬 צ'אט מזג אוויר. הקלידי שאלה, או 'exit' ליציאה.\n")
        while True:
            try:
                q = input("את: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if q.lower() in {"exit", "quit", "יציאה"}:
                break
            if not q:
                continue
            try:
                print(f"\n🤖 {await self.ask(q)}\n")
            except Exception as e:
                print(f"\n❌ שגיאה: {e}\n")

    async def cleanup(self) -> None:
        for c in reversed(self.clients):
            try:
                await c.cleanup()
            except Exception:
                pass


async def main() -> None:
    host = Host()
    try:
        await host.connect()
        await host.chat_loop()
    finally:
        await host.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
