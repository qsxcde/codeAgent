"""应用组合根的按职责拆分实现。

跨层装配只应发生在本包和 ``app.container`` / ``app.main`` 中。
实现模块不得反向导入 ``app.container``；对外兼容入口由 façade 统一导出。
"""

