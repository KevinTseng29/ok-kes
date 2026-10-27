"""例外保護與錯誤現場保存（參考 AzurLaneAutoScript 的 failure_record 與 save_error_log）。

ok-script 的執行器遇到任務丟出未處理的例外時，會直接停用任務，並把 _enabled=False
寫進設定檔，所以一次 OCR 誤讀就可能讓整晚的掛機停掉。這個模組提供：

- guarded_run：包住 TriggerTask.run()。出錯時先記錄、保存現場，下一輪再試；
  連續失敗太多次，或短時間內累計失敗太多次，才交給框架停止任務（框架會發錯誤通知）。
- save_scene：把最近幾輪的截圖、說明與最近的 log 存到 error_scenes/，
  出錯或畫面卡住時呼叫，方便事後重現問題。

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
    # 錯誤現場的資料夾與保留份數
    scene_dir: str = 'error_scenes'
    max_scenes: int = 30
    # 同一種原因多久內只保存一次現場（秒）
    scene_min_interval: float = 60
    # 一併保存的 log 檔與行數
    log_file: str = os.path.join('logs', 'ok-script.log')
    log_tail_lines: int = 300


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
            name = f'{i:02d}_{time.strftime("%H%M%S", time.localtime(t))}_{int(t % 1 * 1000):03d}.png'
            _write_image(os.path.join(folder, name), frame)
        with open(os.path.join(folder, 'info.txt'), 'w', encoding='utf-8') as f:
            f.write(f'任務：{type(task).__name__}\n')
            f.write(f'原因：{reason}\n')
            f.write(f'時間：{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))}\n')
            f.write(f'截圖：{len(frames)} 張（依時間排序，最後一張最接近出錯當下）\n')
            if detail:
                f.write(f'\n{detail}\n')
        tail = _read_log_tail(GUARD.log_file, GUARD.log_tail_lines)
        if tail:
            with open(os.path.join(folder, 'log.txt'), 'w', encoding='utf-8') as f:
                f.write(tail)
        _prune_scenes(GUARD.scene_dir, GUARD.max_scenes)
    except Exception as e:
        task.log_info(f'保存錯誤現場失敗：{e}')
        return None

    task.log_info(f'已保存錯誤現場：{folder}（{len(frames)} 張截圖）')
    return folder


def _write_image(path, frame):
    import cv2  # 延後匯入，單元測試不需要 OpenCV
    ok, buf = cv2.imencode('.png', frame)
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


def _prune_scenes(root, keep):
    """只保留最新的 keep 份現場（資料夾以時間開頭命名，依名稱排序即依時間排序）。"""
    if keep <= 0:
        return
    scenes = sorted(d for d in os.listdir(root)
                    if d[:8].isdigit() and os.path.isdir(os.path.join(root, d)))
    for d in scenes[:-keep]:
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
