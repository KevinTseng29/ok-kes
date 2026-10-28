"""自动出击模式（实验）。

除下面两项外，其余配置和行为与自动出击模式完全一致：
- 「闪光优先级」：灵光一闪三选一时按效果关键字挑（出击模式原本随机）
- 「首层刷特定闪光」：第一层专心刷指定卡牌的指定效果，没刷到就打完第一层撤退
首次创建时自动继承 configs/SortieMode.json 的当前配置；任务配置独立保存在 configs/SortieModeExperimental.json。
"""
import os

from ok.util.config import Config
from ok.util.file import get_relative_path, read_json_file, write_json_file

from SortieMode import SortieMode

_FLASH_PRIORITY_KEY = "闪光优先级"
_SPECIFIC_FLASH_KEY = "首层刷特定闪光"


class SortieModeExperimental(SortieMode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "自动出击模式（实验）"
        # 刷特定闪光时三选一没命中就跳过（handle_view_original），不随机选
        self.specific_flash_skip = True
        self.description = (
            self.description
            + "\n3. 实验功能：灵光一闪三选一按「闪光优先级」挑；可勾选「首层刷特定闪光」。"
        )
        rebuilt = {}
        for key, value in self.default_config.items():
            rebuilt[key] = value
            if key == "闪光卡牌列表":
                rebuilt[_FLASH_PRIORITY_KEY] = []
                rebuilt[_SPECIFIC_FLASH_KEY] = False
        self.default_config = rebuilt
        self.config_description[_FLASH_PRIORITY_KEY] = (
            "灵光一闪三选一时，依序找效果（或名称）含这些关键字的选项，例如「琶音」「移动至手牌并发动」；"
            "都没有就随机选。"
        )
        self.config_description[_SPECIFIC_FLASH_KEY] = (
            "第一层专心刷一个指定的灵光一闪：\n"
            "1. 篝火闪光时先闪「闪光卡牌列表」第一张（例如音乐开始）；\n"
            "2. 三选一里有「闪光优先级」第一项（例如琶音）就选它，记为已刷到；没有就按跳过，留到下一个篝火再闪；"
            "触发的神闪不能跳过时随便选一个；\n"
            "3. 第一层打完（领完结算奖励）还没刷到就撤退重开（通关第一层会返还体力）；刷到了就照常继续打。\n"
            "刷到之后不再闪那张卡，闪光改用列表其余的卡。"
        )

    def _seed_from_sortie_config(self):
        """首次创建实验模式时，继承出击模式的当前配置。"""
        own_file = get_relative_path(Config.config_folder, self._config_file_name(self.__class__.__name__))
        if os.path.exists(own_file):
            return
        data = read_json_file(get_relative_path(Config.config_folder, self._config_file_name("SortieMode")))
        if not isinstance(data, dict):
            return
        seeded = {}
        for key, value in data.items():
            seeded[key] = value
            if key == "闪光卡牌列表":
                seeded.setdefault(_FLASH_PRIORITY_KEY, [])
                seeded.setdefault(_SPECIFIC_FLASH_KEY, False)
        # 实验模式首次创建默认不自动开启，避免重启后两个出击模式互相抢占
        seeded["_enabled"] = False
        write_json_file(own_file, seeded)

    @staticmethod
    def _config_file_name(class_name):
        return f"{class_name}.json"

    def load_config(self):
        self._seed_from_sortie_config()
        super().load_config()

    def _check_upload_if_needed(self):
        """实验模式多了闪光优先级和首层刷特定闪光，不上传到热门配置。"""
