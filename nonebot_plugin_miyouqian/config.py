# -*- coding: utf-8 -*-
"""NoneBot 插件配置（从 .env 读取）。

兼容性要点：
- 优先使用 nonebot.plugin.get_plugin_config（NoneBot 2.2+）
- 老版本通过 driver.config.dict() 取全局配置，再手动构造
- 从 .env 读取的值可能是字符串，需要做类型转换
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

try:
    from nonebot.plugin import get_plugin_config as _nb_get_plugin_config
except Exception:
    _nb_get_plugin_config = None  # type: ignore


class Config(BaseModel):
    """米游签插件配置。"""

    miyouqian_config_path: str = Field(
        default="",
        description="米游签 config.yaml 路径，留空则使用插件目录",
    )
    miyouqian_command: str = Field(
        default="myq",
        description="米游签指令前缀，例如 myq -> /myq run",
    )
    miyouqian_schedule_enable: Optional[bool] = Field(
        default=None,
        description="是否启用每日定时签到，留空读取 config.yaml",
    )
    miyouqian_schedule_time: str = Field(
        default="",
        description="每日执行时间 HH:MM，留空读取 config.yaml",
    )
    miyouqian_schedule_jitter: int = Field(
        default=0,
        description="随机延后分钟数，<=0 表示读取 config.yaml",
    )
    miyouqian_reply_on_run: bool = Field(
        default=True,
        description="手动执行签到后是否把结果回复给触发者",
    )
    miyouqian_login_timeout: int = Field(
        default=120,
        description="扫码登录等待超时秒数",
    )


def _coerce_bool(value: Any) -> Any:
    """把 .env 里常见的 'true'/'1'/'on' 字符串转为 bool。"""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "on", "yes", "y", "是"):
            return True
        if v in ("false", "0", "off", "no", "n", "否", "", "null", "none"):
            return False if v in ("false", "0", "off", "no", "n", "否") else None
    return value


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_plugin_config() -> Config:
    """跨 NoneBot 版本安全地读取插件配置。"""
    from nonebot import get_driver

    raw: dict[str, Any] = {}

    # 1) 尝试新版 API
    if _nb_get_plugin_config is not None:
        try:
            cfg = _nb_get_plugin_config(Config)
            if cfg is not None:
                return cfg  # type: ignore[return-value]
        except Exception:
            pass

    # 2) 兜底：从 driver.config 拿全局配置并过滤 MIYOUQIAN_ 前缀
    driver = get_driver()
    if hasattr(driver.config, "dict"):
        try:
            raw = driver.config.dict()
        except Exception:
            raw = {k: getattr(driver.config, k) for k in dir(driver.config) if not k.startswith("_")}
    else:
        raw = {k: getattr(driver.config, k) for k in dir(driver.config) if not k.startswith("_")}

    # 只挑 miyouqian_ 前缀的项
    mq_cfg: dict[str, Any] = {}
    for key in ("config_path", "command", "schedule_enable", "schedule_time",
                "schedule_jitter", "reply_on_run", "login_timeout"):
        raw_key = f"miyouqian_{key}"
        if raw_key in raw:
            mq_cfg[key] = raw[raw_key]

    # 类型转换
    if "schedule_enable" in mq_cfg:
        mq_cfg["schedule_enable"] = _coerce_bool(mq_cfg["schedule_enable"])
    if "reply_on_run" in mq_cfg:
        mq_cfg["reply_on_run"] = bool(_coerce_bool(mq_cfg["reply_on_run"]))
    if "schedule_jitter" in mq_cfg:
        mq_cfg["schedule_jitter"] = _coerce_int(mq_cfg["schedule_jitter"], 0)
    if "login_timeout" in mq_cfg:
        mq_cfg["login_timeout"] = _coerce_int(mq_cfg["login_timeout"], 120)

    return Config(**{f"miyouqian_{k}": v for k, v in mq_cfg.items()})


def resolve_config_path(plugin_config: Config) -> "pathlib.Path":
    """返回米游签 config.yaml 的实际路径，必要时复制示例配置。"""
    import pathlib
    import shutil

    explicit = plugin_config.miyouqian_config_path.strip()
    if explicit:
        path = pathlib.Path(explicit).expanduser().resolve()
    else:
        path = (pathlib.Path(__file__).resolve().parent / "config.yaml").resolve()

    if not path.exists():
        repo_example = (
            pathlib.Path(__file__).resolve().parents[1] / "config.example.yaml"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        if repo_example.exists():
            shutil.copyfile(repo_example, path)
        else:
            path.touch()
    return path
