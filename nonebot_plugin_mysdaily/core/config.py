# -*- coding: utf-8 -*-
"""配置加载与保存。"""

from __future__ import annotations

import copy
import pathlib
import random
from typing import Any, Optional

import yaml

from . import crypto

SENSITIVE_ACCOUNT_FIELDS = ("cookie", "stuid", "stoken", "mid")
SUPPORTED_CLOUD_GAME_KEYS = ("genshin", "zzz")

DEFAULT_DEVICE_PRESETS: list[dict[str, str]] = [
    {"name": "Xiaomi 14", "model": "23127PN0CC"},
    {"name": "Xiaomi 13", "model": "2211133C"},
    {"name": "Redmi K70", "model": "2311DRK48C"},
    {"name": "Redmi K60", "model": "23013RK75C"},
    {"name": "OnePlus 12", "model": "PJD110"},
    {"name": "OPPO Find X7", "model": "PHZ110"},
    {"name": "vivo X100", "model": "V2309A"},
    {"name": "HONOR 100", "model": "MAA-AN00"},
    {"name": "HUAWEI Mate 60", "model": "BRA-AL00"},
    {"name": "Samsung Galaxy S23", "model": "SM-S9110"},
]

DEFAULT_CONFIG: dict[str, Any] = {
    "enable": True,
    "accounts": [],
    "storage": {
        "data_dir": "data",
        "credentials_file": "credentials.yaml",
        "log_dir": "logs",
        "log_file": "mysdaily.log",
    },
    "device": {"id": "", "fp": "", "name": "", "model": "", "presets": DEFAULT_DEVICE_PRESETS},
    "features": {"game_checkin": True, "cloud_game_checkin": False, "bbs_tasks": False},
    "captcha": {
        "enable": False,
        "max_retries": 3,
        "channels": [{"provider": "damagou", "enable": False, "userkey": "", "type": "", "timeout": 60}],
    },
    "schedule": {"enable": True, "time": "00:00", "jitter_minutes": 30},
    "games": {
        "enabled": ["genshin", "starrail", "zzz"],
        "black_list": {"genshin": [], "starrail": [], "zzz": []},
    },
    "cloud_games": {
        "enabled": ["genshin", "zzz"],
    },
    "bbs": {
        "forums": [5, 2],
        "checkin": True,
        "read": False,
        "like": False,
        "share": False,
        "cancel_like": True,
        "post_limit": 5,
        "delay_seconds": [1, 3],
    },
    "push": {
        "enable": False,
        "error_only": False,
        "channels": [],
    },
}


def load_config(path: str | pathlib.Path) -> dict[str, Any]:
    config_path = pathlib.Path(path)
    if not config_path.exists():
        config = copy.deepcopy(DEFAULT_CONFIG)
        normalize_config(config)
        return config
    with config_path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"配置文件格式错误: {config_path}")
    config = merge_dict(copy.deepcopy(DEFAULT_CONFIG), loaded)
    normalize_config(config)
    merge_credentials(config, load_credentials(config_path, config))
    normalize_config(config)
    return config


def save_config(path: str | pathlib.Path, config: dict[str, Any]) -> None:
    normalize_config(config)
    config_path = pathlib.Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    save_credentials(credentials_path(config_path, config), config)
    public_config = strip_credentials(config)
    with config_path.open("w", encoding="utf-8", newline="\n") as file:
        yaml.safe_dump(public_config, file, allow_unicode=True, sort_keys=False)


def create_config(path: str | pathlib.Path, force: bool = False) -> pathlib.Path:
    config_path = pathlib.Path(path)
    if config_path.exists() and not force:
        raise FileExistsError(f"配置已存在: {config_path}")
    config = copy.deepcopy(DEFAULT_CONFIG)
    save_config(config_path, config)
    return config_path


def merge_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge_dict(base[key], value)
        else:
            base[key] = value
    return base


def normalize_config(config: dict[str, Any]) -> None:
    storage = config.setdefault("storage", {})
    storage.setdefault("data_dir", "data")
    storage.setdefault("credentials_file", "credentials.yaml")
    storage.setdefault("log_dir", "logs")
    storage.setdefault("log_file", "mysdaily.log")
    cloud_games = config.setdefault("cloud_games", {})
    if not isinstance(cloud_games, dict):
        cloud_games = {}
        config["cloud_games"] = cloud_games
    cloud_games["enabled"] = normalize_cloud_game_enabled(cloud_games.get("enabled", SUPPORTED_CLOUD_GAME_KEYS))
    accounts = config.setdefault("accounts", [])
    if isinstance(accounts, dict):
        config["accounts"] = [accounts]
    # 清理重复账号：按 UID 去重（同一米游社账号只保留一份）；
    # 不同 QQ 可拥有同名子账号，因此不再按 name 全局去重。
    seen_uids: dict[str, dict[str, Any]] = {}
    deduped: list[dict[str, Any]] = []
    for account in config["accounts"]:
        # 旧格式迁移：qq_{数字} / qq_{数字}_{后缀} → 纯子账号名 + qq_user_id
        name = str(account.get("name") or "").strip()
        qq = str(account.get("qq_user_id") or "").strip()
        if not qq and name.startswith("qq_"):
            rest = name[3:]
            if "_" in rest:
                qq_part, suffix = rest.split("_", 1)
                if qq_part.isdigit():
                    account["qq_user_id"] = qq_part
                    account["name"] = suffix
            elif rest.isdigit():
                account["qq_user_id"] = rest
                account["name"] = "main"
        account["name"] = (str(account.get("name") or "").strip() or "main")[:20]
        uid = str(account.get("stuid") or "").strip()
        # 按 UID 去重
        if uid and uid in seen_uids:
            seen_uids[uid].update(account)
            continue
        for field in SENSITIVE_ACCOUNT_FIELDS:
            account.setdefault(field, "")
        deduped.append(account)
        if uid:
            seen_uids[uid] = account
    config["accounts"] = deduped
    device = config.setdefault("device", {})
    first_cookie = str(config["accounts"][0].get("cookie", "")) if config["accounts"] else ""
    presets = device.setdefault("presets", copy.deepcopy(DEFAULT_DEVICE_PRESETS))
    if not isinstance(presets, list) or not presets:
        presets = copy.deepcopy(DEFAULT_DEVICE_PRESETS)
        device["presets"] = presets
    if not device.get("name") or not device.get("model"):
        preset = random.choice([item for item in presets if isinstance(item, dict)] or DEFAULT_DEVICE_PRESETS)
        device["name"] = str(preset.get("name") or DEFAULT_DEVICE_PRESETS[0]["name"])
        device["model"] = str(preset.get("model") or DEFAULT_DEVICE_PRESETS[0]["model"])
    if not device.get("id"):
        device["id"] = crypto.device_id(first_cookie or None)
    if not device.get("fp"):
        device["fp"] = crypto.device_fp()
    captcha = config.setdefault("captcha", {})
    captcha["channels"] = normalize_captcha_channels(captcha)
    captcha["enable"] = any(channel.get("enable") for channel in captcha["channels"])
    try:
        captcha["max_retries"] = max(int(captcha.get("max_retries") or 3), 1)
    except (TypeError, ValueError):
        captcha["max_retries"] = 3
    push = config.setdefault("push", {})
    push["channels"] = normalize_push_channels(push)
    push["enable"] = any(channel.get("enable") for channel in push["channels"])
    push["error_only"] = bool(push.get("error_only", False))
    features = config.setdefault("features", {})
    features.setdefault("game_checkin", True)
    features.setdefault("cloud_game_checkin", False)
    features.setdefault("bbs_tasks", False)
    bbs = config.setdefault("bbs", {})
    if not isinstance(bbs, dict):
        bbs = {}
        config["bbs"] = bbs
    bbs["checkin"] = parse_bool(bbs.get("checkin", True))
    bbs["read"] = False
    bbs["like"] = False
    bbs["share"] = False


def normalize_cloud_game_tokens(value: Any) -> dict[str, str]:
    tokens = value if isinstance(value, dict) else {}
    return {key: str(tokens.get(key) or "") for key in SUPPORTED_CLOUD_GAME_KEYS}


def normalize_cloud_game_enabled(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = list(SUPPORTED_CLOUD_GAME_KEYS)
    enabled: list[str] = []
    for item in raw_items:
        key = str(item or "").strip()
        if key in SUPPORTED_CLOUD_GAME_KEYS and key not in enabled:
            enabled.append(key)
    return enabled


PUSH_CHANNEL_FIELDS: dict[str, tuple[str, ...]] = {
    "pushplus": ("token", "topic"),
    "qq": ("push_url", "access_token", "send_id", "msg_type"),
    "telegram": ("token", "chat_id"),
    "dingrobot": ("webhook", "secret"),
    "feishubot": ("webhook",),
    "email": ("smtp_host", "smtp_port", "smtp_user", "smtp_password", "mail_from", "mail_to", "smtp_ssl"),
}

def normalize_push_channels(push: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = {"pushplus", "telegram", "dingrobot", "feishubot", "email", "qq"}
    raw_channels = push.get("channels")
    if not isinstance(raw_channels, list):
        raw_channels = []

    channels: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_channels:
        if not isinstance(raw, dict):
            continue
        provider = str(raw.get("provider") or "").strip()
        if provider not in allowed or provider in seen:
            continue
        seen.add(provider)
        channel: dict[str, Any] = {
            "provider": provider,
            "enable": parse_bool(raw.get("enable", push.get("enable", False))),
        }
        for field in PUSH_CHANNEL_FIELDS[provider]:
            if field == "smtp_port":
                channel[field] = int(raw.get(field) or 465)
            elif field == "smtp_ssl":
                channel[field] = parse_bool(raw.get(field, True))
            else:
                channel[field] = str(raw.get(field) or "")
        if should_keep_push_channel(channel):
            channels.append(channel)
    return channels


def should_keep_push_channel(channel: dict[str, Any]) -> bool:
    if channel.get("enable"):
        return True
    provider = str(channel.get("provider") or "")
    for field in PUSH_CHANNEL_FIELDS.get(provider, ()):
        if field == "smtp_ssl":
            continue
        if field == "smtp_port":
            if int(channel.get(field) or 465) != 465:
                return True
            continue
        if str(channel.get(field) or "").strip():
            return True
    return False


def normalize_captcha_channels(captcha: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = {"damagou"}
    raw_channels = captcha.get("channels")
    if not isinstance(raw_channels, list):
        raw_channels = []
    if not raw_channels:
        raw_channels = [{"provider": "damagou", "enable": False}]

    channels: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_channels:
        if not isinstance(raw, dict):
            continue
        provider = str(raw.get("provider") or "").strip() or "damagou"
        if provider not in allowed or provider in seen:
            continue
        seen.add(provider)
        try:
            timeout = max(float(raw.get("timeout") or 60), 1)
            normalized_timeout: int | float = int(timeout) if timeout.is_integer() else timeout
        except (TypeError, ValueError):
            normalized_timeout = 60
        channels.append(
            {
                "provider": provider,
                "enable": parse_bool(raw.get("enable", captcha.get("enable", False))),
                "userkey": str(raw.get("userkey") or ""),
                "type": str(raw.get("type") or ""),
                "timeout": normalized_timeout,
            }
        )
    if not any(channel["provider"] == "damagou" for channel in channels):
        channels.append({"provider": "damagou", "enable": False, "userkey": "", "type": "", "timeout": 60})
    return channels


def parse_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def validate_unique_account_uids(config: dict[str, Any]) -> None:
    seen: dict[str, int] = {}
    for index, account in enumerate(config.get("accounts", []), start=1):
        uid = str(account.get("stuid") or "").strip()
        if not uid:
            continue
        if uid in seen:
            raise ValueError(f"UID {uid} 已存在于账号 {seen[uid]}，不能重复添加同一账号")
        seen[uid] = index


def find_account(config: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    accounts = config.get("accounts") or []
    if not accounts:
        raise ValueError("配置中没有账号")
    if name is None:
        return accounts[0]
    key = name.strip()
    # 按 UID 精确匹配（UID 全局唯一，runner 优先走此分支）
    for account in accounts:
        if str(account.get("stuid") or "").strip() == key:
            return account
    # 按子账号名精确匹配
    for account in accounts:
        if account.get("name") == key:
            return account
    # 按 QQ 号匹配（匹配该 QQ 号绑定的第一个账号）
    for account in accounts:
        if str(account.get("qq_user_id") or "").strip() == key:
            return account
    raise ValueError(f"未找到账号: {name}")


def upsert_account(config: dict[str, Any], name: str, data: dict[str, Any]) -> dict[str, Any]:
    accounts = config.setdefault("accounts", [])
    new_uid = str(data.get("stuid") or "").strip()
    new_name = name.strip()
    new_qq = str(data.get("qq_user_id") or "").strip()

    # 1. 优先按 UID 查找（同一米游社账号跨名字合并，更新名字/QQ/凭证）
    if new_uid:
        for account in accounts:
            if str(account.get("stuid") or "").strip() == new_uid:
                account["name"] = new_name
                if new_qq:
                    account["qq_user_id"] = new_qq
                account.update(data)
                return account

    # 2. 按 (qq_user_id, name) 联合查找
    #    注意：若同名子账号已有不同 UID，说明用户用同名绑了不同米游社账号，
    #    此时不应覆盖原 UID（会导致原账号数据丢失），而是拒绝并让用户换名字。
    if new_qq:
        for account in accounts:
            if str(account.get("qq_user_id") or "").strip() == new_qq and account.get("name") == new_name:
                existing_uid = str(account.get("stuid") or "").strip()
                if new_uid and existing_uid and existing_uid != new_uid:
                    raise ValueError(
                        f"子账号名「{new_name}」已绑定 UID={existing_uid}，"
                        f"与扫码登录的 UID={new_uid} 不一致。"
                        f"请换一个子账号名（例如 /myq login {new_name}2），或先 delete 该账号。"
                    )
                account.update(data)
                return account

    # 3. 都没找到，追加新账号
    account = {"name": new_name, **data}
    accounts.append(account)
    return account


def find_user_account(config: dict[str, Any], qq_user_id: str, key: str) -> dict[str, Any]:
    """在指定 QQ 号绑定的账号中，按序号 / 子账号名 / UID 查找账号。"""
    user_accounts = [
        a for a in config.get("accounts", [])
        if str(a.get("qq_user_id") or "") == str(qq_user_id)
    ]
    if not user_accounts:
        raise ValueError("你还没有绑定账号，请先使用 login 扫码登录")
    key = str(key).strip()
    # 序号（从 1 开始）
    if key.isdigit():
        idx = int(key)
        if 1 <= idx <= len(user_accounts):
            return user_accounts[idx - 1]
        raise ValueError(f"序号超出范围，你共绑定 {len(user_accounts)} 个账号")
    # 子账号名精确匹配
    for acc in user_accounts:
        if acc.get("name") == key:
            return acc
    # UID 匹配
    for acc in user_accounts:
        if str(acc.get("stuid") or "") == key:
            return acc
    raise ValueError(f"未找到账号: {key}")


def delete_account(config: dict[str, Any], account: dict[str, Any]) -> bool:
    """从配置中移除指定账号对象。"""
    accounts = config.get("accounts", [])
    for idx, acc in enumerate(accounts):
        if acc is account:
            accounts.pop(idx)
            return True
    return False


def load_credentials(config_path: pathlib.Path, config: dict[str, Any]) -> dict[str, Any]:
    path = credentials_path(config_path, config)
    if not path.exists():
        return {"accounts": []}
    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"凭证文件格式错误: {path}")
    loaded.setdefault("accounts", [])
    return loaded


def save_credentials(path: pathlib.Path, config: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    credentials = {
        "accounts": [
            {
                "name": str(account.get("name") or ""),
                "qq_user_id": str(account.get("qq_user_id") or ""),
                "stuid": str(account.get("stuid") or ""),
                **{field: str(account.get(field) or "") for field in SENSITIVE_ACCOUNT_FIELDS},
                "cloud_games": {
                    "tokens": normalize_cloud_game_tokens(
                        (account.get("cloud_games") or {}).get("tokens", {})
                        if isinstance(account.get("cloud_games"), dict)
                        else {}
                    )
                },
            }
            for index, account in enumerate(config.get("accounts", []), start=1)
        ]
    }
    with path.open("w", encoding="utf-8", newline="\n") as file:
        yaml.safe_dump(credentials, file, allow_unicode=True, sort_keys=False)


def merge_credentials(config: dict[str, Any], credentials: dict[str, Any]) -> None:
    if not config.get("accounts") and credentials.get("accounts"):
        config["accounts"] = [
            {
                "name": str(account.get("name") or ""),
                "qq_user_id": str(account.get("qq_user_id") or ""),
            }
            for account in credentials.get("accounts", [])
            if isinstance(account, dict)
        ]
    credential_list = [
        account
        for account in credentials.get("accounts", [])
        if isinstance(account, dict)
    ]
    # 多用户场景：不同 QQ 可有同名子账号（如各有一个 main），
    # 因此 key 必须用 (qq_user_id, name) 而非仅 name，
    # UID 作为全局唯一主键用于跨配置匹配。
    credential_by_uid: dict[str, dict[str, Any]] = {}
    credential_by_qq_name: dict[tuple[str, str], dict[str, Any]] = {}
    credential_by_name: dict[str, dict[str, Any]] = {}
    # 同时建立「旧 name → 迁移后 name」的映射，兼容旧凭证文件
    credential_by_old_name: dict[str, dict[str, Any]] = {}
    for account in credential_list:
        uid = str(account.get("stuid") or "")
        qq = str(account.get("qq_user_id") or "")
        name = str(account.get("name") or "")
        # 旧格式迁移：凭证里的 name 也可能是 qq_{数字} 格式
        if not qq and name.startswith("qq_"):
            rest = name[3:]
            if "_" in rest:
                qq_part, _suffix = rest.split("_", 1)
                if qq_part.isdigit():
                    qq = qq_part
            elif rest.isdigit():
                qq = rest
        # 从 cookie 兜底提取 UID（旧凭证文件可能没有 stuid 字段）
        if not uid:
            cookie = str(account.get("cookie") or "")
            for part in cookie.split(";"):
                part = part.strip()
                if part.startswith("account_id="):
                    uid = part.split("=", 1)[1].strip()
                    account["stuid"] = uid
                    break
        if uid:
            credential_by_uid.setdefault(uid, account)
        if qq and name:
            credential_by_qq_name.setdefault((qq, name), account)
        if name:
            credential_by_name.setdefault(name, account)
            # 记录原始 name（含 qq_ 前缀）用于反向匹配
            credential_by_old_name.setdefault(name, account)

    for account in config.get("accounts", []):
        uid = str(account.get("stuid") or "")
        qq = str(account.get("qq_user_id") or "")
        name = str(account.get("name") or "")
        saved: Optional[dict[str, Any]] = None
        # 1. UID 全局唯一，优先匹配
        if uid:
            saved = credential_by_uid.get(uid)
        # 2. (qq, name) 联合匹配
        if saved is None and qq and name:
            saved = credential_by_qq_name.get((qq, name))
        # 3. 仅 name 匹配（兼容旧凭证文件，单用户场景）
        if saved is None and name:
            saved = credential_by_name.get(name)
        # 4. 兼容旧凭证：用迁移后的 (qq, name) 或旧 name 反向匹配
        if saved is None and qq:
            # config 里迁移前的旧 name 格式是 qq_{qq}_{suffix} 或 qq_{qq}
            old_name_candidates = [f"qq_{qq}", f"qq_{qq}_{name}"]
            for old_name in old_name_candidates:
                if old_name in credential_by_old_name:
                    saved = credential_by_old_name[old_name]
                    break
        for field in SENSITIVE_ACCOUNT_FIELDS:
            if saved and not account.get(field):
                account[field] = str(saved.get(field) or "")
            else:
                account.setdefault(field, "")
        if saved:
            account["qq_user_id"] = qq or str(saved.get("qq_user_id") or "")
            # 同步 UID（旧 config 骨架可能没有 stuid）
            if not account.get("stuid"):
                account["stuid"] = str(saved.get("stuid") or "")
        merge_account_cloud_game_credentials(account, saved)


def strip_credentials(config: dict[str, Any]) -> dict[str, Any]:
    public_config = copy.deepcopy(config)
    for account in public_config.get("accounts", []):
        for field in SENSITIVE_ACCOUNT_FIELDS:
            account.pop(field, None)
        account.pop("cloud_games", None)
    return public_config


def merge_account_cloud_game_credentials(account: dict[str, Any], saved: dict[str, Any] | None) -> None:
    if saved and isinstance(saved.get("cloud_games"), dict):
        saved_tokens = normalize_cloud_game_tokens((saved.get("cloud_games") or {}).get("tokens", {}))
    else:
        saved_tokens = {}
    cloud_games = account.setdefault("cloud_games", {})
    if not isinstance(cloud_games, dict):
        cloud_games = {}
        account["cloud_games"] = cloud_games
    cloud_games["tokens"] = saved_tokens


def credentials_path(config_path: str | pathlib.Path, config: dict[str, Any]) -> pathlib.Path:
    storage = config.get("storage", {})
    data_dir = resolve_storage_path(config_path, str(storage.get("data_dir") or "data"))
    return data_dir / str(storage.get("credentials_file") or "credentials.yaml")


def log_path(config_path: str | pathlib.Path, config: dict[str, Any]) -> pathlib.Path:
    storage = config.get("storage", {})
    log_dir = resolve_storage_path(config_path, str(storage.get("log_dir") or "logs"))
    return log_dir / str(storage.get("log_file") or "mysdaily.log")


def resolve_storage_path(config_path: str | pathlib.Path, value: str) -> pathlib.Path:
    path = pathlib.Path(value)
    if path.is_absolute():
        return path
    return pathlib.Path(config_path).parent / path
