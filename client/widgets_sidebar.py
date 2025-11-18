from __future__ import annotations

import base64
from typing import List, Dict
from PyQt6.QtCore import pyqtSignal, Qt, QEvent, QSize
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QLabel,QMenu
)
from pathlib import Path
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPainterPath


class ConversationSidebar(QWidget):
    """
    Sidebar hiển thị:
    - Danh sách cuộc trò chuyện (1-1 + group) từ server.
    - Kết quả search user từ server.

    item.data(UserRole) = key:
      - "user:<username>"
      - "group:<conversation_id>"
    """
    conversation_selected = pyqtSignal(str)
    search_text_changed = pyqtSignal(str)
    user_add_to_group = pyqtSignal(str)      # 👈 username
    join_group_requested = pyqtSignal(str)   # 👈 tên nhóm khi Enter mà không có user

    
    conversation_selected = pyqtSignal(str)   # key
    search_text_changed = pyqtSignal(str)     # text trong ô search

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("Đoạn chat")
        title.setObjectName("sidebar_title")
          # Avatar mặc định
        assets_dir = Path(__file__).resolve().parent / "assets"
        avatar_path = assets_dir / "default_avatar.png"
        self._default_avatar = QPixmap(str(avatar_path))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Tìm kiếm...")

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("sidebar_list")
        self.list_widget.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.list_widget.customContextMenuRequested.connect(
            self._on_context_menu
        )

        layout.addWidget(title)
        layout.addWidget(self.search_edit)
        layout.addWidget(self.list_widget)

        # dữ liệu
        self._all_conversations: List[Dict] = []   # từ list_conversations
        self._search_results: List[Dict] = []      # từ search_users_result
        self._active_key: str | None = None        # "user:..." hoặc "group:..."
        self._avatar_cache: dict[str, QPixmap] = {}

        # signals
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        self.search_edit.installEventFilter(self)

        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.itemActivated.connect(self._on_item_clicked)

    # ===== API từ ChatWindow =====

    def set_conversations(self, conversations: list[dict]):
        """
        conversations (từ server):
        {
          "conversation_id": ...,
          "is_group": 0/1,
          "partner_username": "..."/None,
          "title": "...",
          "last_time": "...",
          "avatar_b64": "..." hoặc None
        }
        """
        self._all_conversations = conversations or []
        self._apply_filter()

    def set_search_results(self, users: list[dict]):
        """
        users (từ search_users_result):
        { "username": "...", "display_name": "..." }
        """
        self._search_results = users or []
        self._apply_filter()

    def set_active_username(self, key: str | None):
        """
        key = "user:ngochung" hoặc "group:5".
        ChatWindow chỉ cần truyền đúng key đang mở.
        """
        self._active_key = (key or "").strip() or None
        self._apply_filter()

    def clear_search(self):
        self.search_edit.clear()
        self._search_results = []
        self._apply_filter()

    # ===== Nội bộ =====

    def _on_search_text_changed(self, text: str):
        self.search_text_changed.emit(text)
        # Lọc lại list (cả khi server chưa trả search_results)
        self._apply_filter()

    def _get_avatar_for_conv(self, conv: dict) -> QPixmap | None:
        """
        Trả về avatar tròn 32x32 cho 1 convo (user hoặc group).
        - Nếu có avatar_b64 -> decode + bo tròn.
        - Nếu không có -> dùng default_avatar nhưng vẫn bo tròn.
        """
        size = 32

        def make_round(pix: QPixmap) -> QPixmap:
            if pix.isNull():
                return pix
            p = pix.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            rounded = QPixmap(size, size)
            rounded.fill(Qt.GlobalColor.transparent)
            painter = QPainter(rounded)
            path = QPainterPath()
            path.addEllipse(0, 0, size, size)
            painter.setClipPath(path)
            painter.drawPixmap(0, 0, p)
            painter.end()
            return rounded

        b64 = conv.get("avatar_b64") or conv.get("partner_avatar_url")

        # ❌ Không có avatar trong DB -> dùng default nhưng bo tròn
        if not b64:
            if self._default_avatar and not self._default_avatar.isNull():
                return make_round(self._default_avatar)
            return None

        if b64 in self._avatar_cache:
            return self._avatar_cache[b64]

        try:
            raw = base64.b64decode(b64)
            pix = QPixmap()
            if not pix.loadFromData(raw) or pix.isNull():
                # lỗi file -> fallback default tròn
                return make_round(self._default_avatar)

            rounded = make_round(pix)
            self._avatar_cache[b64] = rounded
            return rounded
        except Exception:
            return make_round(self._default_avatar)



    def _apply_filter(self):
        text = self.search_edit.text().strip().lower()
        self.list_widget.clear()

        # Nếu đang gõ search và đã có _search_results từ server -> ưu tiên show kết quả search
        if text and self._search_results:
            for u in self._search_results:
                uname = (u.get("username") or "").strip()
                display = (u.get("display_name") or uname).strip()
                if not uname:
                    continue

                # lọc thêm lần nữa cho chắc (phòng khi server trả rộng)
                if text not in uname.lower() and text not in display.lower():
                    continue

                title = display if display else uname
                key = f"user:{uname}"

                item = QListWidgetItem(title)
                item.setData(Qt.ItemDataRole.UserRole, key)

                # 🔹 THÊM: dùng avatar mặc định cho kết quả search
                if hasattr(self, "_default_avatar") and self._default_avatar and not self._default_avatar.isNull():
                    item.setIcon(QIcon(self._default_avatar))

                self.list_widget.addItem(item)

        else:
            # không có search hoặc chưa có search_results -> dùng danh sách conversation
            for conv in self._all_conversations:
                is_group = conv.get("is_group", 0)
                title = (conv.get("title") or "").strip()
                partner_username = (conv.get("partner_username") or "").strip()

                if not title and not partner_username:
                    continue

                text_target = f"{title} {partner_username}".lower()
                if text and text not in text_target:
                    continue

                if is_group:
                    key = f"group:{conv['conversation_id']}"
                else:
                    key = f"user:{partner_username}"

                item = QListWidgetItem(title or partner_username)
                item.setData(Qt.ItemDataRole.UserRole, key)

                # avatar cho cả 1-1 và group
                avatar_pix = self._get_avatar_for_conv(conv)
                if avatar_pix and not avatar_pix.isNull():
                    item.setIcon(QIcon(avatar_pix))


                self.list_widget.addItem(item)


            # Chọn lại item active nếu có
            if self._active_key:
                for i in range(self.list_widget.count()):
                    it = self.list_widget.item(i)
                    if it.data(Qt.ItemDataRole.UserRole) == self._active_key:
                        self.list_widget.setCurrentItem(it)
                        break

    def _on_item_clicked(self, item: QListWidgetItem):
        key = item.data(Qt.ItemDataRole.UserRole)
        if not key:
            return
        # Khi click 1 đoạn chat -> clear search để hiện full list
        if self.search_edit.text():
            self.search_edit.clear()
            self._search_results = []
            # _apply_filter sẽ được gọi trong _on_search_text_changed
        self.conversation_selected.emit(key)

    # ----- Event filter cho ô search -----

    def eventFilter(self, obj, event):
        if obj is self.search_edit and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                text = self.search_edit.text().strip()
                if not text:
                    return True

                if self.list_widget.count() > 0:
                    current = self.list_widget.currentItem()
                    if current is None:
                        current = self.list_widget.item(0)
                    if current:
                        self._on_item_clicked(current)
                else:
                    # Không có kết quả user -> coi text là tên group cần join
                    name = text
                    self.search_edit.clear()
                    self._search_results = []
                    self.join_group_requested.emit(name)
                return True

            if key == Qt.Key.Key_Down:
                if self.list_widget.count() > 0:
                    self.list_widget.setFocus()
                    if not self.list_widget.currentItem():
                        self.list_widget.setCurrentRow(0)
                return True

        return super().eventFilter(obj, event)
    def _on_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        key = item.data(Qt.ItemDataRole.UserRole) or ""
        key = str(key)
        if not key.startswith("user:"):
            return

        username = key.split(":", 1)[1]

        menu = QMenu(self)
        act_add = menu.addAction("Thêm vào nhóm hiện tại")
        chosen = menu.exec(self.list_widget.mapToGlobal(pos))
        if chosen == act_add:
            self.user_add_to_group.emit(username)
