# -*- coding: utf-8 -*-
"""MysDaily NoneBot2 插件。

把原核心库适配为 NoneBot 插件：
- 复用现有签到/登录/推送逻辑（同步，通过 run_in_executor 调用）
- 用 nonebot_plugin_apscheduler 管理每日定时签到
- 提供 QQ 指令：run / status / login / toggle / reload
"""

from __future__ import annotations

from typing import Optional

from nonebot import get_driver, logger, require
from nonebot.plugin import PluginMetadata

# 声明对 apscheduler 插件的依赖（必须在本插件其他 import 之前）
require("nonebot_plugin_apscheduler")

from .config import Config, get_plugin_config, resolve_config_path
from .matchers import register_matchers
from .runner import MiyoQianRuntime, set_runtime
from .scheduler import setup_daily_job

__plugin_meta__ = PluginMetadata(
    name="MysDaily",
    description="米游社签到、云游戏签到、米游币任务、商品兑换（NoneBot2 插件）",
    usage=(
        "指令前缀默认 myq（可通过 .env 的 MYSDAILY_COMMAND 修改）：\n"
        "  /myq run [账号名] [--games|--bbs] [--game genshin]\n"
        "  /myq status\n"
        "  /myq login [账号名]\n"
        "  /myq toggle game|cloud|bbs on|off\n"
        "  /myq reload\n"
        "权限：超级用户 + 群管理员/群主"
    ),
    type="application",
    homepage="https://github.com/thginaca/nonebot-plugin-mysdaily",
    config=Config,
    supported_adapters={"~onebot.v11"},
)

# ---------------------------------------------------------------------------
# 配置与 matcher 注册
# ---------------------------------------------------------------------------
plugin_config: Config = Config()

# 提前用默认值注册；on_startup 后 matcher 不重注册，因为仅需 command 前缀
register_matchers(plugin_config.mysdaily_command)

_runtime: Optional[MiyoQianRuntime] = None

driver = get_driver()


@driver.on_startup
async def _on_startup() -> None:
    """加载插件配置、初始化运行时并注册每日定时签到任务。"""
    global plugin_config
    old_command = plugin_config.mysdaily_command
    try:
        plugin_config = get_plugin_config()
    except Exception as exc:
        logger.warning(f"读取 .env 配置失败，将使用默认值: {exc}")
        plugin_config = Config()

    # 配置过的指令前缀与默认不一致时，再补注册一次 matcher
    if plugin_config.mysdaily_command != old_command:
        try:
            register_matchers(plugin_config.mysdaily_command)
        except Exception:
            pass

    config_path = resolve_config_path(plugin_config)
    runtime = MiyoQianRuntime(config_path)
    set_runtime(runtime)
    logger.info(f"MysDaily 配置文件: {config_path}")
    setup_daily_job(runtime, plugin_config)


@driver.on_shutdown
async def _on_shutdown() -> None:
    """退出时清理。"""
    logger.info("MysDaily 插件已停止")
