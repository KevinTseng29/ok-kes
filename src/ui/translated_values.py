"""讓設定頁的「值」也照介面語言顯示：自由輸入的清單、單行與多行文字欄位。

框架只翻譯欄位名稱、下拉選項與可選清單；自己輸入的清單（任務優先級、移除卡牌列表…）
和文字欄位（指定面具卡牌…）會原樣顯示，繁體介面下就變成簡繁混雜。

這裡把顯示文字換成 og.app.tr(值)（繁體介面由 src/zh_tw_ui 轉成繁體），並記住顯示文字
對應的原值：沒改動的項目存回原值，新增或改過的照輸入的文字保存。執行時設定值會先轉成
簡體再和 OCR 比對，所以存繁體也能用。
"""
from ok import og


def _shown(value):
    return og.app.tr(value) if isinstance(value, str) and value else value


def _patch_list_item():
    from ok.gui.tasks import ModifyListItem as module
    from ok.gui.widget.UpdateConfigWidgetItem import value_to_string

    original = module.ModifyListItem.update_value

    def update_value(self):
        if self.options_available is not None:
            return original(self)
        full_text = value_to_string([_shown(item) for item in self.config.get(self.key)])
        display_text = full_text
        if len(display_text) > module.MAX_LIST_DISPLAY_LENGTH:
            display_text = f'{display_text[:module.MAX_LIST_DISPLAY_LENGTH - 3]}...'
        self.list_text.setText(display_text)
        self.list_text.setToolTip(full_text if display_text != full_text else '')

    module.ModifyListItem.update_value = update_value


def _patch_list_dialog():
    from ok.gui.tasks.ModifyListDialog import ModifyListDialog

    original_init = ModifyListDialog.__init__
    original_confirm = ModifyListDialog.confirm

    def __init__(self, items, parent, options_available=None, allow_duplication=False):
        original_init(self, items, parent, options_available, allow_duplication)
        self._source_by_shown = None
        if self.options_available is None:
            self._source_by_shown = {}
            for item in self.original_items:
                self._source_by_shown.setdefault(_shown(item), item)
            self.list_widget.clear()
            self.list_widget.addItems([_shown(item) for item in self.original_items])
            self.update_list_actions()

    def confirm(self):
        if getattr(self, '_source_by_shown', None) is None:
            return original_confirm(self)
        texts = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        self.list_modified.emit([self._source_by_shown.get(text, text) for text in texts])
        self.close()

    ModifyListDialog.__init__ = __init__
    ModifyListDialog.confirm = confirm


def _patch_text_widget(widget_class, editor_name, read_text):
    """單行／多行文字欄位：顯示翻譯後的值，沒改動就存回原值。"""
    def update_value(self):
        value = self.config.get(self.key)
        self._source_value, self._shown_value = value, _shown(value)
        editor = getattr(self, editor_name)
        editor.blockSignals(True)
        editor.setText(self._shown_value)
        editor.blockSignals(False)
        self._update_width(self._shown_value or '')

    def value_changed(self, *args):
        text = read_text(self, *args)
        if text == getattr(self, '_shown_value', None):
            self.update_config(self._source_value)
        else:
            self.update_config(text)
        self._update_width(text)

    widget_class.update_value = update_value
    widget_class.value_changed = value_changed


def install():
    """在建立 ok.OK 之前呼叫；重複呼叫不會重複包裝。"""
    from ok.gui.tasks.LabelAndLineEdit import LabelAndLineEdit
    from ok.gui.tasks.LabelAndTextEdit import LabelAndTextEdit
    from ok.gui.tasks.ModifyListDialog import ModifyListDialog

    if getattr(ModifyListDialog, '_ok_kes_translated_values', False):
        return
    _patch_list_item()
    _patch_list_dialog()
    _patch_text_widget(LabelAndLineEdit, 'line_edit', lambda self, text: text)
    _patch_text_widget(LabelAndTextEdit, 'text_edit', lambda self: self.text_edit.toPlainText())
    ModifyListDialog._ok_kes_translated_values = True
