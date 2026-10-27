"""例外保護與錯誤現場保存（參考 AzurLaneAutoScript 的 failure_record 與 save_error_log）。

ok-script 的執行器遇到任務丟出未處理的例外時，會直接停用任務，並把 _enabled=False
寫進設定檔，所以一次 OCR 誤讀就可能讓整晚的掛機停掉。這個模組提供：

- guarded_run：包住 TriggerTask.run()。出錯時先記錄、保存現場，下一輪再試；
  連續失敗太多次，或短時間內累計失敗太多次，才交給框架停止任務（框架會發錯誤通知）。
- save_scene：把最近幾輪的截圖、說明與最近的 log 存到 error_scenes/，
  出錯或畫面卡住時呼叫，方便事後重現問題。依份數與總大小自動清理。
- maybe_clean_screenshots：框架只在程式啟動時清理 screenshots/，
  這裡在執行中定期檢查，超過上限就從最舊的檔案刪起。

用法：
    @guarded_run
    def run(self): ...

所有參數集中在 GUARD，改 GUARD.enabled = False 即可整個關閉。
本模組不依賴 ok 套件，方便單元測試。
"""

import functools
import os
import random
import shutil
import time
import traceback
from collections import deque
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


GUARD = GuardSettings()

# 框架用來控制流程的例外（使用者停止任務等），必須原樣往外丟
_PASSTHROUGH = ('TaskDisabledException', 'FinishedException')


class _GuardState:
    def __init__(self, buffer_size):
        self.frames = deque(maxlen=buffer_size)
        self.consecutive = 0
        self.failures = deque()
        self.last_scene = {}


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
        return result

    return wrapper


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
