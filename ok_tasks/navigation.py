"""回大廳與各模式入口（參考 ALAS 的 ui_goto_main 與頁面導航）。

國際服實測的 UI 結構（MuMu 1280x720）：
- 大廳右側有固定選單：故事、出擊、模擬、卡厄思、方舟都市、戰鬥員、救援。
  閒置一段時間後 UI 會整個隱藏，只剩立繪，點一下空白處才會出現。
- 子頁共用標頭：左上是返回鍵加頁名，右上是「回大廳」⌂ 與全域選單 ≡。
- 卡厄思模式：大廳 → 卡厄思 → 零號系統；出擊模式：大廳 → 出擊。
  之後的頁面（零號系統首頁點法典、出擊頁點進入）交給各模式原本的處理函式。

handle_chaos_navigation / handle_sortie_navigation 是 PAGE_HANDLERS 形式：
每輪看一次畫面，需要時做一步並回傳 True。它們取代原本的 handle_non_battle_page
（看到大廳、營救、方舟城市就停止）；把 NAV 的兩個開關設成 False 即可恢復成停止。

run() 已把 OCR 文字轉成簡體，所以這裡比對的都是簡體；國服與國際服用詞不同時兩種都列。
設定集中在 NAV。本模組不依賴 ok 套件，方便單元測試。
"""

import re
import time
from dataclasses import dataclass


@dataclass
class NavigationSettings:
    # 在大廳時自動進入目前的模式；False 時維持原本「回到大廳就停止」
    enter_mode_from_lobby: bool = True
    # 卡厄思頁要點哪張卡：'零号系统' 或 '卡厄思显现'
    chaos_entry: str = '零号系统'
    # 誤入其他功能頁（救援、方舟都市等）時按「回大廳」；False 時改為停止
    leave_foreign_pages: bool = True
    # 畫面完全沒有文字超過這個秒數，就點一下空白處喚醒大廳 UI
    wake_after_blank: float = 6.0
    # 導航點擊後等待畫面切換的秒數
    transition_wait: float = 2.0


NAV = NavigationSettings()

# 相對座標，依國際服 1280x720 實測
LOBBY_MENU_REGION = (0.78, 0.08, 1.0, 0.80)
TITLE_REGION = (0.05, 0.0, 0.32, 0.09)
CHAOS_CARD_REGION = (0.0, 0.55, 1.0, 0.95)
HOME_BUTTON = (0.898, 0.050)
# 大廳立繪的位置，點了只會觸發角色台詞
WAKE_POINT = (0.35, 0.40)

# 大廳選單裡國服與國際服寫法相同的項目，出現兩個以上就當作在大廳
LOBBY_MARKERS = ('故事', '出击', '卡厄思')

CHAOS_MENU_TITLE = '卡厄思'
CHAOS_ENTRIES = {
    '零号系统': ('零号系统', '零式系统'),
    '卡厄思显现': ('卡厄思显现',),
}

# 誤入時要離開的子頁標題。不含「故事」：劇情裡的戰鬥與卡厄思關卡會手動開啟
# 出擊／卡厄思模式，打完會回到故事頁，不能把它當成走錯頁。
_COMMON_FOREIGN_TITLES = ('救援', '营救', '方舟都市', '方舟城市')
CHAOS_FOREIGN_TITLES = _COMMON_FOREIGN_TITLES + ('出击',)
SORTIE_FOREIGN_TITLES = _COMMON_FOREIGN_TITLES + ('卡厄思', '卡厄思显现', '零号系统', '零式系统')


def _clean(text):
    return re.sub(r'[^一-鿿\w]', '', text or '')


def _center_in(task, box, region):
    cx = (box.x + box.width / 2) / task.width
    cy = (box.y + box.height / 2) / task.height
    x1, y1, x2, y2 = region
    return x1 <= cx <= x2 and y1 <= cy <= y2


def _find(task, names, region):
    """在區域內找文字完全等於 names 其中之一的 OCR 框。"""
    for box in task.all_texts or []:
        if _clean(box.name) in names and _center_in(task, box, region):
            return box
    return None


def is_lobby(task):
    """大廳：右側選單出現至少兩個固定項目。"""
    found = {_clean(b.name) for b in task.all_texts or [] if _center_in(task, b, LOBBY_MENU_REGION)}
    return sum(marker in found for marker in LOBBY_MARKERS) >= 2


def click_home(task, reason):
    """按子頁右上角的「回大廳」。"""
    task.log_info(f'{reason}，點擊回大廳')
    task.click(*HOME_BUTTON)
    task.sleep(NAV.transition_wait)


def _enter_from_lobby(task, menu_name, mode_name):
    if not NAV.enter_mode_from_lobby:
        task.log_info('回到大廳，停止目前模式')
        task.disable()
        return True
    box = _find(task, (menu_name,), LOBBY_MENU_REGION)
    if not box:
        return False
    task.log_info(f'在大廳，點擊「{menu_name}」進入{mode_name}')
    task.click_box(box, after_sleep=0)
    task.sleep(NAV.transition_wait)
    return True


def _leave_foreign_page(task, titles):
    box = _find(task, titles, TITLE_REGION)
    if not box:
        return False
    page = _clean(box.name)
    if not NAV.leave_foreign_pages:
        task.log_info(f'檢測到「{page}」頁面，停止目前模式')
        task.disable()
        return True
    click_home(task, f'誤入「{page}」頁面')
    return True


def _wake_blank_screen(task):
    """畫面持續沒有任何文字（大廳閒置時會隱藏 UI）時，點一下立繪處喚醒。"""
    now = time.time()
    if task.all_texts:
        task._nav_blank_since = None
        return False
    last_seen = getattr(task, '_nav_blank_last', 0)
    task._nav_blank_last = now
    since = getattr(task, '_nav_blank_since', None)
    # 中間有其他處理函式接手過（隔太久才再呼叫），就重新計時
    if since is None or now - last_seen > 3:
        task._nav_blank_since = now
        return False
    if now - since < NAV.wake_after_blank:
        return False
    task.log_info(f'畫面已 {now - since:.0f} 秒沒有文字，點擊空白處喚醒介面')
    task._nav_blank_since = now
    task.click(*WAKE_POINT)
    task.sleep(1)
    return True


def handle_chaos_navigation(task):
    """卡厄思模式的導航：大廳 → 卡厄思 → 零號系統；誤入其他功能頁就回大廳。"""
    if is_lobby(task):
        return _enter_from_lobby(task, '卡厄思', '卡厄思模式')
    if _find(task, (CHAOS_MENU_TITLE,), TITLE_REGION):
        names = CHAOS_ENTRIES.get(NAV.chaos_entry, CHAOS_ENTRIES['零号系统'])
        card = _find(task, names, CHAOS_CARD_REGION)
        if card:
            task.log_info(f'在卡厄思頁，點擊「{_clean(card.name)}」')
            task.click_box(card, after_sleep=0)
            task.sleep(NAV.transition_wait)
            return True
    if _leave_foreign_page(task, CHAOS_FOREIGN_TITLES):
        return True
    return _wake_blank_screen(task)


def handle_sortie_navigation(task):
    """出擊模式的導航：大廳 → 出擊；誤入其他功能頁就回大廳。"""
    if is_lobby(task):
        return _enter_from_lobby(task, '出击', '出擊模式')
    if _leave_foreign_page(task, SORTIE_FOREIGN_TITLES):
        return True
    return _wake_blank_screen(task)
