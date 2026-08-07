# -*- coding: utf-8 -*-
"""基于 nonebot_plugin_apscheduler 的每日签到调度。

替代原 `mysdaily_core.service.scheduler.DailyScheduler`（基于 threading），
与 NoneBot 生命周期一致，无需额外线程，重启 bot 即重新注册任务。
"""

from __future__ import annotations

from typing import Optional

from nonebot.log import logger
from nonebot_plugin_apscheduler import scheduler

from .config import Config
from .runner import MiyoQianRuntime

JOB_ID = "mysdaily_checkin"


def _parse_time(value: str) -> tuple[int, int]:
    parts = value.strip().split(":", 1)
    if len(parts) != 2:
        raise ValueError("schedule.time 必须是 HH:MM 格式")
    hour = int(parts[0])
    minute = int(parts[1])
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("schedule.time 超出范围")
    return hour, minute


def resolve_schedule(config_yaml: dict, plugin_config: Config) -> tuple[bool, str, int]:
    """合并 .env 与 config.yaml 的调度配置，.env 优先。"""
    sched = config_yaml.get("schedule") or {}
    enable = (
        plugin_config.mysdaily_schedule_enable
        if plugin_config.mysdaily_schedule_enable is not None
        else bool(sched.get("enable", False))
    )
    time_str = (
        plugin_config.mysdaily_schedule_time.strip()
        or str(sched.get("time", "00:00"))
    )
    jitter = (
        plugin_config.mysdaily_schedule_jitter
        if plugin_config.mysdaily_schedule_jitter > 0
        else int(sched.get("jitter_minutes", 30) or 0)
    )
    return enable, time_str, max(jitter, 0)


async def _daily_job(runtime: MiyoQianRuntime) -> None:
    """定时任务实际执行函数：不回发会话，只走配置的推送渠道。"""
    logger.info("MiyoQian 定时任务触发，开始执行")
    await runtime.run_and_notify(
        bot=None,
        reply_event=None,
        reply=False,
    )


def setup_daily_job(runtime: MiyoQianRuntime, plugin_config: Config) -> None:
    """根据当前配置注册/更新每日签到任务。"""
    config_yaml = runtime.load_config()
    enable, time_str, jitter_minutes = resolve_schedule(config_yaml, plugin_config)

    # 移除旧任务（无论是否启用都先清理）
    if scheduler.get_job(JOB_ID):
        scheduler.remove_job(JOB_ID)

    if not enable:
        logger.info("MiyoQian 每日调度已禁用，不注册定时任务")
        return

    try:
        hour, minute = _parse_time(time_str)
    except ValueError as exc:
        logger.error(f"MiyoQian 调度时间配置无效: {exc}")
        return

    # APScheduler 的 jitter 单位是秒，在触发时间基础上随机偏移
    jitter_seconds = jitter_minutes * 60
    scheduler.add_job(
        _daily_job,
        "cron",
        id=JOB_ID,
        args=[runtime],
        hour=hour,
        minute=minute,
        jitter=jitter_seconds if jitter_seconds > 0 else None,
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    jitter_desc = f"，随机波动 ±{jitter_minutes} 分钟" if jitter_minutes > 0 else ""
    logger.info(f"MiyoQian 定时任务已注册：每日 {time_str}{jitter_desc}")


def reload_daily_job(runtime: MiyoQianRuntime, plugin_config: Config) -> None:
    """配置变更后重新注册任务。"""
    setup_daily_job(runtime, plugin_config)
