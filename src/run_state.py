"""卡厄思這一局的主練狀態（目前是裝備欄）存檔，重啟 ok-kes 不會忘記已經裝了什麼。

裝備名稱只有腳本自己裝上去時才知道；重啟後記錄是空的，腳本會以為裝備欄沒東西，
下一件同號位、有列在優先級的裝備就可能把稀有裝備（例如混沌指控）換掉。
任務每輪有變化就 save()，重啟後第一輪 load() 讀回；一局結束時 clear()。
存在 configs/run_state.json，依任務類別分開；超過 MAX_AGE 秒的舊紀錄不讀。
本模組不依賴 ok 套件，方便單元測試。
"""
import json
import os
import threading
import time

STATE_FILE = os.path.join('configs', 'run_state.json')
MAX_AGE = 3 * 3600
_lock = threading.Lock()


def _read(path):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path, data):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    temp = path + '.tmp'
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(temp, path)


def save(name, state, path=STATE_FILE, now=None):
    with _lock:
        data = _read(path)
        data[name] = {'saved_at': time.time() if now is None else now, 'state': state}
        _write(path, data)


def load(name, path=STATE_FILE, now=None, max_age=MAX_AGE):
    """這個任務最近一次存的狀態；沒有或太舊回傳 None。"""
    entry = _read(path).get(name)
    if not isinstance(entry, dict) or not isinstance(entry.get('state'), dict):
        return None
    now = time.time() if now is None else now
    if now - float(entry.get('saved_at', 0) or 0) > max_age:
        return None
    return entry['state']


def clear(name, path=STATE_FILE):
    with _lock:
        data = _read(path)
        if data.pop(name, None) is not None:
            _write(path, data)
