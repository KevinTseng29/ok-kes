"""每一局探險結果的戰績存檔（configs/run_stats.json），重啟 ok-kes 也不歸零。

任務在探險結果頁判定成功／失敗時呼叫 record()（每局記下模式）；運行總覽分頁用 summary() 分模式顯示「今日」與「全部」。
只保留最近 MAX_ROUNDS 局的明細。本模組不依賴 ok 套件，方便單元測試。
"""
import json
import os
import threading
import time

STATS_FILE = os.path.join('configs', 'run_stats.json')
MAX_ROUNDS = 5000
_lock = threading.Lock()
_cache = {'path': None, 'mtime': None, 'data': None}


def _empty(now):
    return {'since': time.strftime('%Y-%m-%d %H:%M', time.localtime(now)), 'rounds': []}


def _load(path):
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    if _cache['path'] == path and _cache['mtime'] == mtime:
        return _cache['data']
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get('rounds'), list):
        return None
    _cache.update(path=path, mtime=mtime, data=data)
    return data


def _save(path, data):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    temp = path + '.tmp'
    with open(temp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(temp, path)


def record(success, mode='', path=STATS_FILE, now=None):
    """記下一局的結果。"""
    now = time.time() if now is None else now
    with _lock:
        data = _load(path) or _empty(now)
        data['rounds'].append({'time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now)),
                               'mode': mode, 'success': bool(success)})
        del data['rounds'][:-MAX_ROUNDS]
        _save(path, data)


def reset(path=STATS_FILE, now=None):
    """清空戰績，從現在重新累計。"""
    with _lock:
        _save(path, _empty(time.time() if now is None else now))


def _count(rounds):
    wins = sum(1 for r in rounds if r.get('success'))
    return wins, len(rounds) - wins


def summary(path=STATS_FILE, now=None, modes=None):
    """回傳 {'today': (勝, 敗), 'total': (勝, 敗), 'since': 開始累計時間, 'last': 最後一局或 None}。
    modes 給了就只算這些模式（任務類別名稱）的局，例如卡厄思與出擊分開算。"""
    now = time.time() if now is None else now
    data = _load(path) or _empty(now)
    rounds = [r for r in data['rounds'] if modes is None or r.get('mode') in modes]
    today = time.strftime('%Y-%m-%d', time.localtime(now))
    return {
        'today': _count([r for r in rounds if str(r.get('time', '')).startswith(today)]),
        'total': _count(rounds),
        'since': data.get('since', ''),
        'last': rounds[-1] if rounds else None,
    }


def rate_text(wins, losses):
    """「6 勝 1 敗（86%）」；還沒有局數時只顯示「0 勝 0 敗」。"""
    total = wins + losses
    text = f'{wins} 勝 {losses} 敗'
    return f'{text}（{round(wins * 100 / total)}%）' if total else text
