"""對話框推進：畫面上只有一段台詞時，點那段台詞讓對話前進。

國際服局內與地圖上的對話沒有「自動」或「跳過」按鈕，劇情模式的 handle_auto_chat／
handle_skip_story 認不到；卡住兜底又不再亂點，對話就停住。實際看到的有幾種（error_scenes 實測）：
- 左上角頭像＋台詞框，右下角 ▽
- 畫面下方置中的旁白，一到兩行，右下角 ▽
- 局內下方的旁白，上方另有血量、晶石數等介面數字

判斷：只看含 3 個以上中文字的文字（介面上的數字、單字按鈕不算），上下相連且左右範圍重疊的
行歸成同一塊；整個畫面剛好只有一塊、不超過 max_lines 行、至少一行以句末標點結尾，
就當成對話框。符合時只點那段文字的中央，不點其他地方。
- 兩次點擊至少間隔 click_interval 秒，讓遊戲顯示下一句。
- 點到新的一句就清掉 guard 的點擊紀錄，長對話不會被當成原地打轉；
  點了還是同一句（沒反應）就不清，交給 guard 回首頁或停止。

另外放右上角自動對話按鈕的狀態判斷（auto_chat_speed），讓它停在最快倍速。

本模組不依賴 ok 套件，方便單元測試。
"""
import re
import time
from dataclasses import dataclass

import guard


@dataclass
class DialogueSettings:
    enabled: bool = True
    max_lines: int = 4
    click_interval: float = 1.5
    # 算成台詞的最少中文字數（更短的當成介面文字忽略）
    min_han: int = 3
    # 同一塊的行：上下間距的上限（畫面比例）
    max_line_gap: float = 0.04


DIALOGUE = DialogueSettings()

_HAN = re.compile(r'[一-鿿]')
_SENTENCE_END = re.compile(r'[。！？!?…」』）)~～]$')


def _clean(text):
    return re.sub(r'\s+', '', text or '')


def _blocks(boxes, height):
    """由上到下把上下相連、左右範圍重疊的行歸成同一塊。"""
    blocks = []
    for box in sorted(boxes, key=lambda b: b.y):
        block = blocks[-1] if blocks else None
        if block:
            last = block[-1]
            near = box.y - (last.y + last.height) <= DIALOGUE.max_line_gap * height
            overlap = box.x < last.x + last.width and last.x < box.x + box.width
            if near and overlap:
                block.append(box)
                continue
        blocks.append([box])
    return blocks


def dialogue_lines(task):
    """畫面上只有一段台詞時，回傳由上到下的文字框；否則回傳 None。"""
    lines = [b for b in task.all_texts or [] if len(_HAN.findall(b.name or '')) >= DIALOGUE.min_han]
    blocks = _blocks(lines, task.height)
    if len(blocks) != 1:
        return None
    block = blocks[0]
    if len(block) > DIALOGUE.max_lines:
        return None
    if not any(_SENTENCE_END.search(_clean(b.name)) for b in block):
        return None
    return block


def auto_chat_speed(icon):
    """右上角自動對話按鈕（模板框內的 BGR 圖）是什麼狀態，看兩個箭頭的顏色：
    'fast' 兩個箭頭都亮橘色（最快倍速）、'slow' 只亮第一個（一倍速）、'off' 白色（未開啟）；
    都不像就回傳 None（找到的不是這個按鈕）。"""
    import cv2

    half = icon.shape[1] // 2
    if half == 0 or icon.shape[0] == 0:
        return None
    hsv = cv2.cvtColor(icon[:, :, :3], cv2.COLOR_BGR2HSV)
    bright = hsv[..., 2] >= 150
    warm = bright & (hsv[..., 1] >= 50)
    white = bright & (hsv[..., 1] < 30)
    area = icon.shape[0] * half
    warm_left, warm_right = int(warm[:, :half].sum()), int(warm[:, half:].sum())
    # 實測：最快倍速右／左亮橘像素比 0.69~0.89，一倍速 0.07~0.27
    if warm_left >= 0.1 * area:
        return 'fast' if warm_right >= 0.5 * warm_left else 'slow'
    if white[:, :half].sum() >= 0.1 * area and white[:, half:].sum() >= 0.1 * area:
        return 'off'
    return None


def advance_dialogue_box(task):
    """是對話框就點台詞讓它前進，回傳 True；不是回傳 False。"""
    if not DIALOGUE.enabled:
        return False
    lines = dialogue_lines(task)
    if not lines:
        task._dialogue_text = None
        return False
    now = time.time()
    if now - getattr(task, '_dialogue_click_time', 0) < DIALOGUE.click_interval:
        return True
    text = ''.join(_clean(b.name) for b in lines)
    if text != getattr(task, '_dialogue_text', None):
        # 一句一句推進是正常流程，不算原地打轉
        guard.clear_click_record(task)
    task._dialogue_text = text
    task._dialogue_click_time = now
    x = (min(b.x for b in lines) + max(b.x + b.width for b in lines)) / 2 / task.width
    y = (min(b.y for b in lines) + max(b.y + b.height for b in lines)) / 2 / task.height
    task.log_info(f'對話框：點擊台詞繼續「{text[:20]}」')
    task.click(x, y)
    return True
