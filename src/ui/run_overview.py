"""運行總覽分頁（仿 ALAS）：左邊狀態欄、右邊即時日誌，一直都在，不擠進即時觸發頁。

- 戰績：src/run_stats.py 存檔的「今日」與「全部」，重啟不歸零，可重置。
- 本局：正在跑的卡厄思／出擊任務的 info（層數、節點、信用點……）與日誌裡的生命值。
- 主練：刷存档主战员、三格裝備（名稱、品質，效果放在提示）、預設卡組各卡牌已有／需要張數。
- 即時日誌：接框架的 communicate.log；精簡模式隱藏除錯雜訊（run_overview_data.NOISY），
  捲到最下面時自動跟著最新一行，往上捲就停住不動。
繁體介面下，任務寫死的簡體文字（info、日誌、卡名）顯示時轉成繁體。
"""
import html

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, CheckBox, FluentIcon, MessageBox,
                            NavigationItemPosition, PlainTextEdit, PushButton, SmoothScrollArea, StrongBodyLabel,
                            isDarkTheme)

from ok import og
from ok.gui.Communicate import communicate
from ok.gui.widget.Card import Card
from ok.gui.widget.CustomTab import CustomTab
from src import run_overview_data as data
from src import run_stats

MODES = ('ChaosModeExperimental', 'ChaosMode', 'SortieMode', 'StoryMode')
MAX_LOG_LINES = 3000
STATUS_WIDTH = 360
LOG_COLORS = {'WARNING': '#d08700', 'ERROR': '#e04848', 'CRITICAL': '#e04848', 'DEBUG': '#8a8a8a'}


def _tr(text):
    return og.app.tr(text) if text and og.app else text


def _show(text):
    """任務的簡體文字：繁體介面下轉成繁體顯示。"""
    try:
        from src.zh_tw_ui import _convert, _is_traditional
        return _convert(text) if text and og.app and _is_traditional(og.app) else text
    except Exception:
        return text


def _section(title):
    label = StrongBodyLabel(title)
    label.setContentsMargins(0, 8, 0, 0)
    return label


def _value_label():
    label = BodyLabel('')
    label.setWordWrap(True)
    label.setTextFormat(Qt.RichText)
    # 換行的標籤在版面裡會縮到最小寬度，要明確撐滿狀態欄
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    return label


class RunOverviewTab(CustomTab):

    def __init__(self):
        super().__init__()
        self._hp = None
        self._follow = True

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(self._build_status())
        row_layout.addWidget(self._build_log(), 1)
        row.setMinimumHeight(620)
        row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.add_widget(row, 1)

        communicate.log.connect(self._on_log)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(1000)
        self._refresh_status()

    @property
    def name(self):
        return '运行总览'

    @property
    def icon(self):
        return FluentIcon.HOME

    @property
    def position(self):
        return NavigationItemPosition.TOP

    @property
    def add_after_default_tabs(self):
        return False

    # ---------- 狀態欄 ----------

    def _build_status(self):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_section(_tr('战绩')))
        self.stats_label = _value_label()
        layout.addWidget(self.stats_label)
        reset = PushButton(_tr('重置战绩'))
        reset.clicked.connect(self._reset_stats)
        layout.addWidget(reset)
        layout.addWidget(_section(_tr('本局')))
        self.run_label = _value_label()
        layout.addWidget(self.run_label)
        layout.addWidget(_section(_tr('主练')))
        self.member_label = _value_label()
        layout.addWidget(self.member_label)
        layout.addStretch(1)
        box.setFixedWidth(STATUS_WIDTH - 40)
        # 預設卡組很長時狀態欄自己捲動，不撐高整頁
        scroll = SmoothScrollArea()
        scroll.setWidget(box)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet('QScrollArea{background:transparent;border:none}')
        box.setStyleSheet('background:transparent')
        # Card 的版面會把最小寬度改回內容的最小值，蓋掉 setFixedWidth，所以把寬度給在捲動區上
        scroll.setMinimumWidth(STATUS_WIDTH - 32)
        card = Card(_tr('状态'), scroll, stretch=1)
        card.setMaximumWidth(STATUS_WIDTH)
        return card

    def _active_task(self):
        executor = getattr(og, 'executor', None) or self.executor
        if executor is None:
            return None
        current = getattr(executor, 'current_task', None)
        if type(current).__name__ in MODES:
            return current
        tasks = list(getattr(executor, 'trigger_tasks', []) or []) + list(getattr(executor, 'onetime_tasks', []) or [])
        return next((t for t in tasks if type(t).__name__ in MODES and getattr(t, 'enabled', False)), None)

    def _refresh_status(self):
        if not self.isVisible():
            return
        try:
            self.stats_label.setText(self._stats_html())
            task = self._active_task()
            self.run_label.setText(self._run_html(task))
            member_html, member_tip = self._member_html(task)
            self.member_label.setText(member_html)
            self.member_label.setToolTip(member_tip)
        except Exception as e:  # 狀態欄出錯不影響任務
            self.logger.error('运行总览更新失败', e)

    def _stats_html(self):
        stats = run_stats.summary()
        lines = [
            f"{_tr('今日')}：{run_stats.rate_text(*stats['today'])}",
            f"{_tr('全部')}：{run_stats.rate_text(*stats['total'])}",
        ]
        if stats['since']:
            lines.append(f"<span style='color:gray'>{_tr('自')} {stats['since']} {_tr('起')}</span>")
        return '<br>'.join(lines)

    def _run_html(self, task):
        if task is None:
            return _tr('没有运行中的任务')
        executor = getattr(og, 'executor', None)
        state = _tr('已暂停') if getattr(executor, 'paused', False) else _tr('运行中')
        info = getattr(task, 'info', {}) or {}
        lines = [f"{html.escape(_tr(task.name))}（{state}）"]
        for key, label in (('所处层数，节点，类型', '位置'), ('当前信用点', '信用点'),
                           ('本局已移除卡牌', '已移除卡牌'), ('本局已获得中立牌', '已获得中立牌'),
                           ('当前胜率', '本次启动胜率')):
            if key in info:
                lines.append(f"{_tr(label)}：{html.escape(_show(str(info[key])))}")
        if self._hp:
            current, maximum = self._hp
            lines.append(f"{_tr('生命值')}：{current}/{maximum}（{round(current * 100 / maximum) if maximum else 0}%）")
        return '<br>'.join(lines)

    def _member_html(self, task):
        if task is None:
            return '—', ''
        config = getattr(task, 'config', {}) or {}
        name = config.get('刷存档主战员') or ''
        if not name and config.get('出战主战员优先级'):
            name = '、'.join(config.get('出战主战员优先级')[:3])
        lines = [html.escape(_show(str(name)) or '—')]
        tips = []
        member_status = getattr(task, 'member_status', None)
        if isinstance(member_status, dict):
            lines.append(f"<b>{_tr('装备')}</b>")
            for slot, item, quality, description in data.equipment_rows(member_status.get('equipment')):
                text = f"{html.escape(_show(item))}（{html.escape(_show(quality))}）" if item else '—'
                lines.append(f"{slot}{_tr('号位')}：{text}")
                if description:
                    tips.append(f"{slot}{_tr('号位')} {_show(item)}：{_show(description)}")
        deck_lines = self._deck_lines(task)
        if deck_lines:
            lines.append(f"<b>{_tr('预设卡组')}</b>")
            lines.extend(deck_lines)
        return '<br>'.join(lines), '\n'.join(tips)

    def _deck_lines(self, task):
        if not getattr(task, 'preset_deck_enabled', False):
            return []
        try:
            import preset_deck
            records = preset_deck.load_preset_records(task)
            rows = data.deck_progress(records, getattr(task, '_preset_name_counts', None), preset_deck._name_matches)
        except Exception:
            return []
        lines = []
        for card, owned, needed in rows:
            have = '?' if owned is None else owned
            done = owned is not None and owned >= needed
            color = 'gray' if done else ('#d08700' if owned else 'inherit')
            lines.append(f"<span style='color:{color}'>{html.escape(_show(card))}　{have}/{needed}</span>")
        return lines

    def _reset_stats(self):
        box = MessageBox(_tr('重置战绩'), _tr('清空今日与全部战绩，从现在重新累计？'), self.window())
        if box.exec():
            run_stats.reset()
            self._refresh_status()

    # ---------- 即時日誌 ----------

    def _build_log(self):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.detail_box = CheckBox(_tr('显示详细日志'))
        bar.addWidget(self.detail_box)
        bar.addStretch(1)
        self.hint_label = CaptionLabel('')
        bar.addWidget(self.hint_label)
        clear = PushButton(_tr('清空'))
        clear.clicked.connect(lambda: self.log_view.clear())
        bar.addWidget(clear)
        layout.addLayout(bar)
        self.log_view = PlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(MAX_LOG_LINES)
        self.log_view.verticalScrollBar().valueChanged.connect(self._on_scroll)
        layout.addWidget(self.log_view, 1)
        return Card(_tr('即时日志'), box, stretch=1)

    def _on_scroll(self, value):
        bar = self.log_view.verticalScrollBar()
        self._follow = value >= bar.maximum() - 2
        self.hint_label.setText('' if self._follow else _tr('已暂停自动滚动，滚到最下面继续'))

    def _on_log(self, level, line):
        time_text, _, message = data.parse_log(line)
        hp = data.hp_from(message)
        if hp:
            self._hp = hp
        if not self.detail_box.isChecked() and data.is_noisy(message):
            return
        level_name = data.LEVEL_NAMES.get(level, 'INFO')
        color = LOG_COLORS.get(level_name) or ('#e6e6e6' if isDarkTheme() else '#202020')
        text = html.escape(_show(message))
        stamp = f"<span style='color:gray'>{time_text}</span> " if time_text else ''
        bar = self.log_view.verticalScrollBar()
        position = bar.value()
        self.log_view.appendHtml(f"{stamp}<span style='color:{color}'>{text}</span>")
        if self._follow:
            bar.setValue(bar.maximum())
        else:
            bar.setValue(position)
