"""Record the README demo as an asciinema cast.

The tool calls and their output are real: this script starts the server,
connects to it as an MCP client and debugs examples/crash. Only the user's
question and the final explanation are scripted.

    make -C examples
    uv run python demo/record.py
    npx svg-term-cli --in demo/demo.cast --out images/demo.svg --window --no-cursor
"""

import asyncio
import json
import re
import sys
import textwrap
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
CAST = ROOT / "demo" / "demo.cast"
WIDTH, HEIGHT = 88, 34

RESET, BOLD, DIM = "\x1b[0m", "\x1b[1m", "\x1b[2m"
CYAN, GREEN, MAGENTA, YELLOW = "\x1b[36m", "\x1b[32m", "\x1b[35m", "\x1b[33m"

QUESTION = "Why does examples/crash segfault?"
ANSWER = (
    'find_user() returns NULL when a name is missing. "carol" is not in the users '
    "array, and main() dereferences the result at crash.c:24 without checking it. "
    "Handle the NULL case before printing."
)


class Cast:
    def __init__(self) -> None:
        self.time = 0.0
        self.events: list[list] = []

    def out(self, text: str, delay: float = 0.0) -> None:
        self.time += delay
        self.events.append([round(self.time, 3), "o", text.replace("\n", "\r\n")])

    def type(self, text: str, cps: float = 28) -> None:
        for char in text:
            self.out(char, 1 / cps)

    def pause(self, seconds: float) -> None:
        self.time += seconds

    def save(self, path: Path) -> None:
        header = {"version": 2, "width": WIDTH, "height": HEIGHT, "env": {"TERM": "xterm-256color"}}
        lines = [json.dumps(header)] + [json.dumps(event) for event in self.events]
        path.write_text("\n".join(lines) + "\n")


def tidy(text: str) -> str:
    text = text.replace(str(ROOT), "~/MDB-MCP")
    return re.sub(r"\n{2,}", "\n", text).strip()


async def main() -> None:
    cast = Cast()
    params = StdioServerParameters(command=sys.executable, args=["-m", "mdb_mcp"], cwd=str(ROOT))

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()

            async def tool(name: str, shown: str, **arguments) -> str:
                cast.out(f"{MAGENTA}●{RESET} {BOLD}{name}{RESET}{DIM}({shown}){RESET}\n", 0.5)
                result = await client.call_tool(name, arguments)
                text = tidy(result.content[0].text)
                lines = text.splitlines()
                for index, line in enumerate(lines):
                    gutter = "└ " if index == 0 else "  "
                    if line.startswith("--- program output"):
                        line = f"{YELLOW}{line}{RESET}"
                    cast.out(f"  {DIM}{gutter}{RESET}{line[: WIDTH - 4]}\n", 0.25 if index == 0 else 0.03)
                cast.out("\n")
                cast.pause(0.9)
                return text

            cast.out(f"{DIM}mdb-mcp demo · GDB · real tool output{RESET}\n\n")
            cast.pause(0.6)
            cast.out(f"{CYAN}{BOLD}❯{RESET} ")
            cast.type(QUESTION)
            cast.out("\n\n", 0.5)

            started = await tool(
                "debugger_start",
                'debugger="gdb", program="examples/crash"',
                debugger="gdb",
                program=str(ROOT / "examples" / "crash"),
            )
            session = re.search(r"session (\w+)", started).group(1)
            for command in ("run", "print u", "print names[i]"):
                await tool(
                    "debugger_command",
                    f'session_id="{session}", command="{command}"',
                    session_id=session,
                    command=command,
                )
            await tool("debugger_terminate", f'session_id="{session}"', session_id=session)

    cast.out(f"{GREEN}{BOLD}✓{RESET} ", 0.4)
    for index, line in enumerate(textwrap.wrap(ANSWER, WIDTH - 4)):
        cast.out(("" if index == 0 else "  ") + line + "\n", 0.35)
    cast.pause(4)
    cast.out("")
    cast.save(CAST)
    print(f"wrote {CAST} ({cast.time:.1f}s)")


if __name__ == "__main__":
    asyncio.run(main())
