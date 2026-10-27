import importlib.util
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ok_tasks'))

import dialogue  # noqa: E402
import guard  # noqa: E402
from dialogue import DialogueSettings, advance_dialogue_box, dialogue_lines  # noqa: E402


class FakeBox:
    """OCR 框；以相對座標的左上與右下建立（畫面 1280x720）。"""

    def __init__(self, name, x1, y1, x2, y2):
        self.name = name
        self.x, self.y = x1 * 1280, y1 * 720
        self.width, self.height = (x2 - x1) * 1280, (y2 - y1) * 720


class FakeTask:
    width, height = 1280, 720

    def __init__(self, texts=()):
        self.all_texts = list(texts)
        self.clicks = []

    def click(self, x, y, **kwargs):
        guard.record_click(self, x, y)
        self.clicks.append((round(x, 3), round(y, 3)))

    def log_info(self, message):
        pass


def boxes(rows):
    return [FakeBox(*row) for row in rows]


# 以下是 error_scenes 實際畫面的 OCR 結果（國際服、已轉簡體）
# 左上角頭像＋台詞框
MAP_DIALOGUE = boxes([('确认干员抵达座标。', 0.106, 0.167, 0.247, 0.204),
                      ('之后就交给您了。', 0.109, 0.203, 0.231, 0.239)])
# 畫面下方置中的旁白（兩行寬度不同，置中而非靠左）
CENTER_NARRATION = boxes([('000', 0.616, 0.501, 0.634, 0.517),
                          ('「梦境号」，开始通讯。', 0.395, 0.808, 0.6, 0.861),
                          ('目前座标固定完毕。空间稳定度无异常。', 0.318, 0.857, 0.666, 0.897)])
# 卡厄思局內的旁白，上方有血量與晶石數
RUN_NARRATION = boxes([('2968/2968', 0.159, 0.022, 0.266, 0.053), ('160', 0.782, 0.035, 0.813, 0.068),
                       ('太初的气息静静地降临在你面前。', 0.346, 0.814, 0.637, 0.857)])
# 不是對話：零號系統首頁、出擊戰鬥
ZERO_SYSTEM_HOME = boxes([
    ('零号系统', 0.08, 0.024, 0.165, 0.068), ('4/4+', 0.813, 0.032, 0.863, 0.065),
    ('最高达成难度', 0.038, 0.121, 0.136, 0.149), ('内容介绍', 0.888, 0.115, 0.959, 0.154),
    ('10', 0.045, 0.16, 0.07, 0.199), ('法典', 0.791, 0.449, 0.834, 0.489), ('环境变数', 0.078, 0.464, 0.141, 0.494),
    ('备援协议', 0.078, 0.533, 0.143, 0.569), ('升级', 0.077, 0.607, 0.113, 0.637), ('图鉴', 0.077, 0.681, 0.112, 0.714),
    ('法典纪录', 0.076, 0.75, 0.141, 0.786), ('56天11小时', 0.087, 0.831, 0.191, 0.868),
    ('56天11小时', 0.819, 0.825, 0.924, 0.863), ('卡厄思物质', 0.101, 0.892, 0.184, 0.931),
    ('乐每周进度', 0.68, 0.885, 0.769, 0.922), ('0/8000', 0.862, 0.887, 0.92, 0.921)])
SORTIE_BATTLE = boxes([
    ('837/1043', 0.169, 0.026, 0.256, 0.05), ('50>', 0.41, 0.024, 0.484, 0.062), ('1878', 0.675, 0.217, 0.703, 0.235),
    ('节奏', 0.355, 0.756, 0.382, 0.771), ('粉丝福利', 0.464, 0.744, 0.516, 0.767), ('聚光灯', 0.584, 0.744, 0.616, 0.775),
    ('基本攻擎', 0.359, 0.771, 0.409, 0.794), ('基本技能', 0.471, 0.761, 0.521, 0.789),
    ('寒霜盾牌', 0.241, 0.774, 0.289, 0.787), ('节奏', 0.693, 0.767, 0.72, 0.786),
    ('区基本攻学', 0.695, 0.779, 0.747, 0.815), ('基本技能', 0.258, 0.793, 0.296, 0.804),
    ('圆05/10', 0.46, 0.95, 0.54, 0.993)])
NEXT_LINE = boxes([('请小心前进。', 0.105, 0.169, 0.200, 0.200)])


class DialogueTestCase(unittest.TestCase):
    def setUp(self):
        dialogue.DIALOGUE = DialogueSettings()
        self.now = 1000.0
        dialogue.time = types.SimpleNamespace(time=lambda: self.now)
        self.addCleanup(setattr, dialogue, 'time', __import__('time'))
        self.addCleanup(setattr, dialogue, 'DIALOGUE', DialogueSettings())


class TestDetection(DialogueTestCase):
    def test_real_dialogue_types_detected(self):
        expected = {
            '左上頭像框': (MAP_DIALOGUE, ['确认干员抵达座标。', '之后就交给您了。']),
            '置中旁白': (CENTER_NARRATION, ['「梦境号」，开始通讯。', '目前座标固定完毕。空间稳定度无异常。']),
            '局內旁白': (RUN_NARRATION, ['太初的气息静静地降临在你面前。']),
        }
        for name, (texts, lines) in expected.items():
            found = dialogue_lines(FakeTask(texts))
            self.assertIsNotNone(found, name)
            self.assertEqual([b.name for b in found], lines, name)

    def test_other_pages_not_dialogue(self):
        cases = {
            '零號系統首頁': ZERO_SYSTEM_HOME,
            '出擊戰鬥': SORTIE_BATTLE,
            '事件選項': [FakeBox('询问是谁确认【星之流浪者】资讯', 0.2, 0.75, 0.35, 0.8),
                     FakeBox('请求演奏随机命运从3条分支中选择1条获得', 0.4, 0.75, 0.6, 0.8),
                     FakeBox('请求怀疑之曲获得预见的命运', 0.65, 0.75, 0.8, 0.8)],
            '戰鬥': [FakeBox('697/968', 0.18, 0.03, 0.24, 0.05), FakeBox('寒霜盾牌', 0.40, 0.83, 0.45, 0.86),
                   FakeBox('基本技能', 0.40, 0.86, 0.45, 0.88)],
            '單一按鈕': [FakeBox('确认', 0.9, 0.92, 0.95, 0.95)],
            '沒有句末標點': [FakeBox('存档资料储存上限', 0.7, 0.4, 0.85, 0.43)],
            '兩塊分開的文字': [FakeBox('第一段文字。', 0.1, 0.1, 0.2, 0.13), FakeBox('第二段文字。', 0.6, 0.7, 0.7, 0.73)],
            '上下隔太遠': [FakeBox('第一句话。', 0.1, 0.1, 0.2, 0.13), FakeBox('第二句话。', 0.1, 0.3, 0.2, 0.33)],
            '超過四行': [FakeBox(f'第{i}行文字。', 0.1, 0.1 + i * 0.03, 0.2, 0.13 + i * 0.03) for i in range(5)],
            '沒有文字': [],
        }
        for name, texts in cases.items():
            self.assertIsNone(dialogue_lines(FakeTask(texts)), name)


class TestAdvance(DialogueTestCase):
    def test_clicks_center_of_dialogue_text(self):
        task = FakeTask(MAP_DIALOGUE)
        self.assertTrue(advance_dialogue_box(task))
        (x, y), = task.clicks
        self.assertAlmostEqual(x, (0.106 + 0.247) / 2, places=2)
        self.assertAlmostEqual(y, (0.167 + 0.239) / 2, places=2)
        # 置中旁白點兩行的整體中央，不受介面數字影響
        task = FakeTask(CENTER_NARRATION)
        advance_dialogue_box(task)
        (x, y), = task.clicks
        self.assertAlmostEqual(x, (0.318 + 0.666) / 2, places=2)
        self.assertAlmostEqual(y, (0.808 + 0.897) / 2, places=2)

    def test_waits_between_clicks(self):
        task = FakeTask(MAP_DIALOGUE)
        advance_dialogue_box(task)
        self.now += 1.0
        self.assertTrue(advance_dialogue_box(task))
        self.assertEqual(len(task.clicks), 1)
        self.now += 1.0
        advance_dialogue_box(task)
        self.assertEqual(len(task.clicks), 2)

    def test_new_lines_clear_click_record_same_line_does_not(self):
        task = FakeTask(MAP_DIALOGUE)
        advance_dialogue_box(task)
        self.now += 2
        advance_dialogue_box(task)            # 同一句：紀錄累積
        self.assertEqual(len(task._guard_state.clicks), 2)
        task.all_texts = NEXT_LINE
        self.now += 2
        advance_dialogue_box(task)            # 新的一句：先清再記
        self.assertEqual(len(task._guard_state.clicks), 1)

    def test_long_dialogue_is_not_a_loop_but_stuck_line_is(self):
        task = FakeTask()
        for i in range(30):
            task.all_texts = [FakeBox(f'这是第{i}句台词。', 0.105, 0.169, 0.246, 0.200)]
            self.now += 2
            advance_dialogue_box(task)
        self.assertEqual(guard.click_loop(task._guard_state.clicks), '')
        task.all_texts = MAP_DIALOGUE
        for _ in range(15):
            self.now += 2
            advance_dialogue_box(task)
        self.assertIn('同一處', guard.click_loop(task._guard_state.clicks))

    def test_not_dialogue_or_disabled(self):
        task = FakeTask([FakeBox('确认', 0.9, 0.92, 0.95, 0.95)])
        self.assertFalse(advance_dialogue_box(task))
        dialogue.DIALOGUE.enabled = False
        self.assertFalse(advance_dialogue_box(FakeTask(MAP_DIALOGUE)))


# 夜間日誌裡被誤點過的文字：戰鬥提示、選卡頁提示、戰鬥中角色台詞
BATTLE_HINT = boxes([('预测将有强力攻击。请注意。', 0.38, 0.30, 0.62, 0.34)])
CARD_HINT = boxes([('长按卡牌以查看资讯。', 0.42, 0.92, 0.58, 0.95)])
BATTLE_BARK = boxes([('如预期般攻击相当有效率。', 0.40, 0.20, 0.60, 0.24)])


class TestNotDialogue(DialogueTestCase):
    def test_ui_hints_ignored(self):
        for texts in (BATTLE_HINT, CARD_HINT):
            self.assertIsNone(dialogue_lines(FakeTask(texts)))

    def test_quiet_right_after_battle(self):
        task = FakeTask(BATTLE_BARK)
        dialogue.mark_battle(task)
        self.now += 7
        self.assertFalse(advance_dialogue_box(task))
        self.assertEqual(task.clicks, [])
        # 離開戰鬥一段時間後的台詞照常推進
        self.now += 2
        self.assertTrue(advance_dialogue_box(task))
        self.assertEqual(len(task.clicks), 1)


AUTO_CHAT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'auto_chat')


@unittest.skipUnless(importlib.util.find_spec('cv2'), '需要 opencv')
class TestAutoChatSpeed(unittest.TestCase):
    """實際截到的按鈕（1280x720 的模板框）：每點一次在 未開啟 → 一倍速 → 最快 之間循環。"""

    def icon(self, name, scale=1.0):
        import cv2
        image = cv2.imread(os.path.join(AUTO_CHAT_DIR, name + '.png'))
        return cv2.resize(image, None, fx=scale, fy=scale) if scale != 1.0 else image

    def test_states(self):
        expected = {'fast': 'fast', 'slow': 'slow', 'off': 'off', 'none': None}
        for name in sorted(os.listdir(AUTO_CHAT_DIR)):
            name = name[:-4]
            for scale in (1.0, 1.5):  # 1920x1080 畫面的框是 1.5 倍
                with self.subTest(name=name, scale=scale):
                    self.assertEqual(dialogue.auto_chat_speed(self.icon(name, scale)),
                                     expected[name.split('_')[0]])

    def test_empty_icon(self):
        import numpy as np
        self.assertIsNone(dialogue.auto_chat_speed(np.zeros((0, 0, 3), np.uint8)))


if __name__ == '__main__':
    unittest.main()
