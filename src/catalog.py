"""事件任務、卡牌、裝備的目錄：腳本執行時記下看到的名稱與效果，給設定頁挑選。

- ok_tasks 的辨識函式（事件選項、卡牌、裝備）呼叫 record()；設定頁「目录设置 → 自动收集目录」
  關閉時不記錄。
- 存在設定資料夾的 catalog.json，只在本機，不會上傳。依遊戲語言分開存，國服與國際服用詞不同。
- 文字是 OCR 轉簡體後的結果。同一項在 CATALOG.repeat_window 秒內重複看到只算一次（每輪都會
  辨識同一個畫面），出現次數可用來分辨 OCR 讀錯的條目。
- 新條目立刻存檔，只更新次數的話最多每 CATALOG.save_interval 秒存一次。
- 卡牌、裝備第一次看到時另存一張裁切的 JPG（catalog_images/），給設定頁對照；
  條目被淘汰或刪除時圖片一起刪，所以總量受 max_entries_per_kind 限制。
- 每筆記下在哪裡看到（sources：出击、零号系统、赛季卡厄思；卡厄思模式還分不出種類時記成卡厄思），
  出擊與各種卡厄思的事件、卡牌、裝備不一定相同，挑選時依來源篩選。

本模組不依賴 ok 套件，方便單元測試。
"""
import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass

KINDS = ('event', 'card', 'equipment')
KIND_NAMES = {'event': '事件任务', 'card': '卡牌', 'equipment': '装备'}
# 來源：模式 → 可能的來源（卡厄思模式分不出種類時記成「卡厄思」）
SORTIE_SOURCE = '出击'
CHAOS_SOURCES = ('零号系统', '赛季卡厄思', '卡厄思')
MODE_SOURCES = {'SortieMode': (SORTIE_SOURCE,), 'SortieModeExperimental': (SORTIE_SOURCE,), 'ChaosMode': CHAOS_SOURCES,
                'ChaosModeExperimental': CHAOS_SOURCES}
CONFIG_NAME = '目录设置'
ENABLED_KEY = '自动收集目录'


@dataclass
class CatalogSettings:
    file_name: str = 'catalog.json'
    image_dir: str = 'catalog_images'
    jpg_quality: int = 85
    repeat_window: float = 60
    save_interval: float = 30
    max_entries_per_kind: int = 2000


CATALOG = CatalogSettings()


def _norm(text):
    return re.sub(r'\s+', '', text or '')


def _write_image(path, image):
    import cv2
    ok, buf = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, CATALOG.jpg_quality])
    if not ok:
        raise OSError('JPG 編碼失敗')
    buf.tofile(path)


def entry_key(kind, name, text):
    if kind == 'event':
        return _norm(text)
    if kind == 'card':
        return f'{_norm(name)}|{_norm(text)}'
    return _norm(name)


class Catalog:
    def __init__(self, path, clock=time.time):
        self.path = path
        self.clock = clock
        self.lock = threading.Lock()
        self.data = self._load()
        self.dirty = False
        self.last_save = 0.0

    def _load(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _bucket(self, lang, kind):
        return self.data.setdefault(lang, {}).setdefault(kind, {})

    def record(self, kind, name, text, lang, info='', image=None, source=''):
        """記一筆；回傳 True 表示是新條目。名稱或內容太短（OCR 沒讀到）就略過。
        image 是裁切好的畫面（numpy 陣列）或產生它的函式，條目還沒有圖時才取用並存檔。
        source 是在哪裡看到的（出击、零号系统…），記在 sources 裡並累計次數。"""
        name, text = (name or '').strip(), (text or '').strip()
        if kind not in KINDS or (kind == 'event' and len(_norm(text)) < 2) or (kind != 'event' and not _norm(name)):
            return False
        now = self.clock()
        key = entry_key(kind, name, text)
        removed_images = []
        with self.lock:
            bucket = self._bucket(lang, kind)
            entry = bucket.get(key)
            is_new = entry is None
            if is_new:
                entry = bucket[key] = {'name': name, 'text': text, 'info': info, 'seen': 0, 'last': 0}
                removed_images = self._evict(bucket, keep=key)
            if now - entry['last'] >= CATALOG.repeat_window:
                entry['seen'] += 1
                if source:
                    sources = entry.setdefault('sources', {})
                    sources[source] = sources.get(source, 0) + 1
            entry['last'] = now
            # 裝備以名稱去重，描述與品質以最新看到的為準；
            # 少了品質的資訊（選擇裝備界面讀不到品質）不蓋掉已有品質的資訊
            if text:
                entry['text'] = text
            if info and not (entry.get('info') or '').startswith(info):
                entry['info'] = info
            needs_image = image is not None and not entry.get('image')
            self.dirty = True
        for path in removed_images:
            self._delete_image(path)
        if needs_image:
            image = image() if callable(image) else image
            needs_image = image is not None
        if needs_image:
            self._save_image(entry, lang, kind, key, image)
        self.save(force=is_new or needs_image)
        return is_new

    def _evict(self, bucket, keep):
        overflow = len(bucket) - CATALOG.max_entries_per_kind
        removed = []
        if overflow > 0:
            candidates = sorted((k for k in bucket if k != keep), key=lambda k: (bucket[k]['seen'], bucket[k]['last']))
            for key in candidates[:overflow]:
                removed.append(bucket.pop(key).get('image'))
        return [path for path in removed if path]

    def image_path(self, entry):
        """條目圖片的絕對路徑；沒有圖或檔案不見了回傳 None。"""
        relative = entry.get('image')
        if not relative:
            return None
        path = os.path.normpath(os.path.join(os.path.dirname(self.path), relative))
        return path if os.path.exists(path) else None

    def _save_image(self, entry, lang, kind, key, image):
        digest = hashlib.sha1(f'{lang}|{kind}|{key}'.encode('utf-8')).hexdigest()[:16]
        relative = os.path.join(CATALOG.image_dir, kind, f'{digest}.jpg')
        path = os.path.join(os.path.dirname(self.path), relative)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _write_image(path, image)
        except Exception:
            return
        with self.lock:
            entry['image'] = relative.replace(os.sep, '/')

    def _delete_image(self, relative):
        try:
            os.remove(os.path.join(os.path.dirname(self.path), relative))
        except OSError:
            pass

    def entries(self, kind, lang):
        """回傳 [(key, entry)]，依出現次數多到少排序。"""
        with self.lock:
            bucket = dict(self.data.get(lang, {}).get(kind, {}))
        return sorted(bucket.items(), key=lambda item: (-item[1]['seen'], -item[1]['last']))

    def remove(self, kind, lang, keys):
        with self.lock:
            bucket = self.data.get(lang, {}).get(kind, {})
            images = [bucket.pop(key, {}).get('image') for key in keys]
            self.dirty = True
        for path in images:
            if path:
                self._delete_image(path)
        self.save(force=True)

    def save(self, force=False):
        with self.lock:
            if not self.dirty or (not force and self.clock() - self.last_save < CATALOG.save_interval):
                return False
            payload = json.dumps(self.data, ensure_ascii=False, indent=1)
            self.dirty = False
            self.last_save = self.clock()
        try:
            os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
            tmp = f'{self.path}.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write(payload)
            os.replace(tmp, self.path)
            return True
        except OSError:
            self.dirty = True
            return False


_catalogs = {}
_catalogs_lock = threading.Lock()


def default_path():
    from src.config import _get_config_folder
    return os.path.join(_get_config_folder(), CATALOG.file_name)


def get_catalog(path=None):
    path = path or default_path()
    with _catalogs_lock:
        if path not in _catalogs:
            _catalogs[path] = Catalog(path)
        return _catalogs[path]


def collecting_enabled(task):
    try:
        return task.get_global_config(CONFIG_NAME).get(ENABLED_KEY, True) is not False
    except Exception:
        return True


def crop(frame, region):
    """依相對座標 (x1, y1, x2, y2) 裁切畫面，稍微外擴一點；畫面不存在時回傳 None。"""
    if frame is None:
        return None
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = region
    pad = 0.005
    left, top = int(max(0.0, x1 - pad) * width), int(max(0.0, y1 - pad) * height)
    right, bottom = int(min(1.0, x2 + pad) * width), int(min(1.0, y2 + pad) * height)
    if right <= left or bottom <= top:
        return None
    return frame[top:bottom, left:right].copy()


def union(*regions):
    regions = [r for r in regions if r]
    return (min(r[0] for r in regions), min(r[1] for r in regions),
            max(r[2] for r in regions), max(r[3] for r in regions))


def record(task, kind, name, text, lang, info='', region=None, path=None, source=''):
    """給辨識函式呼叫：開關打開時記進目錄；有 region 時順便存該區域的裁切圖。"""
    if not collecting_enabled(task):
        return False
    image = (lambda: crop(getattr(task, 'frame', None), region)) if region else None
    return get_catalog(path).record(kind, name, text, lang, info, image, source)


def from_sources(entry, sources):
    """條目是否在這些來源看過；沒有來源紀錄的舊條目一律算符合。"""
    seen = entry.get('sources')
    return not sources or not seen or any(source in seen for source in sources)


def mode_of(config):
    """由模式設定檔名（ChaosMode.json 等）判斷是哪個模式；看不出來回傳空字串。"""
    name = os.path.splitext(os.path.basename(getattr(config, 'config_file', '') or ''))[0]
    return name if name in MODE_SOURCES else ''


def matches(entry, query, shown=None):
    """搜尋：去空白後，名稱、內容、補充資訊或其顯示文字包含關鍵字即符合。"""
    query = _norm(query)
    if not query:
        return True
    fields = [entry.get('name', ''), entry.get('text', ''), entry.get('info', '')]
    if shown:
        fields += [shown(field) for field in fields if field]
    return any(query in _norm(field) for field in fields)
