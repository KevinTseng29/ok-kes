import ok
from src.config import config
from src.ui.SponsorDialog import install_sponsor_dialog
from src.zh_tw_ui import install as install_zh_tw_ui

if __name__ == '__main__':
    install_sponsor_dialog()
    install_zh_tw_ui()
    config = config
    config['debug'] = True
    ok = ok.OK(config)
    ok.start()
