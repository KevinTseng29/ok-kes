"""運行總覽上的本機開關（configs/run_switches.json），重啟 ok-kes 也記得。

不放進任務設定：任務設定會被 config_sync 上傳，任務設定不加欄位。本模組不依賴 ok 套件，方便單元測試。
"""
import json
import os

SWITCHES_FILE = os.path.join('configs', 'run_switches.json')
# 出擊：理性用完（跳出「補充理性」）就打完這局停止，之後的戰利品領不了，繼續打意義不大
STOP_WHEN_RATIONAL_EXHAUSTED = 'stop_when_rational_exhausted'
DEFAULTS = {STOP_WHEN_RATIONAL_EXHAUSTED: True}


def _load(path):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def get(name, path=SWITCHES_FILE):
    return bool(_load(path).get(name, DEFAULTS.get(name, False)))


def set_switch(name, value, path=SWITCHES_FILE):
    data = _load(path)
    data[name] = bool(value)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    temp = path + '.tmp'
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(temp, path)
