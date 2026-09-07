悉尼购物分摊计算器

运行方式
1. 双击 dist\shop.exe 启动程序，内置浏览器已整合在同一个 exe 中。
2. 如需从源码运行：`C:\Users\64648\AppData\Local\Programs\Python\Python312\python.exe src\shopping_calculator.py`
3. 输入金额，选择需要分摊的人，点击“添加”。
4. 点击“全选/取消”可以快速选择或清空默认人员。
5. 点击记录或个人金额可以修改金额，程序会自动重新计算总额。
6. 点击“复制结果”复制每个人应付总额，点击“复制明细”复制完整分摊明细。

发票 JSON 导入
1. 点击“复制提取代码”，把代码粘贴到购物发票网页的浏览器控制台执行。
2. 控制台会把商品 JSON 复制到剪贴板。
3. 回到程序，点击“导入发票JSON”，粘贴 JSON 后开始逐个商品分配。
4. 分配时可以全选、清空选择、跳过商品，或“添加并下一项”。
5. 促销折扣行（例如 BUY 2 for $5.50）会显示为负数折扣，请分配给享受该促销的人。

内置浏览器
1. 点击“内置浏览器”会自动打开 Everyday Rewards 的 My Activity 页面。
2. 登录状态会保留；打开某笔消费明细后，点击“提取当前页小票”。
3. 称重商品会把商品名、重量/单价和最终金额分别识别，例如 Banana Cavendish、1.307 kg NET @ $4.90/kg、6.40。
4. 识别图片、导入 JSON、内置浏览器和复制提取代码入口统一位于菜单栏“工具”中。

每月九折
1. 主页面点击“9折：关闭”后，所有人的每条商品分摊金额按 0.9 倍显示和计算。
2. 再点击一次“9折：已开启”即可恢复原价，原始记录不会被修改。
3. 小票中的“WOW 10% OFFER”总折扣行不会重复导入；其他促销折扣仍按原有方式处理。

用户管理
1. 程序默认人员为 msc、nhy、wpq、zyf。
2. 可以添加新用户。
3. 只有总金额为 0 且没有历史记录的用户可以删除。

重新生成 exe
源码入口：src\shopping_calculator.py
输出文件：dist\shop.exe

当前使用 Python 3.12 和 PyInstaller 6.22.2 打包：
C:\Users\64648\AppData\Local\Programs\Python\Python312\python.exe -m PyInstaller --onefile --windowed --name shop --distpath dist --workpath build_shop --specpath build_shop --noconfirm src\shopping_calculator.py

说明：构建临时目录和 Python 缓存已加入 .gitignore；内置浏览器通过同一个 shop.exe 的隐藏宿主模式运行。

运行测试：
C:\Users\64648\AppData\Local\Programs\Python\Python312\python.exe -m unittest discover -s tests -t . -v

项目结构
- src\：当前应用源码
- tests\：自动化回归测试
- dist\：发布的 shop.exe
- build\：PyInstaller 临时产物和 Python 缓存（已忽略）
- archive\legacy\：旧版源码归档，不参与当前构建

更新记录
2026-04-27
- 使用 shop_NEW.py 重新生成 dist\shop.exe。
- 更新 readme.txt，补充运行、发票导入、用户管理和打包说明。
- 修复发票导入中促销折扣行被当成正数商品的问题。
