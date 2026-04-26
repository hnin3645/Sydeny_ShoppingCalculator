# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox, scrolledtext


DEFAULT_PEOPLE = ("msc", "nhy", "wpq", "zyf")
SELECTED_COLOR = "lightgreen"
EPSILON = 1e-9
INVOICE_EXTRACTOR_SCRIPT = r"""const rows = [];
let lastProductName = "";

[...document.querySelectorAll('div.sub-heading.items')].forEach(row => {
  const text = row.querySelector('p')?.innerText.replace(/\s+/g, ' ').trim() || "";
  const priceText = row.querySelector('span.text-right.price')?.innerText.trim() || "";
  const amount = parseFloat(priceText.replace(/[^0-9.]/g, ''));

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


@dataclass
class ExpenseEntry:
    """一条消费记录：amount 是原始总金额，shares 是每个人分摊后的金额。"""

    people: tuple[str, ...]
    amount: float
    shares: dict[str, float] = field(default_factory=dict)
    item_name: str = ""
    quantity_info: str = ""
    price_text: str = ""

    @classmethod
    def create(
        cls,
        people: list[str],
        amount: float,
        item_name: str = "",
        quantity_info: str = "",
        price_text: str = "",
    ) -> "ExpenseEntry":
        share = amount / len(people)
        return cls(
            tuple(people),
            amount,
            {name: share for name in people},
            item_name.strip(),
            quantity_info.strip(),
            price_text.strip(),
        )

    def set_total_amount(self, amount: float) -> None:
        self.amount = amount
        share = amount / len(self.people)
        self.shares = {name: share for name in self.people}

    def set_single_person_amount(self, name: str, amount: float) -> None:
        self.people = (name,)
        self.amount = amount
        self.shares = {name: amount}

    def display_detail(self) -> str:
        name = self.item_name or "手动记录"
        if self.quantity_info:
            return f"{name} | {self.quantity_info}"
        return name


class ShoppingCalculator:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("购物金额计算器")
        self.center_window(self.root, 1000, 620)

        self.amount = tk.StringVar()
        self.total_records_text = tk.StringVar(value="查看总记录：0.00")

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

    def create_menu(self) -> None:
        menu = tk.Menu(self.root)
        self.root.config(menu=menu)

        file_menu = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="文件", menu=file_menu)
        file_menu.add_command(label="导入发票 JSON", command=self.show_invoice_importer)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit)

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

        tk.Button(top_frame, text="添加", width=8, command=self.add_entry).pack(side=tk.LEFT, padx=4)
        tk.Button(top_frame, text="导入发票JSON", width=13, command=self.show_invoice_importer).pack(side=tk.LEFT, padx=4)
        tk.Button(top_frame, text="复制提取代码", width=12, command=self.copy_invoice_extractor_to_clipboard).pack(side=tk.LEFT, padx=4)
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
                    self.totals[name] += share

    def refresh_total_button(self) -> None:
        total = sum(entry.amount for entry in self.entries)
        self.total_records_text.set(f"查看总记录：{total:.2f}")

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
            listbox.insert(tk.END, f"{self.format_amount(entry.shares[name], signed=True)}  {entry.display_detail()}")
            row_entries.append(entry_index)
        self.person_row_entries[name] = row_entries

    def add_entry(self) -> None:
        try:
            amount = self.parse_amount(self.amount.get())
            selected_people = [name for name, selected in self.selected.items() if selected]
            if not selected_people:
                raise ValueError("至少选择一个人")

            self.entries.append(ExpenseEntry.create(selected_people, amount))
            self.amount.set("")
            self.clear_selection()
            self.refresh_all()
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))

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
        self.center_window(records_win, 360, 420)
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
            self.general_records_listbox.insert(tk.END, f"{entry.display_detail()} | {people}: {entry.amount:.2f}")

    def edit_entry(self, event: tk.Event) -> None:
        selection = event.widget.curselection()
        if not selection:
            return

        entry_index = selection[0]
        if entry_index >= len(self.entries):
            return

        entry = self.entries[entry_index]
        self.show_amount_editor(
            title="编辑记录",
            initial_amount=entry.amount,
            on_save=lambda amount: self.update_total_entry(entry_index, amount),
        )

    def update_total_entry(self, entry_index: int, amount: float) -> None:
        self.entries[entry_index].set_total_amount(amount)
        self.refresh_all()

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
        entry = self.entries[entry_index]
        if len(entry.people) > 1:
            messagebox.showinfo("信息", "多人订单只能通过总记录修改。")
            return

        self.show_amount_editor(
            title=f"编辑{name}的记录",
            initial_amount=entry.shares[name],
            on_save=lambda amount: self.update_single_person_entry(entry_index, name, amount),
        )

    def update_single_person_entry(self, entry_index: int, name: str, amount: float) -> None:
        self.entries[entry_index].set_single_person_amount(name, amount)
        self.refresh_all()

    def show_amount_editor(self, title: str, initial_amount: float, on_save) -> None:
        edit_win = tk.Toplevel(self.root)
        edit_win.title(title)
        self.center_window(edit_win, 260, 150)
        edit_win.transient(self.root)
        edit_win.grab_set()

        amount_var = tk.StringVar(value=f"{initial_amount:.2f}")

        tk.Label(edit_win, text="新金额:").pack(pady=(14, 6))
        entry = tk.Entry(edit_win, textvariable=amount_var, width=16)
        entry.pack(pady=4)
        entry.focus_set()
        entry.select_range(0, tk.END)

        def save_changes() -> None:
            try:
                on_save(self.parse_amount(amount_var.get()))
                edit_win.destroy()
            except ValueError as exc:
                messagebox.showerror("错误", str(exc), parent=edit_win)

        entry.bind("<Return>", lambda _event: save_changes())
        tk.Button(edit_win, text="保存", width=10, command=save_changes).pack(pady=12)

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

            invoice_rows.append(
                {
                    "item": item_name or f"商品 {index}",
                    "quantity_info": quantity_info,
                    "price": amount,
                    "price_text": price_text,
                }
            )

        return invoice_rows

    def parse_imported_price(self, price_value: object, price_text: str) -> float:
        source = price_value
        if source is None or source == "":
            source = price_text

        if isinstance(source, (int, float)):
            amount = float(source)
        else:
            price_string = str(source).strip()
            cleaned = "".join(char for char in price_string if char.isdigit() or char in ".-")
            amount = self.parse_amount(cleaned)

        if amount < 0:
            raise ValueError("商品金额不能小于 0。")
        return amount

    def show_invoice_allocator(self, invoice_rows: list[dict[str, object]], parent: tk.Misc) -> None:
        allocator_win = tk.Toplevel(self.root)
        allocator_win.title("分配发票商品")
        self.center_window(allocator_win, 560, 430)
        allocator_win.transient(parent)
        allocator_win.grab_set()

        current_index = 0
        imported_count = 0
        selected_people = {name: False for name in self.people}
        person_buttons: dict[str, tk.Button] = {}

        status_var = tk.StringVar()
        item_var = tk.StringVar()
        quantity_var = tk.StringVar()
        price_var = tk.StringVar()

        main_frame = tk.Frame(allocator_win, padx=16, pady=16)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.grid_columnconfigure(0, weight=1)

        tk.Label(main_frame, textvariable=status_var, anchor="w").grid(row=0, column=0, sticky="ew")
        tk.Label(main_frame, textvariable=item_var, anchor="w", justify=tk.LEFT, wraplength=510, font=("TkDefaultFont", 12, "bold")).grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(8, 4),
        )
        tk.Label(main_frame, textvariable=quantity_var, anchor="w", justify=tk.LEFT, wraplength=510).grid(row=2, column=0, sticky="ew")
        tk.Label(main_frame, textvariable=price_var, anchor="w").grid(row=3, column=0, sticky="ew", pady=(4, 12))

        people_frame = tk.LabelFrame(main_frame, text="分配给", padx=10, pady=10)
        people_frame.grid(row=4, column=0, sticky="ew")
        for column in range(4):
            people_frame.grid_columnconfigure(column, weight=1)

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

        action_frame = tk.Frame(main_frame)
        action_frame.grid(row=5, column=0, sticky="ew", pady=(12, 0))

        bottom_frame = tk.Frame(main_frame)
        bottom_frame.grid(row=6, column=0, sticky="ew", pady=(18, 0))

        def current_row() -> dict[str, object]:
            return invoice_rows[current_index]

        def refresh_item() -> None:
            row = current_row()
            status_var.set(f"第 {current_index + 1} / {len(invoice_rows)} 个商品")
            item_var.set(str(row["item"]))
            quantity = str(row.get("quantity_info") or "")
            quantity_var.set(f"数量信息：{quantity}" if quantity else "数量信息：无")

            price = float(row["price"])
            price_text = str(row.get("price_text") or "")
            price_var.set(f"金额：{price:.2f}" + (f"（原文：{price_text}）" if price_text else ""))
            refresh_person_buttons()

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
            current_index += 1
            refresh_item()

        def skip_current() -> None:
            go_next()

        def add_current_and_next() -> None:
            nonlocal imported_count
            assigned_people = [person for person, selected in selected_people.items() if selected]
            if not assigned_people:
                messagebox.showerror("错误", "请至少选择一个人来分配当前商品。", parent=allocator_win)
                return

            row = current_row()
            self.entries.append(
                ExpenseEntry.create(
                    assigned_people,
                    float(row["price"]),
                    str(row["item"]),
                    str(row.get("quantity_info") or ""),
                    str(row.get("price_text") or ""),
                )
            )
            imported_count += 1
            self.refresh_all()
            go_next()

        tk.Button(action_frame, text="全选/取消", width=10, command=set_all_people).pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(action_frame, text="清空选择", width=10, command=clear_allocator_selection).pack(side=tk.LEFT, padx=4)

        tk.Button(bottom_frame, text="跳过此商品", width=12, command=skip_current).pack(side=tk.LEFT)
        tk.Button(bottom_frame, text="关闭", width=8, command=allocator_win.destroy).pack(side=tk.RIGHT, padx=(8, 0))
        tk.Button(bottom_frame, text="添加并下一项", width=14, command=add_current_and_next).pack(side=tk.RIGHT)

        refresh_item()

    def copy_totals_to_clipboard(self) -> None:
        result = "\n".join(f"{name}: {self.totals[name]:.2f}" for name in self.people)
        self.root.clipboard_clear()
        self.root.clipboard_append(result)
        messagebox.showinfo("已复制", "每个人的金额已复制到剪贴板！")

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
                lines.append(f"  - {entry.display_detail()}: {entry.shares[name]:.2f}")
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
    root = tk.Tk()
    app = ShoppingCalculator(root)
    root.mainloop()
