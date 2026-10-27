"""擬人化輸入（參考 AzurLaneAutoScript 的做法）。

ok-script 預設的 click_box 每次都點在方框正中央、點完固定等 1 秒。
這個模組提供 HumanizeMixin，讓任務的點擊、滑動、按鍵：

- 點擊位置：在目標方框內以近似常態分布隨機取點（越靠中心越常點到），
  做法同 ALAS 的 random_rectangle_point（多個均勻亂數取平均）。
- 固定座標點擊：加上幾個像素的小幅抖動。
- 操作節奏：點擊前加入反應延遲，偶爾停頓久一點；點擊後的等待時間隨機伸縮。
- 按壓時間：PC 端（PostMessage 等）隨機化按下時間。
  MuMu（nemu_ipc）的按壓時間與滑動軌跡由框架處理，框架已採用 ALAS 的隨機按壓與貝茲曲線。
- 每次點擊交給 guard.record_click 記錄，用來判斷是否在原地打轉。

用法：任務類別把 HumanizeMixin 放在最前面繼承，例如
    class ChaosMode(HumanizeMixin, TriggerTask): ...

所有參數集中在 HUMANIZE，改 HUMANIZE.enabled = False 即可整個關閉。
本模組不依賴 ok 套件，方便單元測試。
"""

import random
from dataclasses import dataclass

import guard


@dataclass
class HumanizeSettings:
    enabled: bool = True
    # 方框內可點範圍：以方框中心為準，取寬高的這個比例作為取點區域
    box_inner_ratio: float = 0.6
    # 方框小於這個像素時直接點中心附近（避免點到框外）
    min_box_size: int = 6
    # 固定座標點擊的抖動半徑，以畫面寬度的比例表示（1920 寬約 6 像素）
    point_jitter_ratio: float = 0.003
    # 模擬常態分布時取平均的亂數個數，越大越集中於中心
    distribution_n: int = 3
    # 點擊前的反應延遲（秒）
    reaction_delay: tuple = (0.05, 0.25)
    # 偶爾的停頓：機率與時間（秒）
    hesitate_prob: float = 0.03
    hesitate_delay: tuple = (0.5, 1.8)
    # 點擊後等待時間的伸縮倍率
    after_sleep_scale: tuple = (0.85, 1.35)
    # 按下時間（秒），PC 端生效
    down_time: tuple = (0.04, 0.11)
    # 滑動時間的伸縮倍率
    swipe_duration_scale: tuple = (0.85, 1.25)


HUMANIZE = HumanizeSettings()

_rng = random.Random()


def normal_between(a, b, n=3, rng=None):
    """在 [a, b] 間取近似常態分布的浮點數（n 個均勻亂數取平均，同 ALAS）。"""
    rng = rng or _rng
    if a >= b:
        return float(b)
    return sum(rng.uniform(a, b) for _ in range(n)) / n


def normal_int_between(a, b, n=3, rng=None):
    a, b = round(a), round(b)
    if a >= b:
        return b
    return round(normal_between(a, b, n, rng))


def point_in_box(x, y, width, height, relative_x=0.5, relative_y=0.5, settings=None, rng=None):
    """在方框內取一個擬人化的點擊座標。

    以 (relative_x, relative_y) 指定的位置為中心，在方框寬高 box_inner_ratio 的範圍內
    以近似常態分布取點。中心落在方框內時，結果會被限制在方框內。
    """
    s = settings or HUMANIZE
    cx = x + width * relative_x
    cy = y + height * relative_y
    if width < s.min_box_size or height < s.min_box_size:
        return int(round(cx)), int(round(cy))

    half_w = width * s.box_inner_ratio / 2
    half_h = height * s.box_inner_ratio / 2
    px = normal_between(cx - half_w, cx + half_w, s.distribution_n, rng)
    py = normal_between(cy - half_h, cy + half_h, s.distribution_n, rng)

    if 0 <= relative_x <= 1:
        px = min(max(px, x + 1), x + width - 2)
    if 0 <= relative_y <= 1:
        py = min(max(py, y + 1), y + height - 2)
    return int(round(px)), int(round(py))


def jitter_point(x, y, screen_width, screen_height, settings=None, rng=None):
    """固定座標點擊的小幅抖動，結果限制在畫面內。"""
    s = settings or HUMANIZE
    r = max(1, int(round(screen_width * s.point_jitter_ratio))) if screen_width else 0
    if r <= 0:
        return int(x), int(y)
    nx = normal_int_between(x - r, x + r, s.distribution_n, rng)
    ny = normal_int_between(y - r, y + r, s.distribution_n, rng)
    if screen_width:
        nx = min(max(nx, 0), screen_width - 1)
    if screen_height:
        ny = min(max(ny, 0), screen_height - 1)
    return nx, ny


def scale_duration(seconds, scale_range, rng=None):
    """把等待時間隨機伸縮；0 維持 0。"""
    if not seconds or seconds <= 0:
        return seconds
    lo, hi = scale_range
    return seconds * normal_between(lo, hi, 2, rng)


def reaction_delay(settings=None, rng=None):
    """點擊前的反應延遲，偶爾加上一段停頓。"""
    s = settings or HUMANIZE
    rng = rng or _rng
    delay = normal_between(*s.reaction_delay, n=2, rng=rng)
    if rng.random() < s.hesitate_prob:
        delay += rng.uniform(*s.hesitate_delay)
    return delay


def _is_box(obj):
    return all(hasattr(obj, attr) for attr in ("x", "y", "width", "height"))


class HumanizeMixin:
    """讓任務的輸入更接近真人操作。必須放在 BaseTask / TriggerTask 之前繼承。"""

    _hz_in_box_click = False

    @property
    def _hz(self):
        return HUMANIZE

    def _hz_wait(self, seconds):
        if seconds and seconds > 0:
            self.sleep(seconds)

    def click_box(self, box=None, relative_x=0.5, relative_y=0.5, raise_if_not_found=False,
                  move_back=False, move=True, down_time=0.01, after_sleep=1):
        s = self._hz
        if not s.enabled:
            return super().click_box(box, relative_x, relative_y, raise_if_not_found,
                                     move_back, move, down_time, after_sleep)

        if isinstance(box, list):
            box = box[0] if len(box) > 0 else None
        if isinstance(box, str):
            box = self.get_box_by_name(box)
        if not box or not _is_box(box):
            # 交給框架處理找不到方框時的記錄與例外
            return super().click_box(None, relative_x, relative_y, raise_if_not_found,
                                     move_back, move, down_time, after_sleep)

        x, y = point_in_box(box.x, box.y, box.width, box.height, relative_x, relative_y, s)
        self._hz_in_box_click = True
        try:
            return self.click(x, y, name=getattr(box, "name", None), move_back=move_back, move=move,
                              down_time=down_time, after_sleep=after_sleep)
        finally:
            self._hz_in_box_click = False

    def click(self, x=-1, y=-1, move_back=False, name=None, interval=-1, move=True,
              down_time=0.02, after_sleep=0, key='left', hcenter=False, vcenter=False):
        s = self._hz
        is_pixel = not (isinstance(x, list) or _is_box(x)) and not (0 < x < 1 or 0 < y < 1) and x >= 0 and y >= 0
        if is_pixel and self.width and self.height:
            # 相對座標、方框都會在框架轉成像素後再呼叫一次 click，只在這一層記錄才不會重複
            guard.record_click(self, x / self.width, y / self.height)
        passthrough = (
                not s.enabled
                or isinstance(x, list)
                or _is_box(x)
                or (0 < x < 1 or 0 < y < 1)  # 相對座標：框架會轉成像素後再呼叫 click
                or x < 0 or y < 0  # -1 代表目前位置，不動它
        )
        if passthrough:
            return super().click(x, y, move_back=move_back, name=name, interval=interval, move=move,
                                 down_time=down_time, after_sleep=after_sleep, key=key,
                                 hcenter=hcenter, vcenter=vcenter)

        if not self._hz_in_box_click:
            x, y = jitter_point(x, y, self.width, self.height, s)

        self._hz_wait(reaction_delay(s))
        return super().click(x, y, move_back=move_back, name=name, interval=interval, move=move,
                             down_time=normal_between(*s.down_time, n=2),
                             after_sleep=scale_duration(after_sleep, s.after_sleep_scale),
                             key=key, hcenter=hcenter, vcenter=vcenter)

    def swipe_relative(self, from_x, from_y, to_x, to_y, duration=0.5, settle_time=0):
        s = self._hz
        if not s.enabled:
            return super().swipe_relative(from_x, from_y, to_x, to_y, duration, settle_time)
        jr = s.point_jitter_ratio
        from_x += normal_between(-jr, jr, s.distribution_n)
        from_y += normal_between(-jr, jr, s.distribution_n) * 16 / 9
        to_x += normal_between(-jr, jr, s.distribution_n)
        to_y += normal_between(-jr, jr, s.distribution_n) * 16 / 9
        clamp = lambda v: min(max(v, 0.0), 0.999)
        self._hz_wait(reaction_delay(s))
        return super().swipe_relative(clamp(from_x), clamp(from_y), clamp(to_x), clamp(to_y),
                                      scale_duration(duration, s.swipe_duration_scale), settle_time)

    def mouse_down(self, x=-1, y=-1, name=None, key="left"):
        s = self._hz
        if s.enabled and x >= 0 and y >= 0:
            x, y = jitter_point(x, y, self.width, self.height, s)
            self._hz_wait(reaction_delay(s))
        return super().mouse_down(x, y, name=name, key=key)

    def send_key(self, key, down_time=0.02, interval=-1, after_sleep=0):
        s = self._hz
        if not s.enabled:
            return super().send_key(key, down_time=down_time, interval=interval, after_sleep=after_sleep)
        self._hz_wait(reaction_delay(s))
        return super().send_key(key, down_time=normal_between(*s.down_time, n=2), interval=interval,
                                after_sleep=scale_duration(after_sleep, s.after_sleep_scale))
