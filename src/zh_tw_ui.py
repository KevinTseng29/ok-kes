"""繁體中文介面。

框架本身的字串（開始、停止、設定頁等）已有繁體翻譯，但 ok-kes 自己的任務名稱、設定名稱、
說明文字與狀態欄都寫死成簡體，i18n 也沒有 zh_TW 的 po 檔，介面會簡繁混雜。

install() 包住框架的 App.tr：介面語言是繁體（zh_TW / zh_HK / zh_MO）且字串沒有現成翻譯時，
用 OpenCC 轉成繁體再顯示。只影響顯示：下拉選單與可選清單由框架把顯示文字對回原本的選項，
設定檔存的仍是原值，與 OCR 比對的邏輯不受影響。

CONVERSION 用 's2tw'：只換字形、不換詞彙，避免把遊戲用語改掉（例如 's2twp' 會把「刷新」改成「重新整理」）。
"""
import functools
import re

CONVERSION = 's2tw'
TRADITIONAL_LOCALES = ('zh_TW', 'zh_HK', 'zh_MO')
_HAN = re.compile(r'[一-鿿]')


@functools.lru_cache(maxsize=4096)
def _convert(text):
    return _converter().convert(text)


@functools.lru_cache(maxsize=1)
def _converter():
    from opencc import OpenCC
    return OpenCC(CONVERSION)


def _is_traditional(app):
    try:
        return app.locale.name() in TRADITIONAL_LOCALES
    except Exception:
        return False


def wrap_tr(tr):
    @functools.wraps(tr)
    def wrapper(app, key):
        translated = tr(app, key)
        if translated != key or not isinstance(key, str) or not _HAN.search(key):
            return translated
        if not _is_traditional(app):
            return translated
        try:
            return _convert(key)
        except Exception:
            return translated

    wrapper._zh_tw_wrapped = True
    return wrapper


def install():
    """在建立 ok.OK 之前呼叫；重複呼叫不會重複包裝。"""
    import ok
    if not getattr(ok.App.tr, '_zh_tw_wrapped', False):
        ok.App.tr = wrap_tr(ok.App.tr)
