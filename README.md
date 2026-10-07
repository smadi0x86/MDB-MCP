# MDB-MCP

[![CI](https://github.com/smadi0x86/MDB-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/smadi0x86/MDB-MCP/actions/workflows/ci.yml)

An MCP server that gives your AI assistant a real debugger. It drives GDB or LLDB,
so the assistant can set breakpoints, run your program, read memory and walk the
stack the same way you would.

<p align="center">
  <img src="images/demo.svg" alt="Finding a NULL pointer dereference with mdb-mcp" width="720">
</p>

## Install

You need [uv](https://docs.astral.sh/uv/) and at least one debugger:

```bash
# Debian / Ubuntu
sudo apt install gdb lldb python3-lldb

# macOS (LLDB ships with the Xcode command line tools)
xcode-select --install
```

Then add the server to your client. For Claude Code:

```bash
claude mcp add mdb -- uvx --from git+https://github.com/smadi0x86/MDB-MCP mdb-mcp
```

For Claude Desktop, Cursor or Windsurf:

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

VS Code takes the same entry under `"servers"` in `.vscode/mcp.json`, with
`"type": "stdio"` added. On Windows with WSL, set `"command": "wsl"` and put the full
path to `uvx` at the start of `args`.

## Tools

```
debugger_status      which debuggers are usable, and the open sessions
debugger_start       start a gdb or lldb session, optionally loading a program
debugger_command     run any gdb or lldb command
debugger_interrupt   pause a running program, like Ctrl-C
debugger_terminate   kill the program and close the session
```

Everything else is a normal debugger command, so `break main`, `bt`, `x/16gx $sp`
and `frame variable` all work. Commands that resume the program wait for it to stop
(10 seconds by default, adjustable per call). If it is still running after that, the
assistant can interrupt it or keep waiting.

GDB is the default on Linux and LLDB on macOS. Either can be picked explicitly. GDB
loads your `~/.gdbinit`, so pwndbg and GEF keep working.

## Try it

```bash
make -C examples
```

Then ask your assistant why `examples/crash` segfaults (give it the absolute path).

## Configuration

To use a debugger other than the one on your `PATH`, set it in the server's `env` in
your client config:

```json
"env": {
  "MDB_GDB_PATH": "gdb-multiarch",
  "MDB_LLDB_PATH": "/opt/homebrew/opt/llvm/bin/lldb"
}
```

## Troubleshooting

If LLDB shows up as unavailable, `debugger_status` tells you why. On Debian and
Ubuntu it is usually a missing `python3-lldb`, which has to match your LLDB version.

The program can't read from your keyboard. Feed it a file instead:

```
run < input.txt                    # gdb
process launch -i input.txt        # lldb
```

If attaching to a running process fails on Linux, check
`/proc/sys/kernel/yama/ptrace_scope`. A value of 1 only allows debugging child
processes.

## Security

A debugger can run shell commands (`shell`, `python`, `platform shell`, `script`),
and the programs you debug run as your user. Only debug code you trust, and keep
tool approval on for `debugger_command` unless you are in a sandbox.

## Development

```bash
uv sync
uv run pytest                      # tests for a missing debugger are skipped
uv run ruff check . && uv run ruff format --check .
```

The demo above is recorded from real tool calls with `demo/record.py`. See the top of
that file for how to regenerate it.

## License

GPL-3.0

[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/smadi0x86-mdb-mcp-badge.png)](https://mseep.ai/app/smadi0x86-mdb-mcp)
