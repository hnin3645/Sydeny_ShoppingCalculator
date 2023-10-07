import tkinter as tk
from tkinter import messagebox, StringVar, Listbox, Toplevel

class ShoppingCalculator:
    def __init__(self, root):
        self.root = root
        self.root.title("购物金额计算器")
        
        self.root.geometry("1000x600+{}+{}".format(int((self.root.winfo_screenwidth() - 400) / 2), 
                                                  int((self.root.winfo_screenheight() - 500) / 2)))

        # 定义变量
        self.amount = StringVar()
        self.entries = []
        self.listbox_to_name = {}
        
        self.buttons_status = {
            "msc": False,
            "nhy": False,
            "wpq": False,
            "zyf": False
        }

        self.totals = {
            "msc": 0.0,
            "nhy": 0.0,
            "wpq": 0.0,
            "zyf": 0.0
        }
        
        self.records = {
            "msc": [],
            "nhy": [],
            "wpq": [],
            "zyf": []
        }
        
        self.create_widgets()

    # 为每个名字创建标签和按钮
    def create_label_button_pair(self, name):
        label = tk.Label(self.root, text=f"{name}: {self.totals[name]:.2f}")
        label.pack(pady=10)
        setattr(self, f"{name}_label", label)

        button = tk.Button(self.root, text=f"查看{name}记录", command=lambda: self.show_individual_records(name))
        button.pack(pady=5)
        setattr(self, f"{name}_records_btn", button)

    # 创建界面组件
    def create_widgets(self):
        # 输入金额标签和输入框
        self.amount_label = tk.Label(self.root, text="请输入金额:")
        self.amount_label.grid(row=0, column=0, pady=10, padx=50, sticky=tk.NSEW)
        
        self.amount_entry = tk.Entry(self.root, textvariable=self.amount, width=20)
        self.amount_entry.grid(row=0, column=1, pady=10, padx=50, columnspan=1, sticky=tk.W)

        # 添加按钮
        self.add_btn = tk.Button(self.root, text="添加", command=self.update_totals)
        self.add_btn.grid(row=0, column=2, pady=10, padx=10)

        # 查看总记录按钮
        self.general_records_btn = tk.Button(self.root, text="查看总记录", command=self.show_general_records)
        self.general_records_btn.grid(row=0, column=3, pady=10, padx=10)
        
        # 人名按钮
        for idx, name in enumerate(self.buttons_status.keys()):
            btn = tk.Button(self.root, text=name, command=lambda n=name: self.toggle_button(n))
            btn.grid(row=1, column=idx, padx=50)
            setattr(self, f"{name}_button", btn)

        # 为每个名字创建标签
        for idx, name in enumerate(self.totals.keys()):
            label = tk.Label(self.root, text=f"{name}: {self.totals[name]:.2f}")
            label.grid(row=2, column=idx, pady=10, padx=50, sticky=tk.NSEW)
            setattr(self, f"{name}_label", label)

        # 为每个名字创建一个框架，里面包含个人记录
        for idx, name in enumerate(self.buttons_status.keys()):
            frame = tk.Frame(self.root)
            frame.grid(row=3, column=idx, pady=10, padx=50, sticky=tk.W)
            setattr(self, f"{name}_frame", frame)

            # 初始化时直接显示个人记录
            self.show_individual_records(name)

    # 切换按钮状态
    def toggle_button(self, name):
        self.buttons_status[name] = not self.buttons_status[name]
        button = getattr(self, f"{name}_button")  # 使用正确的变量名获取按钮
        if self.buttons_status[name]:
            button.config(bg="lightgreen")
        else:
            button.config(bg="SystemButtonFace")

    # 显示总记录
    def show_general_records(self):
        if not self.entries:
            messagebox.showinfo("信息", "没有记录可供显示。")
            return
        records_win = Toplevel(self.root)
        records_win.title("总记录")
        listbox = Listbox(records_win)
        listbox.pack(fill=tk.BOTH, expand=True)
        listbox.delete(0, tk.END)  # 清除所有旧的记录
        for entry in self.entries:
            listbox.insert(tk.END, f"{', '.join(entry['names'])}: {entry['amount']:.2f}")
        listbox.bind('<Double-Button-1>', self.edit_entry)


    # 显示个人记录
    def show_individual_records(self, name):
        frame = getattr(self, f"{name}_frame")

        # 检查是否已经存在Listbox
        listbox = None
        for child in frame.winfo_children():
            if isinstance(child, tk.Listbox):
                listbox = child
                # 清空现有的Listbox内容
                listbox.delete(0, tk.END)
                break

        # 如果没有找到Listbox，创建一个新的
        if listbox is None:
            listbox = Listbox(frame, height=20)
            listbox.pack(fill=tk.BOTH, expand=True)
            listbox.bind('<Double-Button-1>', self.edit_individual_entry)  # 绑定编辑事件
            self.listbox_to_name[listbox] = name  # 为Listbox关联名字

        if not self.records[name]:
            # 如果没有记录，您可以根据需要添加其他代码，例如显示标签
            pass
        else:
            for record in self.records[name]:
                listbox.insert(tk.END, f"+{record:.2f}")


    # 更新总计
    def update_totals(self):
        try:
            total_amount = float(self.amount.get())
            if total_amount < 0:
                raise ValueError("金额不能为负数")
            selected_names = [name for name, status in self.buttons_status.items() if status]
            if not selected_names:
                raise ValueError("至少选择一个人")
            shared_amount = total_amount / len(selected_names)
            self.entries.append({
                "names": selected_names,
                "amount": total_amount
            })
            for name in selected_names:
                self.totals[name] += shared_amount
                label = getattr(self, f"{name}_label")
                label.config(text=f"{name}: {self.totals[name]:.2f}")
                self.records[name].append(shared_amount)
                # 更新每个选中的人的记录显示
                self.show_individual_records(name)
        except ValueError as e:
            messagebox.showerror("错误", str(e))
        finally:
            self.amount.set("")
            for name in self.buttons_status:
                self.buttons_status[name] = False
                button = getattr(self, f"{name}_button")
                button.config(bg="SystemButtonFace")

    # 编辑个人记录
    def edit_individual_entry(self, event):
        name = self.listbox_to_name[event.widget]  # 使用字典来获取名字
        idx = event.widget.curselection()[0]
        prev_amount = self.records[name][idx]

        is_multi_person_entry = False
        for entry in self.entries:
            if name in entry['names'] and abs(entry['amount'] / len(entry['names']) - prev_amount) < 1e-6:
                if len(entry['names']) > 1:
                    is_multi_person_entry = True
                    break

        if is_multi_person_entry:
            messagebox.showinfo("信息", "多人订单只能通过总金额修改。")
            return
    
        def save_changes():
            try:
                new_amount = float(amount_var.get())
                if new_amount < 0:
                    raise ValueError("金额不能为负数")
                diff = new_amount - prev_amount
                self.totals[name] += diff
                label = getattr(self, f"{name}_label")
                label.config(text=f"{name}: {self.totals[name]:.2f}")
                event.widget.delete(idx)
                event.widget.insert(idx, f"+{new_amount:.2f}")
                self.records[name][idx] = new_amount

                for entry in self.entries:
                    if name in entry['names'] and abs(entry['amount']/len(entry['names']) - prev_amount) < 1e-6:
                        shared_amount = entry['amount'] + diff * len(entry['names'])
                        entry['amount'] = shared_amount

                edit_win.destroy()
                self.show_individual_records(name)
            except ValueError as e:
                messagebox.showerror("错误", str(e))

        edit_win = Toplevel(self.root)
        edit_win.title(f"编辑{name}的记录")
        label = tk.Label(edit_win, text="新金额:")
        label.pack(pady=10)
        amount_var = StringVar(value=str(prev_amount))
        amount_entry = tk.Entry(edit_win, textvariable=amount_var)
        amount_entry.pack(pady=10)
        save_btn = tk.Button(edit_win, text="保存", command=save_changes)
        save_btn.pack(pady=20)

    # 编辑记录
    def edit_entry(self, event):
        idx = event.widget.curselection()[0]
        entry = self.entries[idx]

        def save_changes():
            try:
                new_amount = float(amount_var.get())
                if new_amount < 0:
                    raise ValueError("金额不能为负数")
                shared_amount = new_amount / len(entry['names'])
                event.widget.delete(idx)
                event.widget.insert(idx, f"{', '.join(entry['names'])}: {new_amount:.2f}")
                diff = shared_amount - (entry['amount'] / len(entry['names']))
                for name in entry['names']:
                    self.totals[name] += diff
                    label = getattr(self, f"{name}_label")
                    label.config(text=f"{name}: {self.totals[name]:.2f}")
                    record_idx = self.records[name].index(entry['amount'] / len(entry['names']))
                    self.records[name][record_idx] = shared_amount
                entry['amount'] = new_amount
                edit_win.destroy()
                for name in entry['names']:
                    self.show_individual_records(name)
            except ValueError as e:
                messagebox.showerror("错误", str(e))

        edit_win = Toplevel(self.root)
        edit_win.title("编辑记录")
        label = tk.Label(edit_win, text="新金额:")
        label.pack(pady=10)
        amount_var = StringVar(value=str(entry['amount']))
        amount_entry = tk.Entry(edit_win, textvariable=amount_var)
        amount_entry.pack(pady=10)
        save_btn = tk.Button(edit_win, text="保存", command=save_changes)
        save_btn.pack(pady=20)

root = tk.Tk()
app = ShoppingCalculator(root)
root.mainloop()
