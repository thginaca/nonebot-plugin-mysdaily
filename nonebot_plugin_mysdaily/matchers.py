# -*- coding: utf-8 -*-
"""QQ 指令处理器。

权限：任何人可触发所有指令。
所有 login 均强制绑定 QQ 号（qq_{user_id}），需要多账号时加后缀（qq_{user_id}_{name}）。

指令结构（前缀默认 `myq`，可通过 .env 的 MYSDAILY_COMMAND 修改）：
    /myq                      显示帮助
    /myq run [账号名]           立即执行签到（不填则全体账号）
    /myq run --games           仅执行游戏社区/云游戏签到
    /myq run --bbs             仅执行米游币社区任务
    /myq run --game genshin    仅执行指定游戏（可重复）
    /myq status [UID|账号名]    查看账号状态（可按 UID 或名称筛选）
    /myq login [账号名]         扫码登录（自动绑定QQ号）
    /myq toggle game|cloud|bbs on|off
    /myq reload                重载配置与定时任务
"""

from __future__ import annotations

import asyncio
import base64
import io
import pathlib
from typing import Optional

import qrcode
from nonebot import on_command
from nonebot.adapters.onebot.v11 import (
    Bot,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.log import logger
from nonebot.params import CommandArg

from .auth.login import QRLogin
from .core import cookies
from .core.config import (
    find_account,
    load_config,
    save_config,
    upsert_account,
)
from .core.http import ApiClient

from .runner import get_runtime
from .scheduler import reload_daily_job


# ---------------------------------------------------------------------------
# 权限：任何人可触发
# ---------------------------------------------------------------------------
ANYONE = None


# ---------------------------------------------------------------------------
# 子命令处理
# ---------------------------------------------------------------------------
def _help_text(command: str) -> str:
    return (
        f"MiyoQian 指令帮助（前缀 {command}）\n"
        f"  {command}                      显示本帮助\n"
        f"  {command} run [账号名]           立即执行签到（不填则全体账号）\n"
        f"  {command} run --games           仅执行游戏社区/云游戏签到\n"
        f"  {command} run --bbs             仅执行米游币社区任务\n"
        f"  {command} run --game <name>     仅执行指定游戏（可重复）\n"
        f"  {command} status [UID|账号名]    查看账号状态（可按 UID 或名称筛选）\n"
        f"  {command} login [账号名]         扫码登录（自动绑定QQ号）\n"
        f"  {command} toggle game|cloud|bbs on|off\n"
        f"  {command} reload                重载配置与定时任务\n"
    )


async def _handle_run(bot: Bot, event: MessageEvent, args: list[str]) -> None:
    runtime = get_runtime()
    account: Optional[str] = None
    games_only = False
    bbs_only = False
    only_games: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--games", "--games-only", "-g"):
            games_only = True
        elif arg in ("--bbs", "--bbs-only", "-b"):
            bbs_only = True
        elif arg in ("--game", "--games"):
            if i + 1 < len(args):
                only_games.append(args[i + 1])
                i += 1
            else:
                await bot.send(event, "参数 --game 需要指定游戏名")
                return
        elif not arg.startswith("-") and account is None:
            account = arg
        else:
            await bot.send(event, f"未识别的参数: {arg}")
            return
        i += 1

    if games_only and bbs_only:
        await bot.send(event, "--games 和 --bbs 不能同时使用")
        return

    await bot.send(event, "⏳ 开始执行 MiyoQian 任务，请稍候…")
    await runtime.run_and_notify(
        bot,
        event,
        account=account,
        games_only=games_only,
        bbs_only=bbs_only,
        only_games=only_games or None,
        reply=True,
    )


async def _handle_status(bot: Bot, event: MessageEvent, args: list[str]) -> None:
    runtime = get_runtime()
    config = runtime.load_config()
    accounts = config.get("accounts", [])
    if not accounts:
        await bot.send(event, "当前没有配置任何账号，请先使用 login 扫码登录")
        return

    # 筛选：支持按完整账号名、UID，或QQ号匹配
    filter_text = args[0] if args else None
    if filter_text:
        matched = []
        for acc in accounts:
            name = acc.get("name", "")
            uid = str(acc.get("stuid", ""))
            qq_id = acc.get("qq_user_id", "")
            if name == filter_text or uid == filter_text:
                matched.append(acc)
            elif qq_id == filter_text or name == f"qq_{filter_text}":
                matched.append(acc)
            elif qq_id and name.startswith(f"qq_{qq_id}_{filter_text}"):
                matched.append(acc)
        if not matched:
            await bot.send(event, f"未找到匹配账号：{filter_text}")
            return
        accounts = matched

    lines = ["【账号列表】"]
    for idx, acc in enumerate(accounts, 1):
        name = acc.get("name", "未命名")
        uid = acc.get("stuid", "")
        cookie_ok = "✅" if acc.get("cookie") else "❌"
        qq_id = acc.get("qq_user_id", "")
        # 简化显示：qq_123456789 → 123456789, qq_123456789_alt → 123456789_alt
        display_name = name
        if qq_id and name.startswith(f"qq_{qq_id}"):
            display_name = name[len("qq_"):]
        line = f"{idx}. {display_name} (UID: {uid or '未登录'}) {cookie_ok}"
        lines.append(line)

    features = config.get("features", {})
    games = config.get("games", {}).get("enabled", [])
    cloud_games = config.get("cloud_games", {}).get("enabled", [])
    lines.append("\n【任务开关】")
    lines.append(f"游戏社区签到: {'✅' if features.get('game_checkin') else '❌'} ({', '.join(games) or '未选择'})")
    lines.append(f"云游戏签到:   {'✅' if features.get('cloud_game_checkin') else '❌'} ({', '.join(cloud_games) or '未选择'})")
    lines.append(f"米游币任务:   {'✅' if features.get('bbs_tasks') else '❌'}")

    sched = config.get("schedule", {})
    from .scheduler import resolve_schedule
    from . import plugin_config

    enable, time_str, jitter = resolve_schedule(config, plugin_config)
    if enable:
        lines.append(f"\n【定时任务】每日 {time_str} 执行，随机波动 ±{jitter} 分钟")
    else:
        lines.append("\n【定时任务】未启用")

    if runtime.running:
        lines.append("\n⏳ 当前有任务正在执行")
    await bot.send(event, "\n".join(lines))


async def _handle_login(bot: Bot, event: MessageEvent, args: list[str]) -> None:
    """扫码登录：在执行器中跑同步 QRLogin，把二维码图片发给触发者。

    群聊中账号自动绑定 QQ 号（qq_{user_id}），私聊中使用给定名字或默认 main。
    """
    runtime = get_runtime()
    config = runtime.load_config()
    device = config["device"]
    timeout = plugin_config_login_timeout()

    # 用 QQ 号绑定账号名，防止不同用户互相覆盖
    qq_user_id = str(event.user_id)
    if args:
        account_name = f"qq_{qq_user_id}_{args[0]}"
    else:
        account_name = f"qq_{qq_user_id}"

    # 检查是否已有同名账号（如果 UID 不同，提醒用户）
    existing = None
    for acc in config.get("accounts", []):
        if acc.get("name") == account_name:
            existing = acc
            break
    if existing:
        existing_uid = existing.get("stuid", "")
        warn_msg = f"⚠️ 已存在账号「{account_name}」(UID: {existing_uid})\n扫码登录将更新此账号的凭证。"
        await bot.send(event, warn_msg)
    else:
        await bot.send(event, f"正在为账号 {account_name} 生成二维码，请稍候…")

    loop = asyncio.get_running_loop()
    holder: dict = {}

    # 步骤1：fetch 拿到 url + ticket，并保留 client/login 实例
    try:
        url = await loop.run_in_executor(None, _fetch_and_keep, holder, config, device)
    except Exception as exc:
        logger.opt(exception=True).error("生成二维码失败")
        await bot.send(event, f"生成二维码失败: {exc}")
        return

    # 异步发送二维码图片
    await bot.send(event, _make_qr_image(url))
    await bot.send(
        event,
        "请用米游社 APP 扫码：我的 -> 左上角扫一扫\n"
        f"等待超时 {timeout} 秒，扫码成功后自动保存凭证…",
    )

    # 步骤2：用同一个 login.wait(ticket) 阻塞等待确认
    try:
        account_data = await loop.run_in_executor(None, _wait_login, holder, timeout)
    except TimeoutError:
        await bot.send(event, "扫码登录超时，请重新执行 login 指令")
        return
    except Exception as exc:
        logger.opt(exception=True).error("扫码登录失败")
        await bot.send(event, f"扫码登录失败: {exc}")
        return

    # 重新加载最新配置并写入凭证
    config = runtime.load_config()
    old_count = len(config.get("accounts", []))
    # 绑定 QQ 号，便于区分不同用户
    account_data["qq_user_id"] = qq_user_id
    upsert_account(config, account_name, account_data)
    save_config(runtime.config_path, config)
    new_count = len(config.get("accounts", []))
    uid = account_data.get("stuid", "")
    msg = f"✅ 账号 {account_name} 登录成功 (UID: {uid}, QQ: {qq_user_id})"
    if new_count > old_count:
        msg += f"，当前共 {new_count} 个账号"
    else:
        msg += "，已更新凭证"
    await bot.send(event, msg)


async def _handle_toggle(bot: Bot, event: MessageEvent, args: list[str]) -> None:
    if len(args) < 2:
        await bot.send(event, "用法: toggle game|cloud|bbs on|off")
        return
    key_map = {"game": "game_checkin", "cloud": "cloud_game_checkin", "bbs": "bbs_tasks"}
    key = key_map.get(args[0].lower())
    if not key:
        await bot.send(event, f"未知任务: {args[0]}，可选 game/cloud/bbs")
        return
    value = args[1].lower()
    if value in ("on", "1", "true", "开"):
        enable = True
    elif value in ("off", "0", "false", "关"):
        enable = False
    else:
        await bot.send(event, f"未知开关值: {args[1]}，可选 on/off")
        return

    runtime = get_runtime()
    config = runtime.load_config()
    config.setdefault("features", {})[key] = enable
    save_config(runtime.config_path, config)
    label = {"game_checkin": "游戏社区签到", "cloud_game_checkin": "云游戏签到", "bbs_tasks": "米游币任务"}[key]
    await bot.send(event, f"已{'开启' if enable else '关闭'} {label}")


async def _handle_reload(bot: Bot, event: MessageEvent) -> None:
    runtime = get_runtime()
    from . import plugin_config

    reload_daily_job(runtime, plugin_config)
    await bot.send(event, "✅ 配置已重载，定时任务已更新")


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _make_qr_image(text: str) -> MessageSegment:
    """生成二维码图片，返回 OneBot image 消息段（base64 前缀，兼容性最好）。"""
    image = qrcode.make(text)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    encoded = base64.b64encode(stream.getvalue()).decode("ascii")
    return MessageSegment.image(f"base64://{encoded}")


def _fetch_and_keep(holder: dict, config: dict, device: dict) -> str:
    """生成二维码，并把 ApiClient / QRLogin / ticket 保留在 holder 里供后续 wait 使用。"""
    client = ApiClient()
    login = QRLogin(
        client,
        str(device["id"]),
        str(device["fp"]),
        str(device.get("model") or "Mi 14"),
        str(device.get("name") or "Mihoyo Capture"),
    )
    url, ticket = login.fetch()
    holder["client"] = client
    holder["login"] = login
    holder["ticket"] = ticket
    return url


def _wait_login(holder: dict, timeout: int) -> dict[str, str]:
    """用同一个 login/ticket 阻塞等待扫码确认，完成后关闭 client。"""
    login: QRLogin = holder["login"]
    client = holder.get("client")
    try:
        scan = login.wait(holder["ticket"], timeout=timeout)
        account_data = {**scan, **login.get_additional_tokens(scan["stoken"], scan["mid"])}
        account_data["cookie"] = cookies.build_cookie(
            account_data["stuid"],
            account_data["mid"],
            account_data["ltoken"],
            account_data["cookie_token"],
        )
        return account_data
    finally:
        if client is not None:
            client.close()


def plugin_config_login_timeout() -> int:
    from . import plugin_config

    return plugin_config.mysdaily_login_timeout


# ---------------------------------------------------------------------------
# 主指令注册
# ---------------------------------------------------------------------------
def register_matchers(command: str) -> None:
    """根据配置的指令前缀注册主命令。"""

    main = on_command(command, permission=ANYONE, priority=10, block=True)

    @main.handle()
    async def _dispatch(bot: Bot, event: MessageEvent, args: Message = CommandArg()):
        raw = args.extract_plain_text().strip()
        if not raw:
            await bot.send(event, _help_text(command))
            return

        parts = raw.split()
        sub = parts[0].lower()
        rest = parts[1:]

        if sub in ("run", "执行", "签到"):
            await _handle_run(bot, event, rest)
        elif sub in ("status", "状态", "st"):
            await _handle_status(bot, event, rest)
        elif sub in ("login", "登录", "扫码"):
            await _handle_login(bot, event, rest)
        elif sub in ("toggle", "开关"):
            await _handle_toggle(bot, event, rest)
        elif sub in ("reload", "重载"):
            await _handle_reload(bot, event)
        elif sub in ("help", "帮助", "?", "？"):
            await bot.send(event, _help_text(command))
        else:
            await bot.send(event, f"未知子命令: {sub}\n\n" + _help_text(command))
