# MDB-MCP

[![CI](https://github.com/smadi0x86/MDB-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/smadi0x86/MDB-MCP/actions/workflows/ci.yml)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)

An MCP server that lets AI assistants debug native programs with **GDB** or **LLDB**.
Your assistant sets breakpoints, runs the program, inspects memory and registers, and
reads backtraces using ordinary debugger commands.

<p align="center">
  <img src="images/demo.svg" alt="An assistant using mdb-mcp to find a NULL pointer dereference" width="720">
</p>

- **Both debuggers, one interface.** GDB on Linux and LLDB on macOS are picked
  automatically, and either can be requested explicitly.
- **Handles real programs.** Execution commands wait until the target stops, slow
  or looping programs can be interrupted, and the program's output is kept apart
  from debugger output.
- **Small tool surface.** Five tools. Everything else is a normal GDB or LLDB
  command, which models already know well.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- GDB and/or LLDB
  - **Linux:** `sudo apt install gdb`. For LLDB: `sudo apt install lldb python3-lldb`
  - **macOS:** LLDB comes with the Xcode Command Line Tools (`xcode-select --install`)

## Setup

The server runs over stdio. Point your MCP client at `uvx`:

### Claude Code

```bash
claude mcp add mdb -- uvx --from git+https://github.com/smadi0x86/MDB-MCP mdb-mcp
```

### Claude Desktop, Cursor, Windsurf

```json
{
  "mcpServers": {
    "mdb": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/smadi0x86/MDB-MCP", "mdb-mcp"]
    }
  }
}
```

### VS Code

In `.vscode/mcp.json`:

```json
{
  "servers": {
    "mdb": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/smadi0x86/MDB-MCP", "mdb-mcp"]
    }
  }
}
```

On Windows with WSL, use `"command": "wsl"` and put the full path to `uvx` first in `args`.

### From a local checkout

```bash
git clone https://github.com/smadi0x86/MDB-MCP && cd MDB-MCP
uv sync
```

Then use `"command": "uv", "args": ["run", "--directory", "/path/to/MDB-MCP", "mdb-mcp"]`.

## Tools

| Tool | What it does |
|------|--------------|
| `debugger_status` | Shows which debuggers are usable (and why not) and lists active sessions |
| `debugger_start` | Starts a session (`debugger`: `auto`, `gdb` or `lldb`), optionally loading a `program` with `args` |
| `debugger_command` | Runs any GDB or LLDB command. Execution commands wait up to `timeout` seconds for the target to stop |
| `debugger_interrupt` | Pauses a running target, like Ctrl-C, and shows where it stopped |
| `debugger_terminate` | Kills the program and closes the session |

Active sessions are also available as the `debugger://sessions` resource.

## Try it

```bash
make -C examples
```

Then ask your assistant:

> Load `/path/to/MDB-MCP/examples/crash` in the debugger, run it, and tell me why it crashes.

See [examples/](examples) for more prompts.

## Configuration

| Variable | Purpose |
|----------|---------|
| `MDB_GDB_PATH` | GDB binary to use, e.g. `gdb-multiarch` (default: `gdb` on `PATH`) |
| `MDB_LLDB_PATH` | LLDB binary to use (default: `lldb` on `PATH`, then Xcode, then Homebrew LLVM) |

GDB loads your `~/.gdbinit`, so extensions such as pwndbg or GEF stay available.

## How it works

- **GDB** runs under its machine interface (GDB/MI) through
  [pygdbmi](https://github.com/cs01/pygdbmi). The debugged program gets its own
  pseudo-terminal, so its output never mixes with GDB's protocol stream and it
  cannot read input meant for GDB.
- **LLDB** runs as a separate `lldb` process with a small worker loaded into its
  embedded Python. The `lldb` module always matches the Python it was built for,
  and an LLDB crash cannot take the server down with it.

## Troubleshooting

**LLDB shows as unavailable.** Ask your assistant to run `debugger_status`, or run:

```bash
uv run python -c "from mdb_mcp.backends import detect; print(detect('lldb'))"
```

On Debian and Ubuntu, LLDB's Python support is a separate package (`python3-lldb`).
It must match your LLDB version.

**The program needs input.** The target's terminal is not connected to anything
you can type into. Use `run < input.txt` (GDB) or `process launch -i input.txt` (LLDB).

**Attaching to a running process fails on Linux.** Check
`/proc/sys/kernel/yama/ptrace_scope`. A value of `1` only allows debugging your own
child processes.

## Security

Debugger commands are powerful: GDB's `shell` and `python` commands, LLDB's
`platform shell` and `script`, and the programs you run all execute with your user's
permissions. Only debug programs you trust, and keep your client's tool-approval
prompts on for `debugger_command` unless you are working in a sandbox.

## Development

```bash
uv sync
uv run pytest           # GDB and LLDB tests skip if that debugger is not installed
uv run ruff check . && uv run ruff format --check .
```

The demo at the top is recorded from real tool calls:

```bash
make -C examples
uv run python demo/record.py
npx svg-term-cli --in demo/demo.cast --out images/demo.svg --window --no-cursor --padding 18
```

### Upgrading from 0.1

Version 0.2 replaces the per-debugger tools (`gdb_start`, `gdb_command`,
`lldb_start`, `lldb_command`, ...) with the five `debugger_*` tools above. Old
configs that run `server.py` still work, but `mdb-mcp` is the supported entry point.

## License

GPL-3.0. See [LICENSE](LICENSE).

[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/smadi0x86-mdb-mcp-badge.png)](https://mseep.ai/app/smadi0x86-mdb-mcp)
