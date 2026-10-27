"""例外保護與錯誤現場保存（參考 AzurLaneAutoScript 的 failure_record 與 save_error_log）。

ok-script 的執行器遇到任務丟出未處理的例外時，會直接停用任務，並把 _enabled=False
寫進設定檔，所以一次 OCR 誤讀就可能讓整晚的掛機停掉。這個模組提供：

- guarded_run：包住 TriggerTask.run()。出錯時先記錄、保存現場，下一輪再試；
  連續失敗太多次，或短時間內累計失敗太多次，才交給框架停止任務（框架會發錯誤通知）。
- save_scene：把最近幾輪的截圖、說明與最近的 log 存到 error_scenes/，
  出錯或畫面卡住時呼叫，方便事後重現問題。依份數與總大小自動清理。
- maybe_clean_screenshots：框架只在程式啟動時清理 screenshots/，
  這裡在執行中定期檢查，超過上限就從最舊的檔案刪起。
- watch（任務類別設 watch_progress = True 才啟用）：參考 ALAS 的 click_record 與 stuck_record，
  每輪 run() 之後檢查是否在原地打轉（反覆點同一兩處）或卡住（太久沒點擊、畫面文字也沒變），
  發生時先保存現場並按回首頁；recover_window 內又發生就停止任務並通知。
  點擊由 HumanizeMixin.click 呼叫 record_click 記錄；刻意重複點同一處的流程
  （再次觀測、重新合成等）要呼叫 clear_click_record。

用法：
    @guarded_run
    def run(self): ...

所有參數集中在 GUARD，改 GUARD.enabled = False 即可整個關閉。
本模組不依賴 ok 套件，方便單元測試。
"""

import functools
import os
import random
import re
import shutil
import time
import traceback
from collections import Counter, deque
from dataclasses import dataclass


@dataclass
class GuardSettings:
    enabled: bool = True
    # 連續失敗幾次就停止任務（同 ALAS）
    max_consecutive_failures: int = 3
    # 時間窗（秒）內累計失敗幾次就停止任務，避免失敗與成功交替時永遠不停
    max_failures_in_window: int = 10
    failure_window: float = 600
    # 失敗後到下一輪前的等待（秒）
    retry_delay: tuple = (2.0, 4.0)
    # 保留最近幾輪的截圖
    frame_buffer_size: int = 10
    # 錯誤現場的資料夾、保留份數與總大小上限（MB）
    scene_dir: str = 'error_scenes'
    max_scenes: int = 30
    max_scene_mb: float = 300
    # 現場截圖除了最後一張存 PNG，其餘存 JPG 的品質
    jpg_quality: int = 90
    # 同一種原因多久內只保存一次現場（秒）
    scene_min_interval: float = 60
    # 一併保存的 log 檔與行數
    log_file: str = os.path.join('logs', 'ok-script.log')
    log_tail_lines: int = 300
    # 框架截圖資料夾（src/config.py 的 screenshots_folder）的大小上限（MB）與檢查間隔（秒）
    screenshot_dir: str = 'screenshots'
    screenshot_max_mb: float = 300
    screenshot_check_interval: float = 3600
    # 原地打轉（參考 ALAS 的 click_record）：最近 click_record_size 次點擊中，同一處 ≥ click_same_limit 次、
    # 兩處各 ≥ click_pair_limit 次，或幾乎只在兩處之間來回（前兩處合計 ≥ click_two_targets_limit 次）
    click_record_size: int = 15
    click_same_limit: int = 12
    click_pair_limit: int = 6
    click_two_targets_limit: int = 14
    # 點擊位置以這個格距（畫面比例）歸成同一處，吸收擬人化的位置抖動
    click_grid: float = 0.03
    # 卡住（參考 ALAS 的 stuck_record）：這麼多秒沒有點擊、畫面文字也沒明顯變化
    stuck_timeout: float = 90
    # 畫面文字與上次有進展時相比，相同的比例低於這個值才算有變化（避免 OCR 跳字當成變化）
    text_same_ratio: float = 0.7
    # 兩次檢查相隔超過這麼多秒（任務暫停、其他處理接手很久）就重新計時
    watch_gap_reset: float = 30
    # 打轉或卡住時先按回首頁；之後這麼多秒內又發生就停止任務
    recover_window: float = 600
    home_button: tuple = (0.898, 0.050)


GUARD = GuardSettings()

# 框架用來控制流程的例外（使用者停止任務等），必須原樣往外丟
_PASSTHROUGH = ('TaskDisabledException', 'FinishedException')


class _GuardState:
    def __init__(self, buffer_size):
        self.frames = deque(maxlen=buffer_size)
        self.consecutive = 0
        self.failures = deque()
        self.last_scene = {}
        self.reset_watch()

    def reset_watch(self):
        self.clicks = deque(maxlen=GUARD.click_record_size)
        self.clicked = False
        self.paused = False
        self.last_watch = None
        self.last_progress = None
        self.progress_texts = set()
        self.last_recover = None


def _state(task):
    state = getattr(task, '_guard_state', None)
    if state is None:
        state = _GuardState(GUARD.frame_buffer_size)
        task._guard_state = state
    return state


def _is_passthrough(error):
    return any(cls.__name__ in _PASSTHROUGH for cls in type(error).__mro__)


def record_frame(task):
    """記下這一輪的截圖，出錯時一併保存。"""
    frame = getattr(task, 'frame', None)
    if frame is None:
        return
    copy = getattr(frame, 'copy', None)
    _state(task).frames.append((time.time(), copy() if copy else frame))


def guarded_run(run):
    """包住 TriggerTask.run()：出錯時保存現場並在下一輪重試，失敗太多次才停止任務。"""

    @functools.wraps(run)
    def wrapper(task, *args, **kwargs):
        if not GUARD.enabled:
            return run(task, *args, **kwargs)
        maybe_clean_screenshots(task)
        try:
            record_frame(task)
            result = run(task, *args, **kwargs)
        except Exception as e:
            if _is_passthrough(e) or _handle_failure(task, e):
                raise
            return None
        _state(task).consecutive = 0
        if getattr(task, 'watch_progress', False) and getattr(task, 'enabled', True):
            try:
                watch(task)
            except Exception as e:
                if _is_passthrough(e):
                    raise
                task.log_info(f'檢查打轉／卡住時出錯：{e}')
        return result

    return wrapper


# ---------- 原地打轉與卡住 ----------

def reset(task):
    """任務重新啟動時呼叫，清掉上一次的打轉／卡住紀錄。"""
    _state(task).reset_watch()


def record_click(task, x, y):
    """記下一次點擊（相對座標）；由 HumanizeMixin.click 呼叫。"""
    if not GUARD.enabled:
        return
    state = _state(task)
    if state.paused:
        return
    state.clicks.append((round(x / GUARD.click_grid), round(y / GUARD.click_grid)))
    state.clicked = True


def clear_click_record(task):
    """刻意重複點同一處的流程（再次觀測、重新合成、重開一局）呼叫，避免被當成打轉。"""
    _state(task).clicks.clear()


def click_loop(clicks):
    """依最近的點擊判斷是否在原地打轉；回傳說明文字，沒有打轉回傳空字串。"""
    if len(clicks) < GUARD.click_record_size:
        return ''
    counts = [count for _, count in Counter(clicks).most_common(2)] + [0]
    first, second = counts[0], counts[1]
    total = len(clicks)
    if first >= GUARD.click_same_limit:
        return f'最近 {total} 次點擊有 {first} 次點在同一處'
    if second >= GUARD.click_pair_limit or first + second >= GUARD.click_two_targets_limit:
        return f'最近 {total} 次點擊都在兩處之間來回（{first}＋{second} 次）'
    return ''


def _text_set(task):
    texts = set()
    for box in getattr(task, 'all_texts', None) or []:
        name = re.sub(r'\s+', '', getattr(box, 'name', '') or '')
        if len(name) >= 2:
            texts.add(name)
    return texts


def _texts_changed(before, after):
    if not before and not after:
        return False
    same = len(before & after) / max(len(before), len(after))
    return same < GUARD.text_same_ratio


def watch(task):
    """每輪 run() 之後檢查是否在原地打轉或卡住；處理了（回首頁或停止）回傳 True。"""
    state = _state(task)
    now = time.time()
    texts = _text_set(task)
    if state.last_watch is None or now - state.last_watch > GUARD.watch_gap_reset:
        state.last_progress, state.progress_texts = now, texts
    elif state.clicked or _texts_changed(state.progress_texts, texts):
        state.last_progress, state.progress_texts = now, texts
    state.last_watch = now
    state.clicked = False

    loop = click_loop(state.clicks)
    if loop:
        return _recover(task, 'loop', loop)
    idle = now - state.last_progress
    if idle >= GUARD.stuck_timeout:
        return _recover(task, 'no_progress', f'已 {idle:.0f} 秒沒有點擊，畫面文字也沒有變化')
    return False


def _notify(task, message):
    try:
        task.log_info(message, notify=True)
    except TypeError:
        task.log_info(message)


def _recover(task, reason, detail):
    """先按回首頁；recover_window 內第二次發生就停止任務。"""
    state = _state(task)
    now = time.time()
    save_scene(task, reason, detail)
    state.clicks.clear()
    state.last_progress, state.progress_texts = now, _text_set(task)
    if state.last_recover is not None and now - state.last_recover < GUARD.recover_window:
        state.last_recover = None
        _notify(task, f'{detail}；回首頁後仍無法恢復，停止任務，請查看 {GUARD.scene_dir}/ 的現場')
        task.disable()
        return True
    state.last_recover = now
    task.log_info(f'{detail}，先點擊回首頁')
    state.paused = True
    try:
        task.click(*GUARD.home_button)
    finally:
        state.paused = False
    task.sleep(2)
    return True


def _handle_failure(task, error):
    """記錄失敗並保存現場；回傳 True 表示失敗太多次，該停止任務。"""
    state = _state(task)
    now = time.time()
    state.consecutive += 1
    state.failures.append(now)
    while state.failures and now - state.failures[0] > GUARD.failure_window:
        state.failures.popleft()

    task.log_error(
        f'執行出錯（連續第 {state.consecutive} 次，'
        f'{GUARD.failure_window / 60:g} 分鐘內第 {len(state.failures)} 次）：',
        error,
    )
    save_scene(task, 'exception', traceback.format_exc())

    if (state.consecutive >= GUARD.max_consecutive_failures
            or len(state.failures) >= GUARD.max_failures_in_window):
        task.log_info('失敗次數過多，停止任務')
        # 使用者重新啟動任務時從頭計算
        state.consecutive = 0
        state.failures.clear()
        return True

    task.sleep(random.uniform(*GUARD.retry_delay))
    return False


def save_scene(task, reason, detail=''):
    """保存錯誤現場：最近幾輪的截圖、說明與最近的 log。

    回傳資料夾路徑；同一種原因在 scene_min_interval 內已保存過，或保存失敗時回傳 None。
    """
    state = _state(task)
    now = time.time()
    if now - state.last_scene.get(reason, 0) < GUARD.scene_min_interval:
        return None
    state.last_scene[reason] = now

    stamp = time.strftime('%Y%m%d_%H%M%S', time.localtime(now))
    folder = os.path.join(GUARD.scene_dir, f'{stamp}_{type(task).__name__}_{reason}')
    frames = list(state.frames)
    try:
        os.makedirs(folder, exist_ok=True)
        for i, (t, frame) in enumerate(frames):
            # 最後一張最接近出錯當下，存 PNG 保留原始像素以便重跑 OCR；其餘存 JPG 省空間
            ext = 'png' if i == len(frames) - 1 else 'jpg'
            name = f'{i:02d}_{time.strftime("%H%M%S", time.localtime(t))}_{int(t % 1 * 1000):03d}.{ext}'
            _write_image(os.path.join(folder, name), frame)
        with open(os.path.join(folder, 'info.txt'), 'w', encoding='utf-8') as f:
            f.write(f'任務：{type(task).__name__}\n')
            f.write(f'原因：{reason}\n')
            f.write(f'時間：{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))}\n')
            f.write(f'截圖：{len(frames)} 張（依時間排序，最後一張是 PNG，最接近出錯當下）\n')
            if detail:
                f.write(f'\n{detail}\n')
        tail = _read_log_tail(GUARD.log_file, GUARD.log_tail_lines)
        if tail:
            with open(os.path.join(folder, 'log.txt'), 'w', encoding='utf-8') as f:
                f.write(tail)
        _prune_scenes(GUARD.scene_dir, GUARD.max_scenes, GUARD.max_scene_mb * 1024 * 1024)
    except Exception as e:
        task.log_info(f'保存錯誤現場失敗：{e}')
        return None

    task.log_info(f'已保存錯誤現場：{folder}（{len(frames)} 張截圖）')
    return folder


def _write_image(path, frame):
    import cv2  # 延後匯入，單元測試不需要 OpenCV
    ext = os.path.splitext(path)[1]
    params = [cv2.IMWRITE_JPEG_QUALITY, GUARD.jpg_quality] if ext == '.jpg' else []
    ok, buf = cv2.imencode(ext, frame, params)
    if ok:
        buf.tofile(path)  # 用 tofile 才能寫入含中文的路徑


def _read_log_tail(path, lines, max_bytes=512 * 1024):
    """讀取 log 檔最後幾行；檔案不存在時回傳空字串。"""
    if not lines or not os.path.isfile(path):
        return ''
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - max_bytes))
        data = f.read()
    return '\n'.join(data.decode('utf-8', errors='replace').splitlines()[-lines:])


def _prune_scenes(root, keep, max_bytes=0):
    """依份數與總大小清理現場，從最舊的刪起；最新的一份一定保留。

    資料夾以時間開頭命名，依名稱排序即依時間排序；其他資料夾不動。
    """
    scenes = sorted(d for d in os.listdir(root)
                    if d[:8].isdigit() and os.path.isdir(os.path.join(root, d)))
    if keep > 0:
        for d in scenes[:-keep]:
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)
        scenes = scenes[-keep:]
    if max_bytes > 0:
        sizes = [_folder_size(os.path.join(root, d)) for d in scenes]
        total = sum(sizes)
        for d, size in zip(scenes[:-1], sizes):
            if total <= max_bytes:
                break
            shutil.rmtree(os.path.join(root, d), ignore_errors=True)
            total -= size


_last_screenshot_check = None


def maybe_clean_screenshots(task):
    """每隔 screenshot_check_interval 秒檢查一次框架的截圖資料夾，超過上限就從最舊的檔案刪起。

    框架只在程式啟動時清理這個資料夾，連續掛機好幾天會一直變大。
    """
    global _last_screenshot_check
    now = time.time()
    if _last_screenshot_check is None:
        # 框架啟動時剛清理過，下次檢查從現在開始計時
        _last_screenshot_check = now
        return
    if now - _last_screenshot_check < GUARD.screenshot_check_interval:
        return
    _last_screenshot_check = now
    try:
        removed, freed = _trim_folder(GUARD.screenshot_dir, GUARD.screenshot_max_mb * 1024 * 1024)
    except Exception as e:
        task.log_info(f'清理截圖資料夾失敗：{e}')
        return
    if removed:
        task.log_info(f'截圖資料夾超過 {GUARD.screenshot_max_mb:g} MB，'
                      f'刪除最舊的 {removed} 個檔案（{freed / 1024 / 1024:.1f} MB）')


def _trim_folder(root, max_bytes):
    """資料夾總大小超過 max_bytes 時，依修改時間從最舊的檔案刪起。回傳（刪除數, 釋放的位元組）。"""
    if not os.path.isdir(root):
        return 0, 0
    files = []
    for dirpath, _, names in os.walk(root):
        for name in names:
            path = os.path.join(dirpath, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            files.append((st.st_mtime, st.st_size, path))
    total = sum(size for _, size, _ in files)
    removed = freed = 0
    for _, size, path in sorted(files):
        if total <= max_bytes:
            break
        try:
            os.remove(path)
        except OSError:
            continue  # 框架可能正在寫入這個檔案
        total -= size
        removed += 1
        freed += size
    return removed, freed


def _folder_size(path):
    total = 0
    for dirpath, _, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total
