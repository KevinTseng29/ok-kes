"""遊戲畫面上的 LOG 懸浮層改成常駐（參考 ALAS 一直顯示日誌）。

框架原本只在模擬器是前景視窗時顯示懸浮層：切到其他程式就藏起來、點回模擬器又跳出來，
畫面一下有一下沒有；而且只有開「顯示框選」才會建立，單開「懸浮層顯示日誌」沒有作用。
install() 改成：
- 遊戲視窗開著、沒有最小化就顯示；開了「懸浮層顯示日誌」就顯示，不必開框選
- 不再置頂整個桌面，改成遊戲視窗的附屬視窗：只疊在遊戲上面，切到其他程式時不會蓋住它們，
  遊戲最小化時跟著隱藏

在建立 ok.OK 之前呼叫；重複呼叫不會重複修改。
"""
import ctypes
import functools

GWLP_HWNDPARENT = -8


def _user32():
    user32 = ctypes.windll.user32
    user32.GetWindowLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int)
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t)
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    return user32


def _game_hwnd():
    from ok import og
    hwnd_window = getattr(getattr(og, 'device_manager', None), 'hwnd_window', None)
    return getattr(hwnd_window, 'hwnd', 0) or 0


def game_window_shown(hwnd):
    """遊戲視窗存在、可見且沒有最小化。"""
    if not hwnd:
        return False
    user32 = _user32()
    return bool(user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd))


def _logs_enabled():
    from ok import og
    config = getattr(getattr(og, 'app', None), 'ok_config', None)
    return bool(config.get('show_overlay_logs', True)) if config is not None else False


def _attach_to_game(widget):
    """把懸浮層設成遊戲視窗的附屬視窗：z 順序永遠緊貼在遊戲上面。"""
    owner = _game_hwnd()
    if not owner:
        return
    user32 = _user32()
    hwnd = int(widget.winId())
    if user32.GetWindowLongPtrW(hwnd, GWLP_HWNDPARENT) != owner:
        user32.SetWindowLongPtrW(hwnd, GWLP_HWNDPARENT, owner)


def refresh_visibility(overlay):
    """取代 OverlayWindow.refresh_visibility：開了日誌也算需要顯示，顯示時掛到遊戲視窗下。"""
    required = (overlay._boxes_enabled or overlay._boxes_active or overlay._custom_drawing_active
                or bool(overlay.blur_images) or bool(overlay.custom_painters) or _logs_enabled())
    if overlay._source_visible and required:
        if not overlay.isVisible():
            overlay.show()
        _attach_to_game(overlay)
    elif overlay.isVisible():
        overlay.hide()


def install():
    import ok
    from PySide6.QtCore import Qt
    from ok.gui.overlay.OverlayWindow import OverlayWindow
    from ok.gui.start.StartTab import StartTab

    if getattr(OverlayWindow, '_pinned_to_game', False):
        return
    OverlayWindow._pinned_to_game = True

    init = OverlayWindow.__init__
    update_overlay = OverlayWindow.update_overlay

    @functools.wraps(init)
    def __init__(self, *args, **kwargs):
        init(self, *args, **kwargs)
        # 改由附屬視窗維持在遊戲上面；改旗標會把已顯示的視窗藏起來，所以重新判斷一次
        self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        self.refresh_visibility()

    @functools.wraps(update_overlay)
    def update_overlay_pinned(self, visible, *geometry):
        # 框架傳來的 visible 是「是不是前景視窗」，改看遊戲視窗本身有沒有顯示
        update_overlay(self, game_window_shown(_game_hwnd()), *geometry)

    OverlayWindow.__init__ = __init__
    OverlayWindow.update_overlay = update_overlay_pinned
    OverlayWindow.refresh_visibility = refresh_visibility

    show_main = ok.App.do_show_main

    @functools.wraps(show_main)
    def do_show_main(self):
        show_main(self)
        # 框架只在開框選時才建立懸浮層；開了日誌也要建立
        self.get_overlay_view()

    ok.App.do_show_main = do_show_main

    log_toggled = StartTab.on_overlay_log_toggled

    @functools.wraps(log_toggled)
    def on_overlay_log_toggled(self, checked):
        log_toggled(self, checked)
        from ok import og
        og.app.get_overlay_view().refresh_visibility()

    StartTab.on_overlay_log_toggled = on_overlay_log_toggled
