"""End-to-end tests: a real MCP client talking to the server over stdio."""

import re
import sys
from contextlib import asynccontextmanager

import anyio
import pytest
from conftest import available
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import AnyUrl

pytestmark = pytest.mark.skipif(not available("gdb"), reason="GDB not usable")

SERVER = StdioServerParameters(command=sys.executable, args=["-m", "mdb_mcp"])


async def call(client, tool, **arguments):
    result = await client.call_tool(tool, arguments)
    return result.content[0].text


@asynccontextmanager
async def connect():
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def test_lists_the_five_tools():
    async with connect() as client:
        tools = {tool.name for tool in (await client.list_tools()).tools}
        assert tools == {
            "debugger_status",
            "debugger_start",
            "debugger_command",
            "debugger_interrupt",
            "debugger_terminate",
        }


async def test_full_debugging_flow(programs):
    async with connect() as client:
        started = await call(client, "debugger_start", debugger="gdb", program=str(programs["crash"]))
        session_id = re.search(r"session (\w+)", started).group(1)

        status = await call(client, "debugger_status")
        assert session_id in status

        resource = await client.read_resource(AnyUrl("debugger://sessions"))
        assert session_id in resource.contents[0].text

        crashed = await call(client, "debugger_command", session_id=session_id, command="run", timeout=30)
        assert "SIGSEGV" in crashed
        pointer = await call(client, "debugger_command", session_id=session_id, command="print u")
        assert "0x0" in pointer

        closed = await call(client, "debugger_terminate", session_id=session_id)
        assert "closed" in closed
        assert session_id not in await call(client, "debugger_status")


async def test_interrupt_from_a_second_call_while_command_waits(programs):
    async with connect() as client:
        started = await call(client, "debugger_start", debugger="gdb", program=str(programs["spin"]))
        session_id = re.search(r"session (\w+)", started).group(1)
        results = {}

        async def run():
            results["run"] = await call(client, "debugger_command", session_id=session_id, command="run", timeout=60)

        async with anyio.create_task_group() as group:
            group.start_soon(run)
            await anyio.sleep(3)
            results["interrupt"] = await call(client, "debugger_interrupt", session_id=session_id)

        assert "SIGINT" in results["run"]
        await call(client, "debugger_terminate", session_id=session_id)


async def test_errors_are_readable(tmp_path):
    async with connect() as client:
        assert "no session" in await call(client, "debugger_command", session_id="nope", command="bt")
        missing = await call(client, "debugger_start", program=str(tmp_path / "missing"))
        assert "program not found" in missing
        assert "nothing to do" in await call(client, "debugger_terminate", session_id="nope")
        multi = await call(client, "debugger_command", session_id="nope", command="bt\nkill")
        assert "one command per call" in multi
