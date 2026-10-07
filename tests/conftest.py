import shutil
import subprocess
from pathlib import Path

import pytest

from mdb_mcp.backends import detect

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

# Runs until interrupted, so tests can exercise timeouts and interrupts.
SPIN_C = """
#include <stdio.h>
#include <unistd.h>

int target(int x) { return x * 2; }

int main(void) {
    printf("started\\n");
    fflush(stdout);
    sleep(2);
    target(21);
    for (;;) {}
}
"""


def available(kind):
    return detect(kind).available


BACKENDS = [
    pytest.param("gdb", marks=[pytest.mark.gdb, pytest.mark.skipif(not available("gdb"), reason="GDB not usable")]),
    pytest.param("lldb", marks=[pytest.mark.lldb, pytest.mark.skipif(not available("lldb"), reason="LLDB not usable")]),
]


def _compile(source: Path, output: Path) -> Path:
    compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    if compiler is None:
        pytest.skip("no C compiler available")
    subprocess.run([compiler, "-g", "-O0", "-o", str(output), str(source)], check=True)
    return output


@pytest.fixture(scope="session")
def programs(tmp_path_factory):
    build = tmp_path_factory.mktemp("programs")
    spin_source = build / "spin.c"
    spin_source.write_text(SPIN_C)
    return {
        "example": _compile(EXAMPLES / "example.c", build / "example"),
        "crash": _compile(EXAMPLES / "crash.c", build / "crash"),
        "spin": _compile(spin_source, build / "spin"),
    }
