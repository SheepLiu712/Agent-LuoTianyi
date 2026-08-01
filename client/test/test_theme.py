import re

from src.utils.theme import VoiceTheme


def test_full_theme_resolves_every_qss_token():
    qss = VoiceTheme.load_full_qss()

    assert qss
    assert re.search(r"\{\{[A-Z0-9_]+\}\}", qss) is None


def test_dynamics_styles_match_the_integrated_layout():
    qss = VoiceTheme.load_qss("voice_dialogs.qss")

    assert qss.count("QLabel#dynamicItemHeader") == 1
    assert qss.count("QLabel#dynamicItemPreview") == 1
    assert "QWidget#detailWidget" in qss
    assert "QPushButton#publishBtn" in qss
    assert "addDynamicButton" not in qss
