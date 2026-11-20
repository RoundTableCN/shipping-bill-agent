"""One-click Streamlit launcher with reliable child-process cleanup.

Usage:
    python scripts/launch_streamlit.py
    python scripts/launch_streamlit.py --no-browser
    python scripts/launch_streamlit.py --port 8502

On Windows the launcher creates a Job Object with
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.  Closing this console (or Ctrl+C) closes
the job and terminates the Streamlit process tree, so the next launch starts
cleanly.  POSIX uses a process group and SIGTERM.
"""

from __future__ import annotations

import argparse
import atexit
import ctypes
import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "streamlit_app.py"
LOG = ROOT / "out" / "launcher" / "streamlit.log"

_proc: subprocess.Popen | None = None
_job = None
_kernel32 = None
_stopping = False
_console_handler = None
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
DEBUG_LOG = ROOT / "out" / "launcher" / "launcher_debug.log"


def _debug(message: str) -> None:
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DEBUG_LOG.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        pass


def _free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _create_windows_job():
    """Create a job that kills all assigned children when its handle closes."""
    global _kernel32
    if os.name != "nt":
        return None
    try:
        from ctypes import wintypes

        class LARGE_INTEGER(ctypes.Union):
            _fields_ = [("QuadPart", ctypes.c_longlong)]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", LARGE_INTEGER),
                ("PerJobUserTimeLimit", LARGE_INTEGER),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        _kernel32.SetInformationJobObject.restype = wintypes.BOOL
        _kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        _kernel32.CloseHandle.restype = wintypes.BOOL
        _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            print(f"提示：CreateJobObject 失败（err={ctypes.get_last_error()}）")
            return None
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = 0x2000  # LIMIT_KILL_ON_JOB_CLOSE
        if not _kernel32.SetInformationJobObject(
            job, 9, ctypes.byref(info), ctypes.sizeof(info)
        ):
            print(f"提示：SetInformationJobObject 失败（err={ctypes.get_last_error()}）")
            _kernel32.CloseHandle(job)
            return None
        return job
    except Exception:
        return None


def _assign_to_job(proc: subprocess.Popen) -> bool:
    global _job
    _debug(
        f"assign_enter job={_job!r} bool={bool(_job)} kernel32={bool(_kernel32)} "
        f"platform={os.name} pid={proc.pid}"
    )
    if _job is None or _kernel32 is None or os.name != "nt":
        _debug("assign_skip")
        return False
    try:
        from ctypes import wintypes

        handle = wintypes.HANDLE(int(proc._handle))  # type: ignore[attr-defined]
        ok = bool(_kernel32.AssignProcessToJobObject(_job, handle))
        if not ok:
            err = ctypes.get_last_error()
            _debug(f"assign_job_failed err={err} pid={proc.pid}")
            print(f"提示：Job Object 绑定失败（err={err}），将使用控制台清理。")
        else:
            _debug(f"assign_job_ok pid={proc.pid}")
        return ok
    except Exception as exc:
        _debug(f"assign_job_exception {exc!r}")
        print(f"提示：Job Object 绑定异常：{exc}")
        return False


def _install_console_handler() -> None:
    """Kill the child when the console window is closed."""
    global _console_handler
    if os.name != "nt":
        return
    try:
        HandlerRoutine = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

        def _handler(event: int) -> bool:
            # 2=CTRL_CLOSE_EVENT, 5=LOGOFF, 6=SHUTDOWN
            if event in (2, 5, 6):
                _stop()
                return True
            return False

        _console_handler = HandlerRoutine(_handler)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.SetConsoleCtrlHandler(_console_handler, True)
    except Exception:
        pass


def _stop() -> None:
    global _proc, _job, _stopping
    if _stopping:
        return
    _stopping = True
    proc = _proc
    if proc is not None and proc.poll() is None:
        print("正在关闭 Streamlit ...")
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                text=True,
            )
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except OSError:
                proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                proc.kill()
            else:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except OSError:
                    proc.kill()
    if _job is not None and _kernel32 is not None:
        try:
            _kernel32.CloseHandle(_job)
        except Exception:
            pass
        _job = None
    _proc = None
    print("Streamlit 已关闭。")


def _on_signal(_signum, _frame) -> None:
    raise KeyboardInterrupt


def _wait_health(url: str, timeout: float, proc: subprocess.Popen) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main(argv: list[str] | None = None) -> int:
    global _proc, _job
    parser = argparse.ArgumentParser(description="Start the shipping agent UI.")
    parser.add_argument("--port", type=int, default=int(os.getenv("SHIPPING_AGENT_PORT", "8501")))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if not APP.exists():
        print(f"找不到应用文件：{APP}")
        return 1
    try:
        import streamlit  # noqa: F401
    except ImportError:
        print(f"当前 Python 缺少 Streamlit：{sys.executable}")
        print("请在该 Python 下安装依赖：")
        print(f'  "{sys.executable}" -m pip install -r "{ROOT / "requirements.txt"}"')
        return 1

    LOG.parent.mkdir(parents=True, exist_ok=True)
    port = _free_port(args.port)
    url = f"http://127.0.0.1:{port}"
    health = f"{url}/_stcore/health"

    _job = _create_windows_job()
    _debug(f"start job={_job!r} pid={os.getpid()}")
    print(f"清理方式：{'Windows Job Object' if _job is not None else '控制台信号/进程树'}")
    atexit.register(_stop)
    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_signal)

    log_file = LOG.open("w", encoding="utf-8", buffering=1)
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP),
        "--server.headless=true",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ]
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    if _job is not None:
        creationflags |= CREATE_BREAKAWAY_FROM_JOB
    print(f"启动 Streamlit：{url}")
    print(f"日志：{LOG}")
    try:
        try:
            _proc = subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
                start_new_session=(os.name != "nt"),
            )
        except OSError:
            # Parent job may forbid breakaway; retry without it.
            if _job is not None:
                _proc = subprocess.Popen(
                    command,
                    cwd=str(ROOT),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                    start_new_session=False,
                )
            else:
                raise
        _assign_to_job(_proc)
        _install_console_handler()
        if not _wait_health(health, args.timeout, _proc):
            print("Streamlit 未能正常启动，日志末尾：")
            try:
                lines = LOG.read_text(encoding="utf-8", errors="replace").splitlines()
                print("\n".join(lines[-30:]))
            except OSError:
                pass
            return 1

        print(f"航运智能账单助手已启动：{url}")
        print("关闭此窗口或按 Ctrl+C 会同时关闭 Streamlit 及其子进程。")
        if not args.no_browser:
            webbrowser.open(url)
        if args.smoke_test:
            print("smoke-test: health=200")
            return 0

        while _proc.poll() is None:
            time.sleep(0.5)
        return _proc.returncode or 0
    except KeyboardInterrupt:
        return 0
    finally:
        _stop()
        log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
