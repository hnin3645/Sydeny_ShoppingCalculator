悉尼购物分摊计算器

运行方式
1. 双击 dist\shop.exe 启动程序。
2. 输入金额，选择需要分摊的人，点击“添加”。
3. 点击“全选/取消”可以快速选择或清空默认人员。
4. 点击记录或个人金额可以修改金额，程序会自动重新计算总额。
5. 点击“复制结果”复制每个人应付总额，点击“复制明细”复制完整分摊明细。

发票 JSON 导入
1. 点击“复制提取代码”，把代码粘贴到购物发票网页的浏览器控制台执行。
2. 控制台会把商品 JSON 复制到剪贴板。
3. 回到程序，点击“导入发票JSON”，粘贴 JSON 后开始逐个商品分配。
4. 分配时可以全选、清空选择、跳过商品，或“添加并下一项”。

用户管理
1. 程序默认人员为 msc、nhy、wpq、zyf。
2. 可以添加新用户。
3. 只有总金额为 0 且没有历史记录的用户可以删除。

重新生成 exe
源码入口：shop_NEW.py
输出文件：dist\shop.exe

当前使用 Python 3.12.8 和 PyInstaller 6.20.0 打包：
C:\Users\64648\AppData\Local\Programs\Python\Python312\python.exe -m PyInstaller --onefile --windowed --name shop --distpath dist --workpath build --specpath build --noconfirm shop_NEW.py

说明：__pycache__ 只保存 Python 字节码缓存，不是 exe 打包工具。生成 exe 需要 PyInstaller 或其他打包工具。

更新记录
2026-04-27
- 使用 shop_NEW.py 重新生成 dist\shop.exe。
- 更新 readme.txt，补充运行、发票导入、用户管理和打包说明。
