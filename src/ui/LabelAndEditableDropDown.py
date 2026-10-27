"""可直接輸入、也可從下拉選單挑選的文字設定（設定類型 'editable_drop_down'）。

用法：config_type[key] = {'type': 'editable_drop_down', 'options': [...]}，預設值必須是字串。
options 也可以是 {值: [...]} 搭配 'options_key'：依同一份設定裡 options_key 欄位的值挑選項，
例如依「游戏语言」切換國服／國際服的角色名（每次展開選單時重新挑，不必重開程式）。
輸入文字時會列出包含該文字的選項，選項多時不用捲動找。

選單項目照介面語言顯示（經 og.app.tr，繁體介面會轉成繁體），選到的項目存回原本的選項文字；
手動輸入、不在選單裡的文字原樣保存。只影響設定頁，不會在 default_config 加欄位。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCompleter
from qfluentwidgets import EditableComboBox

from ok import og
from ok.gui.tasks.ConfigLabelAndWidget import ConfigLabelAndWidget

TYPE_NAME = 'editable_drop_down'


class LabelAndEditableDropDown(ConfigLabelAndWidget):

    def __init__(self, config_desc, options, config, key: str, options_key=None):
        super().__init__(config_desc, config, key)
        self.key = key
        self.options_source = options
        self.options_key = options_key
        self.display_to_option = None

        self.combo_box = EditableComboBox()
        self.combo_box.setMinimumWidth(160)
        self.load_options()
        self.update_value()
        self.combo_box.currentTextChanged.connect(self.text_changed)
        self.combo_box.dropButton.pressed.connect(self.load_options)
        self.add_widget(self.combo_box, stretch=0)

    def current_options(self):
        if not isinstance(self.options_source, dict):
            return list(self.options_source)
        options = self.options_source.get(self.config.get(self.options_key))
        if options is None:
            options = next(iter(self.options_source.values()), [])
        return list(options)

    def load_options(self):
        mapping = {}
        for option in self.current_options():
            mapping.setdefault(og.app.tr(option), option)
        if mapping == self.display_to_option:
            return
        self.display_to_option = mapping
        text = self.combo_box.text()
        self.combo_box.blockSignals(True)
        self.combo_box.clear()
        self.combo_box.addItems(list(mapping))
        self.combo_box.setText(text)
        self.combo_box.blockSignals(False)
        # 選項多時打字篩選：輸入名字的任一部分就列出符合的選項
        completer = QCompleter(list(mapping), self.combo_box)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setMaxVisibleItems(10)
        self.combo_box.setCompleter(completer)

    def text_changed(self, text):
        text = text.strip()
        self.update_config(self.display_to_option.get(text, text))

    def update_value(self):
        value = self.config.get(self.key) or ''
        self.combo_box.blockSignals(True)
        self.combo_box.setText(og.app.tr(value) if value else '')
        self.combo_box.blockSignals(False)


def install():
    """讓框架的設定頁認得 'editable_drop_down'；在建立 ok.OK 之前呼叫，重複呼叫不會重複包裝。"""
    from ok.gui.tasks import ConfigCard, ConfigItemFactory

    original = ConfigItemFactory.config_widget
    if getattr(original, '_editable_drop_down', False):
        return

    def config_widget(config_type, config_desc, config, key, value, task):
        the_type = config_type.get(key) if config_type is not None else None
        if isinstance(the_type, dict) and the_type.get('type') == TYPE_NAME:
            return LabelAndEditableDropDown(config_desc, the_type.get('options', []), config, key,
                                            options_key=the_type.get('options_key'))
        return original(config_type, config_desc, config, key, value, task)

    config_widget._editable_drop_down = True
    ConfigItemFactory.config_widget = config_widget
    ConfigCard.config_widget = config_widget
