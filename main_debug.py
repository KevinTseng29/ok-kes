import ok
from src.config import config
from src.ui.LabelAndEditableDropDown import install as install_editable_drop_down
from src.ui.SponsorDialog import install_sponsor_dialog
from src.ui.catalog_dialog import install as install_catalog_dialog
from src.ui.translated_values import install as install_translated_values
from src.window_recovery import install_window_recovery
from src.zh_tw_ui import install as install_zh_tw_ui

if __name__ == '__main__':
    install_sponsor_dialog()
    install_zh_tw_ui()
    install_editable_drop_down()
    install_translated_values()
    install_catalog_dialog()
    install_window_recovery()
    config = config
    config['debug'] = True
    ok = ok.OK(config)
    ok.start()
