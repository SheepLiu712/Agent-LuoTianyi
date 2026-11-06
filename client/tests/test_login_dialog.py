import os
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit
from src.gui import login_dialog as dialog_module
from src.gui.login_dialog import LoginDialog


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def dialog(qapp, monkeypatch):
    monkeypatch.setattr(dialog_module.credential, "load_credentials", lambda: None)
    binder = Mock(spec=dialog_module.AgentBinder)
    binder.on_login.return_value = (True, "ok")
    binder.on_register.return_value = (True, "ok")
    window = LoginDialog(binder)
    yield window
    window.close()
    window.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize(
    ("tab", "focus_name"),
    [
        (0, None),
        (0, "l_username"),
        (0, "l_password"),
        (0, "l_btn"),
        (1, None),
        (1, "r_username"),
        (1, "r_password"),
        (1, "r_confirm_password"),
        (1, "r_invite"),
        (1, "r_btn"),
    ],
)
def test_escape_keeps_login_and_registration_open(dialog, qapp, tab, focus_name):
    fields = dialog.findChildren(QLineEdit)
    for index, field in enumerate(fields):
        field.setText(f"draft-{index}")
    values = [field.text() for field in fields]
    dialog.tabs.setCurrentIndex(tab)
    dialog.show()
    qapp.processEvents()
    finished = QSignalSpy(dialog.finished)
    target = getattr(dialog, focus_name) if focus_name else dialog
    target.setFocus()

    QTest.keyClick(target, Qt.Key.Key_Escape)
    qapp.processEvents()

    assert dialog.isVisible()
    assert finished.count() == 0
    assert dialog.tabs.currentIndex() == tab
    assert [field.text() for field in fields] == values
    dialog.binder.on_login.assert_not_called()
    dialog.binder.on_register.assert_not_called()


@pytest.mark.parametrize("tab", [0, 1])
def test_explicit_close_still_cancels_login(dialog, qapp, tab):
    dialog.tabs.setCurrentIndex(tab)
    dialog.show()
    qapp.processEvents()
    rejected = QSignalSpy(dialog.rejected)

    assert dialog.close()

    assert not dialog.isVisible()
    assert rejected.count() == 1
    assert dialog.result() == QDialog.DialogCode.Rejected


@pytest.mark.parametrize("submit_with", ["click", "return"])
def test_successful_login_still_accepts_dialog(dialog, qapp, submit_with):
    dialog.l_username.setText("test-user")
    dialog.l_password.setText("test-password")
    dialog.show()
    qapp.processEvents()
    accepted = QSignalSpy(dialog.accepted)

    if submit_with == "click":
        QTest.mouseClick(dialog.l_btn, Qt.MouseButton.LeftButton)
    else:
        dialog.l_btn.setFocus()
        QTest.keyClick(dialog.l_btn, Qt.Key.Key_Return)

    dialog.binder.on_login.assert_called_once()
    assert accepted.count() == 1
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert not dialog.isVisible()


def test_successful_registration_still_returns_to_login(dialog, qapp, monkeypatch):
    monkeypatch.setattr(dialog_module.QMessageBox, "information", lambda *args: None)
    dialog.tabs.setCurrentIndex(1)
    dialog.r_username.setText("test-user")
    dialog.r_password.setText("test-password")
    dialog.r_confirm_password.setText("test-password")
    dialog.r_invite.setText("test-invite")
    dialog.show()
    qapp.processEvents()
    finished = QSignalSpy(dialog.finished)

    QTest.mouseClick(dialog.r_btn, Qt.MouseButton.LeftButton)

    dialog.binder.on_register.assert_called_once()
    assert dialog.isVisible()
    assert dialog.tabs.currentIndex() == 0
    assert finished.count() == 0


@pytest.mark.parametrize("button_name", ["reset_btn", "server_btn"])
def test_escape_still_closes_child_dialog_only(dialog, qapp, button_name):
    dialog.show()
    qapp.processEvents()
    finished = QSignalSpy(dialog.finished)
    visible_after_escape = []

    def dismiss_child():
        child = qapp.activeModalWidget()
        if child is not None:
            QTest.keyClick(child, Qt.Key.Key_Escape)
            visible_after_escape.append(child.isVisible())
            child.close()

    QTimer.singleShot(0, dismiss_child)
    QTest.mouseClick(getattr(dialog, button_name), Qt.MouseButton.LeftButton)

    assert visible_after_escape == [False]
    assert dialog.isVisible()
    assert finished.count() == 0
