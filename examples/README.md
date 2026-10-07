# Examples

Two small C programs to try the server with.

| Program     | What it does                                              |
|-------------|-----------------------------------------------------------|
| `example.c` | Computes a factorial recursively. Good for stepping and backtraces. |
| `crash.c`   | Looks up users by name and crashes on a missing one (NULL dereference). |

Build both with debug info:

```bash
make -C examples
```

Then ask your assistant something like:

> Load `/absolute/path/to/examples/crash` in the debugger, run it, and tell me why it crashes.

> Debug `/absolute/path/to/examples/example`: break on `factorial`, continue until `n == 1`, and show the backtrace.
