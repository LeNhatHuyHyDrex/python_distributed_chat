from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFrame, QGraphicsDropShadowEffect, QStackedWidget, QListWidget
)


from .widgets_messages import MessageList
from .widgets_sidebar import ConversationSidebar


class ClickableLabel(QLabel):
    """
    QLabel có signal clicked để bắt sự kiện click chuột.
    Dùng cho avatar profile.
    """
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _load_round_avatar(path: str, size: int) -> QPixmap:
    pix = QPixmap(path)
    if pix.isNull():
        return QPixmap()

    pix = pix.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )

    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)

    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    circle = QPainterPath()
    circle.addEllipse(0, 0, size, size)
    painter.setClipPath(circle)
    painter.drawPixmap(0, 0, pix)
    painter.end()

    return result


def _apply_styles(win: QWidget):
    win.setStyleSheet("""
    QWidget#central_bg {
        background-color: #120322;
    }
    QFrame#card {
        border-radius: 24px;
        background-color: #1b0936;
    }
    QLabel#title {
        font-size: 20px;
        font-weight: 700;
        color: #f5e9ff;
    }
    QLabel#section_title {
        font-size: 16px;
        font-weight: 600;
        color: #f2e4ff;
    }
    QLabel#subtitle {
        font-size: 12px;
        color: #b7a4e6;
    }
    QLabel#status_label {
        font-size: 12px;
        color: #ff8c9b;
    }
    QLabel#sidebar_title {
        font-size: 14px;
        font-weight: 600;
        color: #d9c3ff;
    }
    QLineEdit {
        background-color: #2b174d;
        border-radius: 10px;
        padding: 8px 12px;
        border: 1px solid #3e2670;
        color: #f9f5ff;
        selection-background-color: #7b3ff2;
    }
    QLineEdit:focus {
        border: 1px solid #a66bff;
    }
    QPushButton {
        border-radius: 10px;
        padding: 8px 16px;
        font-weight: 600;
        color: white;
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 #7b3ff2,
            stop:1 #c850c0
        );
    }
    QPushButton#secondary_button {
        background-color: transparent;
        border: 1px solid #7b3ff2;
        color: #d2b9ff;
    }
    QPushButton#link_button {
        background-color: transparent;
        border: none;
        color: #b7a4e6;
        text-decoration: underline;
        font-size: 12px;
    }
    QPushButton#link_button:hover {
        color: #ffffff;
    }
    QPushButton#icon_button {
        background-color: #2b174d;
        padding: 0;
        border-radius: 16px;
        min-width: 32px;
        min-height: 32px;
        max-width: 32px;
        max-height: 32px;
    }
    QPushButton#icon_button:hover {
        background-color: #3a2066;
    }
    QPushButton#danger_button {
        background-color: #5a1030;
    }
    QPushButton#danger_button:hover {
        background-color: #7a143f;
    }
    QListWidget#chat_list {
        background-color: #16062b;
        border-radius: 12px;
        border: 1px solid #3e2670;
        color: #f2e4ff;
    }
    QListWidget#sidebar_list {
        background-color: #14042a;
        border-radius: 12px;
        border: 1px solid #3e2670;
        color: #f2e4ff;
    }
    QListWidget#sidebar_list::item {
        padding: 8px 10px;
    }
    QListWidget#sidebar_list::item:selected {
        background-color: #2f1659;
    }
    QFrame#bubble_out {
        border-radius: 16px;
        background-color: qlineargradient(
            x1:0, y1:0, x2:1, y2:1,
            stop:0 #7b3ff2,
            stop:1 #c850c0
        );
    }
    QFrame#bubble_in {
        border-radius: 16px;
        background-color: #2b174d;
    }
    QFrame#info_panel {
        background-color: #14042a;
        border-radius: 16px;
        border: 1px solid #3e2670;
    }
    QListWidget#info_list {
        background-color: #16062b;
        border-radius: 12px;
        border: 1px solid #3e2670;
        color: #f2e4ff;
        font-size: 11px;
    }
    QListWidget#info_list::item {
        padding: 4px 6px;
    }

    QLabel#profile_avatar,
    QLabel#partner_avatar {
        border-radius: 999px;
        border: none;
    }

    """)


def _build_auth_page(win: QWidget):
    win.login_panel = QWidget()
    login_layout = QVBoxLayout(win.login_panel)
    login_layout.setSpacing(10)

    login_title = QLabel("Đăng nhập / Đăng ký")
    login_title.setObjectName("section_title")

    win.auth_stack = QStackedWidget()

    # Login page
    login_page = QWidget()
    lp_layout = QVBoxLayout(login_page)
    lp_layout.setSpacing(8)

    win.le_login_username = QLineEdit()
    win.le_login_username.setPlaceholderText("Tên đăng nhập")

    win.le_login_password = QLineEdit()
    win.le_login_password.setPlaceholderText("Mật khẩu")
    win.le_login_password.setEchoMode(QLineEdit.EchoMode.Password)

    win.btn_login = QPushButton("Đăng nhập")

    lp_layout.addWidget(win.le_login_username)
    lp_layout.addWidget(win.le_login_password)
    lp_layout.addWidget(win.btn_login)

    # Register page
    register_page = QWidget()
    rp_layout = QVBoxLayout(register_page)
    rp_layout.setSpacing(8)

    win.le_reg_username = QLineEdit()
    win.le_reg_username.setPlaceholderText("Tên đăng nhập")

    win.le_reg_display = QLineEdit()
    win.le_reg_display.setPlaceholderText("Tên hiển thị")

    win.le_reg_pw1 = QLineEdit()
    win.le_reg_pw1.setPlaceholderText("Mật khẩu")
    win.le_reg_pw1.setEchoMode(QLineEdit.EchoMode.Password)

    win.le_reg_pw2 = QLineEdit()
    win.le_reg_pw2.setPlaceholderText("Nhập lại mật khẩu")
    win.le_reg_pw2.setEchoMode(QLineEdit.EchoMode.Password)

    win.btn_register = QPushButton("Đăng ký")

    rp_layout.addWidget(win.le_reg_username)
    rp_layout.addWidget(win.le_reg_display)
    rp_layout.addWidget(win.le_reg_pw1)
    rp_layout.addWidget(win.le_reg_pw2)
    rp_layout.addWidget(win.btn_register)

    win.auth_stack.addWidget(login_page)     # index 0
    win.auth_stack.addWidget(register_page)  # index 1

    switch_row = QHBoxLayout()
    win.btn_show_login = QPushButton("Đã có tài khoản? Đăng nhập")
    win.btn_show_login.setObjectName("link_button")
    win.btn_show_register = QPushButton("Chưa có tài khoản? Đăng ký")
    win.btn_show_register.setObjectName("link_button")
    switch_row.addWidget(win.btn_show_login)
    switch_row.addWidget(win.btn_show_register)

    login_layout.addWidget(login_title)
    login_layout.addWidget(win.auth_stack)
    login_layout.addLayout(switch_row)
    login_layout.addStretch()

    win.main_stack.addWidget(win.login_panel)


def _build_chat_page(win: QWidget):
    win.chat_panel = QWidget()
    chat_outer = QHBoxLayout(win.chat_panel)
    chat_outer.setContentsMargins(0, 0, 0, 0)
    chat_outer.setSpacing(16)

    # Sidebar
    win.sidebar = ConversationSidebar()
    chat_outer.addWidget(win.sidebar, 1)

    # Center chat
    win.chat_area = QWidget()
    chat_layout = QVBoxLayout(win.chat_area)
    chat_layout.setSpacing(8)

    # Ẩn ô "Gửi tới", vì mình chọn từ sidebar
    win.le_to_user = QLineEdit()
    win.le_to_user.setVisible(False)

    win.chat_list = MessageList()

    input_row = QHBoxLayout()

    input_row = QHBoxLayout()

    win.btn_send_image = QPushButton("📷")
    win.btn_send_image.setObjectName("icon_button")
    win.btn_send_image.setFixedSize(32, 32)

    win.btn_send_file = QPushButton("📎")
    win.btn_send_file.setObjectName("icon_button")
    win.btn_send_file.setFixedSize(32, 32)

    win.btn_send_video = QPushButton("🎬")
    win.btn_send_video.setObjectName("icon_button")
    win.btn_send_video.setFixedSize(32, 32)

    win.le_message = QLineEdit()
    win.le_message.setPlaceholderText("Nhập tin nhắn...")

    win.btn_send = QPushButton("Gửi")

    # Thứ tự: Ảnh – File – Video – ô nhập – Gửi
    input_row.addWidget(win.btn_send_image)
    input_row.addWidget(win.btn_send_file)
    input_row.addWidget(win.btn_send_video)
    input_row.addWidget(win.le_message)
    input_row.addWidget(win.btn_send)



    win.btn_broadcast = QPushButton("Gửi thông báo server (test)")
    win.btn_broadcast.setObjectName("secondary_button")

    win.lbl_chat_status = QLabel("")
    win.lbl_chat_status.setObjectName("status_label")

    chat_layout.addWidget(win.chat_list)
    chat_layout.addLayout(input_row)
    chat_layout.addWidget(win.btn_broadcast)
    chat_layout.addWidget(win.lbl_chat_status)

    chat_outer.addWidget(win.chat_area, 2)

    # Info panel bên phải
    win.info_panel = QFrame()
    win.info_panel.setObjectName("info_panel")
    info_layout = QVBoxLayout(win.info_panel)
    info_layout.setContentsMargins(12, 12, 12, 12)
    info_layout.setSpacing(10)

    win.lbl_partner_avatar = QLabel()
    win.lbl_partner_avatar.setObjectName("partner_avatar")
    win.lbl_partner_avatar.setFixedSize(80, 80)
    win.lbl_partner_avatar.setScaledContents(True)
    if getattr(win, "avatar_large", None) and not win.avatar_large.isNull():
        win.lbl_partner_avatar.setPixmap(win.avatar_large)

    win.lbl_partner_name = QLabel("Chưa chọn đoạn chat")
    win.lbl_partner_name.setObjectName("section_title")

    win.lbl_partner_username = QLabel("")
    win.lbl_partner_username.setObjectName("subtitle")

    info_layout.addWidget(
        win.lbl_partner_avatar, 0, Qt.AlignmentFlag.AlignHCenter
    )
    info_layout.addWidget(
        win.lbl_partner_name, 0, Qt.AlignmentFlag.AlignHCenter
    )
    info_layout.addWidget(
        win.lbl_partner_username, 0, Qt.AlignmentFlag.AlignHCenter
    )

    info_layout.addSpacing(8)

    win.btn_media = QPushButton("Ảnh & Video")
    win.btn_files = QPushButton("File")
    win.btn_links = QPushButton("Link")
    win.btn_delete_conversation = QPushButton("Xóa đoạn chat")
    win.btn_delete_conversation.setObjectName("danger_button")
    win.btn_leave_group = QPushButton("Rời nhóm")
    win.btn_leave_group.setObjectName("secondary_button")

    info_layout.addWidget(win.btn_media)
    info_layout.addWidget(win.btn_files)
    info_layout.addWidget(win.btn_links)

    # List hiển thị Ảnh/Video/File/Link
    win.list_attachments = QListWidget()
    win.list_attachments.setObjectName("info_list")
    win.list_attachments.setVisible(False)      # mặc định ẩn
    win.list_attachments.setMinimumHeight(120)  # cho nó có chiều cao chút

    info_layout.addWidget(win.list_attachments)

    info_layout.addStretch()
    info_layout.addWidget(win.btn_delete_conversation)
    info_layout.addWidget(win.btn_media)
    info_layout.addWidget(win.btn_files)
    info_layout.addWidget(win.btn_links)

    win.list_attachments = QListWidget()
    ...

    info_layout.addWidget(win.list_attachments)

    info_layout.addStretch()
    info_layout.addWidget(win.btn_leave_group)       # 👈 thêm dòng này
    info_layout.addWidget(win.btn_delete_conversation)

    chat_outer.addWidget(win.info_panel, 1)

    win.main_stack.addWidget(win.chat_panel)


def setup_chatwindow_ui(win: QWidget):
    win.setWindowTitle("Mini Messenger - Distributed Chat")
    win.resize(1050, 640)

    central = QWidget()
    central.setObjectName("central_bg")
    win.setCentralWidget(central)

    root_layout = QVBoxLayout(central)
    root_layout.setContentsMargins(40, 40, 40, 40)
    root_layout.setSpacing(0)

    # load avatars mặc định (hình tròn)
    assets_dir = Path(__file__).resolve().parent / "assets"
    avatar_path = assets_dir / "default_avatar.png"
    win.avatar_small = _load_round_avatar(str(avatar_path), 32)
    win.avatar_large = _load_round_avatar(str(avatar_path), 80)

    win.card = QFrame()
    win.card.setObjectName("card")
    card_layout = QVBoxLayout(win.card)
    card_layout.setContentsMargins(24, 24, 24, 24)
    card_layout.setSpacing(12)

    # header
    header = QHBoxLayout()
    header.setSpacing(12)

    title = QLabel("Mini Messenger")
    title.setObjectName("title")
    header.addWidget(title)

    header.addStretch()

    win.lbl_user_info = QLabel("Chưa đăng nhập")
    win.lbl_user_info.setObjectName("section_title")

    win.lbl_profile_avatar = ClickableLabel()
    win.lbl_profile_avatar.setObjectName("profile_avatar")
    win.lbl_profile_avatar.setFixedSize(32, 32)
    win.lbl_profile_avatar.setScaledContents(True)
    if win.avatar_small and not win.avatar_small.isNull():
        win.lbl_profile_avatar.setPixmap(win.avatar_small)

    # 👉 THÊM NÚT TẠO NHÓM Ở ĐÂY
    win.btn_create_group = QPushButton("Tạo nhóm")
    win.btn_create_group.setObjectName("secondary_button")
    win.btn_create_group.setFixedHeight(32)

    win.btn_logout = QPushButton("⎋")
    win.btn_logout.setObjectName("icon_button")
    win.btn_logout.setToolTip("Đăng xuất")
    win.btn_logout.setFixedSize(32, 32)

    header.addWidget(win.lbl_user_info)
    header.addSpacing(8)
    header.addWidget(win.lbl_profile_avatar)
    header.addSpacing(4)
    header.addWidget(win.btn_create_group)  # 👈 nhớ add vào
    header.addWidget(win.btn_logout)

    card_layout.addLayout(header)


    win.lbl_auth_status = QLabel("")
    win.lbl_auth_status.setObjectName("status_label")
    card_layout.addWidget(win.lbl_auth_status)

    win.main_stack = QStackedWidget()
    card_layout.addWidget(win.main_stack, 1)

    _build_auth_page(win)
    _build_chat_page(win)

    win.main_stack.setCurrentWidget(win.login_panel)

    shadow = QGraphicsDropShadowEffect(win.card)
    shadow.setBlurRadius(40)
    shadow.setOffset(0, 20)
    shadow.setColor(QColor(0, 0, 0, 150))
    win.card.setGraphicsEffect(shadow)

    root_layout.addWidget(win.card)
    _apply_styles(win)
