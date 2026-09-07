# -*- coding: utf-8 -*-
"""Built-in browser companion (pywebview) for shopping_calculator.

tkinter owns the mainloop in the shopping calculator process. pywebview runs in
a separate helper process (webview_host.py) whose main thread calls
webview.start() — required on Windows EdgeChromium. A tk Toplevel control panel
drives navigation and invoice extraction over localhost TCP JSON lines.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
from typing import Any, Callable

BROWSER_WINDOW_TITLE = "购物计算器 - 内置浏览器"
CONTROL_WINDOW_TITLE = "浏览器"
DEFAULT_START_URL = "https://www.everyday.com.au/index.html#/my-activity"

# Extract IPC timeout (seconds). Host GUI job wait is slightly shorter.
EXTRACT_TIMEOUT_SEC = 20.0

# Kept for importers / docs; extraction JS lives in webview_host (helper process).
try:
    from webview_host import INVOICE_EXTRACTOR_EVAL_JS as INVOICE_EXTRACTOR_EVAL_JS
except Exception:  # pragma: no cover - host may be absent during partial installs
    INVOICE_EXTRACTOR_EVAL_JS = ""


def try_import_webview():
    """Return webview module or None if missing."""
    try:
        import webview  # type: ignore

        return webview
    except ImportError:
        return None


def _host_script_path() -> str:
    # In source mode the helper is a Python script. In a frozen build the same
    # executable is relaunched with a private host-mode argument.
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "webview_host.py")


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _HostClient:
    """JSON-lines TCP client talking to webview_host.

    Uses recv-into-buffer with sock.settimeout so TimeoutError surfaces reliably
    (makefile().readline() often ignores socket timeouts).
    """

    def __init__(self, port: int) -> None:
        self._port = port
        self._sock: socket.socket | None = None
        self._recv_buf = b""
        self._lock = threading.Lock()

    def connect(self, timeout: float = 8.0) -> None:
        deadline = time.monotonic() + timeout
        last_err: BaseException | None = None
        while time.monotonic() < deadline:
            try:
                sock = socket.create_connection(("127.0.0.1", self._port), timeout=1.0)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self._sock = sock
                self._recv_buf = b""
                return
            except OSError as exc:
                last_err = exc
                time.sleep(0.05)
        raise ConnectionError(f"无法连接内置浏览器进程（端口 {self._port}）：{last_err}")

    def close(self) -> None:
        with self._lock:
            if self._sock is not None:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
            self._recv_buf = b""

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def _recv_line(self, sock: socket.socket, timeout: float) -> str:
        """Read one newline-terminated line using sock timeout + internal buffer."""
        deadline = time.monotonic() + timeout
        while b"\n" not in self._recv_buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("请求超时")
            sock.settimeout(max(remaining, 0.01))
            try:
                chunk = sock.recv(4096)
            except (socket.timeout, TimeoutError) as exc:
                raise TimeoutError("请求超时") from exc
            if not chunk:
                raise ConnectionError("浏览器进程已断开")
            self._recv_buf += chunk
        line, self._recv_buf = self._recv_buf.split(b"\n", 1)
        return line.decode("utf-8", errors="replace")

    def request(self, cmd: str, timeout: float = 30.0, **extra: Any) -> dict[str, Any]:
        if self._sock is None:
            raise ConnectionError("未连接到浏览器进程")

        payload = {"cmd": cmd, **extra}
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self._lock:
            sock = self._sock
            sock.settimeout(timeout)
            try:
                sock.sendall(line.encode("utf-8"))
                resp_line = self._recv_line(sock, timeout)
            except TimeoutError:
                raise
            except OSError as exc:
                # Some platforms surface timed-out recv as OSError / socket.timeout
                if isinstance(exc, socket.timeout) or "timed out" in str(exc).lower():
                    raise TimeoutError("请求超时") from exc
                raise ConnectionError(str(exc)) from exc

        if not resp_line.strip():
            raise ConnectionError("浏览器进程已断开")
        try:
            data = json.loads(resp_line)
        except json.JSONDecodeError as exc:
            raise ConnectionError(f"无效响应：{resp_line!r}") from exc
        if not isinstance(data, dict):
            raise ConnectionError(f"无效响应类型：{type(data)}")
        return data


class BuiltInBrowserSession:
    """One at a time: tk control panel + helper-process pywebview window."""

    def __init__(
        self,
        root: tk.Tk,
        *,
        parse_invoice_json: Callable[[str], list[dict[str, object]]],
        show_invoice_allocator: Callable[[list[dict[str, object]], tk.Misc], None],
        copy_extractor_script: Callable[[], None],
        parent_for_dialogs: tk.Misc | None = None,
    ) -> None:
        self.root = root
        self.parse_invoice_json = parse_invoice_json
        self.show_invoice_allocator = show_invoice_allocator
        # Kept for public API / shopping_calculator wiring; browser panel no longer shows copy.
        self.copy_extractor_script = copy_extractor_script
        self.parent_for_dialogs = parent_for_dialogs or root

        self.control_win: tk.Toplevel | None = None
        self.url_var = tk.StringVar(value=DEFAULT_START_URL)
        self.status_var = tk.StringVar(value="就绪")

        self._proc: subprocess.Popen[str] | None = None
        self._client: _HostClient | None = None
        self._port: int | None = None
        self._started = False
        self._closing = False
        self._extracting = False
        self._lock = threading.Lock()
        self._poll_after_id: str | None = None

    @property
    def is_open(self) -> bool:
        if self.control_win is not None:
            try:
                if self.control_win.winfo_exists():
                    return True
            except tk.TclError:
                pass
        return self._host_alive()

    def _host_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def open_or_focus(self) -> None:
        webview = try_import_webview()
        if webview is None:
            messagebox.showerror(
                "缺少依赖",
                "未安装内置浏览器依赖 pywebview。\n\n"
                "请在当前 Python 环境执行：\n"
                "  pip install pywebview\n\n"
                "Windows（Python 3.12）示例：\n"
                "  py -3.12 -m pip install \"pywebview>=5\"\n\n"
                "Windows 还需安装 Microsoft Edge WebView2 Runtime。",
                parent=self.parent_for_dialogs,
            )
            return

        if self.control_win is not None:
            try:
                if self.control_win.winfo_exists():
                    self.control_win.lift()
                    self.control_win.focus_force()
                    self._ensure_host()
                    return
            except tk.TclError:
                self.control_win = None

        self._create_control_panel()
        self._ensure_host()

    def _create_control_panel(self) -> None:
        win = tk.Toplevel(self.root)
        win.title(CONTROL_WINDOW_TITLE)
        self._center(win, 680, 140)
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", self._on_control_close)

        main = tk.Frame(win, padx=10, pady=10)
        main.pack(fill=tk.BOTH, expand=True)

        url_row = tk.Frame(main)
        url_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(url_row, text="地址:").pack(side=tk.LEFT)
        url_entry = tk.Entry(url_row, textvariable=self.url_var)
        url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        url_entry.bind("<Return>", lambda _e: self.navigate())
        url_entry.focus_set()

        btn_row = tk.Frame(main)
        btn_row.pack(fill=tk.X)
        tk.Button(btn_row, text="前往", width=8, command=self.navigate).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(btn_row, text="刷新", width=8, command=self.reload).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_row, text="后退", width=8, command=self.go_back).pack(side=tk.LEFT, padx=4)
        tk.Button(
            btn_row,
            text="提取当前页小票",
            width=14,
            command=self.extract_current_page,
            bg="#1565c0",
            fg="white",
        ).pack(side=tk.LEFT, padx=8)
        tk.Button(btn_row, text="关闭", width=8, command=self._on_control_close).pack(side=tk.RIGHT)

        status_row = tk.Frame(main)
        status_row.pack(fill=tk.X, pady=(8, 0))
        tk.Label(status_row, textvariable=self.status_var, anchor="w", fg="#444").pack(fill=tk.X)

        self.control_win = win
        self.status_var.set("正在打开 Everyday Rewards；进入消费明细后可提取当前页小票。")
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        if self._poll_after_id is not None:
            try:
                self.root.after_cancel(self._poll_after_id)
            except Exception:
                pass
            self._poll_after_id = None
        self._poll_after_id = self.root.after(500, self._poll_host)

    def _poll_host(self) -> None:
        self._poll_after_id = None
        if self._closing:
            return
        if self._proc is not None and self._proc.poll() is not None:
            self._on_host_exited()
            return
        if self.control_win is not None:
            try:
                if self.control_win.winfo_exists():
                    self._schedule_poll()
            except tk.TclError:
                pass

    def _on_host_exited(self) -> None:
        self._started = False
        if self._client is not None:
            self._client.close()
            self._client = None
        self._proc = None
        self._port = None
        if not self._closing and self.control_win is not None:
            try:
                if self.control_win.winfo_exists():
                    self.status_var.set("浏览器窗口已关闭。可再次点击「前往」或菜单重新打开。")
            except tk.TclError:
                pass

    def _ensure_host(self, url: str | None = None) -> bool:
        """Spawn helper process if needed. Returns True if host is ready."""
        with self._lock:
            if self._host_alive() and self._client is not None and self._client.connected:
                self.status_var.set("浏览器窗口已打开。已启用登录缓存。")
                return True

            # Stale handles
            self._cleanup_host_unlocked(send_quit=False)

            start_url = url if url is not None else (
                self._normalize_url(self.url_var.get()) or DEFAULT_START_URL
            )
            script = _host_script_path()
            if not os.path.isfile(script):
                self.status_var.set("找不到 webview_host.py。")
                messagebox.showerror(
                    "浏览器启动失败",
                    f"找不到辅助脚本：\n{script}",
                    parent=self.control_win or self.parent_for_dialogs,
                )
                return False

            port = _pick_free_port()
            self._port = port
            creationflags = 0
            if sys.platform == "win32":
                # Avoid flashing a console window for the helper.
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

            try:
                if getattr(sys, "frozen", False):
                    command = [sys.executable, "--webview-host", "--port", str(port), "--url", start_url]
                else:
                    command = [sys.executable, script, "--port", str(port), "--url", start_url]
                self._proc = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    creationflags=creationflags,
                )
            except OSError as exc:
                self._proc = None
                self.status_var.set("启动失败。")
                messagebox.showerror(
                    "浏览器启动失败",
                    f"无法启动内置浏览器进程：\n{exc}",
                    parent=self.control_win or self.parent_for_dialogs,
                )
                return False

            client = _HostClient(port)
            try:
                client.connect(timeout=12.0)
                # Confirm IPC
                ping = client.request("ping", timeout=5.0)
                if not ping.get("ok"):
                    raise ConnectionError(ping.get("error") or "ping failed")
            except Exception as exc:
                err_detail = str(exc)
                if self._proc is not None:
                    try:
                        # Give a moment for stderr
                        time.sleep(0.2)
                        if self._proc.poll() is not None and self._proc.stderr:
                            err_out = self._proc.stderr.read() or ""
                            if err_out.strip():
                                err_detail = f"{exc}\n{err_out.strip()}"
                    except Exception:
                        pass
                self._cleanup_host_unlocked(send_quit=False)
                self._on_webview_start_failed(err_detail)
                return False

            self._client = client
            self._started = True
            self.status_var.set("浏览器已启动。")
            self._schedule_poll()
            return True

    def _cleanup_host_unlocked(self, *, send_quit: bool) -> None:
        client = self._client
        self._client = None
        proc = self._proc
        self._proc = None
        self._port = None
        self._started = False

        if client is not None:
            if send_quit:
                try:
                    client.request("quit", timeout=2.0)
                except Exception:
                    pass
            client.close()

        if proc is not None and proc.poll() is None:
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            if proc.stderr:
                try:
                    proc.stderr.close()
                except Exception:
                    pass

    def _on_webview_start_failed(self, exc: object) -> None:
        messagebox.showerror(
            "浏览器启动失败",
            f"无法启动内置浏览器：\n{exc}\n\n"
            "Windows 请确认已安装 Edge WebView2 Runtime，并执行：\n"
            '  py -3.12 -m pip install "pywebview>=5"',
            parent=self.control_win or self.parent_for_dialogs,
        )
        self.status_var.set("启动失败。")

    def _on_control_close(self) -> None:
        self._closing = True
        if self._poll_after_id is not None:
            try:
                self.root.after_cancel(self._poll_after_id)
            except Exception:
                pass
            self._poll_after_id = None

        with self._lock:
            self._cleanup_host_unlocked(send_quit=True)

        if self.control_win is not None:
            try:
                self.control_win.destroy()
            except tk.TclError:
                pass
        self.control_win = None
        self._closing = False

    def reset_handle(self) -> None:
        """Called by host if session should be considered closed."""
        self._on_control_close()

    @staticmethod
    def _center(window: tk.Misc, width: int, height: int) -> None:
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = max((screen_width - width) // 2, 0)
        y = max((screen_height - height) // 2, 0)
        window.geometry(f"{width}x{height}+{x}+{y}")

    @staticmethod
    def _normalize_url(raw: str) -> str:
        url = (raw or "").strip()
        if not url or url == "about:blank":
            return DEFAULT_START_URL
        if "://" not in url:
            url = "https://" + url
        return url

    def navigate(self) -> None:
        if try_import_webview() is None:
            self.open_or_focus()
            return

        url = self._normalize_url(self.url_var.get())
        if url != DEFAULT_START_URL:
            self.url_var.set(url)

        if not self._host_alive() or self._client is None or not self._client.connected:
            self.url_var.set(url)
            ok = self._ensure_host(url)
            if ok:
                self.status_var.set(f"已前往：{url}" if url != DEFAULT_START_URL else "浏览器已启动。")
            return

        def do_nav() -> None:
            try:
                assert self._client is not None
                resp = self._client.request("navigate", url=url, timeout=15.0)
                if resp.get("ok"):
                    self.root.after(0, lambda: self.status_var.set(f"已前往：{url}"))
                else:
                    err = resp.get("error") or "未知错误"
                    self.root.after(0, lambda: self.status_var.set(f"导航失败：{err}"))
            except Exception as exc:
                self.root.after(0, lambda: self.status_var.set(f"导航失败：{exc}"))

        threading.Thread(target=do_nav, daemon=True).start()

    def reload(self) -> None:
        if not self._host_alive() or self._client is None:
            self.status_var.set("浏览器尚未打开。")
            return

        def do_reload() -> None:
            try:
                assert self._client is not None
                resp = self._client.request("reload", timeout=15.0)
                if resp.get("ok"):
                    self.root.after(0, lambda: self.status_var.set("已刷新。"))
                else:
                    err = resp.get("error") or "未知错误"
                    self.root.after(0, lambda: self.status_var.set(f"刷新失败：{err}"))
            except Exception as exc:
                self.root.after(0, lambda: self.status_var.set(f"刷新失败：{exc}"))

        threading.Thread(target=do_reload, daemon=True).start()

    def go_back(self) -> None:
        if not self._host_alive() or self._client is None:
            self.status_var.set("浏览器尚未打开。")
            return

        def do_back() -> None:
            try:
                assert self._client is not None
                resp = self._client.request("back", timeout=15.0)
                if resp.get("ok"):
                    self.root.after(0, lambda: self.status_var.set("已后退。"))
                else:
                    err = resp.get("error") or "未知错误"
                    self.root.after(0, lambda: self.status_var.set(f"后退失败：{err}"))
            except Exception as exc:
                self.root.after(0, lambda: self.status_var.set(f"后退失败：{exc}"))

        threading.Thread(target=do_back, daemon=True).start()

    def extract_current_page(self) -> None:
        if not self._host_alive() or self._client is None or not self._started:
            messagebox.showinfo(
                "提示",
                "请先打开内置浏览器并进入发票页面，再提取。",
                parent=self.control_win or self.parent_for_dialogs,
            )
            return
        if self._extracting:
            return

        self._extracting = True
        self.status_var.set("正在提取当前页小票…")
        parent = self.control_win or self.parent_for_dialogs

        def worker() -> None:
            try:
                assert self._client is not None
                resp = self._client.request("extract", timeout=EXTRACT_TIMEOUT_SEC)
                if not resp.get("ok"):
                    err = str(resp.get("error") or "extract failed")
                    if "timed out" in err.lower() or "timeout" in err.lower():
                        raise TimeoutError(err)
                    raise RuntimeError(err)
                result = resp.get("data")
                self.root.after(0, lambda: self._finish_extract(result, parent))
            except TimeoutError:
                self.root.after(0, lambda: self._finish_extract_timeout(parent))
            except Exception as exc:
                self.root.after(0, lambda: self._finish_extract_error(exc, parent))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_extract_timeout(self, parent: tk.Misc) -> None:
        self._extracting = False
        msg = "提取超时，请刷新页面后重试或改用识别小票图片"
        self.status_var.set(msg)
        messagebox.showerror("提取超时", msg, parent=parent)

    def _finish_extract_error(self, exc: BaseException, parent: tk.Misc) -> None:
        self._extracting = False
        self.status_var.set("提取失败。")
        messagebox.showerror("提取失败", f"无法在当前页执行提取脚本：\n{exc}", parent=parent)

    def _finish_extract(self, result: object, parent: tk.Misc) -> None:
        self._extracting = False
        raw: str
        if result is None:
            raw = "[]"
        elif isinstance(result, (list, dict)):
            raw = json.dumps(result, ensure_ascii=False)
        else:
            raw = str(result).strip()
            if raw.startswith("'") and raw.endswith("'"):
                raw = raw[1:-1]

        try:
            rows = self.parse_invoice_json(raw if raw else "[]")
        except ValueError as exc:
            self.status_var.set("解析失败。")
            messagebox.showerror("错误", str(exc), parent=parent)
            return

        if not rows:
            self.status_var.set("未识别到商品行。")
            messagebox.showinfo(
                "提示",
                "当前页不像可提取的发票页，可改用「识别小票图片」。\n"
                "已支持 Coles 与 Everyday/Woolworths 等常见版式（尽力而为）。",
                parent=parent,
            )
            return

        self.status_var.set(f"已提取 {len(rows)} 条商品，打开分配窗口。")
        self.show_invoice_allocator(rows, parent)
