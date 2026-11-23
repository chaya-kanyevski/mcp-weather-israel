"""MCP Client גנרי – מתחבר ל-MCP Server אחד, מגלה את ה-Tools שלו ומפעיל אותם.

ה-Host מחזיק מופע אחד של MCPClient לכל Server.
"""
from __future__ import annotations

import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    def __init__(self) -> None:
        self.session: ClientSession | None = None
        self.exit_stack = AsyncExitStack()
        self.name = ""
        self.tools: list = []

    async def connect_to_server(self, server_script_path: str) -> list:
        """מריץ את קובץ ה-Server כתהליך (process) ופותח איתו ערוץ stdio."""
        path = Path(server_script_path).resolve()
        if path.suffix != ".py":
            raise ValueError("קובץ ה-Server חייב להיות קובץ .py")
        self.name = path.stem

        params = StdioServerParameters(
            command=sys.executable,  # אותו Python של הסביבה הנוכחית (uv)
            args=[str(path)],
            cwd=str(path.parent),
        )
        read, write = await self.exit_stack.enter_async_context(stdio_client(params))
        self.session = await self.exit_stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

        self.tools = (await self.session.list_tools()).tools  # גילוי ה-Tools
        return self.tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        if self.session is None:
            raise RuntimeError("Client לא מחובר ל-Server")
        result = await self.session.call_tool(name, arguments)
        parts = [getattr(c, "text", str(c)) for c in result.content]
        text = "\n".join(parts)
        return f"ERROR: {text}" if getattr(result, "isError", False) else text

    async def cleanup(self) -> None:
        await self.exit_stack.aclose()
