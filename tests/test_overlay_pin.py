import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import overlay_pin  # noqa: E402


class FakeOverlay:
    """OverlayWindow 在 refresh_visibility 會用到的狀態。"""

    def __init__(self, source_visible, boxes=False):
        self._source_visible = source_visible
        self._boxes_enabled = boxes
        self._boxes_active = False
        self._custom_drawing_active = False
        self.blur_images = []
        self.custom_painters = {}
        self.visible = False
        self.attached = 0

    def isVisible(self):
        return self.visible

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False


class TestRefreshVisibility(unittest.TestCase):
    def refresh(self, overlay, logs):
        with patch.object(overlay_pin, '_logs_enabled', return_value=logs), \
                patch.object(overlay_pin, '_attach_to_game',
                             side_effect=lambda o: setattr(o, 'attached', o.attached + 1)):
            overlay_pin.refresh_visibility(overlay)

    def test_logs_alone_keep_overlay_shown_and_attached(self):
        overlay = FakeOverlay(source_visible=True)
        self.refresh(overlay, logs=True)
        self.assertTrue(overlay.visible)
        self.assertEqual(overlay.attached, 1)
        # 已顯示時再判斷一次：維持顯示，仍確認掛在遊戲視窗下
        self.refresh(overlay, logs=True)
        self.assertTrue(overlay.visible)
        self.assertEqual(overlay.attached, 2)

    def test_hidden_when_game_window_hidden_or_nothing_to_show(self):
        overlay = FakeOverlay(source_visible=True)
        overlay.visible = True
        self.refresh(overlay, logs=False)
        self.assertFalse(overlay.visible)
        overlay = FakeOverlay(source_visible=False)
        overlay.visible = True
        self.refresh(overlay, logs=True)
        self.assertFalse(overlay.visible)

    def test_boxes_still_show_without_logs(self):
        overlay = FakeOverlay(source_visible=True, boxes=True)
        self.refresh(overlay, logs=False)
        self.assertTrue(overlay.visible)

    def test_no_game_window(self):
        self.assertFalse(overlay_pin.game_window_shown(0))


if __name__ == '__main__':
    unittest.main()
