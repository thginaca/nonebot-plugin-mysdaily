# -*- coding: utf-8 -*-
"""任务执行异步包装与结果回发。

原 `nonebot_plugin_mysdaily.service.runner.run_tasks` 是同步阻塞调用（内部使用 httpx.Client），
在 NoneBot 异步事件循环中必须通过 `run_in_executor` 放到线程池执行。

执行完成后：
1. 仍然调用原 `notifier.send_push`，走配置中已有的推送渠道（pushplus / telegram / 钉钉 / 飞书 / 邮箱 / qq-HTTP）；
2. 若提供了触发会话（OneBot `Event`），额外用 `bot.call_api` 把结果文本回发给该会话，
   这样在 QQ 里手动触发时无需配置额外推送渠道即可收到结果。
"""

from __future__ import annotations

import asyncio
import pathlib
import threading
from typing import Any, Optional

from nonebot.adapters.onebot.v11 import Bot, Event, MessageSegment
from nonebot.log import logger

from .core.config import load_config, log_path
from .core.logs import append_log, configure_logger, format_line
from .service.notifier import is_task_success, send_push
from .service.runner import run_tasks


class MiyoQianRuntime:
    """MiyoQian 运行时单例：持有配置路径、当前运行状态，提供执行入口。"""

    def __init__(self, config_path: pathlib.Path) -> None:
        self.config_path = config_path
        self._lock = threading.RLock()
        self._running = False

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def load_config(self) -> dict[str, Any]:
        """读取最新配置（每次执行前调用，便于热加载 Web 修改）。"""
        return load_config(self.config_path)

    def log_file(self, config: dict[str, Any]) -> pathlib.Path:
        return log_path(self.config_path, config)

    async def run_and_notify(
        self,
        bot: Optional[Bot],
        reply_event: Optional[Event],
        *,
        account: Optional[str] = None,
        games_only: bool = False,
        bbs_only: bool = False,
        only_games: Optional[list[str]] = None,
        reply: bool = True,
    ) -> list[str]:
        """执行签到任务并推送结果。

        :param bot: OneBot Bot 实例，用于回发结果；定时任务可传 None
        :param reply_event: 触发会话，若 reply=True 且非空则回发该会话
        :param reply: 是否回发触发会话
        """
        if self.running:
            message = "已有签到任务正在执行，请稍后再试"
            if reply and reply_event is not None and bot is not None:
                await _safe_send(bot, reply_event, message)
            return [message]

        with self._lock:
            self._running = True

        config = self.load_config()
        log_file = self.log_file(config)
        configure_logger(log_file)

        collected: list[tuple[str, str]] = []

        def emit_component(message: str, component: str) -> None:
            collected.append((component, message))
            append_log(log_file, format_line(message, component), component=component)

        append_log(log_file, format_line("收到执行请求", "nonebot"), component="nonebot")

        loop = asyncio.get_running_loop()

        def sync_run() -> list[str]:
            return run_tasks(
                config,
                str(self.config_path),
                account,
                games_only,
                bbs_only,
                only_games,
                emit_component=emit_component,
            )

        try:
            lines = await loop.run_in_executor(None, sync_run)
        except Exception as exc:
            logger.opt(exception=True).error("MiyoQian 任务执行失败")
            append_log(log_file, format_line(f"任务执行异常: {exc}", "nonebot"), component="nonebot")
            push_result = send_push(config, "MiyoQian 任务失败", str(exc), success=False)
            if push_result:
                append_log(log_file, format_line(push_result, "push"), component="push")
            if reply and reply_event is not None and bot is not None:
                await _safe_send(bot, reply_event, f"MiyoQian 任务执行失败：{exc}")
            return [f"任务执行失败：{exc}"]
        finally:
            with self._lock:
                self._running = False

        append_log(log_file, format_line("签到任务执行完成", "nonebot"), component="nonebot")
        success = is_task_success(lines)
        push_result = send_push(
            config,
            "MiyoQian 任务完成",
            "\n".join(lines),
            success=success,
        )
        if push_result:
            append_log(log_file, format_line(push_result, "push"), component="push")

        if reply and reply_event is not None and bot is not None:
            text = _format_reply(lines, success)
            await _safe_send(bot, reply_event, text)
        return lines


def _format_reply(lines: list[str], success: bool) -> str:
    """把任务输出格式化为 QQ 友好的文本（控制在合理长度内）。"""
    if not lines:
        return "MiyoQian 任务执行完成，但未产生输出"
    status = "✅ 全部成功" if success else "⚠️ 存在失败项"
    body = "\n".join(lines)
    # QQ 单条消息不宜过长，超过阈值则截断并提示查看日志
    limit = 3500
    if len(body) > limit:
        body = body[:limit] + "\n...（日志过长已截断，完整记录见 logs/mysdaily.log）"
    return f"MiyoQian 任务执行完成 ({status})\n\n{body}"


async def _safe_send(bot: Bot, event: Event, message: str) -> None:
    """发送消息，吞掉异常避免影响主流程。"""
    try:
        await bot.send(event, MessageSegment.text(message))
    except Exception:
        logger.opt(exception=True).warning("回发 MiyoQian 结果失败")


# 全局运行时实例，由插件 __init__.py 在启动钩子里赋值
runtime: Optional[MiyoQianRuntime] = None


def get_runtime() -> MiyoQianRuntime:
    if runtime is None:
        raise RuntimeError("MiyoQian 插件尚未初始化，请检查 on_startup 是否执行")
    return runtime


def set_runtime(value: MiyoQianRuntime) -> None:
    global runtime
    runtime = value
