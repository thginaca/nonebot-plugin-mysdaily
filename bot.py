# -*- coding: utf-8 -*-
"""NoneBot 启动入口。

运行方式：
    python bot.py
或：
    nb run

首次运行前请复制 .env.example 为 .env 并填写 SUPERUSERS 与 OneBot 连接信息。
"""

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

nonebot.init()

driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

# 加载插件（也可通过 .env 的 PLUGINS 配置加载，二选一）
nonebot.load_from_toml("pyproject.toml")

if __name__ == "__main__":
    nonebot.run()
