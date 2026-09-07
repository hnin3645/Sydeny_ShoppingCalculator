import tkinter as tk
from tkinter import messagebox, StringVar, Listbox, Toplevel

class ShoppingCalculator:
    def __init__(self, root):
        self.root = root
        self.root.title("购物金额计算器")
        
        self.root.geometry("1200x600+{}+{}".format(int((self.root.winfo_screenwidth() - 400) / 2), 
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
        
        # 创建菜单栏
        self.create_menu()
        
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
        # 顶部控件区域用Frame+pack自适应
        self.top_frame = tk.Frame(self.root)
        self.top_frame.grid(row=0, column=0, columnspan=10, sticky='w')

        self.amount_label = tk.Label(self.top_frame, text="请输入金额:")
        self.amount_label.pack(side=tk.LEFT, padx=2)
        self.amount_entry = tk.Entry(self.top_frame, textvariable=self.amount, width=10)
        self.amount_entry.pack(side=tk.LEFT, padx=2)
        self.add_btn = tk.Button(self.top_frame, text="添加", command=self.update_totals, width=6)
        self.add_btn.pack(side=tk.LEFT, padx=2)
        self.general_records_btn_text = StringVar()
        self.general_records_btn_text.set("查看总金额：0.0")
        self.general_records_btn = tk.Button(self.top_frame, textvariable=self.general_records_btn_text, command=self.show_general_records, width=12)
        self.general_records_btn.pack(side=tk.LEFT, padx=150)
        self.select_all_btn = tk.Button(self.top_frame, text="全选所有人", command=self.select_all_people, width=10)
        self.select_all_btn.pack(side=tk.LEFT, padx=2)
        
        # Output按钮
        self.output_btn = tk.Button(self.top_frame, text="输出结果", command=self.copy_totals_to_clipboard, width=10)
        self.output_btn.pack(side=tk.LEFT, padx=2)

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
                if record > 0:
                    listbox.insert(tk.END, f"+{record:.2f}")
                elif record < 0:
                    listbox.insert(tk.END, f"-{abs(record):.2f}")
                else:
                    listbox.insert(tk.END, "0.00")


    # 更新总计
    def update_totals(self):
        try:
            total_amount = float(self.amount.get())
            # if total_amount < 0:
            #     raise ValueError("金额不能为负数")
            
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
            
            # 更新"查看总记录"按钮上的文本
            current_total = float(self.general_records_btn_text.get().split('：')[1])
            current_total += total_amount
            self.general_records_btn_text.set(f"查看总记录：{current_total:.2f}")
            
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
                # if new_amount < 0:
                #     raise ValueError("金额不能为负数")
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
                # if new_amount < 0:
                #     raise ValueError("金额不能为负数")
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

    def select_all_people(self):
        # 检查当前是否已经全选
        all_selected = all(self.buttons_status.values())
        
        # 如果已经全选，则取消全选；否则全选所有人
        new_status = not all_selected
        
        for name in self.buttons_status:
            self.buttons_status[name] = new_status
            button = getattr(self, f"{name}_button")
            if new_status:
                button.config(bg="lightgreen")
            else:
                button.config(bg="SystemButtonFace")

    def copy_totals_to_clipboard(self):
        # 生成每个人的名字和金额的字符串
        result = "\n".join([f"{name}: {self.totals[name]:.2f}" for name in self.totals])
        self.root.clipboard_clear()
        self.root.clipboard_append(result)
        messagebox.showinfo("已复制", "每个人的金额已复制到剪贴板！")

    def _perform_delete_person(self, name):
        """执行删除联系人的具体操作"""
        try:
            # 再次确认金额为0
            if self.totals[name] != 0.0:
                messagebox.showerror("错误", f"用户 '{name}' 的总金额不为0，无法删除。")
                return
            
            # 1. 从数据结构中删除
            del self.buttons_status[name]
            del self.totals[name]
            del self.records[name]
            
            # 2. 销毁UI组件
            button = getattr(self, f"{name}_button", None)
            if button:
                button.destroy()
                delattr(self, f"{name}_button")
            
            label = getattr(self, f"{name}_label", None)
            if label:
                label.destroy()
                delattr(self, f"{name}_label")
            
            frame = getattr(self, f"{name}_frame", None)
            if frame:
                frame.destroy()
                delattr(self, f"{name}_frame")
            
            # 3. 重新布局剩余的按钮和标签
            self._relayout_widgets()
            
            # 4. 更新总金额显示
            self._update_total_amount()
            
            messagebox.showinfo("成功", f"用户 '{name}' 已成功删除！")
            
        except Exception as e:
            messagebox.showerror("错误", f"删除用户时发生错误: {str(e)}")

    def _relayout_widgets(self):
        """重新布局剩余的按钮和标签"""
        # 获取所有剩余的联系人
        remaining_names = list(self.buttons_status.keys())
        
        # 重新布局按钮
        for idx, name in enumerate(remaining_names):
            button = getattr(self, f"{name}_button")
            button.grid(row=1, column=idx, padx=50)
            
            label = getattr(self, f"{name}_label")
            label.grid(row=2, column=idx, pady=10, padx=50, sticky=tk.NSEW)
            
            frame = getattr(self, f"{name}_frame")
            frame.grid(row=3, column=idx, pady=10, padx=50, sticky=tk.W)
            
            # 更新个人记录显示
            self.show_individual_records(name)

    def _update_total_amount(self):
        """更新总金额显示"""
        total_amount = sum(self.totals.values())
        self.general_records_btn_text.set(f"查看总记录：{total_amount:.2f}")

    def create_menu(self):
        # 创建菜单栏
        self.menu = tk.Menu(self.root)
        self.root.config(menu=self.menu)

        # 创建File菜单
        self.file_menu = tk.Menu(self.menu, tearoff=0)
        self.menu.add_cascade(label="File", menu=self.file_menu)
        self.file_menu.add_command(label="退出", command=self.root.quit)

        # 创建Edit菜单
        self.edit_menu = tk.Menu(self.menu, tearoff=0)
        self.menu.add_cascade(label="Edit", menu=self.edit_menu)
        self.edit_menu.add_command(label="用户编辑", command=self.show_user_editor)

    def show_user_editor(self):
        """显示用户编辑对话框，集成添加和删除用户功能"""
        # 创建用户编辑对话框
        editor_win = Toplevel(self.root)
        editor_win.title("用户编辑")
        editor_win.geometry("400x500")
        editor_win.transient(self.root)  # 设置为主窗口的临时窗口
        editor_win.grab_set()  # 模态对话框
        
        # 居中显示
        editor_win.geometry("+{}+{}".format(
            int((self.root.winfo_screenwidth() - 400) / 2),
            int((self.root.winfo_screenheight() - 500) / 2)
        ))
        
        # 创建主框架
        main_frame = tk.Frame(editor_win)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # === 添加用户部分 ===
        add_frame = tk.LabelFrame(main_frame, text="添加用户", padx=10, pady=10)
        add_frame.pack(fill=tk.X, pady=(0, 20))
        
        # 用户名输入
        tk.Label(add_frame, text="用户名:").pack(anchor=tk.W)
        new_user_var = StringVar()
        new_user_entry = tk.Entry(add_frame, textvariable=new_user_var, width=30)
        new_user_entry.pack(fill=tk.X, pady=(5, 10))
        
        # 添加用户按钮
        def add_user():
            name = new_user_var.get().strip()
            if not name:
                # 自动分配默认名字
                base = '路人'
                idx = 1
                while f'{base}{idx}' in self.buttons_status:
                    idx += 1
                name = f'{base}{idx}'
            
            if name in self.buttons_status:
                messagebox.showerror("错误", "该用户名已存在")
                return

            # 动态添加到数据结构
            self.buttons_status[name] = False
            self.totals[name] = 0.0
            self.records[name] = []

            # 动态添加按钮
            idx = len(self.buttons_status) - 1
            btn = tk.Button(self.root, text=name, command=lambda n=name: self.toggle_button(n))
            btn.grid(row=1, column=idx, padx=50)
            setattr(self, f"{name}_button", btn)

            # 动态添加标签
            label = tk.Label(self.root, text=f"{name}: {self.totals[name]:.2f}")
            label.grid(row=2, column=idx, pady=10, padx=50, sticky=tk.NSEW)
            setattr(self, f"{name}_label", label)

            # 动态添加frame
            frame = tk.Frame(self.root)
            frame.grid(row=3, column=idx, pady=10, padx=50, sticky=tk.W)
            setattr(self, f"{name}_frame", frame)
            self.show_individual_records(name)

            new_user_var.set("")
            messagebox.showinfo("成功", f"用户 '{name}' 已成功添加！")
            
            # 刷新删除用户列表
            refresh_delete_list()
        
        add_btn = tk.Button(add_frame, text="添加用户", command=add_user, bg="green", fg="white")
        add_btn.pack(pady=5)
        
        # === 删除用户部分 ===
        delete_frame = tk.LabelFrame(main_frame, text="删除用户", padx=10, pady=10)
        delete_frame.pack(fill=tk.BOTH, expand=True)
        
        # 检查是否有可以删除的用户（总金额为0的用户）
        deletable_users = [name for name, total in self.totals.items() if total == 0.0]
        
        if not deletable_users:
            tk.Label(delete_frame, text="没有可以删除的用户。\n只有总金额为0的用户才能被删除。", 
                    fg="red", justify=tk.CENTER).pack(pady=20)
        else:
            # 创建说明标签
            tk.Label(delete_frame, text="注意：只能删除总金额为0的用户", 
                    fg="red", font=("Arial", 9)).pack(pady=5)
            
            # 创建用户列表
            list_frame = tk.Frame(delete_frame)
            list_frame.pack(fill=tk.BOTH, expand=True, pady=10)
            
            # 创建列表框和滚动条
            listbox_frame = tk.Frame(list_frame)
            listbox_frame.pack(fill=tk.BOTH, expand=True)
            
            user_listbox = tk.Listbox(listbox_frame, height=10)
            scrollbar = tk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=user_listbox.yview)
            user_listbox.configure(yscrollcommand=scrollbar.set)
            
            user_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            
            # 显示用户信息
            info_label = tk.Label(delete_frame, text="")
            info_label.pack(pady=5)
            
            def refresh_delete_list():
                user_listbox.delete(0, tk.END)
                deletable_users = [name for name, total in self.totals.items() if total == 0.0]
                for user in deletable_users:
                    user_listbox.insert(tk.END, user)
                if not deletable_users:
                    info_label.config(text="没有可删除的用户")
                else:
                    info_label.config(text="")
            
            def update_info(event):
                selection = user_listbox.curselection()
                if selection:
                    name = user_listbox.get(selection[0])
                    total = self.totals[name]
                    record_count = len(self.records[name])
                    info_text = f"用户: {name}\n总金额: {total:.2f}\n记录数量: {record_count}"
                    info_label.config(text=info_text)
            
            user_listbox.bind('<<ListboxSelect>>', update_info)
            
            # 删除按钮
            def delete_selected_user():
                selection = user_listbox.curselection()
                if not selection:
                    messagebox.showerror("错误", "请选择要删除的用户")
                    return
                
                name = user_listbox.get(selection[0])
                
                # 再次检查金额是否为0
                if self.totals[name] != 0.0:
                    messagebox.showerror("错误", f"用户 '{name}' 的总金额不为0，无法删除。")
                    return
                
                # 确认删除
                result = messagebox.askyesno("确认删除", 
                                           f"确定要删除用户 '{name}' 吗？\n"
                                           f"此操作不可撤销！")
                if result:
                    self._perform_delete_person(name)
                    refresh_delete_list()
                    messagebox.showinfo("成功", f"用户 '{name}' 已成功删除！")
            
            delete_btn = tk.Button(delete_frame, text="删除选中用户", command=delete_selected_user, 
                                  bg="red", fg="white")
            delete_btn.pack(pady=10)
            
            # 初始化列表
            refresh_delete_list()
        
        # 关闭按钮
        close_btn = tk.Button(main_frame, text="关闭", command=editor_win.destroy)
        close_btn.pack(pady=20)

root = tk.Tk()
app = ShoppingCalculator(root)
root.mainloop()
