import os
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QMessageBox
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


@pytest.mark.parametrize("focus_name", ["l_username", "l_password"])
@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter], ids=["return", "enter"])
def test_enter_in_login_fields_submits_login(dialog, qapp, focus_name, key):
    dialog.l_username.setText("test-user")
    dialog.l_password.setText("test-password")
    dialog.show()
    qapp.processEvents()
    target = getattr(dialog, focus_name)
    target.setFocus()
    qapp.processEvents()
    clicks = {name: QSignalSpy(getattr(dialog, name).clicked) for name in ("l_btn", "r_btn", "reset_btn", "server_btn")}
    accepted = QSignalSpy(dialog.accepted)

    def dismiss_unexpected_modal():
        child = qapp.activeModalWidget()
        if child is not None:
            child.reject()

    QTimer.singleShot(0, dismiss_unexpected_modal)
    QTest.keyClick(target, key)
    qapp.processEvents()

    assert {name: spy.count() for name, spy in clicks.items()} == {
        "l_btn": 1,
        "r_btn": 0,
        "reset_btn": 0,
        "server_btn": 0,
    }
    dialog.binder.on_login.assert_called_once_with("test-user", "test-password", do_auto_login=False)
    dialog.binder.on_register.assert_not_called()
    assert accepted.count() == 1
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert not dialog.isVisible()


@pytest.mark.parametrize("button_name", ["reset_btn", "server_btn"])
@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter], ids=["return", "enter"])
def test_enter_on_secondary_buttons_keeps_login_as_primary(dialog, qapp, button_name, key):
    dialog.l_username.setText("test-user")
    dialog.l_password.setText("test-password")
    dialog.show()
    qapp.processEvents()
    target = getattr(dialog, button_name)
    target.setFocus()
    qapp.processEvents()
    login_clicked = QSignalSpy(dialog.l_btn.clicked)
    secondary_clicked = QSignalSpy(target.clicked)
    accepted = QSignalSpy(dialog.accepted)

    def dismiss_unexpected_modal():
        child = qapp.activeModalWidget()
        if child is not None:
            child.reject()

    QTimer.singleShot(0, dismiss_unexpected_modal)
    QTest.keyClick(target, key)
    qapp.processEvents()

    assert secondary_clicked.count() == 0
    assert login_clicked.count() == 1
    dialog.binder.on_login.assert_called_once_with("test-user", "test-password", do_auto_login=False)
    assert accepted.count() == 1


@pytest.mark.parametrize("focus_name", ["r_username", "r_password", "r_confirm_password", "r_invite"])
@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter], ids=["return", "enter"])
@pytest.mark.parametrize("tab_path", [(1,), (1, 0, 1)], ids=["register", "round-trip"])
@pytest.mark.parametrize("focus_primary", [False, True], ids=["input-focus", "primary-focus-history"])
def test_enter_tracks_registration_then_login_after_tab_switch(
    dialog, qapp, monkeypatch, focus_name, key, tab_path, focus_primary
):
    monkeypatch.setattr(dialog_module.QMessageBox, "information", lambda *args: None)
    dialog.l_username.setText("login-user")
    dialog.l_password.setText("login-password")
    dialog.r_username.setText("register-user")
    dialog.r_password.setText("register-password")
    dialog.r_confirm_password.setText("register-password")
    dialog.r_invite.setText("test-invite")
    dialog.show()
    qapp.processEvents()
    if focus_primary:
        dialog.l_btn.setFocus()
    for index in tab_path:
        QTest.mouseClick(
            dialog.tabs.tabBar(), Qt.MouseButton.LeftButton, pos=dialog.tabs.tabBar().tabRect(index).center()
        )
        qapp.processEvents()
        if focus_primary:
            (dialog.l_btn if index == 0 else dialog.r_btn).setFocus()
            qapp.processEvents()
    target = getattr(dialog, focus_name)
    target.setFocus()
    qapp.processEvents()
    login_clicked = QSignalSpy(dialog.l_btn.clicked)
    register_clicked = QSignalSpy(dialog.r_btn.clicked)
    accepted = QSignalSpy(dialog.accepted)

    QTest.keyClick(target, key)
    qapp.processEvents()

    assert register_clicked.count() == 1
    assert login_clicked.count() == 0
    dialog.binder.on_register.assert_called_once_with("register-user", "register-password", "test-invite")
    dialog.binder.on_login.assert_not_called()
    assert dialog.tabs.currentIndex() == 0
    assert dialog.isVisible()
    assert accepted.count() == 0

    dialog.l_password.setFocus()
    QTest.keyClick(dialog.l_password, key)
    qapp.processEvents()

    assert register_clicked.count() == 1
    assert login_clicked.count() == 1
    dialog.binder.on_login.assert_called_once_with("login-user", "login-password", do_auto_login=False)
    assert accepted.count() == 1


@pytest.mark.parametrize(
    ("tab", "focus_name", "expected_message"),
    [
        (0, "l_username", "请输入用户名和密码"),
        (0, "l_password", "请输入用户名和密码"),
        (1, "r_username", "请填写所有信息"),
        (1, "r_password", "请填写所有信息"),
        (1, "r_confirm_password", "请填写所有信息"),
        (1, "r_invite", "请填写所有信息"),
    ],
)
@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter], ids=["return", "enter"])
def test_enter_in_empty_fields_shows_active_form_validation(dialog, qapp, tab, focus_name, expected_message, key):
    dialog.tabs.setCurrentIndex(tab)
    dialog.show()
    qapp.processEvents()
    target = getattr(dialog, focus_name)
    target.setFocus()
    qapp.processEvents()
    login_clicked = QSignalSpy(dialog.l_btn.clicked)
    register_clicked = QSignalSpy(dialog.r_btn.clicked)
    reset_clicked = QSignalSpy(dialog.reset_btn.clicked)
    server_clicked = QSignalSpy(dialog.server_btn.clicked)
    finished = QSignalSpy(dialog.finished)
    messages = []

    def dismiss_validation():
        child = qapp.activeModalWidget()
        if child is not None:
            if isinstance(child, QMessageBox):
                messages.append((child.windowTitle(), child.text()))
            child.close()

    QTimer.singleShot(0, dismiss_validation)
    QTest.keyClick(target, key)
    qapp.processEvents()

    assert messages == [("错误", expected_message)]
    assert login_clicked.count() == (1 if tab == 0 else 0)
    assert register_clicked.count() == (1 if tab == 1 else 0)
    assert reset_clicked.count() == 0
    assert server_clicked.count() == 0
    dialog.binder.on_login.assert_not_called()
    dialog.binder.on_register.assert_not_called()
    assert dialog.isVisible()
    assert dialog.tabs.currentIndex() == tab
    assert finished.count() == 0


@pytest.mark.parametrize(
    ("button_name", "expected_title"), [("reset_btn", "重置账号"), ("server_btn", "服务器地址设置")]
)
@pytest.mark.parametrize("activate_with", ["mouse", "space"])
@pytest.mark.parametrize("key", [Qt.Key.Key_Return, Qt.Key.Key_Enter], ids=["return", "enter"])
def test_secondary_actions_still_open_then_return_to_login(
    dialog, qapp, button_name, expected_title, activate_with, key
):
    dialog.l_username.setText("test-user")
    dialog.l_password.setText("test-password")
    dialog.show()
    qapp.processEvents()
    target = getattr(dialog, button_name)
    clicked = QSignalSpy(target.clicked)
    login_clicked = QSignalSpy(dialog.l_btn.clicked)
    register_clicked = QSignalSpy(dialog.r_btn.clicked)
    accepted = QSignalSpy(dialog.accepted)
    opened = []

    def dismiss_secondary():
        child = qapp.activeModalWidget()
        if child is not None:
            opened.append((child.windowTitle(), child.isVisible()))
            child.close()

    QTimer.singleShot(0, dismiss_secondary)
    if activate_with == "mouse":
        QTest.mouseClick(target, Qt.MouseButton.LeftButton)
    else:
        target.setFocus()
        QTest.keyClick(target, Qt.Key.Key_Space)
    qapp.processEvents()

    assert opened == [(expected_title, True)]
    assert clicked.count() == 1
    assert login_clicked.count() == 0
    assert register_clicked.count() == 0
    dialog.binder.on_login.assert_not_called()
    dialog.binder.on_register.assert_not_called()
    assert accepted.count() == 0
    assert dialog.isVisible()

    dialog.l_password.setFocus()
    QTest.keyClick(dialog.l_password, key)
    qapp.processEvents()

    assert clicked.count() == 1
    assert login_clicked.count() == 1
    dialog.binder.on_login.assert_called_once_with("test-user", "test-password", do_auto_login=False)
    assert accepted.count() == 1
