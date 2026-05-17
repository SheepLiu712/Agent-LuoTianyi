"""
用户偏好设置对话框 - 让用户可以自定义重要日期和相处模式
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QWidget, QLabel, QLineEdit, QPushButton, QComboBox,
                               QCheckBox, QListWidget, QListWidgetItem, QTextEdit,
                               QTimeEdit, QSpinBox, QMessageBox, QDateEdit, QFrame)
from PySide6.QtCore import Qt, QTime, QDate, QTimer
from PySide6.QtGui import QFont, QPixmap
from pathlib import Path
from .user_preferences_manager import UserPreferencesManager
from ..network.network_client import NetworkClient


class UserPreferencesDialog(QDialog):
    """用户偏好设置对话框"""

    def __init__(self, preferences_manager: UserPreferencesManager, parent=None, agent_binder=None, network_client=None):
        super().__init__(parent)
        self.preferences_manager = preferences_manager
        self.agent_binder = agent_binder
        self.network_client: NetworkClient | None = network_client
        self.setWindowTitle("用户自定义设置")
        self.setMinimumSize(650, 550)
        self.setModal(True)

        # Bilibili cookie 相关状态
        self._qr_key: str | None = None
        self._qr_poll_timer: QTimer | None = None

        self.init_ui()
        self.load_current_settings()

        # 自动同步本地保存的 Cookie 到服务端（服务端不落盘）
        if self._bili_sync_local_to_server():
            self._bili_check_status()

    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout()

        # 创建标签页
        tab_widget = QTabWidget()

        # 标签页1: 重要日期
        self.dates_tab = self._create_dates_tab()
        tab_widget.addTab(self.dates_tab, "📅 重要日期")

        # 标签页2: 相处模式
        self.relationship_tab = self._create_relationship_tab()
        tab_widget.addTab(self.relationship_tab, "💬 相处模式")

        # 标签页3: 提醒设置
        self.reminder_tab = self._create_reminder_tab()
        tab_widget.addTab(self.reminder_tab, "⏰ 提醒设置")

        # 标签页4: Bilibili Cookie 管理
        self.bili_tab = self._create_bilibili_tab()
        tab_widget.addTab(self.bili_tab, "B站 Cookie")

        layout.addWidget(tab_widget)

        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.save_button = QPushButton("保存")
        self.save_button.clicked.connect(self.save_settings)
        self.save_button.setStyleSheet("""
            QPushButton {
                background-color: #66CCFF;
                color: white;
                border: none;
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #55BBEE;
            }
        """)

        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #D8D8D8;
                color: #333333;
                border: none;
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #C8C8C8;
            }
        """)

        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.save_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def _create_dates_tab(self) -> QWidget:
        """创建重要日期标签页"""
        widget = QWidget()
        layout = QVBoxLayout()

        # 添加日期区域
        add_group = QVBoxLayout()
        add_group.addWidget(QLabel("添加重要日期"))

        # 名称
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("名称:"))
        self.date_name_input = QLineEdit()
        self.date_name_input.setPlaceholderText("例如：我的生日")
        name_layout.addWidget(self.date_name_input)
        add_group.addLayout(name_layout)

        # 日期
        date_layout = QHBoxLayout()
        date_layout.addWidget(QLabel("日期:"))
        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())
        date_layout.addWidget(self.date_input)
        add_group.addLayout(date_layout)

        # 类型
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("类型:"))
        self.date_type_combo = QComboBox()
        self.date_type_combo.addItems(["生日", "纪念日", "日程", "其他"])
        type_layout.addWidget(self.date_type_combo)
        type_layout.addStretch()
        add_group.addLayout(type_layout)

        # 提醒消息
        msg_layout = QHBoxLayout()
        msg_layout.addWidget(QLabel("提醒消息:"))
        self.date_message_input = QLineEdit()
        self.date_message_input.setPlaceholderText("留空则使用默认消息")
        msg_layout.addWidget(self.date_message_input)
        add_group.addLayout(msg_layout)

        # 添加按钮
        add_button = QPushButton("添加日期")
        add_button.clicked.connect(self.add_important_date)
        add_group.addWidget(add_button)

        layout.addLayout(add_group)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # 日期列表
        layout.addWidget(QLabel("已设置的重要日期:"))
        self.dates_list = QListWidget()
        layout.addWidget(self.dates_list)

        # 删除按钮
        delete_button = QPushButton("删除选中")
        delete_button.clicked.connect(self.delete_selected_date)
        layout.addWidget(delete_button)

        widget.setLayout(layout)
        return widget

    def _create_relationship_tab(self) -> QWidget:
        """创建相处模式标签页"""
        widget = QWidget()
        layout = QVBoxLayout()

        # 关系类型
        rel_layout = QHBoxLayout()
        rel_layout.addWidget(QLabel("关系类型:"))
        self.relationship_combo = QComboBox()
        self.relationship_combo.addItems(["朋友", "知己", "粉丝", "搭档", "家人", "其他"])
        self.relationship_combo.setEditable(True)
        rel_layout.addWidget(self.relationship_combo)
        rel_layout.addStretch()
        layout.addLayout(rel_layout)

        # 表达风格
        style_layout = QHBoxLayout()
        style_layout.addWidget(QLabel("表达风格:"))
        self.style_combo = QComboBox()
        self.style_combo.addItems(["活泼可爱", "温柔可人", "俏皮调皮", "诗意文艺", "热情洋溢", "文静恬淡", "随意自然"])
        self.style_combo.setEditable(True)
        style_layout.addWidget(self.style_combo)
        style_layout.addStretch()
        layout.addLayout(style_layout)

        # 性格特点
        layout.addWidget(QLabel("性格特点 (用逗号分隔):"))
        self.personality_input = QLineEdit()
        self.personality_input.setPlaceholderText("例如：温柔、耐心、善解人意")
        layout.addWidget(self.personality_input)

        # 自定义上下文
        layout.addWidget(QLabel("自定义上下文 (可选):"))
        self.custom_context_input = QTextEdit()
        self.custom_context_input.setMaximumHeight(100)
        self.custom_context_input.setPlaceholderText("在这里添加任何你想让天依知道的关于你们关系的信息...")
        layout.addWidget(self.custom_context_input)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def _create_reminder_tab(self) -> QWidget:
        """创建提醒设置标签页"""
        widget = QWidget()
        layout = QVBoxLayout()

        # 启用提醒
        self.enable_reminder_check = QCheckBox("启用重要日期提醒")
        layout.addWidget(self.enable_reminder_check)

        # 提醒时间
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("每天提醒时间:"))
        self.reminder_time_edit = QTimeEdit()
        self.reminder_time_edit.setTime(QTime(9, 0))
        time_layout.addWidget(self.reminder_time_edit)
        time_layout.addStretch()
        layout.addLayout(time_layout)

        # 检查间隔
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("检查间隔 (小时):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 24)
        self.interval_spin.setValue(1)
        interval_layout.addWidget(self.interval_spin)
        interval_layout.addStretch()
        layout.addLayout(interval_layout)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    # ── Bilibili Cookie 管理 ───────────────────────────────────────

    def _create_bilibili_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout()

        # ── 状态显示 ──
        status_group = QVBoxLayout()
        status_group.addWidget(QLabel("Bilibili Cookie 状态"))

        self.bili_status_label = QLabel("点击「检查状态」获取当前 Cookie 信息")
        self.bili_status_label.setWordWrap(True)
        self.bili_status_label.setStyleSheet("padding: 8px; background: #f5f5f5; border-radius: 4px;")
        status_group.addWidget(self.bili_status_label)

        btn_row = QHBoxLayout()
        check_btn = QPushButton("检查状态")
        check_btn.clicked.connect(self._bili_check_status)
        btn_row.addWidget(check_btn)

        refresh_btn = QPushButton("API 续期")
        refresh_btn.setToolTip("使用 refresh_token 静默续期 SESSDATA")
        refresh_btn.clicked.connect(self._bili_api_refresh)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch()
        status_group.addLayout(btn_row)
        layout.addLayout(status_group)

        # ── 登录方式标签页 ──
        login_tabs = QTabWidget()
        login_tabs.addTab(self._create_qr_tab(), "QR 码")
        login_tabs.addTab(self._create_password_tab(), "账号密码")
        login_tabs.addTab(self._create_sms_tab(), "手机验证码")
        login_tabs.addTab(self._create_paste_tab(), "手动粘贴")
        layout.addWidget(login_tabs)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def _create_qr_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("首次登录 / 获取 refresh_token（Cookie 保存到本地并同步到服务端内存）"))

        self.qr_image_label = QLabel()
        self.qr_image_label.setFixedSize(200, 200)
        self.qr_image_label.setStyleSheet("border: 1px solid #ccc; background: white;")
        self.qr_image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.qr_image_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.qr_status_label = QLabel("")
        self.qr_status_label.setWordWrap(True)
        layout.addWidget(self.qr_status_label)

        start_qr_btn = QPushButton("开始 QR 码登录")
        start_qr_btn.clicked.connect(self._bili_start_qr_login)
        layout.addWidget(start_qr_btn)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def _create_password_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("B站账号密码登录（RSA 加密传输）"))

        layout.addWidget(QLabel("账号（手机号/邮箱）:"))
        self.bili_username_input = QLineEdit()
        self.bili_username_input.setPlaceholderText("输入 B站 账号")
        layout.addWidget(self.bili_username_input)

        layout.addWidget(QLabel("密码:"))
        self.bili_password_input = QLineEdit()
        self.bili_password_input.setPlaceholderText("输入密码")
        self.bili_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.bili_password_input)

        login_btn = QPushButton("登录")
        login_btn.setStyleSheet("""
            QPushButton {
                background-color: #FB7299; color: white; border: none;
                padding: 8px 20px; border-radius: 4px; font-size: 14px;
            }
            QPushButton:hover { background-color: #E8618A; }
        """)
        login_btn.clicked.connect(self._bili_password_login)
        layout.addWidget(login_btn)

        # 安全提示
        tips = QLabel(
            "• 密码经 B站 RSA 公钥加密传输，服务端无法获取明文\n"
            "• Cookie 保存在本地，使用时才同步到服务端内存，不落盘\n"
            "• refresh_token 仅用于续期 SESSDATA，无法操作用户账号\n"
            "• 服务端重启后 Cookie 不会丢失，从本地重新同步即可\n"
            "• 可随时在 B站「设置-安全设置-登录设备管理」中撤销授权"
        )
        tips.setWordWrap(True)
        tips.setStyleSheet("color: #888; font-size: 12px; padding: 8px; background: #fafafa; border-radius: 4px; margin-top: 12px;")
        layout.addWidget(tips)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def _create_sms_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("手机验证码登录（需手机号已绑定 B站 账号）"))

        layout.addWidget(QLabel("手机号:"))
        self.bili_phone_input = QLineEdit()
        self.bili_phone_input.setPlaceholderText("输入 B站 绑定手机号")
        layout.addWidget(self.bili_phone_input)

        code_row = QHBoxLayout()
        self.bili_sms_code_input = QLineEdit()
        self.bili_sms_code_input.setPlaceholderText("验证码")
        code_row.addWidget(self.bili_sms_code_input)

        self.bili_sms_send_btn = QPushButton("获取验证码")
        self.bili_sms_send_btn.clicked.connect(self._bili_sms_send)
        code_row.addWidget(self.bili_sms_send_btn)
        layout.addLayout(code_row)

        login_btn = QPushButton("登录")
        login_btn.setStyleSheet("""
            QPushButton {
                background-color: #FB7299; color: white; border: none;
                padding: 8px 20px; border-radius: 4px; font-size: 14px;
            }
            QPushButton:hover { background-color: #E8618A; }
        """)
        login_btn.clicked.connect(self._bili_sms_login)
        layout.addWidget(login_btn)

        # 安全提示
        tips = QLabel(
            "• Cookie 保存在本地，使用时才同步到服务端内存，不落盘\n"
            "• refresh_token 仅用于续期 SESSDATA，无法操作用户账号\n"
            "• 验证码仅用于本次登录，不会记录\n"
            "• 服务端重启后 Cookie 不会丢失，从本地重新同步即可\n"
            "• 可随时在 B站「设置-安全设置-登录设备管理」中撤销授权"
        )
        tips.setWordWrap(True)
        tips.setStyleSheet("color: #888; font-size: 12px; padding: 8px; background: #fafafa; border-radius: 4px; margin-top: 12px;")
        layout.addWidget(tips)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def _create_paste_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("手动设置 Cookies（从浏览器复制后粘贴）"))
        layout.addWidget(QLabel("格式: SESSDATA=xxx; bili_jct=xxx; refresh_token=xxx"))
        self.bili_input = QTextEdit()
        self.bili_input.setMaximumHeight(80)
        self.bili_input.setPlaceholderText("从浏览器复制的 Cookie 字符串...")
        layout.addWidget(self.bili_input)

        set_btn = QPushButton("同步到服务端（本地同时存档）")
        set_btn.clicked.connect(self._bili_set_cookies)
        layout.addWidget(set_btn)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def _bili_check_status(self):
        """检查 Bilibili cookie 状态"""
        if not self.network_client:
            QMessageBox.warning(self, "提示", "网络客户端未初始化")
            return
        status = self.network_client.get_bilibili_cookie_status()
        error = status.get("error")
        if error:
            self.bili_status_label.setText(f"错误: {error}")
            return

        has = status.get("has_sessdata", False)
        expiry = status.get("expires_at", "N/A")
        remaining = status.get("remaining_days")
        last = status.get("last_refresh", "N/A")
        needs = status.get("needs_refresh", True)
        pool_total = status.get("pool_total", 0)
        pool_valid = status.get("pool_valid", 0)

        remaining_text = f"剩余 {remaining:.1f} 天" if remaining is not None else "未知"
        lines = [
            f"{'✅ 有 Cookie' if has else '❌ 无 Cookie'}",
            f"过期时间: {expiry} ({remaining_text})",
            f"最后刷新: {last}",
            f"Cookie 池: {pool_valid}/{pool_total} 组有效",
            f"{'⚠️ 需要刷新' if needs else '✅ 正常'}",
        ]
        self.bili_status_label.setText("\n".join(lines))

    # ── 本地 Cookie 持久化（客户端存储，服务端不落盘） ──

    @staticmethod
    def _bili_local_path() -> str:
        import os
        os.makedirs("data", exist_ok=True)
        return "data/bilibili_local_cookies.json"

    def _bili_save_local_cookies(self, cookies: dict) -> None:
        """登录成功后，将 cookies 保存到本地（服务端不落盘）。"""
        import json
        try:
            path = self._bili_local_path()
            existing = {}
            if Path(path).exists():
                existing = json.loads(Path(path).read_text(encoding="utf-8"))
            # 合并新 cookies
            existing.update(cookies)
            Path(path).write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            logger = __import__('logging').getLogger(__name__)
            logger.info("Bilibili cookies saved locally (client-side)")
        except Exception as e:
            print(f"Failed to save local cookies: {e}")

    def _bili_load_local_cookies(self) -> dict:
        """从本地加载 cookies。"""
        import json
        try:
            path = self._bili_local_path()
            if Path(path).exists():
                return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Failed to load local cookies: {e}")
        return {}

    def _bili_sync_local_to_server(self) -> bool:
        """将本地保存的 cookies 发送到服务端内存。"""
        local = self._bili_load_local_cookies()
        if not local.get("SESSDATA"):
            return False
        if not self.network_client:
            return False
        try:
            resp = self.network_client.session.post(
                f"{self.network_client.base_url}/api/bilibili/cookie/set",
                json=local,
                verify=self.network_client.verify_ssl,
                timeout=15,
            )
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        return False

    def _bili_api_refresh(self):
        """尝试 API 续期"""
        if not self.network_client:
            QMessageBox.warning(self, "提示", "网络客户端未初始化")
            return
        try:
            resp = self.network_client.session.post(
                f"{self.network_client.base_url}/api/bilibili/cookie/refresh",
                json={},
                verify=self.network_client.verify_ssl,
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    QMessageBox.information(self, "成功", "API 续期成功！")
                else:
                    QMessageBox.warning(self, "提示", "API 续期失败，可能需要 QR 码登录")
            else:
                QMessageBox.warning(self, "错误", f"请求失败: HTTP {resp.status_code}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"请求出错: {e}")
        self._bili_check_status()

    def _bili_start_qr_login(self):
        """开始 QR 码登录流程"""
        if not self.network_client:
            QMessageBox.warning(self, "提示", "网络客户端未初始化")
            return

        result = self.network_client.generate_bilibili_qrcode()
        error = result.get("error")
        if error:
            QMessageBox.warning(self, "错误", f"生成二维码失败: {error}")
            return

        url = result.get("url", "")
        qrcode_key = result.get("qrcode_key", "")
        if not url or not qrcode_key:
            QMessageBox.warning(self, "错误", "服务端返回的二维码信息不完整")
            return

        try:
            import qrcode
            img = qrcode.make(url)
            import os
            os.makedirs("temp", exist_ok=True)
            img_path = "temp/bilibili_qr.png"
            img.save(img_path)
            pixmap = QPixmap(img_path)
            self.qr_image_label.setPixmap(
                pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        except ImportError:
            self.qr_image_label.setText("请扫码:\n" + url)
        except Exception as e:
            self.qr_status_label.setText(f"显示二维码失败: {e}")

        self._qr_key = qrcode_key
        self.qr_status_label.setText("请使用 B站 App 扫描二维码...")

        self._qr_poll_timer = QTimer()
        self._qr_poll_timer.timeout.connect(self._bili_poll_qr)
        self._qr_poll_timer.start(2000)

    def _bili_poll_qr(self):
        """轮询 QR 码扫码结果"""
        if not self._qr_key or not self.network_client:
            return

        result = self.network_client.poll_bilibili_qrcode(self._qr_key)
        status = result.get("status", "error")

        if status == "success":
            self._qr_poll_timer.stop()
            self.qr_status_label.setText("✅ 扫码成功！Cookie 已保存到本地")
            self.qr_image_label.clear()
            self._bili_save_local_cookies(result.get("cookies", {}))
            QMessageBox.information(self, "成功", "Bilibili 登录成功！")
            self._bili_check_status()
        elif status == "scanned":
            self.qr_status_label.setText("已扫码，请在手机上确认...")
        elif status == "expired":
            self._qr_poll_timer.stop()
            self.qr_status_label.setText("二维码已过期，请重新生成")
        elif status == "error":
            self._qr_poll_timer.stop()
            self.qr_status_label.setText(f"轮询出错: {result.get('message', '')}")

    def _bili_set_cookies(self):
        """手动设置 cookies"""
        if not self.network_client:
            QMessageBox.warning(self, "提示", "网络客户端未初始化")
            return

        raw = self.bili_input.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, "提示", "请先粘贴 Cookie 字符串")
            return

        cookies = {}
        parts = raw.split(";")
        for part in parts:
            part = part.strip()
            if "=" in part:
                key, _, value = part.partition("=")
                key = key.strip()
                value = value.strip()
                if key in ("SESSDATA", "bili_jct", "bili_ticket", "refresh_token"):
                    cookies[key] = value

        if not cookies.get("SESSDATA"):
            QMessageBox.warning(self, "提示", "未找到 SESSDATA，请确认复制的 cookie 字符串正确")
            return

        result = self.network_client.set_bilibili_cookies(cookies)
        if result.get("error"):
            QMessageBox.warning(self, "错误", f"发送失败: {result['error']}")
        else:
            QMessageBox.information(self, "成功", "Cookie 已保存到本地")
            self._bili_save_local_cookies(cookies)
            self.bili_input.clear()
            self._bili_check_status()

    @staticmethod
    def _bili_encrypt_password(password: str, hash_str: str, pub_key: str) -> str:
        """用 B站 RSA 公钥加密密码（客户端本地加密，不向服务端发送明文）。"""
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
        import base64

        public_key = serialization.load_pem_public_key(pub_key.encode(), backend=default_backend())
        encrypted = public_key.encrypt(
            (hash_str + password).encode(),
            padding.PKCS1v15(),
        )
        return base64.b64encode(encrypted).decode()

    def _bili_password_login(self):
        """B站账号密码登录（客户端 RSA 加密后发送，服务端不接触明文）"""
        if not self.network_client:
            QMessageBox.warning(self, "提示", "网络客户端未初始化")
            return

        username = self.bili_username_input.text().strip()
        password = self.bili_password_input.text()
        if not username or not password:
            QMessageBox.warning(self, "提示", "请填写账号和密码")
            return

        try:
            # 1. 获取 RSA 公钥
            key_resp = self.network_client.session.get(
                f"{self.network_client.base_url}/api/bilibili/cookie/login/key",
                verify=self.network_client.verify_ssl,
                timeout=15,
            )
            if key_resp.status_code != 200:
                QMessageBox.warning(self, "错误", "获取加密密钥失败")
                return
            key_data = key_resp.json()
            pub_key = key_data.get("key", "")
            hash_str = key_data.get("hash", "")
            if not pub_key or not hash_str:
                QMessageBox.warning(self, "错误", "服务端返回的密钥数据不完整")
                return

            # 2. 本地 RSA 加密密码
            encrypted_password = self._bili_encrypt_password(password, hash_str, pub_key)

            # 3. 发送加密后的密码到服务端
            resp = self.network_client.session.post(
                f"{self.network_client.base_url}/api/bilibili/cookie/login/password",
                json={"username": username, "encrypted_password": encrypted_password},
                verify=self.network_client.verify_ssl,
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    QMessageBox.information(self, "成功", "Bilibili 登录成功！Cookie 已保存到本地")
                    self._bili_save_local_cookies(data.get("cookies", {}))
                    self.bili_username_input.clear()
                    self.bili_password_input.clear()
                    self._bili_check_status()
                else:
                    QMessageBox.warning(self, "登录失败", data.get("message", "账号或密码错误"))
            else:
                QMessageBox.warning(self, "错误", f"请求失败: HTTP {resp.status_code}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"请求出错: {e}")

    def _bili_sms_send(self):
        """发送短信验证码"""
        if not self.network_client:
            QMessageBox.warning(self, "提示", "网络客户端未初始化")
            return

        phone = self.bili_phone_input.text().strip()
        if not phone:
            QMessageBox.warning(self, "提示", "请输入手机号")
            return

        try:
            resp = self.network_client.session.post(
                f"{self.network_client.base_url}/api/bilibili/cookie/login/sms/send",
                json={"phone": phone, "country_code": "86"},
                verify=self.network_client.verify_ssl,
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    QMessageBox.information(self, "已发送", "验证码已发送到您的手机")
                    self.bili_sms_send_btn.setEnabled(False)
                    QTimer.singleShot(60000, lambda: self.bili_sms_send_btn.setEnabled(True))
                else:
                    QMessageBox.warning(self, "发送失败", data.get("message", "未知错误"))
            else:
                QMessageBox.warning(self, "错误", f"请求失败: HTTP {resp.status_code}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"请求出错: {e}")

    def _bili_sms_login(self):
        """短信验证码登录"""
        if not self.network_client:
            QMessageBox.warning(self, "提示", "网络客户端未初始化")
            return

        phone = self.bili_phone_input.text().strip()
        code = self.bili_sms_code_input.text().strip()
        if not phone or not code:
            QMessageBox.warning(self, "提示", "请填写手机号和验证码")
            return

        try:
            resp = self.network_client.session.post(
                f"{self.network_client.base_url}/api/bilibili/cookie/login/sms",
                json={"phone": phone, "code": code, "country_code": "86"},
                verify=self.network_client.verify_ssl,
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    QMessageBox.information(self, "成功", "Bilibili 登录成功！Cookie 已保存到本地")
                    self._bili_save_local_cookies(data.get("cookies", {}))
                    self.bili_phone_input.clear()
                    self.bili_sms_code_input.clear()
                    self._bili_check_status()
                else:
                    QMessageBox.warning(self, "登录失败", data.get("message", "未知错误"))
            else:
                QMessageBox.warning(self, "错误", f"请求失败: HTTP {resp.status_code}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"请求出错: {e}")

    def load_current_settings(self):
        """加载当前设置"""
        # 加载重要日期
        dates = self.preferences_manager.get_important_dates()
        self.dates_list.clear()
        for date_info in dates:
            enabled = "✓" if date_info.get("enabled", True) else "✗"
            item_text = f"{enabled} {date_info['name']} - {date_info['date']} ({date_info['type']})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, date_info.get("id"))
            self.dates_list.addItem(item)

        # 加载相处模式
        mode = self.preferences_manager.get_relationship_mode()
        relationship = mode.get("relationship", "朋友")
        speaking_style = mode.get("speaking_style", "活泼可爱")
        personality_traits = mode.get("personality_traits", [])
        custom_context = mode.get("custom_context", "")

        # 设置关系类型
        index = self.relationship_combo.findText(relationship)
        if index >= 0:
            self.relationship_combo.setCurrentIndex(index)
        else:
            self.relationship_combo.setCurrentText(relationship)

        # 设置表达风格
        index = self.style_combo.findText(speaking_style)
        if index >= 0:
            self.style_combo.setCurrentIndex(index)
        else:
            self.style_combo.setCurrentText(speaking_style)

        # 设置性格特点
        self.personality_input.setText("、".join(personality_traits))

        # 设置自定义上下文
        self.custom_context_input.setText(custom_context)

        # 加载提醒设置
        reminder_settings = self.preferences_manager.get_reminder_settings()
        self.enable_reminder_check.setChecked(reminder_settings.get("enable_reminders", True))

        reminder_time = reminder_settings.get("reminder_time", "09:00")
        time_parts = reminder_time.split(":")
        self.reminder_time_edit.setTime(QTime(int(time_parts[0]), int(time_parts[1])))

        self.interval_spin.setValue(reminder_settings.get("check_interval_hours", 1))

    def add_important_date(self):
        """添加重要日期"""
        name = self.date_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "警告", "请输入日期名称！")
            return

        date = self.date_input.date().toString("yyyy-MM-dd")
        type_map = {"生日": "birthday", "纪念日": "anniversary", "日程": "schedule", "其他": "other"}
        date_type = type_map.get(self.date_type_combo.currentText(), "other")
        message = self.date_message_input.text().strip()

        if self.preferences_manager.add_important_date(name, date, date_type, message):
            self.date_name_input.clear()
            self.date_message_input.clear()
            self.load_current_settings()  # 刷新列表
            QMessageBox.information(self, "成功", "重要日期已添加！")
        else:
            QMessageBox.warning(self, "错误", "添加重要日期失败！")

    def delete_selected_date(self):
        """删除选中的重要日期"""
        selected_items = self.dates_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "警告", "请先选择要删除的日期！")
            return

        for item in selected_items:
            date_id = item.data(Qt.ItemDataRole.UserRole)
            self.preferences_manager.remove_important_date(date_id)

        self.load_current_settings()  # 刷新列表
        QMessageBox.information(self, "成功", "已删除选中的日期！")

    def save_settings(self):
        """保存所有设置"""
        try:
            # 保存相处模式
            relationship = self.relationship_combo.currentText()
            speaking_style = self.style_combo.currentText()
            personality_traits = [t.strip() for t in self.personality_input.text().split("、") if t.strip()]
            custom_context = self.custom_context_input.toPlainText().strip()

            self.preferences_manager.set_relationship_mode(
                relationship=relationship,
                speaking_style=speaking_style,
                personality_traits=personality_traits,
                custom_context=custom_context
            )

            # 保存提醒设置
            enable_reminders = self.enable_reminder_check.isChecked()
            reminder_time = self.reminder_time_edit.time().toString("HH:mm")
            check_interval = self.interval_spin.value()

            self.preferences_manager.set_reminder_settings(
                enable_reminders=enable_reminders,
                reminder_time=reminder_time,
                check_interval_hours=check_interval
            )

            # 同步偏好到服务端
            if self.agent_binder and hasattr(self.agent_binder, 'on_send_preferences'):
                preferences_data = {
                    "relationship": relationship,
                    "speaking_style": speaking_style,
                    "personality_traits": personality_traits,
                    "custom_context": custom_context,
                }
                self.agent_binder.on_send_preferences(preferences_data)

            QMessageBox.information(self, "成功", "设置已保存！")
            self.accept()

        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存设置失败: {e}")
