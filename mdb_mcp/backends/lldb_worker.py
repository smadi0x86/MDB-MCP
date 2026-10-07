"""Runs inside LLDB's embedded Python interpreter.

The server starts ``lldb --batch`` and imports this module there, so the
``lldb`` bindings always match the Python they were built for. Requests and
replies are JSON lines over two pipes passed in as file descriptors.

Keep this file free of imports from the rest of the package and compatible
with older Python 3 versions (3.8+): Xcode's LLDB embeds its own interpreter.
"""

import json
import os
import queue
import threading
import time

import lldb

RUNNING_STATES = (
    lldb.eStateRunning,
    lldb.eStateStepping,
    lldb.eStateLaunching,
    lldb.eStateAttaching,
)

# Canonical command prefixes (after alias resolution) that resume the target.
RESUMING_COMMANDS = (
    "process launch",
    "process continue",
    "process attach",
    "process interrupt",
    "process kill",
    "thread step-",
    "thread until",
    "thread continue",
    "_regexp-attach",
)

EXIT_STATES = (lldb.eStateExited, lldb.eStateDetached)

STATE_NAMES = {
    lldb.eStateStopped: "stopped",
    lldb.eStateCrashed: "stopped",
    lldb.eStateSuspended: "stopped",
    lldb.eStateExited: "exited",
    lldb.eStateDetached: "exited",
}


class Worker:
    def __init__(self, out):
        self.out = out
        self.debugger = lldb.SBDebugger.Create(True)
        self.debugger.SetAsync(True)
        self.listener = self.debugger.GetListener()
        self.interpreter = self.debugger.GetCommandInterpreter()

    def send(self, message):
        self.out.write(json.dumps(message) + "\n")
        self.out.flush()

    def process(self):
        return self.debugger.GetSelectedTarget().GetProcess()

    def state(self):
        process = self.process()
        if not process.IsValid():
            return "no process"
        state = process.GetState()
        if state in RUNNING_STATES:
            return "running"
        return STATE_NAMES.get(state, "no process")

    def handle(self, command):
        result = lldb.SBCommandReturnObject()
        self.interpreter.HandleCommand(command, result)
        return result.GetOutput() or "", result.GetError() or "", result.Succeeded()

    def canonical(self, command):
        resolved = lldb.SBCommandReturnObject()
        self.interpreter.ResolveCommand(command, resolved)
        return (resolved.GetOutput() or command).strip()

    def drain_events(self, program, wait_until=None, until_exit=False):
        """Pull process events, so the public state is current.

        With ``wait_until`` set, block until the target stops (or exits, with
        ``until_exit``) or until that deadline passes. Returns True once the
        target is no longer running.
        """
        event = lldb.SBEvent()
        while True:
            self.read_stdio(program)
            if wait_until is None:
                if not self.listener.GetNextEvent(event):
                    return self.state() != "running"
            else:
                if time.time() >= wait_until:
                    return False
                if not self.listener.WaitForEvent(1, event):
                    continue
            if not lldb.SBProcess.EventIsProcessEvent(event):
                continue
            state = lldb.SBProcess.GetStateFromEvent(event)
            if state == lldb.eStateStopped and lldb.SBProcess.GetRestartedFromEvent(event):
                continue
            if until_exit and state not in EXIT_STATES:
                continue
            if wait_until is not None and state not in RUNNING_STATES:
                self.read_stdio(program)
                return True

    def read_stdio(self, program):
        process = self.process()
        if not process.IsValid():
            return
        for read in (process.GetSTDOUT, process.GetSTDERR):
            while True:
                data = read(65536)
                if not data:
                    break
                program.append(data)

    def stop_report(self, output=""):
        process = self.process()
        if self.state() == "exited":
            if "exited with status" in output:
                return ""
            description = process.GetExitDescription()
            suffix = f" ({description})" if description else ""
            return f"Process {process.GetProcessID()} exited with status = {process.GetExitStatus()}{suffix}\n"
        report, _, _ = self.handle("process status")
        return report

    def execute(self, command, timeout):
        program = []
        notes = []
        deadline = time.time() + timeout
        self.drain_events(program)
        if self.state() == "running":
            if not self.drain_events(program, deadline):
                return self.reply("", program, ["not-sent"])
            output = self.stop_report()
        else:
            output = ""

        canonical = self.canonical(command)
        out, err, ok = self.handle(command)
        output += out + err
        if ok and canonical.startswith(RESUMING_COMMANDS):
            kills = canonical.startswith("process kill")
            if self.drain_events(program, deadline, until_exit=kills):
                output += self.stop_report(output)
            else:
                notes.append("still-running")
        else:
            self.drain_events(program)
        return self.reply(output, program, notes, error=not ok)

    def reply(self, output, program, notes, error=False):
        return {
            "output": output,
            "program": "".join(program),
            "notes": notes,
            "state": self.state(),
            "error": error,
        }

    def interrupt(self):
        process = self.process()
        if process.IsValid():
            process.SendAsyncInterrupt()

    def wait(self, timeout):
        program = []
        self.drain_events(program)
        if self.state() == "running" and not self.drain_events(program, time.time() + timeout):
            return self.reply("", program, ["still-running"])
        return self.reply(self.stop_report(), program, [])

    def close(self):
        for index in range(self.debugger.GetNumTargets()):
            process = self.debugger.GetTargetAtIndex(index).GetProcess()
            if process.IsValid():
                process.Kill()
        lldb.SBDebugger.Destroy(self.debugger)


def main(read_fd, write_fd):
    requests = os.fdopen(read_fd, "r")
    replies = os.fdopen(write_fd, "w")
    worker = Worker(replies)
    pending = queue.Queue()

    def reader():
        # Interrupts are handled right away, even while a command waits.
        for line in requests:
            request = json.loads(line)
            if request.get("op") == "interrupt":
                worker.interrupt()
            else:
                pending.put(request)
        pending.put({"op": "quit"})

    threading.Thread(target=reader, daemon=True).start()
    worker.send({"op": "ready", "version": lldb.SBDebugger.GetVersionString().splitlines()[0]})

    while True:
        request = pending.get()
        op = request.get("op")
        if op == "quit":
            worker.close()
            return
        try:
            if op == "execute":
                worker.send(worker.execute(request["command"], request["timeout"]))
            elif op == "wait":
                worker.send(worker.wait(request["timeout"]))
            else:
                worker.send({"fatal": f"unknown op {op!r}"})
        except Exception as exc:
            worker.send({"fatal": f"{type(exc).__name__}: {exc}"})
