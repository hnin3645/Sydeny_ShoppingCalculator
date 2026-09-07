# -*- coding: utf-8 -*-
"""Standalone pywebview host process for shopping_calculator.

Must call webview.start() on the real main thread (required on Windows EdgeChromium).
Parent (app_browser.BuiltInBrowserSession) launches this script via subprocess and
talks over localhost TCP using one JSON object per line.

All window.evaluate_js / load_url / reload / back / destroy calls run on a single
backend worker started via webview.start(backend, window). TCP client threads only
enqueue jobs and wait on a threading.Event (with timeout) — never call the GUI APIs
directly (that can deadlock EdgeChromium).
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import queue
import re
import socket
import sys
import threading
from pathlib import Path
from typing import Any

BROWSER_WINDOW_TITLE = "购物计算器 - 内置浏览器"
DEFAULT_START_URL = "https://www.everyday.com.au/index.html#/my-activity"

# Default wait for GUI jobs (seconds). Client extract timeout is ~20s; host waits a
# touch less so the TCP reply can still be sent before the client gives up.
_JOB_TIMEOUT_DEFAULT = 15.0
_JOB_TIMEOUT_EXTRACT = 18.0
_JOB_TIMEOUT_QUIT = 5.0

# Row scraping: Coles DOM first, then Everyday/Woolworths-style generic text scrape.
# Always returns JSON.stringify(rows) quickly; try/catch → "[]" — never hang in JS.
INVOICE_EXTRACTOR_EVAL_JS = r"""
(() => {
  try {
    const rows = [];
    let lastProductName = "";
    let lastQtyInfo = "";

    const pushRow = (item, quantityInfo, price, priceText) => {
      rows.push({
        item: item,
        quantityInfo: quantityInfo || "",
        price: price,
        priceText: priceText || ""
      });
    };

    const looksLikeWeightUnitLine = (s) => {
      if (/\d+[.,]?\d*\s*(kg|g|ml|l)\b/i.test(s) && (/\bNET\b/i.test(s) || /@/.test(s))) return true;
      if (/@\s*\$\s*\d/.test(s)) return true;
      if (/\/\s*(kg|g|ml|l)\b/i.test(s)) return true;
      return false;
    };

    // --- Coles online invoice DOM ---
    const colesNodes = document.querySelectorAll('div.sub-heading.items');
    if (colesNodes && colesNodes.length) {
      [...colesNodes].forEach(row => {
        const text = row.querySelector('p')?.innerText.replace(/\s+/g, ' ').trim() || "";
        const priceText = row.querySelector('span.text-right.price')?.innerText.trim() || "";
        const amount = parseFloat(String(priceText).replace(/[^0-9.-]/g, ''));

        if (!text) return;

        const isQtyLine = /^Qty\s+/i.test(text);
        const isWeightLine = looksLikeWeightUnitLine(text);

        if (!priceText && !isQtyLine && !isWeightLine) {
          lastProductName = text;
          return;
        }

        if (priceText && !Number.isNaN(amount)) {
          let itemName = text;
          let quantityInfo = "";
          if ((isQtyLine || isWeightLine) && lastProductName) {
            itemName = lastProductName;
            quantityInfo = text;
          }
          pushRow(itemName, quantityInfo, amount, priceText);
          lastProductName = "";
        }
      });
      if (rows.length) return JSON.stringify(rows);
    }

    // --- Structured tables / list rows with price-looking text ---
    const moneyRe = /\$?\s*-?\s*\d{1,3}(?:,\d{3})*\.\d{2}(?!\d)/;
    const skipRe = /\b(TOTAL|SUBTOTAL|SUB\s*TOTAL|GST|TAX|CARD|CHANGE|ABN|TEL|PHONE|POINTS|EVERYDAY\s+REWARDS|EFTPOS|APPROVED|BALANCE|TENDER|VISA|MASTERCARD|DEBIT|CREDIT|ROUNDING|THANK\s+YOU|INVOICE|RECEIPT|TAX\s+INVOICE)\b/i;
    const qtyRe = /^Qty\s+/i;
    // Weight/unit lines (not product names): "1.307 kg NET @ $4.90/kg", "@ $4.90", "/kg"
    const isWeightUnitLine = looksLikeWeightUnitLine;
    const isQtyOrWeightLine = (s) => qtyRe.test(s) || isWeightUnitLine(s);

    const tryStructured = () => {
      const out = [];
      let pending = "";
      let unsafePairing = false;
      const candidates = [
        ...document.querySelectorAll('table tr'),
        ...document.querySelectorAll('li'),
        ...document.querySelectorAll('[class*="item"],[class*="line"],[class*="product"],[class*="receipt"]')
      ];
      const seen = new Set();
      for (const el of candidates) {
        if (!el || seen.has(el)) continue;
        // Prefer leaf-ish rows
        if (el.querySelector && el.querySelector('table tr, li')) continue;
        seen.add(el);
        const text = (el.innerText || "").replace(/\s+/g, ' ').trim();
        if (!text || text.length > 200) continue;
        if (skipRe.test(text)) continue;
        if (isWeightUnitLine(text)) {
          // A weighted product needs context from its preceding product-name
          // line and sometimes a following total line. Candidate elements do
          // not reliably contain all three, so use the ordered body fallback.
          unsafePairing = true;
          break;
        }
        const m = text.match(moneyRe);
        if (!m) {
          if (!isQtyOrWeightLine(text) && text.length >= 2 && text.length < 80) pending = text;
          continue;
        }
        const priceText = m[0].trim();
        const amount = parseFloat(priceText.replace(/[^0-9.-]/g, ''));
        if (Number.isNaN(amount)) continue;
        let label = text.replace(m[0], ' ').replace(/\s+/g, ' ').trim();
        let quantityInfo = "";
        if (isQtyOrWeightLine(label)) {
          if (!pending) {
            // Everyday receipts render the product name and its weight/total in
            // separate nested elements. Some layouts do not expose the name as
            // one of our structured candidates, so returning this partial row
            // would mislabel e.g. Banana Cavendish as "1.307 kg NET ...".
            // Reject the structured pass and let the body-text state machine
            // pair product -> weight -> total instead.
            unsafePairing = true;
            break;
          }
          quantityInfo = label;
          label = pending;
        } else if (isQtyOrWeightLine(text) && pending) {
          // Full text is weight/unit (label after stripping one money may still look like it)
          quantityInfo = text.replace(m[0], ' ').replace(/\s+/g, ' ').trim() || label;
          label = pending;
        } else if (!label && pending) {
          label = pending;
        }
        if (!label) continue;
        out.push({ item: label, quantityInfo, price: amount, priceText });
        pending = "";
      }
      return unsafePairing ? [] : out;
    };

    const structured = tryStructured();
    if (structured.length) return JSON.stringify(structured);

    // --- Fallback: document.body.innerText line pairing ---
    const bodyText = (document.body && document.body.innerText) ? document.body.innerText : "";
    const lines = bodyText.split(/\r?\n/).map(l => l.replace(/\s+/g, ' ').trim()).filter(Boolean);
    const moneyGlobal = /\$?\s*-?\s*\d{1,3}(?:,\d{3})*\.\d{2}(?!\d)/g;
    const allMoneyTokens = (s) => {
      const out = [];
      let m;
      const re = /\$?\s*-?\s*\d{1,3}(?:,\d{3})*\.\d{2}(?!\d)/g;
      while ((m = re.exec(s)) !== null) out.push({ text: m[0], index: m.index });
      return out;
    };
    const allMoney = (s) => allMoneyTokens(s).map(t => t.text);
    const stripMoney = (s) => s.replace(/\$?\s*-?\s*\d{1,3}(?:,\d{3})*\.\d{2}(?!\d)/g, ' ').replace(/\s+/g, ' ').trim();
    const moneyIsUnitPrice = (line, tok) => {
      const after = line.slice(tok.index + tok.text.length);
      if (/^\s*\/\s*(kg|g|ml|l)\b/i.test(after)) return true;
      const before = line.slice(0, tok.index);
      if (/@\s*$/.test(before)) return true;
      return false;
    };
    const resolveQtyPrice = (line, i) => {
      const tokens = allMoneyTokens(line);
      const nonUnit = tokens.filter(t => !moneyIsUnitPrice(line, t));
      let priceText = "";
      let amount = NaN;
      let consumedNext = false;
      if (nonUnit.length >= 1) {
        // Prefer trailing line-total after any unit-price clause
        priceText = nonUnit[nonUnit.length - 1].text.trim();
        amount = parseFloat(priceText.replace(/[^0-9.-]/g, ''));
      } else {
        const next = lines[i + 1] || "";
        const nm = allMoneyTokens(next);
        if (nm.length && !skipRe.test(next) && stripMoney(next) === "") {
          priceText = nm[nm.length - 1].text.trim();
          amount = parseFloat(priceText.replace(/[^0-9.-]/g, ''));
          consumedNext = true;
        } else if (tokens.length && !isWeightUnitLine(line)) {
          // Plain Qty with a single @ price and no next amount: keep legacy fallback
          priceText = tokens[tokens.length - 1].text.trim();
          amount = parseFloat(priceText.replace(/[^0-9.-]/g, ''));
        }
      }
      return { priceText, amount, consumedNext };
    };

    lastProductName = "";
    lastQtyInfo = "";
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (skipRe.test(line)) {
        lastProductName = "";
        lastQtyInfo = "";
        continue;
      }
      const isQtyLine = isQtyOrWeightLine(line);
      const tokens = allMoneyTokens(line);

      if (isQtyLine && lastProductName) {
        let qtyInfo = line;
        const { priceText, amount, consumedNext } = resolveQtyPrice(line, i);
        if (!Number.isNaN(amount)) {
          if (!consumedNext && priceText) {
            const totalAt = qtyInfo.lastIndexOf(priceText);
            if (totalAt >= 0) {
              qtyInfo = (qtyInfo.slice(0, totalAt) + qtyInfo.slice(totalAt + priceText.length))
                .replace(/\s+/g, ' ').trim();
            }
          }
          pushRow(lastProductName, qtyInfo, amount, priceText);
          lastProductName = "";
          lastQtyInfo = "";
          if (consumedNext) i++;
        } else {
          // Remember weight/qty until a money-only total line appears
          lastQtyInfo = qtyInfo;
        }
        continue;
      }

      if (!tokens.length) {
        if (line.length >= 2 && line.length < 100 && !/^\d+$/.test(line)) {
          if (isQtyLine) {
            lastQtyInfo = line;
          } else {
            lastProductName = line;
            lastQtyInfo = "";
          }
        }
        continue;
      }

      // Money-only line: attach to previous product (+ optional qty info)
      if (stripMoney(line) === "" && lastProductName) {
        const priceText = tokens[tokens.length - 1].text.trim();
        const amount = parseFloat(priceText.replace(/[^0-9.-]/g, ''));
        if (!Number.isNaN(amount)) {
          pushRow(lastProductName, lastQtyInfo, amount, priceText);
          lastProductName = "";
          lastQtyInfo = "";
        }
        continue;
      }

      // Do not treat weight/unit lines as product names even if unmatched above
      if (isWeightUnitLine(line)) {
        if (lastProductName) lastQtyInfo = stripMoney(line) || line;
        continue;
      }

      const priceText = tokens[tokens.length - 1].text.trim();
      const amount = parseFloat(priceText.replace(/[^0-9.-]/g, ''));
      if (Number.isNaN(amount)) continue;
      let label = stripMoney(line);
      let quantityInfo = lastQtyInfo;
      if (!label && lastProductName) label = lastProductName;
      if (!label || skipRe.test(label)) {
        lastProductName = "";
        lastQtyInfo = "";
        continue;
      }
      pushRow(label, quantityInfo, amount, priceText);
      lastProductName = "";
      lastQtyInfo = "";
    }
    return JSON.stringify(rows);
  } catch (e) {
    return "[]";
  }
})()
""".strip()


# ---------------------------------------------------------------------------
# Optional Python mirror of the generic innerText fallback (for unit tests).
# Schema matches parse_invoice_json / JS rows: item, quantityInfo, price, priceText.
# ---------------------------------------------------------------------------

_MONEY_RE = re.compile(r"\$?\s*-?\s*\d{1,3}(?:,\d{3})*\.\d{2}(?!\d)")
_SKIP_RE = re.compile(
    r"(?i)\b(TOTAL|SUBTOTAL|SUB\s*TOTAL|GST|TAX|CARD|CHANGE|ABN|TEL|PHONE|POINTS|"
    r"EVERYDAY\s+REWARDS|EFTPOS|APPROVED|BALANCE|TENDER|VISA|MASTERCARD|DEBIT|"
    r"CREDIT|ROUNDING|THANK\s+YOU|INVOICE|RECEIPT|TAX\s+INVOICE)\b"
)
_QTY_RE = re.compile(r"(?i)^Qty\s+")
# Weight/unit lines e.g. "1.307 kg NET @ $4.90/kg" — not product names.
_WEIGHT_WITH_NET_OR_AT = re.compile(
    r"(?i)\d+[.,]?\d*\s*(?:kg|g|ml|l)\b"
)
_HAS_NET_OR_AT = re.compile(r"(?i)(?:\bNET\b|@)")
_UNIT_PRICE_AT = re.compile(r"@\s*\$\s*\d")
_PER_UNIT = re.compile(r"(?i)/\s*(?:kg|g|ml|l)\b")


def _is_weight_unit_line(s: str) -> bool:
    if _WEIGHT_WITH_NET_OR_AT.search(s) and _HAS_NET_OR_AT.search(s):
        return True
    if _UNIT_PRICE_AT.search(s):
        return True
    if _PER_UNIT.search(s):
        return True
    return False


def _is_qty_or_weight_line(s: str) -> bool:
    return bool(_QTY_RE.match(s)) or _is_weight_unit_line(s)


def _parse_money(token: str) -> float | None:
    try:
        return float(re.sub(r"[^0-9.-]", "", token))
    except ValueError:
        return None


def _money_is_unit_price(line: str, start: int, token: str) -> bool:
    after = line[start + len(token) :]
    if re.match(r"(?i)^\s*/\s*(?:kg|g|ml|l)\b", after):
        return True
    before = line[:start]
    if re.search(r"@\s*$", before):
        return True
    return False


def _strip_money(s: str) -> str:
    return re.sub(r"\s+", " ", _MONEY_RE.sub(" ", s)).strip()


def parse_generic_receipt_text(text: str) -> list[dict[str, Any]]:
    """Best-effort line parser mirroring the JS innerText fallback."""
    rows: list[dict[str, Any]] = []
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    last_product = ""
    last_qty_info = ""
    i = 0
    while i < len(lines):
        line = lines[i]
        if _SKIP_RE.search(line):
            last_product = ""
            last_qty_info = ""
            i += 1
            continue

        is_qty = _is_qty_or_weight_line(line)
        moneys = list(_MONEY_RE.finditer(line))

        if is_qty and last_product:
            qty_info = line
            price_text = ""
            amount: float | None = None
            consumed_next = False
            non_unit = [m for m in moneys if not _money_is_unit_price(line, m.start(), m.group(0))]
            if non_unit:
                price_text = non_unit[-1].group(0).strip()
                amount = _parse_money(price_text)
            else:
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                nm = list(_MONEY_RE.finditer(nxt))
                if nm and not _SKIP_RE.search(nxt) and not _strip_money(nxt):
                    price_text = nm[-1].group(0).strip()
                    amount = _parse_money(price_text)
                    consumed_next = True
                elif moneys and not _is_weight_unit_line(line):
                    # Legacy Qty fallback when no separate total is present
                    price_text = moneys[-1].group(0).strip()
                    amount = _parse_money(price_text)
            if amount is not None:
                if not consumed_next and price_text:
                    total_at = qty_info.rfind(price_text)
                    if total_at >= 0:
                        qty_info = re.sub(
                            r"\s+",
                            " ",
                            qty_info[:total_at] + qty_info[total_at + len(price_text) :],
                        ).strip()
                rows.append(
                    {
                        "item": last_product,
                        "quantityInfo": qty_info,
                        "price": amount,
                        "priceText": price_text,
                    }
                )
                last_product = ""
                last_qty_info = ""
                i += 1 + (1 if consumed_next else 0)
                continue
            last_qty_info = qty_info
            i += 1
            continue

        if not moneys:
            if 2 <= len(line) < 100 and not line.isdigit():
                if is_qty:
                    last_qty_info = line
                else:
                    last_product = line
                    last_qty_info = ""
            i += 1
            continue

        # Money-only continuation after product (+ optional weight/qty line)
        if not _strip_money(line) and last_product:
            price_text = moneys[-1].group(0).strip()
            amount = _parse_money(price_text)
            if amount is not None:
                rows.append(
                    {
                        "item": last_product,
                        "quantityInfo": last_qty_info,
                        "price": amount,
                        "priceText": price_text,
                    }
                )
                last_product = ""
                last_qty_info = ""
            i += 1
            continue

        if _is_weight_unit_line(line):
            if last_product:
                last_qty_info = _strip_money(line) or line
            i += 1
            continue

        price_text = moneys[-1].group(0).strip()
        amount = _parse_money(price_text)
        if amount is None:
            i += 1
            continue
        label = _strip_money(line)
        quantity_info = last_qty_info
        if not label and last_product:
            label = last_product
        if not label or _SKIP_RE.search(label):
            last_product = ""
            last_qty_info = ""
            i += 1
            continue
        rows.append(
            {
                "item": label,
                "quantityInfo": quantity_info,
                "price": amount,
                "priceText": price_text,
            }
        )
        last_product = ""
        last_qty_info = ""
        i += 1
    return rows


def _webview_storage_path() -> str:
    """Stable WebView2/profile dir so login cookies survive restarts."""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / "ShoppingCalculator" / "webview"
    elif system == "Darwin":
        path = Path.home() / "Library" / "Application Support" / "ShoppingCalculator" / "webview"
    else:
        path = Path.home() / ".local" / "share" / "ShoppingCalculator" / "webview"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = Path(__file__).resolve().parent / "webview_storage"
        path.mkdir(parents=True, exist_ok=True)
    return str(path)



def _send(conn: socket.socket, payload: dict[str, Any]) -> None:
    data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    conn.sendall(data)


class _GuiJob:
    __slots__ = ("msg", "result", "done")

    def __init__(self, msg: dict[str, Any]) -> None:
        self.msg = msg
        self.result: dict[str, Any] = {"ok": False, "error": "not run"}
        self.done = threading.Event()


def _run_gui_command(window: Any, msg: dict[str, Any]) -> dict[str, Any]:
    """Execute a command that needs the webview window (backend thread only)."""
    cmd = (msg.get("cmd") or "").strip().lower()
    if window is None:
        return {"ok": False, "error": "window not ready"}

    try:
        if cmd == "navigate":
            url = msg.get("url") or DEFAULT_START_URL
            window.load_url(url)
            return {"ok": True}

        if cmd == "reload":
            if hasattr(window, "reload"):
                window.reload()
            else:
                window.evaluate_js("location.reload()")
            return {"ok": True}

        if cmd == "back":
            window.evaluate_js("history.back()")
            return {"ok": True}

        if cmd == "extract":
            result = window.evaluate_js(INVOICE_EXTRACTOR_EVAL_JS)
            if result is None:
                data: Any = "[]"
            elif isinstance(result, (list, dict)):
                data = json.dumps(result, ensure_ascii=False)
            else:
                data = str(result)
            return {"ok": True, "data": data}

        if cmd == "quit":
            try:
                window.destroy()
            except Exception:
                pass
            return {"ok": True, "data": "quitting"}

        return {"ok": False, "error": f"unknown cmd: {cmd}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _backend_worker(window: Any, job_q: queue.Queue, stop_event: threading.Event) -> None:
    """Owns ALL evaluate_js / load_url / reload / back / destroy calls."""
    while not stop_event.is_set():
        try:
            job: _GuiJob = job_q.get(timeout=0.2)
        except queue.Empty:
            continue
        try:
            job.result = _run_gui_command(window, job.msg)
        except Exception as exc:
            job.result = {"ok": False, "error": str(exc)}
        finally:
            job.done.set()
            cmd = (job.msg.get("cmd") or "").strip().lower()
            if cmd == "quit":
                stop_event.set()
                return


def _enqueue_and_wait(
    job_q: queue.Queue,
    msg: dict[str, Any],
    timeout: float,
    stop_event: threading.Event,
) -> dict[str, Any]:
    job = _GuiJob(msg)
    try:
        job_q.put(job, timeout=2.0)
    except queue.Full:
        return {"ok": False, "error": "gui job queue full"}
    if not job.done.wait(timeout=timeout):
        return {"ok": False, "error": "gui operation timed out"}
    if stop_event.is_set() and (msg.get("cmd") or "").strip().lower() != "quit":
        # Still return whatever we have if done fired
        pass
    return job.result


def _serve(
    port: int,
    state: dict[str, Any],
    stop_event: threading.Event,
    job_q: queue.Queue,
) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(5)
    srv.settimeout(0.5)
    state["server_ready"] = True

    clients: list[socket.socket] = []

    while not stop_event.is_set():
        try:
            conn, _addr = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break

        conn.settimeout(None)
        clients.append(conn)
        threading.Thread(
            target=_client_loop,
            args=(conn, state, stop_event, job_q),
            name="webview-host-client",
            daemon=True,
        ).start()

    for c in clients:
        try:
            c.close()
        except OSError:
            pass
    try:
        srv.close()
    except OSError:
        pass


def _client_loop(
    conn: socket.socket,
    state: dict[str, Any],
    stop_event: threading.Event,
    job_q: queue.Queue,
) -> None:
    buf = b""
    try:
        while not stop_event.is_set():
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    _send(conn, {"ok": False, "error": f"bad json: {exc}"})
                    continue
                if not isinstance(msg, dict):
                    _send(conn, {"ok": False, "error": "msg must be object"})
                    continue

                cmd_name = (msg.get("cmd") or "").strip().lower()

                # ping needs no GUI
                if cmd_name == "ping":
                    try:
                        _send(conn, {"ok": True, "data": "pong"})
                    except OSError:
                        return
                    continue

                # Wait briefly for backend/window readiness
                if not state.get("backend_ready") and cmd_name != "quit":
                    for _ in range(50):
                        if stop_event.is_set():
                            break
                        if state.get("backend_ready"):
                            break
                        stop_event.wait(0.1)

                if cmd_name == "extract":
                    timeout = _JOB_TIMEOUT_EXTRACT
                elif cmd_name == "quit":
                    timeout = _JOB_TIMEOUT_QUIT
                else:
                    timeout = _JOB_TIMEOUT_DEFAULT

                resp = _enqueue_and_wait(job_q, msg, timeout, stop_event)
                try:
                    _send(conn, resp)
                except OSError:
                    return

                if cmd_name == "quit":
                    stop_event.set()
                    return
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="pywebview host for shopping_calculator")
    parser.add_argument("--port", type=int, required=True, help="localhost TCP port for JSON IPC")
    parser.add_argument("--url", default=DEFAULT_START_URL, help="initial URL")
    args = parser.parse_args(argv)

    try:
        import webview  # type: ignore
    except ImportError:
        print("pywebview is not installed", file=sys.stderr)
        return 2

    state: dict[str, Any] = {"window": None, "server_ready": False, "backend_ready": False}
    stop_event = threading.Event()
    job_q: queue.Queue = queue.Queue()

    server_thread = threading.Thread(
        target=_serve,
        args=(args.port, state, stop_event, job_q),
        name="webview-host-tcp",
        daemon=True,
    )
    server_thread.start()

    for _ in range(40):
        if state.get("server_ready"):
            break
        if not server_thread.is_alive():
            print("TCP server failed to start", file=sys.stderr)
            return 3
        stop_event.wait(0.05)
    else:
        print("TCP server not ready", file=sys.stderr)
        return 3

    start_url = args.url.strip() or DEFAULT_START_URL
    window = webview.create_window(
        BROWSER_WINDOW_TITLE,
        url=start_url,
        width=1100,
        height=800,
    )
    state["window"] = window

    def _on_closed() -> None:
        stop_event.set()

    try:
        window.events.closed += _on_closed
    except Exception:
        pass

    def backend(win: Any) -> None:
        state["backend_ready"] = True
        _backend_worker(win, job_q, stop_event)

    start_kwargs: dict[str, Any] = {
        "debug": False,
        # Persist cookies/localStorage so Everyday/Coles logins survive reopens.
        "private_mode": False,
        "storage_path": _webview_storage_path(),
    }
    if platform.system() == "Windows":
        start_kwargs["gui"] = "edgechromium"

    try:
        # Recommended pattern: one backend worker owns all GUI/JS calls.
        webview.start(backend, window, **start_kwargs)
    except Exception as exc:
        print(f"webview.start failed: {exc}", file=sys.stderr)
        stop_event.set()
        return 1
    finally:
        stop_event.set()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
