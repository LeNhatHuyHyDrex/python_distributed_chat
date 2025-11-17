from __future__ import annotations

import base64
import os
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, Qt, QEvent, QSize
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QLabel
)


class ConversationSidebar(QWidget):
    """
    Sidebar hiển thị danh sách đoạn chat, kèm ô search.
    - Gõ search: lọc theo username / tên hiển thị (local).
    - Enter khi đang search:
        + Nếu có kết quả: mở đoạn chat đầu tiên trong list.
        + Nếu không có kết quả: coi nội dung search là username và mở chat mới.
    - Xóa search: hiện toàn bộ.
    - Click / Enter 1 item: phát signal conversation_selected(username).
    """
    conversation_selected = pyqtSignal(str)
    # ChatWindow có thể bắt signal này để search trên server nếu muốn
    search_text_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("Đoạn chat")
        title.setObjectName("sidebar_title")

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Tìm kiếm...")

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("sidebar_list")
        self.list_widget.setIconSize(QSize(32, 32))

        layout.addWidget(title)
        layout.addWidget(self.search_edit)
        layout.addWidget(self.list_widget)

        self._all_conversations: list[dict] = []
        self._active_username: str | None = None

        # avatar mặc định
        assets_dir = Path(__file__).resolve().parent / "assets"
        default_path = assets_dir / "default_avatar.png"
        default_pix = QPixmap(str(default_path)) if default_path.exists() else QPixmap()
        self._default_avatar = self._make_round_avatar(default_pix, 32)

        # search text -> vừa lọc local, vừa báo ra ngoài (nếu ChatWindow có bắt signal)
        self.search_edit.textChanged.connect(self._apply_filter)
        self.search_edit.textChanged.connect(self.search_text_changed)
        self.search_edit.installEventFilter(self)

        self.list_widget.itemClicked.connect(self._on_item_clicked)
        # itemActivated được gọi khi nhấn Enter trên item đã chọn
        self.list_widget.itemActivated.connect(self._on_item_clicked)

    # ----- API từ ChatWindow -----

    def set_conversations(self, conversations: list[dict]):
        """
        conversations: list dict từ server:
        {
          "conversation_id": ...,
          "partner_username": "...",
          "partner_display_name": "...",
          "last_time": "2025-11-15 13:20:00" hoặc None,
          "partner_avatar_url": "avatars/user_3.png"  (hoặc avatar_b64 nếu em gửi kiểu đó)
        }
        """
        self._all_conversations = conversations or []
        self._apply_filter()

    def set_active_username(self, username: str | None):
        """
        Đặt đoạn chat đang mở hiện tại để highlight trong sidebar.
        """
        self._active_username = (username or "").strip() or None
        # Gọi lại _apply_filter để cập nhật selection
        self._apply_filter()

    # ----- Nội bộ -----

    def _make_round_avatar(self, pix: QPixmap, size: int) -> QPixmap:
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
        path = QPainterPath()
        path.addEllipse(0, 0, size, size)
        painter.setClipPath(path)
        painter.drawPixmap(0, 0, pix)
        painter.end()
        return result

    def _get_avatar_for_conv(self, conv: dict) -> QPixmap:
        """
        Lấy QPixmap avatar 32x32 cho 1 conversation.

        Ưu tiên:
        - conv["avatar_b64"]  (base64 PNG/JPEG), nếu em chọn lưu base64
        - conv["partner_avatar_url"] / "avatar_url"/"avatar_path" (đường dẫn file trên server/...)
        - Nếu không có gì -> avatar mặc định.
        """
        # 1) Thử base64 (nếu sau này em chuyển sang lưu base64)
        b64 = conv.get("avatar_b64")
        if isinstance(b64, str) and b64:
            try:
                raw = base64.b64decode(b64)
                pix = QPixmap()
                if pix.loadFromData(raw) and not pix.isNull():
                    return self._make_round_avatar(pix, 32)
            except Exception:
                pass

        # 2) Thử đường dẫn file (tương đối so với thư mục server)
        rel_path = (
            conv.get("partner_avatar_url")
            or conv.get("avatar_url")
            or conv.get("avatar_path")
        )
        if isinstance(rel_path, str) and rel_path:
            base_dir = Path(__file__).resolve().parents[1]  # thư mục project
            img_path = base_dir / "server" / rel_path.replace("/", os.sep)
            if img_path.exists():
                pix = QPixmap(str(img_path))
                if not pix.isNull():
                    return self._make_round_avatar(pix, 32)

        # 3) Fallback
        return self._default_avatar

    def _apply_filter(self):
        text = self.search_edit.text().strip().lower()
        self.list_widget.clear()

        for conv in self._all_conversations:
            uname = (conv.get("partner_username") or "").strip()
            if not uname:
                continue
            display_name = (conv.get("partner_display_name") or uname).strip()
            label = display_name
            if display_name != uname:
                label += f" ({uname})"

            if text:
                if text not in uname.lower() and text not in display_name.lower():
                    continue

            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, uname)

            avatar_pix = self._get_avatar_for_conv(conv)
            if avatar_pix and not avatar_pix.isNull():
                item.setIcon(QIcon(avatar_pix))

            self.list_widget.addItem(item)

        # Sau khi fill list, nếu có _active_username thì chọn nó
        if self._active_username:
            for i in range(self.list_widget.count()):
                it = self.list_widget.item(i)
                if it.data(Qt.ItemDataRole.UserRole) == self._active_username:
                    self.list_widget.setCurrentItem(it)
                    break

    def _on_item_clicked(self, item: QListWidgetItem):
        uname = item.data(Qt.ItemDataRole.UserRole)
        if not uname:
            return
        # Khi người dùng chọn một đoạn chat, coi như đã kết thúc search
        if self.search_edit.text():
            self.search_edit.clear()  # trigger _apply_filter -> hiển thị toàn bộ
        self.conversation_selected.emit(uname)

    # ----- Event filter cho ô search -----

    def eventFilter(self, obj, event):
        # Xử lý phím trong ô search: Enter + mũi tên xuống
        if obj is self.search_edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                text = self.search_edit.text().strip()
                if not text:
                    return True

                if self.list_widget.count() > 0:
                    # Nếu có kết quả thì ưu tiên item đang chọn / item đầu tiên
                    current = self.list_widget.currentItem()
                    if current is None:
                        current = self.list_widget.item(0)
                    if current:
                        self._on_item_clicked(current)
                else:
                    # Không có kết quả -> coi text là username mới
                    uname = text
                    self.search_edit.clear()
                    self.conversation_selected.emit(uname)
                return True

            if key == Qt.Key.Key_Down:
                if self.list_widget.count() > 0:
                    self.list_widget.setFocus()
                    if not self.list_widget.currentItem():
                        self.list_widget.setCurrentRow(0)
                return True

        return super().eventFilter(obj, event)
