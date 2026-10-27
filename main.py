import ok
import sys
import os
import traceback
from src.config import config
from src.ui.LabelAndEditableDropDown import install as install_editable_drop_down
from src.ui.SponsorDialog import install_sponsor_dialog
from src.ui.translated_values import install as install_translated_values
from src.zh_tw_ui import install as install_zh_tw_ui

if __name__ == '__main__':
    try:
        install_sponsor_dialog()
        install_zh_tw_ui()
        install_editable_drop_down()
        install_translated_values()
        # PyInstaller --onefile mode: 切换数据目录，但配置文件保存在 exe 所在位置
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            os.chdir(sys._MEIPASS)
            config["config_folder"] = os.path.join(exe_dir, "configs")
        config = config
        ok = ok.OK(config)
        ok.start()
    except Exception as e:
        log_path = os.path.join(os.path.dirname(sys.executable), "error.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"Error: {e}\n\n")
            traceback.print_exc(file=f)
        raise
