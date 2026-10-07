# Examples

Two small C programs to try the server on. Build them with debug info:

```bash
make -C examples
```

`example.c` computes a factorial recursively, which is handy for stepping and
backtraces. `crash.c` looks up users by name and crashes when one is missing.

Prompts to try:

```
Load /path/to/examples/crash in the debugger, run it and tell me why it crashes.

Debug /path/to/examples/example: break on factorial, continue until n == 1 and show the backtrace.
```
