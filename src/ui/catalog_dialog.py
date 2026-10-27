"""設定頁清單的「從目錄挑選」：從自動收集的目錄（src/catalog.py）搜尋事件任務、卡牌、裝備，
看得到效果，選取後加進優先級或拉黑清單。

- 只在 LIST_CATALOGS 列出的清單編輯視窗出現，選項依該模式的「游戏语言」分開；
  裝備 N 號位優先級只列出該號位的裝備。
- 只列出在目前模式看過的項目（出擊、卡厄思分開）；卡厄思模式可再切換只看零號系統或賽季卡厄思。
- 加入的是名稱（事件任務是任務內容；閃光優先級是名稱＋效果，可再刪短）。顯示照介面語言，
  存檔仍是目錄裡的原文（簡體），執行時會先轉簡體再比對。
- 清單裡已有的卡牌、裝備，滑鼠停在上面會顯示目錄裡的效果。
- 卡牌、裝備選一列時，右邊顯示第一次看到時存下的截圖，方便對照 OCR 是否讀錯。
- 國際服（游戏语言＝繁体中文）的卡牌清單改用卡牌資料庫挑選（src/ui/card_picker.py），
  依隊伍角色篩選，別人的牌不會混進來；資料庫讀不到時才用執行時收集的目錄。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QTableWidgetItem
from qfluentwidgets import BodyLabel, ComboBox, LineEdit, MessageBoxBase, PushButton, SubtitleLabel, TableWidget

from ok import og
from src import card_db, catalog

CARD_DB_LANG = '繁体中文'

LIST_CATALOGS = {
    '任务优先级': 'event',
    '拉黑任务': 'event',
    '闪光优先级': 'card',
    '移除卡牌列表': 'card',
    '闪光卡牌列表': 'card',
    '复制卡牌列表': 'card',
    '需要冥想的卡牌': 'card',
    '卡牌奖励优先级': 'card',
    '出牌优先级': 'card',
    '获得卡牌优先级': 'card',
    '丢弃卡牌优先级': 'card',
    '装备1号位优先级': 'equipment',
    '装备2号位优先级': 'equipment',
    '装备3号位优先级': 'equipment',
}
# 這些清單比對的是「卡名＋效果」，加入時一併帶上效果
NAME_AND_TEXT_KEYS = {'闪光优先级'}
# 裝備清單只列該號位的裝備（目錄的 info 以「N号位」開頭）
SLOT_KEYS = {f'装备{slot}号位优先级': f'{slot}号位' for slot in (1, 2, 3)}
PREVIEW_SIZE = (260, 380)


def _tr(text):
    return og.app.tr(text) if text else text


def keyword_of(kind, entry, with_text=False):
    if kind == 'event':
        return entry['text']
    if with_text and entry.get('text'):
        return entry['name'] + entry['text']
    return entry['name']


def _columns(kind):
    if kind == 'event':
        return [_tr('任务内容'), _tr('来源'), _tr('出现次数')]
    return [_tr('名称'), _tr('效果'), _tr('类型'), _tr('来源'), _tr('出现次数')]


def _source_text(entry):
    return '、'.join(_tr(source) for source in entry.get('sources', {}))


def _source_choices(sources):
    """來源篩選的選項：(顯示文字, 來源組)。只有一種來源時不需要篩選。"""
    if len(sources) <= 1:
        return []
    # 「卡厄思」是還分不出種類時的紀錄，只出現在「全部」
    return [(_tr('全部'), tuple(sources))] + [(_tr(s), (s,)) for s in sources if s != '卡厄思']


class CatalogDialog(MessageBoxBase):

    def __init__(self, kind, lang, parent, on_add, with_text=False, path=None, info_prefix=None, sources=()):
        super().__init__(parent)
        self.kind, self.lang, self.on_add, self.with_text = kind, lang, on_add, with_text
        self.info_prefix = info_prefix
        self.sources = tuple(sources)
        self.catalog = catalog.get_catalog(path)
        self.rows = []

        title = f"{_tr('从目录挑选')}：{_tr(catalog.KIND_NAMES[kind])}"
        if info_prefix:
            title += f"（{_tr(info_prefix)}）"
        self.viewLayout.addWidget(SubtitleLabel(title, self))
        self.hint = BodyLabel(_tr('双击或选取后按「加入」；目录是执行时自动记下的，次数越多越可靠。'), self)
        self.hint.setWordWrap(True)
        self.viewLayout.addWidget(self.hint)
        self.search = LineEdit(self)
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText(_tr('搜索名称或效果'))
        self.search.textChanged.connect(self.reload)
        self.source_filter = None
        choices = _source_choices(self.sources)
        if choices:
            self.source_filter = ComboBox(self)
            for text, group in choices:
                self.source_filter.addItem(text, userData=group)
            self.source_filter.currentIndexChanged.connect(lambda _: self.reload())
            search_row = QHBoxLayout()
            search_row.addWidget(self.search, 1)
            search_row.addWidget(self.source_filter)
            self.viewLayout.addLayout(search_row)
        else:
            self.viewLayout.addWidget(self.search)

        self.table = TableWidget(self)
        self.table.setColumnCount(len(_columns(kind)))
        self.table.setHorizontalHeaderLabels(_columns(kind))
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        stretch_column = 0 if kind == 'event' else 1
        for column in range(self.table.columnCount()):
            mode = QHeaderView.ResizeMode.Stretch if column == stretch_column else QHeaderView.ResizeMode.ResizeToContents
            header.setSectionResizeMode(column, mode)
        self.table.itemDoubleClicked.connect(lambda item: self.add_rows([item.row()]))
        self.preview = None
        if kind == 'event':
            self.viewLayout.addWidget(self.table, 1)
        else:
            self.preview = BodyLabel(self)
            self.preview.setFixedWidth(PREVIEW_SIZE[0])
            self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview.setWordWrap(True)
            row_layout = QHBoxLayout()
            row_layout.addWidget(self.table, 1)
            row_layout.addWidget(self.preview)
            self.viewLayout.addLayout(row_layout, 1)
            self.table.itemSelectionChanged.connect(self.show_preview)

        self.empty_label = BodyLabel(self)
        self.empty_label.setWordWrap(True)
        self.viewLayout.addWidget(self.empty_label)

        self.add_button = PushButton(_tr('加入'), self)
        self.add_button.clicked.connect(lambda: self.add_rows(self.selected_rows()))
        self.delete_button = PushButton(_tr('从目录删除'), self)
        self.delete_button.setToolTip(_tr('删除识别错误的条目；之后再看到还会重新记下'))
        self.delete_button.clicked.connect(self.delete_selected)
        self.buttonLayout.insertWidget(0, self.delete_button, 1, Qt.AlignmentFlag.AlignVCenter)
        self.buttonLayout.insertWidget(0, self.add_button, 1, Qt.AlignmentFlag.AlignVCenter)
        self.yesButton.setText(_tr('关闭'))
        self.cancelButton.hide()
        self.widget.setMinimumSize(1000 if self.preview else 900, 620)
        self.reload()

    def active_sources(self):
        if self.source_filter is not None:
            return self.source_filter.currentData() or self.sources
        return self.sources

    def all_entries(self):
        entries = self.catalog.entries(self.kind, self.lang)
        if self.info_prefix:
            entries = [(key, entry) for key, entry in entries if entry.get('info', '').startswith(self.info_prefix)]
        sources = self.active_sources()
        return [(key, entry) for key, entry in entries if catalog.from_sources(entry, sources)]

    def reload(self):
        query = self.search.text()
        self.rows = [(key, entry) for key, entry in self.all_entries() if catalog.matches(entry, query, _tr)]
        self.table.setRowCount(len(self.rows))
        for row, (key, entry) in enumerate(self.rows):
            if self.kind == 'event':
                cells = [_tr(entry['text']), _source_text(entry), str(entry['seen'])]
            else:
                cells = [_tr(entry['name']), _tr(entry.get('text', '')), _tr(entry.get('info', '')),
                         _source_text(entry), str(entry['seen'])]
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, column, item)
        self.table.resizeRowsToContents()
        total = len(self.all_entries())
        if total == 0:
            self.empty_label.setText(_tr('目录还没有资料：开着「自动收集目录」跑几局，看到的项目会自动记在这里。'))
        elif not self.rows:
            self.empty_label.setText(_tr('没有符合搜索的项目。'))
        else:
            self.empty_label.setText('')
        self.empty_label.setVisible(bool(self.empty_label.text()))
        self.show_preview()

    def show_preview(self):
        if self.preview is None:
            return
        rows = self.selected_rows()
        path = self.catalog.image_path(self.rows[rows[0]][1]) if rows and rows[0] < len(self.rows) else None
        pixmap = QPixmap(path) if path else QPixmap()
        if pixmap.isNull():
            self.preview.setPixmap(QPixmap())
            self.preview.setText(_tr('选一列查看截图') if not rows else _tr('这一项没有截图'))
            return
        self.preview.setPixmap(pixmap.scaled(
            *PREVIEW_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def selected_rows(self):
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def add_rows(self, rows):
        keywords = [keyword_of(self.kind, self.rows[row][1], self.with_text) for row in rows if row < len(self.rows)]
        if keywords:
            self.on_add(keywords)

    def delete_selected(self):
        keys = [self.rows[row][0] for row in self.selected_rows()]
        if keys:
            self.catalog.remove(self.kind, self.lang, keys)
            self.reload()


def _effect_lookup(kind, lang, path=None, sources=(), db=None):
    """名稱 → 顯示用的效果說明（卡牌取出現最多的那一筆；有資料庫時以資料庫為準）。"""
    lookup = {}
    if kind == 'event':
        return lookup
    if db is not None:
        for card in db.cards.values():
            if card.get('name') and card.get('text'):
                lookup.setdefault(card['name'], card_db.clean_text(card['text']))
    for _, entry in catalog.get_catalog(path).entries(kind, lang):
        if entry.get('text') and catalog.from_sources(entry, sources):
            lookup.setdefault(entry['name'], entry['text'])
    return lookup


def _card_db_for(kind, lang):
    return card_db.load() if kind == 'card' and lang == CARD_DB_LANG else None


def add_keywords(dialog, keywords, effects=None):
    """把關鍵字加進清單編輯視窗；顯示照介面語言，確認時存回原文。"""
    existing = {dialog.list_widget.item(i).text() for i in range(dialog.list_widget.count())}
    source_by_shown = getattr(dialog, '_source_by_shown', None)
    for keyword in keywords:
        shown = _tr(keyword)
        if not dialog.allow_duplication and shown in existing:
            continue
        dialog.list_widget.addItem(shown)
        item = dialog.list_widget.item(dialog.list_widget.count() - 1)
        if effects and keyword in effects:
            item.setToolTip(_tr(effects[keyword]))
        if source_by_shown is not None:
            source_by_shown.setdefault(shown, keyword)
        existing.add(shown)
    dialog.update_list_actions()


def attach(dialog, key, config, path=None):
    """在清單編輯視窗加上「從目錄挑選」，並替已有項目加上效果提示。回傳是否有加。"""
    kind = LIST_CATALOGS.get(key)
    if kind is None or dialog.options_available is not None:
        return False
    lang = (config.get('游戏语言') if config is not None else None) or '简体中文'
    mode = catalog.mode_of(config)
    sources = catalog.MODE_SOURCES.get(mode, ())
    db = _card_db_for(kind, lang)
    effects = _effect_lookup(kind, lang, path, sources, db)
    source_by_shown = getattr(dialog, '_source_by_shown', None) or {}
    for i in range(dialog.list_widget.count()):
        item = dialog.list_widget.item(i)
        source = source_by_shown.get(item.text(), item.text())
        if source in effects:
            item.setToolTip(_tr(effects[source]))

    def open_picker():
        on_add = lambda words: add_keywords(dialog, words, effects)  # noqa: E731
        if db is not None:
            from src.ui.card_picker import CardPickerDialog
            picker = CardPickerDialog(db, lang, mode, config, dialog.window(), on_add,
                                      with_text=key in NAME_AND_TEXT_KEYS, path=path)
        else:
            picker = CatalogDialog(kind, lang, dialog.window(), on_add,
                                   with_text=key in NAME_AND_TEXT_KEYS, path=path, info_prefix=SLOT_KEYS.get(key),
                                   sources=sources)
        picker.exec()

    button = PushButton(_tr('从目录挑选'), dialog)
    button.clicked.connect(open_picker)
    dialog.buttonLayout.insertWidget(0, button, 1, Qt.AlignmentFlag.AlignVCenter)
    dialog.catalog_button = button
    return True


def install():
    """在建立 ok.OK 之前呼叫；重複呼叫不會重複包裝。"""
    from ok.gui.tasks import ModifyListItem as module

    if getattr(module.ModifyListItem, '_ok_kes_catalog', False):
        return

    def clicked(self):
        dialog = module.ModifyListDialog(
            self.config.get(self.key), self.window(), options_available=self.options_available,
            allow_duplication=self.allow_duplication
        )
        attach(dialog, self.key, self.config)
        dialog.list_modified.connect(self.list_modified)
        dialog.exec()

    module.ModifyListItem.clicked = clicked
    module.ModifyListItem._ok_kes_catalog = True
