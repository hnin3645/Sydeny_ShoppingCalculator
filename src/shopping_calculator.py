# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
import sys
import threading
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import filedialog, messagebox, scrolledtext

from app_browser import BuiltInBrowserSession


DEFAULT_PEOPLE = ("msc", "nhy", "wpq", "zyf")
SELECTED_COLOR = "lightgreen"
EPSILON = 1e-9
AMOUNT_SUM_TOLERANCE = 0.02
PERCENT_SUM_TOLERANCE = 0.05
MONTHLY_DISCOUNT_FACTOR = 0.9

SPLIT_MODE_EQUAL = "equal"
SPLIT_MODE_QUANTITY = "quantity"
SPLIT_MODE_EXACT = "exact"
SPLIT_MODE_PERCENTAGE = "percentage"

SPLIT_MODE_LABELS = {
    SPLIT_MODE_EQUAL: "平均",
    SPLIT_MODE_QUANTITY: "按数量",
    SPLIT_MODE_EXACT: "精确金额",
    SPLIT_MODE_PERCENTAGE: "百分比",
}
LABEL_TO_SPLIT_MODE = {label: mode for mode, label in SPLIT_MODE_LABELS.items()}

INVOICE_EXTRACTOR_SCRIPT = r"""const rows = [];
let lastProductName = "";

[...document.querySelectorAll('div.sub-heading.items')].forEach(row => {
  const text = row.querySelector('p')?.innerText.replace(/\s+/g, ' ').trim() || "";
  const priceText = row.querySelector('span.text-right.price')?.innerText.trim() || "";
  const amount = parseFloat(priceText.replace(/[^0-9.-]/g, ''));

  if (!text) return;

  const isQtyLine = /^Qty\s+/i.test(text);

  // 没有价格，而且不是 Qty 行：通常是商品名，例如 Potato Mash 1.5kg
  if (!priceText && !isQtyLine) {
    lastProductName = text;
    return;
  }

  // 有价格
  if (priceText && !Number.isNaN(amount)) {
    let itemName = text;
    let quantityInfo = "";

    // 如果这一行是 Qty 2 @ xxx，就用上一行商品名当 item
    if (isQtyLine && lastProductName) {
      itemName = lastProductName;
      quantityInfo = text;
    }

    rows.push({
      item: itemName,
      quantityInfo: quantityInfo,
      price: amount,
      priceText: priceText
    });

    lastProductName = "";
  }
});

console.table(rows);
copy(JSON.stringify(rows, null, 2));
console.log("已复制到剪贴板，共 " + rows.length + " 条商品。打开记事本 Ctrl+V 查看。");
"""


def finalize_shares(people: list[str], amount: float, raw_shares: dict[str, float]) -> dict[str, float]:
    """Round to 2 decimals; put remainder on the last person so shares sum to amount."""
    if not people:
        raise ValueError("至少选择一个人")

    result: dict[str, float] = {}
    running = 0.0
    for name in people[:-1]:
        rounded = round(raw_shares[name], 2)
        result[name] = rounded
        running += rounded
    result[people[-1]] = round(amount - running, 2)
    return result


def compute_shares(
    people: list[str],
    amount: float,
    mode: str = SPLIT_MODE_EQUAL,
    inputs: dict[str, float] | None = None,
) -> dict[str, float]:
    """Compute per-person shares from total + split mode + optional per-person inputs."""
    if not people:
        raise ValueError("至少选择一个人")
    if mode not in SPLIT_MODE_LABELS:
        raise ValueError(f"未知分摊方式：{mode}")
    if not math.isfinite(amount):
        raise ValueError("金额必须是有效数字")

    inputs = dict(inputs or {})

    if mode == SPLIT_MODE_EQUAL:
        raw = {name: amount / len(people) for name in people}
        return finalize_shares(people, amount, raw)

    if mode == SPLIT_MODE_QUANTITY:
        quantities: list[float] = []
        for name in people:
            if name not in inputs:
                raise ValueError(f"请输入 {name} 的数量")
            quantity = float(inputs[name])
            if not math.isfinite(quantity) or quantity <= 0:
                raise ValueError(f"{name} 的数量必须是正数")
            quantities.append(quantity)
        total_quantity = sum(quantities)
        if total_quantity <= 0:
            raise ValueError("数量合计必须大于 0")
        raw = {name: amount * (float(inputs[name]) / total_quantity) for name in people}
        return finalize_shares(people, amount, raw)

    if mode == SPLIT_MODE_EXACT:
        values: list[float] = []
        for name in people:
            if name not in inputs:
                raise ValueError(f"请输入 {name} 的金额")
            value = float(inputs[name])
            if not math.isfinite(value):
                raise ValueError(f"{name} 的金额无效")
            values.append(value)
        total_exact = sum(values)
        if abs(total_exact - amount) > AMOUNT_SUM_TOLERANCE:
            raise ValueError(f"精确金额合计 {total_exact:.2f} 必须等于总额 {amount:.2f}")
        raw = {name: float(inputs[name]) for name in people}
        # Tiny rounding fix: force last person so shares sum exactly to amount.
        return finalize_shares(people, amount, raw)

    # percentage
    percentages: list[float] = []
    for name in people:
        if name not in inputs:
            raise ValueError(f"请输入 {name} 的百分比")
        percent = float(inputs[name])
        if not math.isfinite(percent) or percent < 0:
            raise ValueError(f"{name} 的百分比必须是非负数")
        percentages.append(percent)
    total_percent = sum(percentages)
    if abs(total_percent - 100.0) > PERCENT_SUM_TOLERANCE:
        raise ValueError(f"百分比合计 {total_percent:.2f}% 必须等于 100%")
    raw = {name: amount * (float(inputs[name]) / 100.0) for name in people}
    return finalize_shares(people, amount, raw)


@dataclass
class ExpenseEntry:
    """一条消费记录：amount 是原始总金额，shares 是每个人分摊后的金额。"""

    people: tuple[str, ...]
    amount: float
    shares: dict[str, float] = field(default_factory=dict)
    item_name: str = ""
    quantity_info: str = ""
    price_text: str = ""
    split_mode: str = SPLIT_MODE_EQUAL
    split_inputs: dict[str, float] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        people: list[str],
        amount: float,
        item_name: str = "",
        quantity_info: str = "",
        price_text: str = "",
        split_mode: str = SPLIT_MODE_EQUAL,
        split_inputs: dict[str, float] | None = None,
    ) -> "ExpenseEntry":
        inputs = dict(split_inputs or {})
        shares = compute_shares(people, amount, split_mode, inputs)
        return cls(
            tuple(people),
            amount,
            shares,
            item_name.strip(),
            quantity_info.strip(),
            price_text.strip(),
            split_mode,
            inputs,
        )

    def apply_split(
        self,
        people: list[str],
        amount: float,
        split_mode: str = SPLIT_MODE_EQUAL,
        split_inputs: dict[str, float] | None = None,
    ) -> None:
        inputs = dict(split_inputs or {})
        self.people = tuple(people)
        self.amount = amount
        self.split_mode = split_mode
        self.split_inputs = inputs
        self.shares = compute_shares(people, amount, split_mode, inputs)

    def set_total_amount(self, amount: float) -> None:
        self.apply_split(list(self.people), amount, self.split_mode, self.split_inputs)

    def set_single_person_amount(self, name: str, amount: float) -> None:
        self.apply_split([name], amount, SPLIT_MODE_EQUAL, {})

    def display_detail(self) -> str:
        name = self.item_name or "手动记录"
        if self.quantity_info:
            return f"{name} | {self.quantity_info}"
        return name

    def split_mode_label(self) -> str:
        return SPLIT_MODE_LABELS.get(self.split_mode, SPLIT_MODE_LABELS[SPLIT_MODE_EQUAL])


class ShoppingCalculator:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("购物金额计算器")
        self.center_window(self.root, 1120, 620)

        self.amount = tk.StringVar()
        self.split_mode_label = tk.StringVar(value=SPLIT_MODE_LABELS[SPLIT_MODE_EQUAL])
        self.total_records_text = tk.StringVar(value="查看总记录：0.00")
        self.discount_button_text = tk.StringVar(value="9折：关闭")
        self.monthly_discount_enabled = False

        self.people = list(DEFAULT_PEOPLE)
        self.selected = {name: False for name in self.people}
        self.totals = {name: 0.0 for name in self.people}
        self.entries: list[ExpenseEntry] = []

        self.person_widgets: dict[str, dict[str, tk.Widget]] = {}
        self.person_listboxes: dict[str, tk.Listbox] = {}
        self.person_row_entries: dict[str, list[int]] = {}
        self.listbox_to_name: dict[tk.Listbox, str] = {}
        self.general_records_window: tk.Toplevel | None = None
        self.general_records_listbox: tk.Listbox | None = None
        self.invoice_import_window: tk.Toplevel | None = None
        self.browser_session: BuiltInBrowserSession | None = None

        self.default_button_bg = None

        self.create_menu()
        self.create_widgets()
        self.refresh_all()

    @staticmethod
    def center_window(window: tk.Misc, width: int, height: int) -> None:
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = max((screen_width - width) // 2, 0)
        y = max((screen_height - height) // 2, 0)
        window.geometry(f"{width}x{height}+{x}+{y}")

    @staticmethod
    def parse_amount(value: str) -> float:
        value = value.strip().replace(",", "")
        if not value:
            raise ValueError("请输入金额")

        try:
            amount = float(value)
        except ValueError as exc:
            raise ValueError("金额必须是数字") from exc

        if not math.isfinite(amount):
            raise ValueError("金额必须是有效数字")
        return amount

    @staticmethod
    def format_amount(amount: float, signed: bool = False) -> str:
        if signed and amount > 0:
            return f"+{amount:.2f}"
        return f"{amount:.2f}"

    def current_split_mode(self) -> str:
        return LABEL_TO_SPLIT_MODE.get(self.split_mode_label.get(), SPLIT_MODE_EQUAL)

    def create_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=0)
        self.root.config(menu=menu)

        tools_menu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="工具", menu=tools_menu)
        tools_menu.add_command(label="识别小票图片…", command=self.open_receipt_image_ocr)
        tools_menu.add_command(label="导入发票 JSON…", command=self.show_invoice_importer)
        tools_menu.add_command(label="内置浏览器", command=self.open_builtin_browser)
        tools_menu.add_command(label="复制提取代码", command=self.copy_invoice_extractor_to_clipboard)
        tools_menu.add_separator()
        tools_menu.add_command(label="退出", command=self.root.quit)

        edit_menu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="编辑", menu=edit_menu)
        edit_menu.add_command(label="用户编辑", command=self.show_user_editor)

    def create_widgets(self) -> None:
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        top_frame = tk.Frame(self.root, padx=12, pady=10)
        top_frame.grid(row=0, column=0, sticky="ew")

        tk.Label(top_frame, text="请输入金额:").pack(side=tk.LEFT, padx=(0, 4))
        amount_entry = tk.Entry(top_frame, textvariable=self.amount, width=12)
        amount_entry.pack(side=tk.LEFT, padx=(0, 8))
        amount_entry.bind("<Return>", lambda _event: self.add_entry())

        tk.Label(top_frame, text="分摊:").pack(side=tk.LEFT, padx=(4, 2))
        split_menu = tk.OptionMenu(
            top_frame,
            self.split_mode_label,
            *[SPLIT_MODE_LABELS[mode] for mode in (
                SPLIT_MODE_EQUAL,
                SPLIT_MODE_QUANTITY,
                SPLIT_MODE_EXACT,
                SPLIT_MODE_PERCENTAGE,
            )],
        )
        split_menu.config(width=8)
        split_menu.pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(top_frame, text="添加", width=8, command=self.add_entry).pack(side=tk.LEFT, padx=4)
        tk.Button(
            top_frame,
            text="内置浏览器",
            width=10,
            command=self.open_builtin_browser,
            bg="#1565c0",
            fg="white",
        ).pack(side=tk.LEFT, padx=4)
        self.discount_button = tk.Button(
            top_frame,
            textvariable=self.discount_button_text,
            width=11,
            command=self.toggle_monthly_discount,
        )
        self.discount_button.pack(side=tk.LEFT, padx=4)
        self.discount_button_default_bg = self.discount_button.cget("bg")
        tk.Button(
            top_frame,
            textvariable=self.total_records_text,
            width=16,
            command=self.show_general_records,
        ).pack(side=tk.LEFT, padx=24)
        tk.Button(top_frame, text="全选/取消", width=10, command=self.toggle_all_people).pack(side=tk.LEFT, padx=4)
        tk.Button(top_frame, text="复制结果", width=10, command=self.copy_totals_to_clipboard).pack(side=tk.LEFT, padx=4)
        tk.Button(top_frame, text="复制明细", width=10, command=self.copy_details_to_clipboard).pack(side=tk.LEFT, padx=4)

        self.people_frame = tk.Frame(self.root, padx=12, pady=8)
        self.people_frame.grid(row=1, column=0, sticky="nsew")

    def refresh_all(self) -> None:
        self.recalculate_totals()
        self.refresh_total_button()
        self.refresh_people_layout()
        self.refresh_general_records()

    def recalculate_totals(self) -> None:
        self.totals = {name: 0.0 for name in self.people}
        for entry in self.entries:
            for name, share in entry.shares.items():
                if name in self.totals:
                    self.totals[name] += self.effective_amount(share)

    def refresh_total_button(self) -> None:
        total = sum(self.totals.values())
        self.total_records_text.set(f"查看总记录：{total:.2f}")

    def effective_amount(self, amount: float) -> float:
        """Displayed/payable value; source entries always retain their original amounts."""
        factor = MONTHLY_DISCOUNT_FACTOR if self.monthly_discount_enabled else 1.0
        return round(amount * factor, 2)

    def toggle_monthly_discount(self) -> None:
        self.monthly_discount_enabled = not self.monthly_discount_enabled
        if self.monthly_discount_enabled:
            self.discount_button_text.set("9折：已开启")
            self.discount_button.config(bg="#2e7d32", fg="white")
        else:
            self.discount_button_text.set("9折：关闭")
            self.discount_button.config(bg=self.discount_button_default_bg, fg="black")
        self.refresh_all()

    def refresh_people_layout(self) -> None:
        for child in self.people_frame.winfo_children():
            child.destroy()

        self.person_widgets.clear()
        self.person_listboxes.clear()
        self.person_row_entries.clear()
        self.listbox_to_name.clear()

        for index, name in enumerate(self.people):
            self.people_frame.grid_columnconfigure(index, weight=1, uniform="person")
            self.create_person_column(name, index)

    def create_person_column(self, name: str, column: int) -> None:
        frame = tk.Frame(self.people_frame, padx=8, pady=6, relief=tk.GROOVE, borderwidth=1)
        frame.grid(row=0, column=column, padx=6, pady=4, sticky="nsew")
        frame.grid_rowconfigure(2, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        button = tk.Button(frame, text=name, command=lambda person=name: self.toggle_person(person))
        button.grid(row=0, column=0, sticky="ew")
        if self.default_button_bg is None:
            self.default_button_bg = button.cget("bg")

        label = tk.Label(frame, anchor="w")
        label.grid(row=1, column=0, pady=(8, 4), sticky="ew")

        list_frame = tk.Frame(frame)
        list_frame.grid(row=2, column=0, sticky="nsew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        listbox = tk.Listbox(list_frame, height=20, activestyle="dotbox")
        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        listbox.bind("<Double-Button-1>", self.edit_individual_entry)

        self.person_widgets[name] = {"button": button, "label": label, "frame": frame}
        self.person_listboxes[name] = listbox
        self.listbox_to_name[listbox] = name

        self.refresh_person(name)

    def refresh_person(self, name: str) -> None:
        widgets = self.person_widgets[name]
        button = widgets["button"]
        label = widgets["label"]
        listbox = self.person_listboxes[name]

        button.config(bg=SELECTED_COLOR if self.selected[name] else self.default_button_bg)
        label.config(text=f"{name}: {self.totals.get(name, 0.0):.2f}")

        listbox.delete(0, tk.END)
        row_entries: list[int] = []
        for entry_index, entry in enumerate(self.entries):
            if name not in entry.shares:
                continue
            amount = self.effective_amount(entry.shares[name])
            listbox.insert(tk.END, f"{self.format_amount(amount, signed=True)}  {entry.display_detail()}")
            row_entries.append(entry_index)
        self.person_row_entries[name] = row_entries

    def add_entry(self) -> None:
        try:
            amount = self.parse_amount(self.amount.get())
            selected_people = [name for name, selected in self.selected.items() if selected]
            if not selected_people:
                raise ValueError("至少选择一个人")

            mode = self.current_split_mode()
            split_inputs: dict[str, float] = {}
            if mode != SPLIT_MODE_EQUAL:
                collected = self.prompt_split_inputs(
                    parent=self.root,
                    people=selected_people,
                    amount=amount,
                    mode=mode,
                )
                if collected is None:
                    return
                split_inputs = collected

            self.entries.append(
                ExpenseEntry.create(
                    selected_people,
                    amount,
                    split_mode=mode,
                    split_inputs=split_inputs,
                )
            )
            self.amount.set("")
            self.clear_selection()
            self.refresh_all()
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))

    def prompt_split_inputs(
        self,
        parent: tk.Misc,
        people: list[str],
        amount: float,
        mode: str,
        initial_inputs: dict[str, float] | None = None,
    ) -> dict[str, float] | None:
        """Modal dialog collecting per-person quantity / exact / percentage inputs."""
        if mode == SPLIT_MODE_EQUAL:
            return {}

        initial_inputs = dict(initial_inputs or {})
        result: dict[str, float] | None = None

        dialog = tk.Toplevel(parent)
        title_map = {
            SPLIT_MODE_QUANTITY: "按数量分摊",
            SPLIT_MODE_EXACT: "精确金额分摊",
            SPLIT_MODE_PERCENTAGE: "百分比分摊",
        }
        dialog.title(title_map.get(mode, "分摊输入"))
        self.center_window(dialog, 320, 80 + 36 * len(people))
        dialog.transient(parent)
        dialog.grab_set()

        hint_map = {
            SPLIT_MODE_QUANTITY: f"总额 {amount:.2f}：请输入每人数量（正数）",
            SPLIT_MODE_EXACT: f"总额 {amount:.2f}：每人金额合计须等于总额",
            SPLIT_MODE_PERCENTAGE: f"总额 {amount:.2f}：百分比合计须为 100%",
        }
        tk.Label(dialog, text=hint_map.get(mode, ""), wraplength=280, justify=tk.LEFT).pack(
            padx=12, pady=(12, 6), anchor="w"
        )

        vars_by_person: dict[str, tk.StringVar] = {}
        form = tk.Frame(dialog, padx=12)
        form.pack(fill=tk.BOTH, expand=True)

        unit = {"quantity": "", "exact": "$", "percentage": "%"}[mode]
        for row_index, person in enumerate(people):
            tk.Label(form, text=f"{person}:", width=10, anchor="w").grid(row=row_index, column=0, sticky="w", pady=3)
            default_value = ""
            if person in initial_inputs:
                value = initial_inputs[person]
                default_value = f"{value:.4g}" if mode == SPLIT_MODE_QUANTITY else f"{value:.2f}"
            elif mode == SPLIT_MODE_PERCENTAGE and people:
                default_value = f"{100.0 / len(people):.2f}"
            elif mode == SPLIT_MODE_EXACT and people:
                default_value = f"{amount / len(people):.2f}"
            elif mode == SPLIT_MODE_QUANTITY:
                default_value = "1"
            var = tk.StringVar(value=default_value)
            vars_by_person[person] = var
            entry = tk.Entry(form, textvariable=var, width=12)
            entry.grid(row=row_index, column=1, sticky="w", pady=3)
            if unit:
                tk.Label(form, text=unit).grid(row=row_index, column=2, sticky="w", padx=(4, 0))
            if row_index == 0:
                entry.focus_set()
                entry.select_range(0, tk.END)

        def confirm() -> None:
            nonlocal result
            try:
                collected: dict[str, float] = {}
                for person, var in vars_by_person.items():
                    collected[person] = self.parse_amount(var.get())
                # Validate by computing shares.
                compute_shares(people, amount, mode, collected)
                result = collected
                dialog.destroy()
            except ValueError as exc:
                messagebox.showerror("错误", str(exc), parent=dialog)

        def cancel() -> None:
            nonlocal result
            result = None
            dialog.destroy()

        button_frame = tk.Frame(dialog, padx=12, pady=12)
        button_frame.pack(fill=tk.X)
        tk.Button(button_frame, text="确定", width=10, command=confirm).pack(side=tk.RIGHT, padx=(8, 0))
        tk.Button(button_frame, text="取消", width=10, command=cancel).pack(side=tk.RIGHT)
        dialog.bind("<Return>", lambda _event: confirm())
        dialog.bind("<Escape>", lambda _event: cancel())
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.wait_window()
        return result

    def toggle_person(self, name: str) -> None:
        self.selected[name] = not self.selected[name]
        self.refresh_person(name)

    def toggle_all_people(self) -> None:
        new_status = not all(self.selected.values())
        for name in self.selected:
            self.selected[name] = new_status
        for name in self.people:
            self.refresh_person(name)

    def clear_selection(self) -> None:
        for name in self.selected:
            self.selected[name] = False

    def show_general_records(self) -> None:
        if not self.entries:
            messagebox.showinfo("信息", "没有记录可供显示。")
            return

        if self.general_records_window and self.general_records_window.winfo_exists():
            self.general_records_window.lift()
            self.general_records_window.focus_force()
            self.refresh_general_records()
            return

        records_win = tk.Toplevel(self.root)
        records_win.title("总记录")
        self.center_window(records_win, 420, 460)
        records_win.transient(self.root)
        records_win.protocol("WM_DELETE_WINDOW", self.close_general_records)

        frame = tk.Frame(records_win, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        listbox = tk.Listbox(frame, activestyle="dotbox")
        scrollbar = tk.Scrollbar(frame, orient=tk.VERTICAL, command=listbox.yview)
        listbox.configure(yscrollcommand=scrollbar.set)
        listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        listbox.bind("<Double-Button-1>", self.edit_entry)
        listbox.bind("<Delete>", lambda _event: self.delete_selected_general_record())
        listbox.bind("<BackSpace>", lambda _event: self.delete_selected_general_record())

        button_frame = tk.Frame(frame)
        button_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        tk.Button(button_frame, text="删除选中", width=12, command=self.delete_selected_general_record).pack(
            side=tk.LEFT
        )
        tk.Button(button_frame, text="关闭", width=8, command=self.close_general_records).pack(side=tk.RIGHT)

        self.general_records_window = records_win
        self.general_records_listbox = listbox
        self.refresh_general_records()

    def close_general_records(self) -> None:
        if self.general_records_window and self.general_records_window.winfo_exists():
            self.general_records_window.destroy()
        self.general_records_window = None
        self.general_records_listbox = None

    def refresh_general_records(self) -> None:
        if not self.general_records_listbox or not self.general_records_listbox.winfo_exists():
            return

        self.general_records_listbox.delete(0, tk.END)
        for entry in self.entries:
            people = ", ".join(entry.people)
            mode_label = entry.split_mode_label()
            amount = sum(self.effective_amount(share) for share in entry.shares.values())
            self.general_records_listbox.insert(
                tk.END,
                f"{entry.display_detail()} | {people} [{mode_label}]: {amount:.2f}",
            )

        if not self.entries and self.general_records_window and self.general_records_window.winfo_exists():
            self.close_general_records()

    def delete_selected_general_record(self) -> None:
        if not self.general_records_listbox or not self.general_records_listbox.winfo_exists():
            return
        selection = self.general_records_listbox.curselection()
        if not selection:
            messagebox.showinfo("信息", "请先选择一条记录。", parent=self.general_records_window)
            return
        self.delete_entry_at(selection[0], parent=self.general_records_window)

    def delete_entry_at(self, entry_index: int, parent: tk.Misc | None = None) -> bool:
        if entry_index < 0 or entry_index >= len(self.entries):
            return False
        entry = self.entries[entry_index]
        confirmed = messagebox.askyesno(
            "确认删除",
            f"确定删除这条记录吗？\n{entry.display_detail()} | {entry.amount:.2f}",
            parent=parent or self.root,
        )
        if not confirmed:
            return False
        del self.entries[entry_index]
        self.refresh_all()
        return True

    def edit_entry(self, event: tk.Event) -> None:
        selection = event.widget.curselection()
        if not selection:
            return

        entry_index = selection[0]
        if entry_index >= len(self.entries):
            return
        self.show_entry_editor(entry_index)

    def edit_individual_entry(self, event: tk.Event) -> None:
        selection = event.widget.curselection()
        if not selection:
            return

        name = self.listbox_to_name[event.widget]
        row_index = selection[0]
        row_entries = self.person_row_entries.get(name, [])
        if row_index >= len(row_entries):
            return

        entry_index = row_entries[row_index]
        self.show_entry_editor(entry_index)

    def show_entry_editor(self, entry_index: int) -> None:
        if entry_index < 0 or entry_index >= len(self.entries):
            return

        entry = self.entries[entry_index]
        edit_win = tk.Toplevel(self.root)
        edit_win.title("编辑记录")
        self.center_window(edit_win, 420, 460)
        edit_win.transient(self.root)
        edit_win.grab_set()

        amount_var = tk.StringVar(value=f"{entry.amount:.2f}")
        mode_label_var = tk.StringVar(value=entry.split_mode_label())
        selected_people = {name: (name in entry.people) for name in self.people}
        person_buttons: dict[str, tk.Button] = {}
        # Mutable holder for latest split inputs (updated when mode dialog confirms).
        split_inputs_holder: dict[str, float] = dict(entry.split_inputs)

        main_frame = tk.Frame(edit_win, padx=14, pady=14)
        main_frame.pack(fill=tk.BOTH, expand=True)

        detail = entry.display_detail()
        tk.Label(main_frame, text=detail, wraplength=380, justify=tk.LEFT, anchor="w").pack(fill=tk.X, pady=(0, 8))

        amount_row = tk.Frame(main_frame)
        amount_row.pack(fill=tk.X, pady=4)
        tk.Label(amount_row, text="总金额:").pack(side=tk.LEFT)
        amount_entry = tk.Entry(amount_row, textvariable=amount_var, width=14)
        amount_entry.pack(side=tk.LEFT, padx=8)
        amount_entry.focus_set()
        amount_entry.select_range(0, tk.END)

        mode_row = tk.Frame(main_frame)
        mode_row.pack(fill=tk.X, pady=4)
        tk.Label(mode_row, text="分摊方式:").pack(side=tk.LEFT)
        tk.OptionMenu(
            mode_row,
            mode_label_var,
            *[SPLIT_MODE_LABELS[mode] for mode in (
                SPLIT_MODE_EQUAL,
                SPLIT_MODE_QUANTITY,
                SPLIT_MODE_EXACT,
                SPLIT_MODE_PERCENTAGE,
            )],
        ).pack(side=tk.LEFT, padx=8)

        people_frame = tk.LabelFrame(main_frame, text="参与分摊的人", padx=10, pady=10)
        people_frame.pack(fill=tk.X, pady=(10, 8))
        for column in range(4):
            people_frame.grid_columnconfigure(column, weight=1)

        def refresh_person_buttons() -> None:
            for person, button in person_buttons.items():
                button.config(bg=SELECTED_COLOR if selected_people.get(person) else self.default_button_bg)

        def toggle_edit_person(person: str) -> None:
            selected_people[person] = not selected_people[person]
            refresh_person_buttons()

        for index, person in enumerate(self.people):
            button = tk.Button(
                people_frame,
                text=person,
                command=lambda name=person: toggle_edit_person(name),
            )
            button.grid(row=index // 4, column=index % 4, sticky="ew", padx=4, pady=4)
            person_buttons[person] = button
        refresh_person_buttons()

        def collect_people() -> list[str]:
            return [name for name in self.people if selected_people.get(name)]

        def current_mode() -> str:
            return LABEL_TO_SPLIT_MODE.get(mode_label_var.get(), SPLIT_MODE_EQUAL)

        def edit_split_inputs() -> None:
            try:
                amount = self.parse_amount(amount_var.get())
            except ValueError as exc:
                messagebox.showerror("错误", str(exc), parent=edit_win)
                return
            people = collect_people()
            if not people:
                messagebox.showerror("错误", "至少选择一个人", parent=edit_win)
                return
            mode = current_mode()
            if mode == SPLIT_MODE_EQUAL:
                messagebox.showinfo("信息", "平均分摊无需额外输入。", parent=edit_win)
                return
            relevant = {name: split_inputs_holder[name] for name in people if name in split_inputs_holder}
            collected = self.prompt_split_inputs(
                parent=edit_win,
                people=people,
                amount=amount,
                mode=mode,
                initial_inputs=relevant,
            )
            if collected is not None:
                split_inputs_holder.clear()
                split_inputs_holder.update(collected)

        tk.Button(main_frame, text="编辑分摊明细…", command=edit_split_inputs).pack(anchor="w", pady=(0, 8))

        def save_changes() -> None:
            try:
                amount = self.parse_amount(amount_var.get())
                people = collect_people()
                if not people:
                    raise ValueError("至少选择一个人")
                mode = current_mode()
                inputs = {name: split_inputs_holder[name] for name in people if name in split_inputs_holder}
                if mode != SPLIT_MODE_EQUAL:
                    # If inputs incomplete for current people/mode, prompt now.
                    if set(inputs.keys()) != set(people):
                        collected = self.prompt_split_inputs(
                            parent=edit_win,
                            people=people,
                            amount=amount,
                            mode=mode,
                            initial_inputs=inputs,
                        )
                        if collected is None:
                            return
                        inputs = collected
                    else:
                        # Re-validate; if invalid, re-prompt.
                        try:
                            compute_shares(people, amount, mode, inputs)
                        except ValueError:
                            collected = self.prompt_split_inputs(
                                parent=edit_win,
                                people=people,
                                amount=amount,
                                mode=mode,
                                initial_inputs=inputs,
                            )
                            if collected is None:
                                return
                            inputs = collected
                else:
                    inputs = {}

                self.entries[entry_index].apply_split(people, amount, mode, inputs)
                self.refresh_all()
                edit_win.destroy()
            except ValueError as exc:
                messagebox.showerror("错误", str(exc), parent=edit_win)

        def delete_and_close() -> None:
            if self.delete_entry_at(entry_index, parent=edit_win):
                edit_win.destroy()

        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(16, 0))
        tk.Button(button_frame, text="删除", width=10, command=delete_and_close).pack(side=tk.LEFT)
        tk.Button(button_frame, text="取消", width=10, command=edit_win.destroy).pack(side=tk.RIGHT, padx=(8, 0))
        tk.Button(button_frame, text="保存", width=10, command=save_changes).pack(side=tk.RIGHT)
        amount_entry.bind("<Return>", lambda _event: save_changes())

    def open_receipt_image_ocr(self) -> None:
        """Primary CTA: pick a receipt image and run local EasyOCR in a worker thread."""
        try:
            import receipt_ocr
        except ImportError:
            messagebox.showerror(
                "缺少模块",
                "找不到 receipt_ocr.py，请确认它与 shopping_calculator.py 在同一目录。",
                parent=self.root,
            )
            return

        if not receipt_ocr.easyocr_available():
            messagebox.showwarning("需要安装 OCR 依赖", receipt_ocr.install_hint(), parent=self.root)
            return

        file_path = filedialog.askopenfilename(
            parent=self.root,
            title="选择小票图片",
            filetypes=[
                ("图片文件", "*.png *.jpg *.jpeg *.webp *.bmp *.PNG *.JPG *.JPEG *.WEBP *.BMP"),
                ("所有文件", "*.*"),
            ],
        )
        if not file_path:
            return

        progress = tk.Toplevel(self.root)
        progress.title("识别中")
        self.center_window(progress, 420, 140)
        progress.transient(self.root)
        progress.grab_set()
        progress.resizable(False, False)
        status_var = tk.StringVar(value="准备识别…")
        tip = receipt_ocr.first_run_model_note()
        tk.Label(progress, textvariable=status_var, wraplength=380, justify=tk.LEFT).pack(
            padx=16, pady=(16, 8), anchor="w"
        )
        tk.Label(progress, text=tip, wraplength=380, justify=tk.LEFT, fg="#555555").pack(
            padx=16, pady=(0, 12), anchor="w"
        )
        progress.update_idletasks()

        def set_status(msg: str) -> None:
            self.root.after(0, lambda: status_var.set(msg))

        def finish_ok(rows: list) -> None:
            try:
                if progress.winfo_exists():
                    progress.grab_release()
                    progress.destroy()
            except tk.TclError:
                pass
            if not rows:
                messagebox.showinfo(
                    "信息",
                    "没有识别到可导入的商品。可尝试更清晰的照片，或改用「导入 JSON」。",
                    parent=self.root,
                )
                return
            self.show_invoice_allocator(rows, self.root)

        def finish_err(exc: BaseException) -> None:
            try:
                if progress.winfo_exists():
                    progress.grab_release()
                    progress.destroy()
            except tk.TclError:
                pass
            if isinstance(exc, receipt_ocr.OcrUnavailableError):
                messagebox.showwarning("需要安装 OCR 依赖", str(exc), parent=self.root)
            elif isinstance(exc, receipt_ocr.OcrParseError):
                messagebox.showerror("识别失败", str(exc), parent=self.root)
            else:
                messagebox.showerror(
                    "识别失败",
                    f"处理小票图片时出错：\n{exc}\n\n"
                    "请确认已执行：pip install -r requirements-ocr.txt\n"
                    "或改用菜单中的「导入发票 JSON」。",
                    parent=self.root,
                )

        def worker() -> None:
            try:
                rows = receipt_ocr.ocr_image_to_rows(file_path, status_callback=set_status)
                self.root.after(0, lambda: finish_ok(rows))
            except BaseException as exc:  # noqa: BLE001 — marshal any failure back to UI
                self.root.after(0, lambda e=exc: finish_err(e))

        threading.Thread(target=worker, daemon=True).start()

    def show_invoice_importer(self) -> None:
        if self.invoice_import_window and self.invoice_import_window.winfo_exists():
            self.invoice_import_window.lift()
            self.invoice_import_window.focus_force()
            return

        import_win = tk.Toplevel(self.root)
        import_win.title("导入发票 JSON")
        self.center_window(import_win, 720, 520)
        import_win.transient(self.root)
        import_win.protocol("WM_DELETE_WINDOW", self.close_invoice_importer)

        main_frame = tk.Frame(import_win, padx=12, pady=12)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.grid_rowconfigure(1, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        tk.Label(
            main_frame,
            text="粘贴网页脚本复制出来的 JSON 数组，然后开始逐个商品分配。",
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 8))

        json_text = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, height=20)
        json_text.grid(row=1, column=0, sticky="nsew")

        button_frame = tk.Frame(main_frame)
        button_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        def paste_clipboard() -> None:
            try:
                clipboard_text = self.root.clipboard_get()
            except tk.TclError:
                messagebox.showerror("错误", "剪贴板里没有可读取的文本。", parent=import_win)
                return

            json_text.delete("1.0", tk.END)
            json_text.insert("1.0", clipboard_text)

        def start_allocation() -> None:
            try:
                invoice_rows = self.parse_invoice_json(json_text.get("1.0", tk.END))
            except ValueError as exc:
                messagebox.showerror("错误", str(exc), parent=import_win)
                return

            if not invoice_rows:
                messagebox.showinfo("信息", "没有可导入的商品。", parent=import_win)
                return

            self.show_invoice_allocator(invoice_rows, import_win)

        tk.Button(button_frame, text="从剪贴板粘贴", width=14, command=paste_clipboard).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(button_frame, text="复制提取代码", width=12, command=self.copy_invoice_extractor_to_clipboard).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text="清空", width=8, command=lambda: json_text.delete("1.0", tk.END)).pack(side=tk.LEFT, padx=4)
        tk.Button(button_frame, text="开始分配", width=12, command=start_allocation).pack(side=tk.RIGHT, padx=(8, 0))
        tk.Button(button_frame, text="关闭", width=8, command=self.close_invoice_importer).pack(side=tk.RIGHT, padx=4)

        self.invoice_import_window = import_win
        try:
            clipboard_text = self.root.clipboard_get().strip()
        except tk.TclError:
            clipboard_text = ""
        if clipboard_text.startswith("["):
            json_text.insert("1.0", clipboard_text)

        json_text.focus_set()

    def close_invoice_importer(self) -> None:
        if self.invoice_import_window and self.invoice_import_window.winfo_exists():
            self.invoice_import_window.destroy()
        self.invoice_import_window = None

    def parse_invoice_json(self, raw_text: str) -> list[dict[str, object]]:
        raw_text = raw_text.strip()
        if not raw_text:
            raise ValueError("请先粘贴发票 JSON。")

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 格式不正确：第 {exc.lineno} 行，第 {exc.colno} 列。") from exc

        if isinstance(data, dict):
            data = data.get("rows") or data.get("items")
        if not isinstance(data, list):
            raise ValueError("JSON 顶层必须是数组，或包含 rows/items 数组。")

        invoice_rows: list[dict[str, object]] = []
        for index, row in enumerate(data, start=1):
            if not isinstance(row, dict):
                raise ValueError(f"第 {index} 条不是商品对象。")

            item_name = str(row.get("item") or row.get("name") or "").strip()
            quantity_info = str(row.get("quantityInfo") or row.get("quantity_info") or "").strip()
            price_text = str(row.get("priceText") or row.get("price_text") or "").strip()
            amount = self.parse_imported_price(row.get("price"), price_text)
            if self.is_monthly_discount_row(item_name):
                # The main-page 9折 toggle applies this offer per person. Do not
                # import the receipt's aggregate discount as a second entry.
                continue
            is_discount = self.is_discount_invoice_row(item_name, quantity_info, amount)
            if is_discount:
                amount = -abs(amount)

            invoice_rows.append(
                {
                    "item": item_name or f"商品 {index}",
                    "quantity_info": quantity_info,
                    "price": amount,
                    "price_text": price_text,
                    "is_discount": is_discount,
                }
            )

        return invoice_rows

    @staticmethod
    def is_monthly_discount_row(item_name: str) -> bool:
        text = " ".join(item_name.upper().split())
        return "WOW 10% OFFER" in text or "WOOLWORTHS 10% OFFER" in text

    @staticmethod
    def is_discount_invoice_row(item_name: str, quantity_info: str, amount: float) -> bool:
        text = item_name.strip().casefold()
        discount_label = (
            text.startswith("buy ")
            or text.startswith("save ")
            or "discount" in text
            or "coupon" in text
            or "promotion" in text
        )
        return amount < 0 or (discount_label and not quantity_info.strip())

    def parse_imported_price(self, price_value: object, price_text: str) -> float:
        source = price_text.strip() if price_text.strip() else price_value

        if isinstance(source, (int, float)):
            amount = float(source)
        else:
            price_string = str(source).strip().replace("−", "-").replace("–", "-")
            is_negative = "-" in price_string or (price_string.startswith("(") and price_string.endswith(")"))
            cleaned = "".join(char for char in price_string if char.isdigit() or char == ".")
            amount = self.parse_amount(cleaned)
            if is_negative:
                amount = -abs(amount)

        if not math.isfinite(amount):
            raise ValueError("商品金额必须是有效数字。")
        return amount

    def show_invoice_allocator(self, invoice_rows: list[dict[str, object]], parent: tk.Misc) -> None:
        allocator_win = tk.Toplevel(self.root)
        allocator_win.title("分配发票商品")
        self.center_window(allocator_win, 580, 520)
        allocator_win.transient(parent)
        allocator_win.grab_set()

        current_index = 0
        imported_count = 0
        selected_people = {name: False for name in self.people}
        person_buttons: dict[str, tk.Button] = {}
        split_mode_label_var = tk.StringVar(value=SPLIT_MODE_LABELS[SPLIT_MODE_EQUAL])

        # Per-row UI state: people selection + split mode + inputs.
        row_state: dict[int, dict[str, object]] = {}
        # Entries created/updated by this allocator session for undo.
        undo_stack: list[tuple[ExpenseEntry, int]] = []
        # invoice row index -> ExpenseEntry currently associated
        allocated_rows: dict[int, ExpenseEntry] = {}

        status_var = tk.StringVar()
        item_var = tk.StringVar()
        quantity_var = tk.StringVar()
        price_var = tk.StringVar()

        main_frame = tk.Frame(allocator_win, padx=16, pady=16)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.grid_columnconfigure(0, weight=1)

        tk.Label(main_frame, textvariable=status_var, anchor="w").grid(row=0, column=0, sticky="ew")
        tk.Label(main_frame, textvariable=item_var, anchor="w", justify=tk.LEFT, wraplength=530, font=("TkDefaultFont", 12, "bold")).grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(8, 4),
        )
        tk.Label(main_frame, textvariable=quantity_var, anchor="w", justify=tk.LEFT, wraplength=530).grid(row=2, column=0, sticky="ew")
        tk.Label(main_frame, textvariable=price_var, anchor="w").grid(row=3, column=0, sticky="ew", pady=(4, 8))

        split_frame = tk.Frame(main_frame)
        split_frame.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        tk.Label(split_frame, text="分摊方式:").pack(side=tk.LEFT)
        tk.OptionMenu(
            split_frame,
            split_mode_label_var,
            *[SPLIT_MODE_LABELS[mode] for mode in (
                SPLIT_MODE_EQUAL,
                SPLIT_MODE_QUANTITY,
                SPLIT_MODE_EXACT,
                SPLIT_MODE_PERCENTAGE,
            )],
        ).pack(side=tk.LEFT, padx=8)

        people_frame = tk.LabelFrame(main_frame, text="分配给", padx=10, pady=10)
        people_frame.grid(row=5, column=0, sticky="ew")
        for column in range(4):
            people_frame.grid_columnconfigure(column, weight=1)

        action_frame = tk.Frame(main_frame)
        action_frame.grid(row=6, column=0, sticky="ew", pady=(12, 0))

        bottom_frame = tk.Frame(main_frame)
        bottom_frame.grid(row=7, column=0, sticky="ew", pady=(18, 0))

        prev_button: tk.Button
        undo_button: tk.Button

        def current_row() -> dict[str, object]:
            return invoice_rows[current_index]

        def current_mode() -> str:
            return LABEL_TO_SPLIT_MODE.get(split_mode_label_var.get(), SPLIT_MODE_EQUAL)

        def refresh_person_buttons() -> None:
            for person, button in person_buttons.items():
                button.config(bg=SELECTED_COLOR if selected_people.get(person) else self.default_button_bg)

        def toggle_allocator_person(person: str) -> None:
            selected_people[person] = not selected_people[person]
            refresh_person_buttons()

        for index, person in enumerate(self.people):
            button = tk.Button(
                people_frame,
                text=person,
                command=lambda name=person: toggle_allocator_person(name),
            )
            button.grid(row=index // 4, column=index % 4, sticky="ew", padx=4, pady=4)
            person_buttons[person] = button

        def save_current_row_state() -> None:
            previous = row_state.get(current_index, {})
            previous_inputs = previous.get("split_inputs", {}) if isinstance(previous, dict) else {}
            if not isinstance(previous_inputs, dict):
                previous_inputs = {}
            row_state[current_index] = {
                "selected": {name: bool(selected_people.get(name)) for name in self.people},
                "mode_label": split_mode_label_var.get(),
                "split_inputs": dict(previous_inputs),
            }

        def restore_row_state(index: int) -> None:
            state = row_state.get(index)
            for name in selected_people:
                selected_people[name] = False
            if state:
                saved_selected = state.get("selected", {})
                if isinstance(saved_selected, dict):
                    for name in selected_people:
                        selected_people[name] = bool(saved_selected.get(name, False))
                mode_label = state.get("mode_label")
                if isinstance(mode_label, str) and mode_label in LABEL_TO_SPLIT_MODE:
                    split_mode_label_var.set(mode_label)
                else:
                    split_mode_label_var.set(SPLIT_MODE_LABELS[SPLIT_MODE_EQUAL])
            else:
                split_mode_label_var.set(SPLIT_MODE_LABELS[SPLIT_MODE_EQUAL])
            refresh_person_buttons()

        def update_nav_buttons() -> None:
            if current_index <= 0:
                prev_button.config(state=tk.DISABLED)
            else:
                prev_button.config(state=tk.NORMAL)
            undo_button.config(state=tk.NORMAL if undo_stack else tk.DISABLED)

        def refresh_item() -> None:
            row = current_row()
            is_discount = bool(row.get("is_discount"))
            allocated_note = "（已分配，再次添加将覆盖）" if current_index in allocated_rows else ""
            status_var.set(f"第 {current_index + 1} / {len(invoice_rows)} 个商品{allocated_note}")
            item_name = str(row["item"])
            item_var.set(f"折扣：{item_name}" if is_discount and not item_name.startswith("折扣") else item_name)
            quantity = str(row.get("quantity_info") or "")
            if is_discount:
                discount_note = "折扣行：请分配给享受该促销的人"
                quantity_var.set(f"{discount_note}；数量信息：{quantity}" if quantity else discount_note)
            else:
                quantity_var.set(f"数量信息：{quantity}" if quantity else "数量信息：无")

            price = float(row["price"])
            price_text = str(row.get("price_text") or "")
            price_var.set(f"金额：{price:.2f}" + (f"（原文：{price_text}）" if price_text else ""))
            refresh_person_buttons()
            update_nav_buttons()

        def set_all_people() -> None:
            new_status = not all(selected_people.values())
            for person in selected_people:
                selected_people[person] = new_status
            refresh_person_buttons()

        def clear_allocator_selection() -> None:
            for person in selected_people:
                selected_people[person] = False
            refresh_person_buttons()

        def finish_if_done() -> bool:
            nonlocal current_index
            if current_index < len(invoice_rows) - 1:
                return False

            self.refresh_all()
            messagebox.showinfo("完成", f"发票分配完成，已导入 {imported_count} 条记录。", parent=allocator_win)
            allocator_win.destroy()
            self.close_invoice_importer()
            return True

        def go_next() -> None:
            nonlocal current_index
            if finish_if_done():
                return
            save_current_row_state()
            current_index += 1
            restore_row_state(current_index)
            refresh_item()

        def go_previous() -> None:
            nonlocal current_index
            if current_index <= 0:
                return
            save_current_row_state()
            current_index -= 1
            restore_row_state(current_index)
            refresh_item()

        def skip_current() -> None:
            go_next()

        def undo_last() -> None:
            nonlocal current_index, imported_count
            if not undo_stack:
                messagebox.showinfo("信息", "没有可撤销的操作。", parent=allocator_win)
                return

            entry, row_idx = undo_stack.pop()
            if entry in self.entries:
                self.entries.remove(entry)
            allocated_rows.pop(row_idx, None)
            if imported_count > 0:
                imported_count -= 1

            save_current_row_state()
            current_index = row_idx
            restore_row_state(current_index)
            self.refresh_all()
            refresh_item()

        def add_current_and_next() -> None:
            nonlocal imported_count
            assigned_people = [person for person, selected in selected_people.items() if selected]
            if not assigned_people:
                messagebox.showerror("错误", "请至少选择一个人来分配当前商品。", parent=allocator_win)
                return

            row = current_row()
            amount = float(row["price"])
            mode = current_mode()
            previous_inputs = {}
            existing_state = row_state.get(current_index, {})
            maybe_inputs = existing_state.get("split_inputs")
            if isinstance(maybe_inputs, dict):
                previous_inputs = {
                    name: float(maybe_inputs[name])
                    for name in assigned_people
                    if name in maybe_inputs and isinstance(maybe_inputs[name], (int, float))
                }

            split_inputs: dict[str, float] = {}
            if mode != SPLIT_MODE_EQUAL:
                collected = self.prompt_split_inputs(
                    parent=allocator_win,
                    people=assigned_people,
                    amount=amount,
                    mode=mode,
                    initial_inputs=previous_inputs,
                )
                if collected is None:
                    return
                split_inputs = collected

            item_name = str(row["item"])
            if row.get("is_discount") and not item_name.startswith("折扣"):
                item_name = f"折扣：{item_name}"

            try:
                new_entry = ExpenseEntry.create(
                    assigned_people,
                    amount,
                    item_name,
                    str(row.get("quantity_info") or ""),
                    str(row.get("price_text") or ""),
                    split_mode=mode,
                    split_inputs=split_inputs,
                )
            except ValueError as exc:
                messagebox.showerror("错误", str(exc), parent=allocator_win)
                return

            # Persist selection / split inputs for this row.
            row_state[current_index] = {
                "selected": {name: bool(selected_people.get(name)) for name in self.people},
                "mode_label": split_mode_label_var.get(),
                "split_inputs": dict(split_inputs),
            }

            if current_index in allocated_rows:
                old_entry = allocated_rows[current_index]
                if old_entry in self.entries:
                    idx = self.entries.index(old_entry)
                    self.entries[idx] = new_entry
                else:
                    self.entries.append(new_entry)
                    imported_count += 1
                # Keep undo stack pointing at the latest entry for this row.
                undo_stack[:] = [
                    (new_entry, row_idx) if row_idx == current_index else (ent, row_idx)
                    for ent, row_idx in undo_stack
                ]
                if not any(row_idx == current_index for _ent, row_idx in undo_stack):
                    undo_stack.append((new_entry, current_index))
            else:
                self.entries.append(new_entry)
                undo_stack.append((new_entry, current_index))
                imported_count += 1

            allocated_rows[current_index] = new_entry
            self.refresh_all()
            go_next()

        prev_button = tk.Button(bottom_frame, text="上一个商品", width=12, command=go_previous)
        prev_button.pack(side=tk.LEFT)
        undo_button = tk.Button(bottom_frame, text="撤销", width=8, command=undo_last)
        undo_button.pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(bottom_frame, text="跳过此商品", width=12, command=skip_current).pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(bottom_frame, text="关闭", width=8, command=allocator_win.destroy).pack(side=tk.RIGHT, padx=(8, 0))
        tk.Button(bottom_frame, text="添加并下一项", width=14, command=add_current_and_next).pack(side=tk.RIGHT)

        tk.Button(action_frame, text="全选/取消", width=10, command=set_all_people).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(action_frame, text="清空选择", width=10, command=clear_allocator_selection).pack(side=tk.LEFT, padx=4)

        refresh_item()

    def copy_totals_to_clipboard(self) -> None:
        result = "\n".join(f"{name}: {self.totals[name]:.2f}" for name in self.people)
        self.root.clipboard_clear()
        self.root.clipboard_append(result)
        messagebox.showinfo("已复制", "每个人的金额已复制到剪贴板！")

    def open_builtin_browser(self) -> None:
        """Open or focus the pywebview companion browser + tk control panel."""
        if self.browser_session is None:
            self.browser_session = BuiltInBrowserSession(
                self.root,
                parse_invoice_json=self.parse_invoice_json,
                show_invoice_allocator=self.show_invoice_allocator,
                copy_extractor_script=self.copy_invoice_extractor_to_clipboard,
                parent_for_dialogs=self.root,
            )
        self.browser_session.open_or_focus()

    def copy_invoice_extractor_to_clipboard(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(INVOICE_EXTRACTOR_SCRIPT)
        messagebox.showinfo("已复制", "提取发票 JSON 的代码已复制到剪贴板！")

    def copy_details_to_clipboard(self) -> None:
        lines: list[str] = []
        for name in self.people:
            lines.append(f"{name}: {self.totals[name]:.2f}")
            for entry in self.entries:
                if name not in entry.shares:
                    continue
                lines.append(f"  - {entry.display_detail()}: {self.effective_amount(entry.shares[name]):.2f}")
            lines.append("")

        result = "\n".join(lines).strip()
        self.root.clipboard_clear()
        self.root.clipboard_append(result)
        messagebox.showinfo("已复制", "每个人的商品明细已复制到剪贴板！")

    def show_user_editor(self) -> None:
        editor_win = tk.Toplevel(self.root)
        editor_win.title("用户编辑")
        self.center_window(editor_win, 420, 520)
        editor_win.transient(self.root)
        editor_win.grab_set()

        main_frame = tk.Frame(editor_win, padx=20, pady=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        add_frame = tk.LabelFrame(main_frame, text="添加用户", padx=10, pady=10)
        add_frame.pack(fill=tk.X, pady=(0, 16))

        tk.Label(add_frame, text="用户名:").pack(anchor=tk.W)
        new_user_var = tk.StringVar()
        new_user_entry = tk.Entry(add_frame, textvariable=new_user_var, width=30)
        new_user_entry.pack(fill=tk.X, pady=(5, 10))

        delete_frame = tk.LabelFrame(main_frame, text="删除用户", padx=10, pady=10)
        delete_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(delete_frame, text="只能删除没有历史记录且总金额为0的用户", fg="red").pack(anchor=tk.W, pady=(0, 6))

        listbox_frame = tk.Frame(delete_frame)
        listbox_frame.pack(fill=tk.BOTH, expand=True)
        listbox_frame.grid_rowconfigure(0, weight=1)
        listbox_frame.grid_columnconfigure(0, weight=1)

        user_listbox = tk.Listbox(listbox_frame, height=10)
        scrollbar = tk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=user_listbox.yview)
        user_listbox.configure(yscrollcommand=scrollbar.set)
        user_listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        info_label = tk.Label(delete_frame, text="", justify=tk.LEFT)
        info_label.pack(anchor=tk.W, pady=8)

        def refresh_delete_list() -> None:
            user_listbox.delete(0, tk.END)
            for person in self.people:
                if self.can_delete_person(person):
                    user_listbox.insert(tk.END, person)
            info_label.config(text="没有可删除的用户" if user_listbox.size() == 0 else "")

        def add_user() -> None:
            name = new_user_var.get().strip()
            if not name:
                name = self.next_default_user_name()

            if name in self.selected:
                messagebox.showerror("错误", "该用户名已存在", parent=editor_win)
                return

            self.people.append(name)
            self.selected[name] = False
            self.totals[name] = 0.0
            new_user_var.set("")
            self.refresh_all()
            refresh_delete_list()
            messagebox.showinfo("成功", f"用户 '{name}' 已成功添加！", parent=editor_win)

        def update_info(_event=None) -> None:
            selection = user_listbox.curselection()
            if not selection:
                return
            name = user_listbox.get(selection[0])
            info_label.config(text=f"用户: {name}\n总金额: {self.totals[name]:.2f}\n历史记录: 0")

        def delete_selected_user() -> None:
            selection = user_listbox.curselection()
            if not selection:
                messagebox.showerror("错误", "请选择要删除的用户", parent=editor_win)
                return

            name = user_listbox.get(selection[0])
            if not self.can_delete_person(name):
                messagebox.showerror("错误", f"用户 '{name}' 仍有金额或历史记录，无法删除。", parent=editor_win)
                refresh_delete_list()
                return

            confirmed = messagebox.askyesno(
                "确认删除",
                f"确定要删除用户 '{name}' 吗？\n此操作不可撤销！",
                parent=editor_win,
            )
            if not confirmed:
                return

            self.delete_person(name)
            refresh_delete_list()
            messagebox.showinfo("成功", f"用户 '{name}' 已成功删除！", parent=editor_win)

        new_user_entry.bind("<Return>", lambda _event: add_user())
        tk.Button(add_frame, text="添加用户", command=add_user, bg="green", fg="white").pack(pady=5)

        user_listbox.bind("<<ListboxSelect>>", update_info)
        tk.Button(delete_frame, text="删除选中用户", command=delete_selected_user, bg="red", fg="white").pack(pady=8)
        tk.Button(main_frame, text="关闭", command=editor_win.destroy).pack(pady=(16, 0))

        refresh_delete_list()
        new_user_entry.focus_set()

    def next_default_user_name(self) -> str:
        index = 1
        while f"路人{index}" in self.selected:
            index += 1
        return f"路人{index}"

    def can_delete_person(self, name: str) -> bool:
        has_history = any(name in entry.people for entry in self.entries)
        return abs(self.totals.get(name, 0.0)) < EPSILON and not has_history

    def delete_person(self, name: str) -> None:
        if not self.can_delete_person(name):
            raise ValueError(f"用户 '{name}' 仍有金额或历史记录，无法删除。")

        self.people.remove(name)
        self.selected.pop(name, None)
        self.totals.pop(name, None)
        self.refresh_all()


if __name__ == "__main__":
    if "--webview-host" in sys.argv:
        from webview_host import main as webview_host_main

        host_arg_index = sys.argv.index("--webview-host")
        raise SystemExit(webview_host_main(sys.argv[host_arg_index + 1 :]))

    root = tk.Tk()
    app = ShoppingCalculator(root)
    root.mainloop()
