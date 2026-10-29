"""自动卡厄思模式（实验）。

除“预设卡组”外，其余配置和行为与自动卡厄思模式完全一致：
- 首次创建时自动继承 configs/ChaosMode.json 的当前配置
- 旧版“闪光优先级”会转换为预设卡组的初始记录
- 任务配置独立保存在 configs/ChaosModeExperimental.json
"""
import os

from ok.util.config import Config
from ok.util.file import get_relative_path, read_json_file, write_json_file

from ChaosMode import ChaosMode
from preset_deck import convert_legacy_flash_priority
from utils import _disable_other_chaos_tasks


class ChaosModeExperimental(ChaosMode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动卡厄思模式（实验）"
        self.preset_deck_enabled = True
        self.description = (
            "1. 请主动打开游戏内自动战斗和自动剧情功能。\n"
            "2. 国际服玩家请将本模式配置中的\"游戏语言\"设置为繁体中文。\n"
            "3. 实验功能：灵光一闪/神闪按「预设卡组」选择；效果和神闪都不符合时，"
            "在非神闪卡里随机选，三张全神闪选第一张。\n"
            "4. 要闪光、要复制哪张卡也由「预设卡组」决定（冥想只闪效果还没达标的卡），"
            "所以本模式没有闪光卡牌列表、复制卡牌列表、首层刷特定闪光。"
        )

        # 用“预设卡组”替换“闪光优先级”，并保持原来的配置显示顺序。
        rebuilt_defaults = {}
        for key, value in self.default_config.items():
            # 闪光卡牌列表、复制卡牌列表跟预设卡组重复（两边各选各的会互相打架，冥想白花信用点）；
            # 首层刷特定闪光要靠闪光卡牌列表第一张，一起拿掉
            if key in ("闪光优先级", "需要冥想的卡牌", "闪光卡牌列表", "复制卡牌列表", "首层刷特定闪光"):
                continue
            if key == "移除卡牌列表" and "预设卡组" not in rebuilt_defaults:
                rebuilt_defaults["预设卡组"] = []
            rebuilt_defaults[key] = value
            # 一般模式只有合併的“指定记忆卡牌”（名字+效果），实验模式才分开填效果
            if key == "指定记忆卡牌":
                rebuilt_defaults["指定记忆卡牌效果"] = ""
        if "预设卡组" not in rebuilt_defaults:
            rebuilt_defaults["预设卡组"] = []
        self.default_config = rebuilt_defaults

        self.config_description.pop("闪光优先级", None)
        self.config_description.pop("不要神之一闪", None)
        self.config_description.pop("需要冥想的卡牌", None)
        for key in ("闪光卡牌列表", "复制卡牌列表", "首层刷特定闪光"):
            self.config_description.pop(key, None)
        self.config_description["预设卡组"] = (
            "按列表从上到下匹配。一条记录代表一张卡，需要两张就复制一条。\n"
            "匹配顺序：卡牌名 → 卡牌效果 → 神闪效果。\n"
            "效果和神闪效果填写能唯一识别界面文字的关键字即可，可多行。\n"
            "每条记录可以单独勾选“拒绝神闪”：这张卡出现神闪形态时不选它。\n"
            "神闪判断：普通灵光一闪在费用数字下方固定是准星图示，认不到准星就当神闪。\n"
            "选卡页（选择要闪光/复制的卡）也照这里的顺序找：先找效果还没达标的卡；复制只复制张数还不够的卡。\n"
            "编辑窗口支持从官方卡组码离线导入；成功后覆盖列表，保存后生效。\n"
            "卡牌效果和神闪效果都不符合时：在非神闪卡里随机选；三张全神闪选第一张。"
        )
        self.config_type["预设卡组"] = {
            "type": "button",
            "buttons": [
                {
                    "text": "修改",
                    "callback": self._edit_preset_deck,
                }
            ],
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _config_file_name(class_name):
        return f"{class_name}.json"

    def _seed_from_chaos_config(self):
        """首次创建实验模式时，继承普通模式的当前配置。"""
        own_file = get_relative_path(
            Config.config_folder,
            self._config_file_name(self.__class__.__name__),
        )
        if os.path.exists(own_file):
            return
        parent_file = get_relative_path(
            Config.config_folder,
            self._config_file_name("ChaosMode"),
        )
        data = read_json_file(parent_file)
        if not isinstance(data, dict):
            return
        legacy = data.get("闪光优先级", [])
        preset_records = convert_legacy_flash_priority(legacy)
        # 让“预设卡组”出现在原来“闪光优先级”的位置，保持配置界面顺序一致。
        seeded = {}
        inserted = False
        for key, value in data.items():
            if key == "闪光优先级":
                seeded["预设卡组"] = preset_records
                inserted = True
                continue
            if key == "预设卡组":
                continue
            seeded[key] = value
        if not inserted:
            seeded["预设卡组"] = preset_records
        # 实验模式首次创建默认不自动开启，避免重启后两个模式互相抢占。
        seeded["_enabled"] = False
        write_json_file(own_file, seeded)
        try:
            self.log_info(
                f"已从自动卡厄思模式继承配置，"
                f"并将{len(preset_records)}条闪光优先级转换为预设卡组"
            )
        except Exception:
            pass

    def load_config(self):
        self._seed_from_chaos_config()
        super().load_config()

    # ------------------------------------------------------------------
    def _edit_preset_deck(self):
        try:
            from preset_deck_ui import open_preset_deck_editor

            open_preset_deck_editor(self)
        except Exception as exc:
            self.log_error("打开预设卡组编辑器失败", exc)
            try:
                from PySide6.QtWidgets import QMessageBox
                from config_sync import _tr

                QMessageBox.warning(
                    None, _tr("错误"), _tr("打开预设卡组编辑器失败：{error}").format(error=exc)
                )
            except Exception:
                pass

    def _check_upload_if_needed(self):
        """实验模式的配置（预设卡组、分开的记忆效果）和一般模式不同，不上传到热门配置。"""

    def enable(self):
        """开启实验模式时关闭普通卡厄思、出击、剧情模式。"""
        _disable_other_chaos_tasks(self)
        super().enable()
