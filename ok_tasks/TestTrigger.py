from ok import TriggerTask
from humanize import HumanizeMixin

from utils_sortie import handle_secret_enemy


class TestTrigger(HumanizeMixin, TriggerTask):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = "测试trigger"
        self.description = "测试trigger"
        self.trigger_interval = 2
        self.instructions = """<a href="https://github.com/ok-oldking/ok-py">ok-py</a>"""

    def run(self):
        self.all_texts = self.ocr()
        handle_secret_enemy(self)
