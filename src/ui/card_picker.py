"""從卡牌資料庫挑卡（國際服）：先選隊伍角色，只列他們的牌（可加中立牌），避免別人的牌混進來。

- 資料來自 src/card_db.py（遊戲靜態資料，完整、知道每張牌屬於誰）。
- 隊伍最多 3 位，依模式記在 catalog_team.json；第一次開啟時卡厄思取刷存档主战员、
  出擊取出战主战员优先级的前三位。
- 「看過」與截圖來自執行時收集的目錄（src/catalog.py），依卡名對應。
- 閃光優先級（with_text）每個靈光版本各列一次，加入「名稱＋效果片段」；其他清單只加入名稱。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QTableWidgetItem
from qfluentwidgets import (BodyLabel, CheckBox, ComboBox, LineEdit, MessageBoxBase, PushButton,
                            SubtitleLabel, TableWidget)

from ok import og
from src import card_db, catalog

TEAM_SIZE = 3
PREVIEW_SIZE = (260, 380)


def _tr(text):
    return og.app.tr(text) if text else text


class CardPickerDialog(MessageBoxBase):

    def __init__(self, db, lang, mode, config, parent, on_add, with_text=False, path=None, team_folder=None):
        super().__init__(parent)
        self.db, self.lang, self.mode, self.on_add, self.with_text = db, lang, mode, on_add, with_text
        self.team_folder = team_folder
        self.catalog = catalog.get_catalog(path)
        self.rows = []
        team = card_db.load_team(mode, team_folder)
        if team is None:
            team = card_db.default_team(db, config or {}, mode)

        self.viewLayout.addWidget(SubtitleLabel(_tr('从资料库挑选卡牌'), self))
        hint = BodyLabel(_tr('先选队伍角色，只列出他们的牌；双击或选取后按「加入」。'), self)
        hint.setWordWrap(True)
        self.viewLayout.addWidget(hint)

        names = [name for cid, name in db.characters.items() if db.character_ids(name) and
                 db.character_ids(name)[0] == cid]
        team_row = QHBoxLayout()
        team_row.addWidget(BodyLabel(_tr('队伍角色'), self))
        self.member_boxes = []
        for index in range(TEAM_SIZE):
            box = ComboBox(self)
            box.addItem(_tr('（不选）'), userData='')
            for name in names:
                box.addItem(name, userData=name)
            if index < len(team) and team[index] in names:
                box.setCurrentIndex(names.index(team[index]) + 1)
            box.currentIndexChanged.connect(lambda _: self.team_changed())
            self.member_boxes.append(box)
            team_row.addWidget(box)
        self.neutral_box = CheckBox(_tr('中立牌'), self)
        self.neutral_box.setChecked(True)
        self.neutral_box.stateChanged.connect(lambda _: self.reload())
        self.other_box = CheckBox(_tr('其他'), self)
        self.other_box.setToolTip(_tr('诅咒、状态异常、怪物等非角色、非中立的牌'))
        self.other_box.stateChanged.connect(lambda _: self.reload())
        team_row.addWidget(self.neutral_box)
        team_row.addWidget(self.other_box)
        team_row.addStretch(1)
        self.viewLayout.addLayout(team_row)

        self.search = LineEdit(self)
        self.search.setClearButtonEnabled(True)
        self.search.setPlaceholderText(_tr('搜索名称或效果'))
        self.search.textChanged.connect(lambda _: self.reload())
        self.viewLayout.addWidget(self.search)

        self.table = TableWidget(self)
        columns = [_tr('名称'), _tr('角色'), _tr('效果'), _tr('看过')]
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        for column in range(len(columns)):
            mode_ = QHeaderView.ResizeMode.Stretch if column == 2 else QHeaderView.ResizeMode.ResizeToContents
            header.setSectionResizeMode(column, mode_)
        self.table.itemDoubleClicked.connect(lambda item: self.add_rows([item.row()]))
        self.table.itemSelectionChanged.connect(self.show_preview)
        self.preview = BodyLabel(self)
        self.preview.setFixedWidth(PREVIEW_SIZE[0])
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setWordWrap(True)
        table_row = QHBoxLayout()
        table_row.addWidget(self.table, 1)
        table_row.addWidget(self.preview)
        self.viewLayout.addLayout(table_row, 1)

        self.empty_label = BodyLabel(self)
        self.empty_label.setWordWrap(True)
        self.viewLayout.addWidget(self.empty_label)

        self.add_button = PushButton(_tr('加入'), self)
        self.add_button.clicked.connect(lambda: self.add_rows(self.selected_rows()))
        self.buttonLayout.insertWidget(0, self.add_button, 1, Qt.AlignmentFlag.AlignVCenter)
        self.yesButton.setText(_tr('关闭'))
        self.cancelButton.hide()
        self.widget.setMinimumSize(1060, 660)
        self.reload()

    def team(self):
        members = []
        for box in self.member_boxes:
            name = box.currentData()
            if name and name not in members:
                members.append(name)
        return members

    def team_changed(self):
        try:
            card_db.save_team(self.mode, self.team(), self.team_folder)
        except OSError:
            pass
        self.reload()

    def _seen_index(self):
        """執行時收集的目錄：簡化後卡名 → (看過次數, 有截圖的條目)。"""
        index = {}
        for _, entry in self.catalog.entries('card', self.lang):
            key = card_db.normalize(entry.get('name', ''))
            seen, image_entry = index.get(key, (0, None))
            if image_entry is None and entry.get('image'):
                image_entry = entry
            index[key] = (seen + entry.get('seen', 0), image_entry)
        return index

    def reload(self):
        query = card_db.normalize(self.search.text())
        seen = self._seen_index()
        rows = card_db.rows(self.db, self.team(), self.with_text,
                            self.neutral_box.isChecked(), self.other_box.isChecked())
        self.rows = []
        for name, owner, shown, keyword in rows:
            if query and not any(query in card_db.normalize(field) for field in (name, owner, shown)):
                continue
            count, image_entry = seen.get(card_db.normalize(name), (0, None))
            self.rows.append((name, owner, shown, keyword, count, image_entry))
        self.table.setRowCount(len(self.rows))
        for row, (name, owner, shown, _, count, _) in enumerate(self.rows):
            for column, text in enumerate((name, _tr(owner), shown, str(count) if count else '')):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, column, item)
        self.table.resizeRowsToContents()
        if not self.team() and not self.neutral_box.isChecked() and not self.other_box.isChecked():
            self.empty_label.setText(_tr('请先选择队伍角色。'))
        elif not self.rows:
            self.empty_label.setText(_tr('没有符合搜索的卡牌。'))
        else:
            self.empty_label.setText('')
        self.empty_label.setVisible(bool(self.empty_label.text()))
        self.show_preview()

    def selected_rows(self):
        return sorted({index.row() for index in self.table.selectionModel().selectedRows()})

    def show_preview(self):
        rows = self.selected_rows()
        entry = self.rows[rows[0]][5] if rows and rows[0] < len(self.rows) else None
        path = self.catalog.image_path(entry) if entry else None
        pixmap = QPixmap(path) if path else QPixmap()
        if pixmap.isNull():
            self.preview.setPixmap(QPixmap())
            self.preview.setText(_tr('选一列查看截图') if not rows else _tr('还没看过这张牌，没有截图'))
            return
        self.preview.setPixmap(pixmap.scaled(
            *PREVIEW_SIZE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def add_rows(self, rows):
        keywords = [self.rows[row][3] for row in rows if row < len(self.rows)]
        if keywords:
            self.on_add(keywords)
