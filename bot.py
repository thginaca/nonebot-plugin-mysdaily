# -*- coding: utf-8 -*-
"""MysDaily NoneBot 启动入口。

两种加载方式二选一:
  方式 A (推荐): 使用 require() 加载本插件
  方式 B:        在 pyproject.toml 的 [tool.nonebot] plugins 中配置

首次运行前请复制 .env.example 为 .env 并填写 SUPERUSERS 与 OneBot 连接信息。
"""

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

# ---- 方式 A: 用 require() 加载本插件（推荐） ----
# 使用这种方式时，不要在 .env 的 PLUGINS 或 pyproject.toml 中重复配置
nonebot.require("nonebot_plugin_mysdaily")

# ---- 方式 B: 通过 pyproject.toml 加载（替代上面那行） ----
# 取消下面两行的注释，并注释掉上面的 require 行
# nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
