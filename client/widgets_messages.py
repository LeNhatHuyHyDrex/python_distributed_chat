# client/widgets_messages.py

import os
import html
import re
from PyQt6.QtGui import QPixmap

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame,
    QListWidget, QListWidgetItem, QAbstractItemView, QMenu
)


def linkify(text: str) -> str:
    """Chuyển http(s)://... thành <a href=...> để QLabel click được."""
    escaped = html.escape(text)
    url_re = re.compile(r"(https?://[^\s]+)")

    def repl(m):
        url = m.group(1)
        return f'<a href="{url}">{url}</a>'

    return url_re.sub(repl, escaped)


class MessageBubble(QWidget):
    """
    Bubble text.
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

        # 1) Ảnh thumbnail
        thumb_label = QLabel()
        thumb_label.setFixedSize(60, 60)
        thumb_label.setScaledContents(True)

        pix = QPixmap(image_path)
        if not pix.isNull():
            thumb_label.setPixmap(pix)

        # 2) Tên file
        import os
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

        import os
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

    def add_bubble(self, msg_id: int | None, sender_username: str,
                current_username: str | None, content: str):
        is_me = (current_username is not None
                and sender_username == current_username)

        widget = MessageBubble(content, is_me, self)
        item = QListWidgetItem(self)
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, {
            "id": msg_id,
            "sender": sender_username,
            "is_me": is_me,
            "kind": "text",   # QUAN TRỌNG: để không phân biệt với file/video/image
            "path": None,
        })
        self.addItem(item)
        self.setItemWidget(item, widget)
        self.scrollToBottom()

    def add_image_bubble(self, msg_id, sender_username, current_username, image_path: str):
        is_me = (current_username is not None
                and sender_username == current_username)

        widget = ImageBubble(image_path, is_me, self)

        item = QListWidgetItem(self)
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, {
            "id": msg_id,
            "sender": sender_username,
            "is_me": is_me,
            "kind": "image",
            "path": image_path,   # rất quan trọng để double-click popup dùng
        })
        self.addItem(item)
        self.setItemWidget(item, widget)
        self.scrollToBottom()


    def add_file_bubble(self, msg_id: int | None, sender_username: str,
                        current_username: str | None, file_path: str):
        is_me = (current_username is not None
                 and sender_username == current_username)
        widget = FileBubble(file_path, is_me, self)
        item = QListWidgetItem(self)
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, {
            "id": msg_id,
            "sender": sender_username,
            "is_me": is_me,
            "kind": "file",
            "path": file_path,
        })
        self.addItem(item)
        self.setItemWidget(item, widget)
        self.scrollToBottom()

    def add_video_bubble(self, msg_id, sender_username, current_username, file_path):
        is_me = (current_username is not None and sender_username == current_username)
        widget = VideoBubble(file_path, is_me, self)
        item = QListWidgetItem(self)
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, {
            "id": msg_id,
            "sender": sender_username,
            "is_me": is_me,
            "kind": "video",
            "path": file_path,
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

        # CHỈ check 2 điều kiện này
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
