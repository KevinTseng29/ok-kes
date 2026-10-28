"""每一局探險結果的戰績存檔（configs/run_stats.json），重啟 ok-kes 也不歸零。

任務在探險結果頁判定成功／失敗時呼叫 record()（每局記下模式、各層選的命運、打過幾層）；
運行總覽分頁用 summary() 分模式顯示「今日」與「全部」，fate_summary() 統計各命運被選次數與選過的局勝率。
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


def record(success, mode='', path=STATS_FILE, now=None, fates=None, floors=None):
    """記下一局的結果。fates 是這局選的命運 [{'floor': 層, 'name': 名稱}]，floors 是打過的層數。"""
    now = time.time() if now is None else now
    entry = {'time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now)), 'mode': mode, 'success': bool(success)}
    if fates:
        entry['fates'] = [{'floor': int(f.get('floor', 0)), 'name': str(f.get('name', ''))} for f in fates]
    if floors is not None:
        entry['floors'] = int(floors)
    with _lock:
        data = _load(path) or _empty(now)
        data['rounds'].append(entry)
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


def fate_summary(path=STATS_FILE, modes=None):
    """各命運的統計，選過次數多的在前：[{'name', 'picks', 'floors': {層: 次數}, 'wins', 'losses'}]。
    wins／losses 算的是「選過這個命運的局」（同一局選兩次只算一局）。"""
    data = _load(path) or _empty(time.time())
    stats = {}
    for r in data['rounds']:
        if modes is not None and r.get('mode') not in modes:
            continue
        seen = set()
        for fate in r.get('fates') or []:
            name = fate.get('name', '')
            if not name:
                continue
            item = stats.setdefault(name, {'name': name, 'picks': 0, 'floors': {}, 'wins': 0, 'losses': 0})
            item['picks'] += 1
            floor = fate.get('floor', 0)
            item['floors'][floor] = item['floors'].get(floor, 0) + 1
            if name not in seen:
                seen.add(name)
                item['wins' if r.get('success') else 'losses'] += 1
    return sorted(stats.values(), key=lambda item: (-item['picks'], item['name']))


def rate_text(wins, losses):
    """「6 勝 1 敗（86%）」；還沒有局數時只顯示「0 勝 0 敗」。"""
    total = wins + losses
    text = f'{wins} 勝 {losses} 敗'
    return f'{text}（{round(wins * 100 / total)}%）' if total else text
