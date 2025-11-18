# client/widgets_messages.py

import os
import html
import re
from pathlib import Path

from PyQt6.QtGui import QPixmap, QPainter, QPainterPath
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame,
    QListWidget, QListWidgetItem, QAbstractItemView, QMenu
)

# ==== helper linkify ==========================================================

def linkify(text: str) -> str:
    """Chuyển http(s)://... thành <a href=...> để QLabel click được."""
    escaped = html.escape(text)
    url_re = re.compile(r"(https?://[^\s]+)")

    def repl(m):
        url = m.group(1)
        return f'<a href="{url}">{url}</a>'

    return url_re.sub(repl, escaped)


# ==== load avatar mặc định cho bubble group ===================================

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_DEFAULT_AVATAR_PATH = _ASSETS_DIR / "default_avatar.png"
_DEFAULT_AVATAR_PIX: QPixmap | None = None  # sẽ load lazy sau

def _get_default_avatar_pix() -> QPixmap:
    """
    Chỉ tạo QPixmap cho avatar mặc định sau khi đã có QApplication.
    """
    global _DEFAULT_AVATAR_PIX
    if _DEFAULT_AVATAR_PIX is None:
        if _DEFAULT_AVATAR_PATH.exists():
            _DEFAULT_AVATAR_PIX = QPixmap(str(_DEFAULT_AVATAR_PATH))
        else:
            _DEFAULT_AVATAR_PIX = QPixmap()
    return _DEFAULT_AVATAR_PIX

def _make_round_avatar(pix: QPixmap, size: int) -> QPixmap:
    if pix.isNull():
        pix = _get_default_avatar_pix()
    pix = pix.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pix)
    painter.end()
    return result



def _default_group_avatar(size: int = 28) -> QPixmap:
    pix = _get_default_avatar_pix()
    if pix.isNull():
        return QPixmap()
    return _make_round_avatar(pix, size)

# ==== Bubble thường (1-1 hoặc của mình trong group) ===========================

class MessageBubble(QWidget):
    """
    Bubble text bình thường (không avatar + tên).
    """
    def __init__(self, text: str, is_me: bool, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(10)

        bubble = QFrame()
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(4)

        label = QLabel()
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        label.setOpenExternalLinks(True)
        label.setWordWrap(True)
        label.setStyleSheet("color: #fdf8ff;")

        label.setText(linkify(text))
        bubble_layout.addWidget(label)

        if is_me:
            bubble.setObjectName("bubble_out")
            layout.addStretch()
            layout.addWidget(bubble)
        else:
            bubble.setObjectName("bubble_in")
            layout.addWidget(bubble)
            layout.addStretch()


class ImageBubble(QWidget):
    """
    Bubble ảnh: hiện thumbnail nhỏ + tên file.
    """
    def __init__(self, image_path: str, is_me: bool, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(10)

        bubble = QFrame()
        bubble_layout = QHBoxLayout(bubble)  # nằm ngang: [thumbnail][text]
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(8)

        thumb_label = QLabel()
        thumb_label.setFixedSize(60, 60)
        thumb_label.setScaledContents(True)

        pix = QPixmap(image_path)
        if not pix.isNull():
            thumb_label.setPixmap(pix)

        filename = os.path.basename(image_path)
        text_label = QLabel(filename)
        text_label.setStyleSheet("color: #fdf8ff;")

        bubble_layout.addWidget(thumb_label)
        bubble_layout.addWidget(text_label)

        if is_me:
            bubble.setObjectName("bubble_out")
            layout.addStretch()
            layout.addWidget(bubble)
        else:
            bubble.setObjectName("bubble_in")
            layout.addWidget(bubble)
            layout.addStretch()


class FileBubble(QWidget):
    """
    Bubble file.
    """
    def __init__(self, file_path: str, is_me: bool, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(10)

        bubble = QFrame()
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(4)

        filename = os.path.basename(file_path)
        label = QLabel(f"📎 {filename}")
        label.setStyleSheet("color: #fdf8ff;")
        bubble_layout.addWidget(label)

        if is_me:
            bubble.setObjectName("bubble_out")
            layout.addStretch()
            layout.addWidget(bubble)
        else:
            bubble.setObjectName("bubble_in")
            layout.addWidget(bubble)
            layout.addStretch()


class VideoBubble(QWidget):
    """
    Bubble video (chỉ icon + tên file).
    """
    def __init__(self, file_path: str, is_me: bool, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(10)

        bubble = QFrame()
        bubble_layout = QVBoxLayout(bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)
        bubble_layout.setSpacing(4)

        filename = os.path.basename(file_path)
        label = QLabel(f"🎬 {filename}")
        label.setStyleSheet("color: #fdf8ff;")
        bubble_layout.addWidget(label)

        if is_me:
            bubble.setObjectName("bubble_out")
            layout.addStretch()
            layout.addWidget(bubble)
        else:
            bubble.setObjectName("bubble_in")
            layout.addWidget(bubble)
            layout.addStretch()


# ==== Wrapper cho bubble trong GROUP: avatar + tên user =======================

def _wrap_group_bubble(
    inner: QWidget,
    sender_name: str,
    avatar_pix: QPixmap | None = None,
) -> QWidget:
    """
    Bọc 1 bubble (text / image / file / video) trong layout có avatar + tên user.
    Dùng cho tin nhắn của NGƯỜI KHÁC trong group.
    """
    wrapper = QWidget()
    root = QHBoxLayout(wrapper)
    root.setContentsMargins(10, 2, 10, 2)
    root.setSpacing(8)

    # avatar
    avatar_lbl = QLabel()
    avatar_lbl.setFixedSize(28, 28)
    avatar_lbl.setScaledContents(True)

    # nếu không truyền avatar thì dùng avatar mặc định
    if avatar_pix is None or avatar_pix.isNull():
        avatar_pix = _default_group_avatar(28)
    if avatar_pix is not None and not avatar_pix.isNull():
        avatar_lbl.setPixmap(avatar_pix)

    root.addWidget(avatar_lbl, 0, Qt.AlignmentFlag.AlignTop)

    # cột bên phải: tên + bubble
    col = QVBoxLayout()
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(2)

    name_lbl = QLabel(sender_name or "...")
    name_lbl.setStyleSheet("color: #b7a4e6; font-size: 11px;")
    col.addWidget(name_lbl, 0, Qt.AlignmentFlag.AlignLeft)

    col.addWidget(inner)
    root.addLayout(col)
    root.addStretch()

    return wrapper


# ==== MessageList =============================================================

class MessageList(QListWidget):
    """
    Danh sách tin nhắn.
    Chuột phải -> menu "Gỡ tin nhắn này".
    Double click vào bubble file / video / ảnh -> emit signal cho ChatWindow xử lý.
    """
    delete_requested = pyqtSignal(int)           # message_id
    attachment_open_requested = pyqtSignal(str, str)  # path, kind: image/video/file

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chat_list")
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

        self.itemDoubleClicked.connect(self._on_item_double_clicked)

    # ---- Thêm bubble các loại ----

    def add_bubble(
        self,
        msg_id: int | None,
        sender_username: str,
        current_username: str | None,
        content: str,
        is_group: bool = False,
        avatar_pix: QPixmap | None = None,
    ):

        is_me = (current_username is not None
                 and sender_username == current_username)

        base_widget = MessageBubble(content, is_me, self)
        widget = base_widget

        # message group của người khác -> bọc thêm avatar + tên
        if is_group and not is_me:
            widget = _wrap_group_bubble(base_widget, sender_username, avatar_pix)

        item = QListWidgetItem(self)
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, {
            "id": msg_id,
            "sender": sender_username,
            "is_me": is_me,
            "kind": "text",
            "path": None,
            "content": content,
        })
        self.addItem(item)
        self.setItemWidget(item, widget)
        self.scrollToBottom()


    def add_image_bubble(
        self,
        msg_id: int | None,
        sender_username: str,
        current_username: str | None,
        image_path: str,
        is_group: bool = False,
        avatar_pix: QPixmap | None = None,
    ):

        is_me = (current_username is not None
                 and sender_username == current_username)

        base_widget = ImageBubble(image_path, is_me, self)
        widget = base_widget
        if is_group and not is_me:
             widget = _wrap_group_bubble(base_widget, sender_username, avatar_pix)

        item = QListWidgetItem(self)
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, {
            "id": msg_id,
            "sender": sender_username,
            "is_me": is_me,
            "kind": "image",
            "path": image_path,
            "content": image_path,
        })
        self.addItem(item)
        self.setItemWidget(item, widget)
        self.scrollToBottom()


    def add_file_bubble(
        self,
        msg_id: int | None,
        sender_username: str,
        current_username: str | None,
        file_path: str,
        is_group: bool = False,
        avatar_pix: QPixmap | None = None,
    ):
        is_me = (current_username is not None
                 and sender_username == current_username)

        base_widget = FileBubble(file_path, is_me, self)
        widget = base_widget
        if is_group and not is_me:
            widget = _wrap_group_bubble(base_widget, sender_username, avatar_pix)

        item = QListWidgetItem(self)
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, {
            "id": msg_id,
            "sender": sender_username,
            "is_me": is_me,
            "kind": "file",
            "path": file_path,
            "content": file_path,
        })
        self.addItem(item)
        self.setItemWidget(item, widget)
        self.scrollToBottom()


    def add_video_bubble(
        self,
        msg_id: int | None,
        sender_username: str,
        current_username: str | None,
        file_path: str,
        is_group: bool = False,
        avatar_pix: QPixmap | None = None,
    ):
        is_me = (current_username is not None
                 and sender_username == current_username)

        base_widget = VideoBubble(file_path, is_me, self)
        widget = base_widget
        if is_group and not is_me:
            widget = _wrap_group_bubble(base_widget, sender_username, avatar_pix)

        item = QListWidgetItem(self)
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, {
            "id": msg_id,
            "sender": sender_username,
            "is_me": is_me,
            "kind": "video",
            "path": file_path,
            "content": file_path,
        })
        self.addItem(item)
        self.setItemWidget(item, widget)
        self.scrollToBottom()


    # ---- Chuột phải: gỡ tin ----

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        msg_id = data.get("id")
        is_me = data.get("is_me", False)

        if not is_me or msg_id is None:
            return

        menu = QMenu(self)
        act_delete = menu.addAction("Gỡ tin nhắn này")
        chosen = menu.exec(event.globalPos())
        if chosen == act_delete:
            self.delete_requested.emit(msg_id)

    # ---- Double click mở file / video / ảnh ----

    def _on_item_double_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        kind = data.get("kind")
        path = data.get("path")
        if kind in ("image", "video", "file") and path:
            self.attachment_open_requested.emit(path, kind)
