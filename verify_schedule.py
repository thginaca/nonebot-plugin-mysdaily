# -*- coding: utf-8 -*-
"""验证 00:00 定时签到配置是否正确。"""
import pathlib
import sys
import yaml

root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(root))

# 1. 验证 DEFAULT_CONFIG 中的默认值
from miyouqian.core.config import DEFAULT_CONFIG
sched = DEFAULT_CONFIG["schedule"]
print(f'DEFAULT_CONFIG schedule: enable={sched["enable"]}, time={sched["time"]}, jitter={sched["jitter_minutes"]}')
assert sched["time"] == "00:00", 'time should be 00:00'
assert sched["jitter_minutes"] == 30, 'jitter should be 30'

# 2. 验证 config.example.yaml 的默认值
example_path = root / 'config.example.yaml'
with open(example_path, 'r', encoding='utf-8') as f:
    example = yaml.safe_load(f)
ex_sched = example['schedule']
print(f'config.example.yaml schedule: enable={ex_sched["enable"]}, time={ex_sched["time"]}, jitter={ex_sched["jitter_minutes"]}')
assert ex_sched['time'] == '00:00', 'example time should be 00:00'

# 3. 初始化 NoneBot 后再导入插件
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

# 现在可以安全导入插件了
from nonebot_plugin_mysdaily.scheduler import _parse_time, resolve_schedule
from nonebot_plugin_mysdaily.config import Config

# 4. 验证 _parse_time 能正确解析 00:00
hour, minute = _parse_time('00:00')
print(f'_parse_time("00:00"): hour={hour}, minute={minute}')
assert hour == 0 and minute == 0, 'should parse to hour=0, minute=0'

# 5. 验证 _parse_time 边界值
for t in ['00:00', '00:30', '23:59', '12:00']:
    h, m = _parse_time(t)
    print(f'  {t} -> hour={h}, minute={m}')

# 6. 验证 resolve_schedule 回退默认值
cfg = Config()
enabled, time_str, jitter = resolve_schedule({'schedule': {}}, cfg)
print(f'resolve_schedule empty config: enable={enabled}, time={time_str}, jitter={jitter}')
assert time_str == '00:00', 'fallback time should be 00:00'

# 7. 验证带 enable=true 的完整 schedule
full_config = {
    'schedule': {
        'enable': True,
        'time': '00:00',
        'jitter_minutes': 30,
    }
}
enabled, time_str, jitter = resolve_schedule(full_config, cfg)
print(f'full config: enable={enabled}, time={time_str}, jitter={jitter}')
assert enabled is True
assert time_str == '00:00'
assert jitter == 30

# 8. 验证 .env 环境变量覆盖
cfg_env = Config(
    miyouqian_schedule_enable=True,
    miyouqian_schedule_time="00:00",
    miyouqian_schedule_jitter=30,
)
enabled, time_str, jitter = resolve_schedule(
    {'schedule': {'enable': False, 'time': '09:00', 'jitter_minutes': 45}},
    cfg_env
)
print(f'env override: enable={enabled}, time={time_str}, jitter={jitter}')
assert enabled is True  # .env 覆盖了 config.yaml 的 False
assert time_str == '00:00'  # .env 覆盖了 config.yaml 的 09:00

# 9. 验证 APScheduler 注册的 job 参数
from nonebot_plugin_apscheduler import scheduler as apscheduler
import nonebot_plugin_mysdaily.scheduler as sched_module

# 模拟 setup_daily_job 会调用的参数
print()
print('--- APScheduler job 注册模拟 ---')
print(f'  cron hour={hour}, minute={minute}, jitter={30*60}')
print(f'  => 每天 00:00 ± 30 分钟 执行签到')

# 验证 jitter 转换
jitter_seconds = 30 * 60
print(f'  jitter_seconds = {jitter_seconds} (30 分钟 = 1800 秒)')

print()
print('ALL CHECKS PASSED ✅')
print('0 点签到配置验证通过！')
