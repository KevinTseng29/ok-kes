"""運行總覽分頁要顯示的資料整理：解析日誌行、生命值、主練牌組進度、裝備欄。

不依賴 Qt 與 ok 套件，方便單元測試；分頁本身在 src/ui/run_overview.py。
"""
import re

# 精簡模式下隱藏的日誌：狀態欄已經顯示、或對看流程沒幫助的除錯訊息
NOISY = (
    'info_set ', 'hwnd_window', 'update_window_size', 'FeatureSet', 'too many', 'DeviceManager',
    'adb_connect', '卡牌识别调试', '金色边框得分', '神闪大图标检测', '是否选中=', '小地图节点',
)
LEVEL_NAMES = {10: 'DEBUG', 20: 'INFO', 30: 'WARNING', 40: 'ERROR', 50: 'CRITICAL'}

_LINE = re.compile(r'^\S+ (\d{2}:\d{2}:\d{2})[,.]\d+ \w+ \S+ ([^:]+):(.*)$', re.S)
_HP = re.compile(r'当前生命值: (\d+)/(\d+)')


def parse_log(line):
    """「2026-10-28 12:55:23,123 INFO TaskExecutor ChaosModeExperimental:內容」→（時間, 來源, 內容）；
    格式不符時整行當內容。"""
    match = _LINE.match(line or '')
    if not match:
        return '', '', (line or '').strip()
    return match.group(1), match.group(2).strip(), match.group(3).strip()


def is_noisy(message):
    return not message.strip() or any(noise in message for noise in NOISY)


def hp_from(message):
    """日誌裡的「当前生命值: 目前/上限」→（目前, 上限）；沒有就回傳 None。"""
    match = _HP.search(message or '')
    return (int(match.group(1)), int(match.group(2))) if match else None


def deck_progress(records, counts, same_name):
    """預設卡組依卡名分組：[(卡名, 已有張數或 None, 需要張數)]。
    records 一條代表一張；counts 是讀牌堆得到的 {卡名: 張數}（還沒讀過就是 None）；
    same_name 比對兩個卡名是否同一張（OCR 與繁簡差異交給呼叫端）。"""
    groups = []
    for record in records or []:
        name = str(record.get('name', '') or '').strip()
        if not name:
            continue
        for group in groups:
            if same_name(group[0], name):
                group[2] += 1
                break
        else:
            groups.append([name, None, 1])
    if counts is not None:
        for group in groups:
            group[1] = sum(n for key, n in counts.items() if same_name(group[0], key))
    return [tuple(group) for group in groups]


def equipment_rows(equipment):
    """裝備狀態 {'names': [...], 'qualities': [...], 'descriptions': [...]} →
    [(號位, 名稱, 品質, 效果)]，沒有裝備的欄位名稱為空字串。"""
    equipment = equipment if isinstance(equipment, dict) else {}

    def column(key):
        values = equipment.get(key)
        values = values if isinstance(values, list) else []
        return [str(v or '') for v in (values + ['', '', ''])[:3]]

    return list(zip((1, 2, 3), column('names'), column('qualities'), column('descriptions')))
