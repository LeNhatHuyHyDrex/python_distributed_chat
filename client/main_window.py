import socket
import base64
import os
import shutil
import re
from pathlib import Path
from typing import Any

from PyQt6.QtGui import QPixmap, QPainter, QPainterPath, QDesktopServices
from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtWidgets import (
    QMainWindow, QMessageBox, QFileDialog,
    QDialog, QVBoxLayout, QLabel, QListWidgetItem,
    QHBoxLayout, QPushButton, QSlider, QInputDialog
)



from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget

from common.config import SERVER_HOST, SERVER_PORT
from .network import NetworkThread, make_packet
from .ui_layout import setup_chatwindow_ui

class ChatWindow(QMainWindow):
    def send_file(self, path, file_type):
        if not self.current_username:
            self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return

        # If in group, allow sending to group
        if not self.current_group_id and not self.current_partner_username:
            self.lbl_chat_status.setText("⚠️ Hãy chọn người hoặc nhóm để gửi")
            return

        try:
            with open(path, "rb") as f:
                raw = f.read()
        except:
            self.lbl_chat_status.setText("❌ Không đọc được file")
            return

        b64 = base64.b64encode(raw).decode("ascii")

        # group send
        if self.current_group_id:
            pkt = make_packet("send_group_file", {
                "from": self.current_username,
                "conversation_id": self.current_group_id,
                "filename": os.path.basename(path),
                "data": b64,
                "file_type": file_type
            })
        else:
            # private send (as before)
            pkt = make_packet("send_file", {
                "from": self.current_username,
                "to": self.current_partner_username,
                "filename": os.path.basename(path),
                "data": b64,
                "file_type": file_type
            })

        try:
            self.sock.sendall(pkt)
        except:
            self.lbl_chat_status.setText("❌ Lỗi gửi file")

    def show_image_preview(self, image_path: str):
        dlg = QDialog(self)
        dlg.setWindowTitle("Xem ảnh")
        layout = QVBoxLayout(dlg)

        lbl = QLabel()
        pix = QPixmap(image_path)
        if not pix.isNull():
            # Scale theo kích thước màn hình cho đỡ to
            screen_geom = self.screen().availableGeometry()
            max_w = int(screen_geom.width() * 0.6)
            max_h = int(screen_geom.height() * 0.6)
            pix = pix.scaled(
                max_w, max_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            lbl.setPixmap(pix)
        else:
            lbl.setText("Không mở được ảnh này.")

        layout.addWidget(lbl)
        dlg.exec()
    def show_video_player(self, video_path: str):
        if not os.path.exists(video_path):
            QMessageBox.warning(self, "Lỗi", "Không tìm thấy file video.")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Xem video")
        dlg.resize(900, 520)

        layout = QVBoxLayout(dlg)

        # ----- Video Widget -----
        video_widget = QVideoWidget()
        layout.addWidget(video_widget)

        # ----- Player & Audio -----
        player = QMediaPlayer(dlg)
        audio = QAudioOutput(dlg)
        player.setAudioOutput(audio)
        player.setVideoOutput(video_widget)

        # ----- Controls (play/pause + slider) -----
        controls = QHBoxLayout()

        btn_play = QPushButton("⏯")
        btn_play.setFixedWidth(50)
        controls.addWidget(btn_play)

        slider = QSlider()
        slider.setOrientation(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        controls.addWidget(slider)

        layout.addLayout(controls)

        # ----- Load video -----
        player.setSource(QUrl.fromLocalFile(video_path))

        # ===== SIGNALS =====

        # Khi media đã ready, lấy duration
        def on_duration_changed(ms):
            if ms > 0:
                slider.setRange(0, ms)

        player.durationChanged.connect(on_duration_changed)

        # Cập nhật slider theo thời gian phát
        player.positionChanged.connect(lambda pos: slider.setValue(pos))

        # Kéo slider để tua video
        slider.sliderReleased.connect(lambda: player.setPosition(slider.value()))

        # Click nút play/pause
        def toggle_play():
            if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                player.pause()
            else:
                player.play()

        btn_play.clicked.connect(toggle_play)

        # Click lên video → toggle play/pause
        def mousePressEvent(event):
            toggle_play()
        video_widget.mousePressEvent = mousePressEvent

        # ----- Clean Up khi tắt popup -----
        def cleanup():
            try:
                player.stop()
                player.setSource(QUrl())   # Detach file
                player.deleteLater()
            except:
                pass

        dlg.finished.connect(cleanup)

        # Start
        player.play()
        dlg.show()

    def _save_file_from_server(self, src_path: str, suggested_name: str | None = None):
        """
        Cho phép user lưu file từ thư mục server/storage/... về nơi khác trên máy client.
        (Hiện tại server & client cùng máy nên chỉ là copy file.)
        """
        if not os.path.exists(src_path):
            QMessageBox.warning(self, "Lỗi", "File không tồn tại trên máy.")
            return

        if suggested_name is None:
            suggested_name = os.path.basename(src_path)

        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu file về máy",
            suggested_name
        )
        if not dest:
            return

        try:
            shutil.copyfile(src_path, dest)
            QMessageBox.information(self, "Thành công", "Đã lưu file.")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không lưu được file: {e}")

    def on_attachment_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        msg_type = data.get("msg_type")
        path = data.get("path")
        content = data.get("content") or ""

        if msg_type == "image" and path:
            self.show_image_preview(path)
        elif msg_type == "video" and path:
            self.show_video_player(path)
        elif msg_type == "file" and path:
            # gợi ý tên file chính là content
            self._save_file_from_server(path, suggested_name=os.path.basename(content))
        elif msg_type == "link" and content:
            self._open_link(content)


    def __init__(self):
        super().__init__()
        self.sock: socket.socket | None = None
        self.net_thread: NetworkThread | None = None

        self.current_username: str | None = None
        self.current_display_name: str | None = None
        self.current_partner_username: str | None = None
        self.conversations: list[dict[str, Any]] = []
        self.current_group_id: int | None = None
        self.current_group_is_owner: bool = False
        # cache avatar user: (username, size) -> QPixmap
        self._user_avatar_cache: dict[tuple[str, int], QPixmap] = {}
         # cache avatar tròn nhỏ cho từng username, dùng trong group chat
        self._avatar_cache: dict[str, QPixmap] = {}
        # Dựng UI
        setup_chatwindow_ui(self)
                # Ẩn nút tạo nhóm khi chưa đăng nhập
        if hasattr(self, "btn_create_group"):
            self.btn_create_group.setVisible(False)

        # Lưu avatar mặc định (từ assets/default_avatar.png)
        self.default_avatar_small = getattr(self, "avatar_small", None)
        self.default_avatar_large = getattr(self, "avatar_large", None)
        self.main_avatar_b64: str | None = None  # avatar của chính mình (base64, nếu có)

        # Kết nối server + nối signal
        self._connect_to_server()
        self._connect_signals()
        self._update_info_panel(None)

    # ---------- Avatar helpers ----------

    def _make_round_avatar(self, pix: QPixmap, size: int) -> QPixmap:
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

    def _set_current_user_avatar_from_b64(self, avatar_b64: str | None):
        """
        Cập nhật avatar của chính user hiện tại (trên header & dùng làm default).
        """
        self.main_avatar_b64 = avatar_b64 or None

        if avatar_b64:
            try:
                raw = base64.b64decode(avatar_b64)
                pix = QPixmap()
                if pix.loadFromData(raw) and not pix.isNull():
                    self.avatar_small = self._make_round_avatar(pix, 32)
                    self.avatar_large = self._make_round_avatar(pix, 80)
                else:
                    self.avatar_small = self.default_avatar_small
                    self.avatar_large = self.default_avatar_large
            except Exception:
                self.avatar_small = self.default_avatar_small
                self.avatar_large = self.default_avatar_large
        else:
            self.avatar_small = self.default_avatar_small
            self.avatar_large = self.default_avatar_large

        if getattr(self, "lbl_profile_avatar", None) and self.avatar_small:
            self.lbl_profile_avatar.setPixmap(self.avatar_small)

        # Cập nhật lại info panel (vì đang dùng avatar_large làm default)
        self._update_info_panel(self.current_partner_username)

    # ---------- UI signal wiring ----------

    def _connect_signals(self):
        # Auth + Chat signals (ensure each signal connected only once)
        # Auth
        self.btn_login.clicked.connect(self.on_login_clicked)
        self.btn_register.clicked.connect(self.on_register_clicked)
        self.btn_show_login.clicked.connect(lambda: self.auth_stack.setCurrentIndex(0))
        self.btn_show_register.clicked.connect(lambda: self.auth_stack.setCurrentIndex(1))

        # Chat UI buttons (connect once)
        self.btn_send.clicked.connect(self.on_send_clicked)
        self.le_message.returnPressed.connect(self.on_send_clicked)

        if hasattr(self, "btn_send_image"):
            self.btn_send_image.clicked.connect(self.on_send_image_clicked)
        if hasattr(self, "btn_send_file"):
            self.btn_send_file.clicked.connect(self.on_send_file_clicked)
        if hasattr(self, "btn_send_video"):
            self.btn_send_video.clicked.connect(self.on_send_video_clicked)

        if hasattr(self, "btn_create_group"):
            self.btn_create_group.clicked.connect(self.on_create_group_clicked)
        if hasattr(self, "btn_leave_group"):
            self.btn_leave_group.clicked.connect(self.on_leave_group_clicked)

        if hasattr(self, "lbl_partner_avatar") and hasattr(self.lbl_partner_avatar, "clicked"):
            self.lbl_partner_avatar.clicked.connect(self.on_change_group_avatar_clicked)

        # Sidebar
        self.sidebar.conversation_selected.connect(self.on_sidebar_conversation_selected)
        self.sidebar.search_text_changed.connect(self.on_sidebar_search_changed)
        if hasattr(self.sidebar, "user_add_to_group"):
            self.sidebar.user_add_to_group.connect(self.on_add_user_to_group)
        if hasattr(self.sidebar, "join_group_requested"):
            self.sidebar.join_group_requested.connect(self.on_join_group_requested)

        # Misc
        self.btn_logout.clicked.connect(self.on_logout_clicked)
        self.btn_broadcast.clicked.connect(self.on_broadcast_clicked)

        # Info panel buttons for attachments / delete
        if hasattr(self, "btn_delete_conversation"):
            self.btn_delete_conversation.clicked.connect(self.on_delete_conversation_clicked)
        if hasattr(self, "btn_media"):
            self.btn_media.clicked.connect(lambda: self.on_show_attachments("media"))
        if hasattr(self, "btn_files"):
            self.btn_files.clicked.connect(lambda: self.on_show_attachments("files"))
        if hasattr(self, "btn_links"):
            self.btn_links.clicked.connect(lambda: self.on_show_attachments("links"))

        # Chat list interactions
        self.chat_list.delete_requested.connect(self.on_delete_from_context)
        self.chat_list.attachment_open_requested.connect(self.on_chat_attachment_open)

        # Click avatar ở info panel -> đổi avatar nhóm (mousePress)
        if hasattr(self, "lbl_partner_avatar"):
            try:
                self.lbl_partner_avatar.mousePressEvent = self._on_group_avatar_clicked
            except Exception:
                pass

        # Click avatar profile để đổi
        if hasattr(self, "lbl_profile_avatar") and hasattr(self.lbl_profile_avatar, "clicked"):
            try:
                self.lbl_profile_avatar.clicked.connect(self.on_change_profile_avatar_clicked)
            except Exception:
                pass

        # Double-click attachments list
        if hasattr(self, "list_attachments"):
            try:
                self.list_attachments.itemDoubleClicked.connect(self.on_attachment_clicked)
            except Exception:
                pass

    # ...existing code...

    def on_login_clicked(self):
        if not getattr(self, "sock", None):
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText("❌ Chưa kết nối được server")
            return
        username = getattr(self, "le_login_username", None)
        password = getattr(self, "le_login_password", None)
        if username is None or password is None:
            return
        u = username.text().strip()
        p = password.text().strip()
        if not u or not p:
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText("⚠️ Nhập username và password")
            return
        pkt = make_packet("login", {"username": u, "password": p})
        try:
            self.sock.sendall(pkt)
        except OSError as e:
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText(f"❌ Lỗi gửi gói tin: {e}")

    def on_register_clicked(self):
        if not getattr(self, "sock", None):
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText("❌ Chưa kết nối được server")
            return
        uname_w = getattr(self, "le_reg_username", None)
        display_w = getattr(self, "le_reg_display", None)
        pw1_w = getattr(self, "le_reg_pw1", None)
        pw2_w = getattr(self, "le_reg_pw2", None)
        if not (uname_w and pw1_w and pw2_w):
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText("⚠️ Nhập đầy đủ thông tin đăng ký")
            return
        username = uname_w.text().strip()
        display_name = (display_w.text().strip() if display_w else username) or username
        pw1 = pw1_w.text().strip()
        pw2 = pw2_w.text().strip()
        if not username or not pw1 or not pw2:
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText("⚠️ Nhập đầy đủ thông tin đăng ký")
            return
        if pw1 != pw2:
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText("⚠️ Hai mật khẩu không trùng khớp")
            return
        pkt = make_packet("register", {
            "username": username,
            "password": pw1,
            "display_name": display_name
        })
        try:
            self.sock.sendall(pkt)
        except OSError as e:
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText(f"❌ Lỗi gửi gói tin: {e}")

    def on_send_clicked(self):
        if not self.current_username:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return
        content = getattr(self, "le_message", None)
        if content is None:
            return
        text = content.text().strip()
        if not text:
            return
        if self.current_group_id:
            pkt = make_packet("send_group_text", {
                "from": self.current_username,
                "conversation_id": self.current_group_id,
                "content": text,
            })
        else:
            pkt = make_packet("send_text", {
                "from": self.current_username,
                "to": self.current_partner_username,
                "content": text,
            })
        try:
            self.sock.sendall(pkt)
            content.clear()
        except OSError as e:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"❌ Lỗi gửi tin nhắn: {e}")

    def on_change_profile_avatar_clicked(self):
        """
        Đổi avatar profile: chọn file -> preview -> gửi server.
        """
        if not self.current_username:
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText("⚠️ Đăng nhập rồi mới đổi avatar")
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn ảnh đại diện",
            "",
            "Ảnh (*.png *.jpg *.jpeg *.gif)"
        )
        if not path:
            return

        try:
            with open(path, "rb") as f:
                raw = f.read()
        except Exception as e:
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText(f"❌ Không đọc được file: {e}")
            return

        pix = QPixmap()
        if not (pix.loadFromData(raw) and not pix.isNull()):
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText("❌ File không phải ảnh hợp lệ")
            return

        img_b64 = base64.b64encode(raw).decode("ascii")
        # Preview ngay
        self._set_current_user_avatar_from_b64(img_b64)

        if not getattr(self, "sock", None):
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText("❌ Chưa kết nối được server")
            return

        pkt = make_packet("update_avatar", {
            "username": self.current_username,
            "image_b64": img_b64,
        })
        try:
            self.sock.sendall(pkt)
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText("⏳ Đang cập nhật avatar...")
        except OSError as e:
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText(f"❌ Lỗi gửi avatar: {e}")

    def on_logout_clicked(self):
        if not self.current_username:
            return
        username = self.current_username
        pkt = make_packet("logout", {"username": username})
        try:
            self.sock.sendall(pkt)
        except Exception:
            pass

        # reset UI state minimally
        self.current_username = None
        self.current_display_name = None
        self.current_partner_username = None
        self.current_group_id = None
        self.chat_list.clear()
        if hasattr(self.sidebar, "set_conversations"):
            self.sidebar.set_conversations([])
        if hasattr(self.sidebar, "set_search_results"):
            self.sidebar.set_search_results([])
        if hasattr(self, "le_to_user"):
            self.le_to_user.clear()
        if getattr(self, "lbl_user_info", None):
            self.lbl_user_info.setText("Chưa đăng nhập")
        if getattr(self, "lbl_chat_status", None):
            self.lbl_chat_status.setText("Đã đăng xuất")
        self._set_current_user_avatar_from_b64(None)
        self._update_info_panel(None)
        if hasattr(self, "main_stack") and hasattr(self, "login_panel"):
            self.main_stack.setCurrentWidget(self.login_panel)
        if hasattr(self, "btn_create_group"):
            self.btn_create_group.setVisible(False)

    def on_broadcast_clicked(self):
        if not self.current_username:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return
        pkt = make_packet("broadcast", {"message": "Thông báo từ server (test)!"})
        try:
            self.sock.sendall(pkt)
        except OSError as e:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"❌ Lỗi gửi broadcast: {e}")

    def on_delete_from_context(self, message_id: int):
        if not self.current_username:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return
        partner = self.current_partner_username or (getattr(self, "le_to_user", None) and self.le_to_user.text().strip())
        if not partner:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⚠️ Hãy mở một cuộc chat trước")
            return
        pkt = make_packet("delete_message", {
            "by": self.current_username,
            "partner": partner,
            "message_id": message_id
        })
        try:
            self.sock.sendall(pkt)
        except OSError as e:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"❌ Lỗi gửi yêu cầu xóa: {e}")

    def on_delete_conversation_clicked(self):
        # group deletion or private conversation deletion
        if self.current_group_id:
            if not self.current_group_is_owner:
                QMessageBox.information(self, "Thông báo", "Chỉ chủ nhóm mới có quyền xóa nhóm. Thành viên có thể rời nhóm.")
                return
            ans = QMessageBox.question(
                self,
                "Xóa nhóm",
                "Bạn có chắc muốn xóa hoàn toàn nhóm này? Hành động này không thể hoàn tác.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
            pkt = make_packet("delete_group", {
                "conversation_id": self.current_group_id,
                "by": self.current_username,
            })
            try:
                self.sock.sendall(pkt)
                if getattr(self, "lbl_chat_status", None):
                    self.lbl_chat_status.setText("⏳ Đang xóa nhóm...")
            except OSError as e:
                if getattr(self, "lbl_chat_status", None):
                    self.lbl_chat_status.setText(f"❌ Lỗi gửi yêu cầu xóa nhóm: {e}")
            return

        # private conversation delete
        if not self.current_username:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return
        partner = self.current_partner_username
        if not partner:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⚠️ Chưa chọn đoạn chat để xóa")
            return
        ans = QMessageBox.question(
            self,
            "Xóa đoạn chat",
            f"Bạn có chắc muốn xóa toàn bộ tin nhắn với {partner}?\nHành động này sẽ xóa lịch sử cho cả hai bên.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        pkt = make_packet("delete_conversation", {
            "by": self.current_username,
            "partner": partner,
        })
        try:
            self.sock.sendall(pkt)
        except OSError as e:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"❌ Lỗi gửi yêu cầu xóa đoạn chat: {e}")

    def on_change_group_avatar_clicked(self):
        """
        Wrapper for clicked signal (no event) to change group avatar.
        """
        # reuse logic from _on_group_avatar_clicked but without event
        if not self.current_group_id:
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn ảnh nhóm",
            "",
            "Ảnh (*.png *.jpg *.jpeg *.gif)"
        )
        if not path:
            return
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except Exception:
            QMessageBox.warning(self, "Lỗi", "Không đọc được file ảnh.")
            return

        pix = QPixmap()
        if not (pix.loadFromData(raw) and not pix.isNull()):
            QMessageBox.warning(self, "Lỗi", "File không phải ảnh hợp lệ.")
            return

        img_b64 = base64.b64encode(raw).decode("ascii")
        avatar_pix = self._make_round_avatar(pix, 80)
        if hasattr(self, "lbl_partner_avatar"):
            self.lbl_partner_avatar.setPixmap(avatar_pix)

        if not getattr(self, "sock", None):
            QMessageBox.warning(self, "Lỗi", "Mất kết nối server.")
            return

        pkt = make_packet("update_group_avatar", {
            "conversation_id": self.current_group_id,
            "username": self.current_username,
            "image_b64": img_b64,
        })
        try:
            self.sock.sendall(pkt)
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⏳ Đang cập nhật avatar nhóm...")
        except Exception as e:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"❌ Lỗi gửi avatar nhóm: {e}")

    def on_sidebar_conversation_selected(self, key: str):
        key = (key or "").strip()
        if not key:
            return

        if key.startswith("user:"):
            username = key.split(":", 1)[1]
            self.current_partner_username = username
            self.current_group_id = None
            if hasattr(self, "le_to_user"):
                self.le_to_user.setText(username)
            if hasattr(self.sidebar, "set_active_username"):
                self.sidebar.set_active_username(username)
            self._update_info_panel(username)
            # request history 1-1
            pkt = make_packet("load_history", {"from": self.current_username, "to": username})
            try:
                self.sock.sendall(pkt)
            except OSError:
                pass

        elif key.startswith("group:"):
            conv_id = int(key.split(":", 1)[1])
            self.current_partner_username = None
            self.current_group_id = conv_id
            if hasattr(self, "le_to_user"):
                self.le_to_user.setText(f"[Group] {conv_id}")
            self._update_group_info_panel(conv_id)
            # request group history
            self.request_group_history(conv_id)

    def on_sidebar_search_changed(self, text: str):
        text = (text or "").strip()
        if not text:
            if hasattr(self.sidebar, "set_search_results"):
                self.sidebar.set_search_results([])
            return
        if not (getattr(self, "sock", None) and self.current_username):
            return
        pkt = make_packet("search_users", {
            "query": text,
            "exclude_username": self.current_username
        })
        try:
            self.sock.sendall(pkt)
        except OSError:
            pass

    def request_conversations(self):
        if not (getattr(self, "sock", None) and self.current_username):
            return
        pkt = make_packet("list_conversations", {"username": self.current_username})
        try:
            self.sock.sendall(pkt)
        except OSError:
            pass

    def request_group_history(self, conv_id: int):
        if not (getattr(self, "sock", None) and self.current_username):
            return
        pkt = make_packet("load_group_history", {
            "conversation_id": conv_id,
            "username": self.current_username,
        })
        try:
            self.sock.sendall(pkt)
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"⏳ Đang tải lịch sử nhóm #{conv_id}...")
        except OSError as e:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"❌ Lỗi yêu cầu lịch sử nhóm: {e}")

    def on_server_message(self, msg: dict):
        action = msg.get("action")
        data = msg.get("data") or {}

        if action == "register_result":
            if data.get("ok"):
                self.lbl_auth_status.setText("✅ Đăng ký thành công, chuyển sang đăng nhập")
                self.auth_stack.setCurrentIndex(0)
            else:
                self.lbl_auth_status.setText(f"❌ Đăng ký thất bại: {data.get('error')}")
        elif action == "incoming_image":
            from_user = data.get("from")
            filename = data.get("filename")
            msg_id = data.get("message_id")

            img_path = Path(__file__).resolve().parents[1] / "server" / "uploads" / filename
            self.chat_list.add_image_bubble(
                msg_id,
                from_user,
                self.current_username,   
                str(img_path)
            )
        elif action == "update_group_avatar_result":
            if data.get("ok"):
                conv_id = int(data.get("conversation_id") or 0)
                avatar_b64 = data.get("avatar_b64")

                # cập nhật vào list conversations
                for it in self.conversations or []:
                    if it.get("is_group") and it.get("conversation_id") == conv_id:
                        it["avatar_b64"] = avatar_b64
                        break

                self._update_group_info_panel(conv_id)
                self.request_conversations()
                self.lbl_chat_status.setText("✅ Đã cập nhật avatar nhóm")
            else:
                self.lbl_chat_status.setText(
                    "❌ Đổi avatar nhóm thất bại: " + str(data.get("error"))
                )

        elif action == "group_avatar_changed":
            conv_id = data.get("conversation_id")
            avatar_b64 = data.get("avatar_b64")

            for conv in self.conversations:
                if conv.get("conversation_id") == conv_id:
                    conv["avatar_b64"] = avatar_b64

            if self.current_group_id == conv_id:
                self._update_group_info_panel(conv_id)

            self.request_conversations()
            self.lbl_chat_status.setText("📸 Ảnh nhóm đã được cập nhật")

        elif action == "add_group_member_result":
            if data.get("ok"):
                uname = data.get("username")
                self.lbl_chat_status.setText(f"✅ Đã thêm {uname} vào nhóm.")
                self.request_conversations()
            else:
                self.lbl_chat_status.setText(
                    "❌ Thêm thành viên thất bại: " + str(data.get("error"))
                )

        elif action == "leave_group_result":
            if data.get("ok"):
                conv_id = int(data.get("conversation_id") or 0)
                if self.current_group_id == conv_id:
                    self.current_group_id = None
                    self.chat_list.clear()
                    self.le_to_user.clear()
                    self.current_group_id = None
                    self.current_group_is_owner = False
                    self._update_group_buttons_state()

                    self._update_info_panel(None)
                self.lbl_chat_status.setText("✅ Đã rời nhóm.")
                self.request_conversations()
            else:
                self.lbl_chat_status.setText(
                    "❌ Không rời được nhóm: " + str(data.get("error"))
                )

        elif action == "join_group_result":
            if data.get("ok"):
                conv_id = int(data.get("conversation_id") or 0)
                gname = data.get("group_name") or f"#{conv_id}"
                self.lbl_chat_status.setText(f"✅ Đã tham gia nhóm '{gname}'.")
                self.request_conversations()
            else:
                self.lbl_chat_status.setText(
                    "❌ Tham gia nhóm thất bại: " + str(data.get("error"))
                )
        elif action in ("group_created", "create_group_result"):
            if data.get("ok"):
                conv_id = int(data.get("conversation_id") or 0)
                gname = data.get("group_name") or f"Nhóm #{conv_id}"
                self.lbl_chat_status.setText(f"✅ Nhóm '{gname}' đã được tạo/cập nhật.")
                # reload lại sidebar để nhóm hiện ngay
                self.request_conversations()
            else:
                self.lbl_chat_status.setText(
                    "❌ Tạo nhóm thất bại: " + str(data.get("error"))
                )

        elif action == "incoming_group_text":
            conv_id = int(data.get("conversation_id") or 0)
            from_user = data.get("from")
            content = data.get("content")
            msg_id = data.get("message_id")

            if self.current_group_id == conv_id:
                avatar_pix = None
                if from_user != self.current_username:
                    avatar_pix = self._get_user_avatar_pixmap(from_user, 28)

                self.chat_list.add_bubble(
                    msg_id,
                    from_user,
                    self.current_username,
                    content,
                    True,
                    avatar_pix,
                )

            # cập nhật sidebar
            self.request_conversations()


        elif action == "send_group_text_result":
            if data.get("ok"):
                conv_id = int(data.get("conversation_id") or 0)
                content = data.get("content")
                mid = data.get("message_id")
                if self.current_group_id == conv_id:
                    self.chat_list.add_bubble(
                        mid,
                        self.current_username,
                        self.current_username,
                        content,
                        True,
                        None,   # tin của mình, không cần avatar bên trái
                    )

                self.request_conversations()

            else:
                self.lbl_chat_status.setText(
                    "❌ Gửi tin nhắn nhóm thất bại: " + str(data.get("error"))
                )

        elif action == "send_group_image_result":
            if data.get("ok"):
                conv_id = int(data.get("conversation_id") or 0)
                filename = data.get("filename") or ""
                mid = data.get("message_id")
                if self.current_group_id == conv_id and filename:
                    base_dir = Path(__file__).resolve().parents[1]
                    img_path = base_dir / "server" / "storage" / "images" / filename
                    self.chat_list.add_image_bubble(
                        mid,
                        self.current_username,
                        self.current_username,
                        str(img_path),
                        True,
                        None,
                    )
                self.request_conversations()
            else:
                self.lbl_chat_status.setText(
                    "❌ Gửi ảnh nhóm thất bại: " + str(data.get("error"))
                )

        elif action == "send_group_file_result":
            if data.get("ok"):
                conv_id = int(data.get("conversation_id") or 0)
                filename = data.get("filename") or ""
                file_type = (data.get("file_type") or "file").lower()
                mid = data.get("message_id")
                if self.current_group_id == conv_id and filename:
                    base_dir = Path(__file__).resolve().parents[1]
                    storage = Path("files")
                    add_fn = self.chat_list.add_file_bubble
                    if file_type == "video":
                        storage = Path("videos")
                        add_fn = self.chat_list.add_video_bubble
                    elif file_type == "image":
                        storage = Path("images")
                        add_fn = self.chat_list.add_image_bubble
                    full_path = base_dir / "server" / "storage" / storage / filename
                    add_fn(
                        mid,
                        self.current_username,
                        self.current_username,
                        str(full_path),
                        True,
                        None,
                    )
                self.request_conversations()
            else:
                self.lbl_chat_status.setText(
                    "❌ Gửi file nhóm thất bại: " + str(data.get("error"))
                )

        elif action == "group_history_result":
            if not data.get("ok"):
                self.lbl_chat_status.setText(
                    "❌ Lỗi tải lịch sử nhóm: " + str(data.get("error"))
                )
                return

            conv_id = int(data.get("conversation_id") or 0)
            msgs = data.get("messages", [])

            self.current_group_id = conv_id
            self.current_partner_username = None
            self.current_group_is_owner = bool(data.get("is_owner", False))
            self.chat_list.clear()

            base_dir = Path(__file__).resolve().parents[1]
            images_dir = base_dir / "server" / "storage" / "images"
            videos_dir = base_dir / "server" / "storage" / "videos"
            files_dir  = base_dir / "server" / "storage" / "files"

            for m in msgs:
                mid = m.get("id")
                sender = m.get("sender_username")
                msg_type = (m.get("msg_type") or "text").lower()
                content = m.get("content") or ""

                avatar_pix = None
                if sender != self.current_username:
                    avatar_pix = self._get_user_avatar_pixmap(sender, 28)

                if msg_type == "image":
                    img_path = images_dir / content
                    self.chat_list.add_image_bubble(
                        mid, sender, self.current_username, str(img_path),
                        True, avatar_pix,
                    )
                elif msg_type == "video":
                    vpath = videos_dir / content
                    self.chat_list.add_video_bubble(
                        mid, sender, self.current_username, str(vpath),
                        True, avatar_pix,
                    )
                elif msg_type == "file":
                    fpath = files_dir / content
                    self.chat_list.add_file_bubble(
                        mid, sender, self.current_username, str(fpath),
                        True, avatar_pix,
                    )
                else:
                    self.chat_list.add_bubble(
                        mid, sender, self.current_username, content,
                        True, avatar_pix,
                    )

            self._update_group_info_panel(conv_id)
            self._update_group_buttons_state()
            self.lbl_chat_status.setText(f"✅ Đã tải {len(msgs)} tin nhắn trong nhóm #{conv_id}")

        elif action == "login_result":
            if data.get("ok"):
                self.current_username = self.le_login_username.text().strip()
                self.current_display_name = data.get("display_name")
                self.lbl_auth_status.setText("✅ Đăng nhập thành công")
                self.lbl_user_info.setText(
                    f"{self.current_display_name} ({self.current_username})"
                )
                self.main_stack.setCurrentWidget(self.chat_panel)
                self.lbl_chat_status.setText("")
                self.current_partner_username = None

                # Avatar của chính mình (base64 trong DB)
                avatar_b64 = data.get("avatar_b64")
                self._set_current_user_avatar_from_b64(avatar_b64)

                self._update_info_panel(None)
                self.request_conversations()

                # 👇 hiện nút tạo nhóm sau khi login
                if hasattr(self, "btn_create_group"):
                    self.btn_create_group.setVisible(True)
            else:
                self.lbl_auth_status.setText(
                    f"❌ Đăng nhập thất bại: {data.get('error')}"
                )


        elif action == "incoming_text":
            from_user = data.get("from")
            content = data.get("content")
            msg_id = data.get("message_id")
            # Nếu đang mở đúng đoạn chat đó thì add bubble luôn
            if self.le_to_user.text().strip() == from_user:
                self.chat_list.add_bubble(
                    msg_id, from_user, self.current_username, content
                )
            # Cập nhật lại sidebar (đẩy đoạn chat lên trên)
            self.request_conversations()
        

        elif action == "server_broadcast":
            msg_text = data.get("message")
            self.lbl_chat_status.setText(f"[SERVER]: {msg_text}")

        elif action == "send_text_result":
            if data.get("ok"):
                mid = data.get("message_id")
                to_user = data.get("to")
                content = data.get("content")
                if self.le_to_user.text().strip() == to_user:
                    self.chat_list.add_bubble(
                        mid, self.current_username, self.current_username, content
                    )
                self.request_conversations()
            else:
                self.lbl_chat_status.setText("❌ Gửi thất bại: " + str(data.get("error")))

        elif action == "history_result":
            if not data.get("ok"):
                self.lbl_chat_status.setText("❌ Lỗi tải lịch sử: " + str(data.get("error")))
                return

            msgs = data.get("messages", [])
            partner = data.get("with")

            self.current_partner_username = partner
            self.le_to_user.setText(partner or "")
            if partner and hasattr(self.sidebar, "set_active_username"):
                self.sidebar.set_active_username(partner)
            self._update_info_panel(partner)

            self.chat_list.clear()
            base_dir = Path(__file__).resolve().parents[1]
            images_dir = base_dir / "server" / "storage" / "images"
            videos_dir = base_dir / "server" / "storage" / "videos"
            files_dir  = base_dir / "server" / "storage" / "files"

            for m in msgs:
                mid = m.get("id")
                sender = m.get("sender_username")
                msg_type = (m.get("msg_type") or "text").lower()
                content = m.get("content") or ""

                if msg_type == "image":
                    img_path = images_dir / content
                    self.chat_list.add_image_bubble(
                        mid,
                        sender,
                        self.current_username,
                        str(img_path),
                    )
                elif msg_type == "video":
                    vpath = videos_dir / content
                    self.chat_list.add_video_bubble(
                        mid,
                        sender,
                        self.current_username,
                        str(vpath),
                    )
                elif msg_type == "file":
                    fpath = files_dir / content
                    self.chat_list.add_file_bubble(
                        mid,
                        sender,
                        self.current_username,
                        str(fpath),
                    )
                else:
                    # text bình thường
                    self.chat_list.add_bubble(
                        mid,
                        sender,
                        self.current_username,
                        content,
                    )

            self.lbl_chat_status.setText(f"✅ Đã tải {len(msgs)} tin nhắn với {partner}")
            self.request_conversations()

        elif action == "delete_result":
            if data.get("ok"):
                mid = data.get("message_id")
                self.lbl_chat_status.setText(f"✅ Đã gỡ tin nhắn #{mid}")
                to_user = self.le_to_user.text().strip()
                if to_user and self.current_username:
                    pkt = make_packet("load_history", {
                        "from": self.current_username,
                        "to": to_user
                    })
                    try:
                        self.sock.sendall(pkt)
                    except OSError:
                        pass
                self.request_conversations()
            else:
                self.lbl_chat_status.setText("❌ Gỡ thất bại: " + str(data.get("error")))

        elif action == "conversations_result":
            if not data.get("ok"):
                self.lbl_chat_status.setText("❌ Không lấy được danh sách đoạn chat")
                return

            self.conversations = data.get("items", []) or []
            self._user_avatar_cache.clear()
            if hasattr(self.sidebar, "set_conversations"):
                self.sidebar.set_conversations(self.conversations)

            # Đang mở group -> update info panel nhóm
            if self.current_group_id:
                self._update_group_info_panel(self.current_group_id)
            else:
                # Đang chat 1-1 -> info panel user như cũ
                self._update_info_panel(self.current_partner_username)

        elif action == "search_users_result":
            if data.get("ok"):
                items = data.get("items", []) or []
                if hasattr(self.sidebar, "set_search_results"):
                    self.sidebar.set_search_results(items)
            # nếu fail thì bỏ qua, không cần báo lỗi

        elif action == "attachments_result":
            self._handle_attachments_result(data)
            if data.get("ok"):
                kind = (data.get("filter") or "").lower()
                kind_label = {
                    "media": "ảnh / video",
                    "files": "file",
                    "links": "link",
                }.get(kind, "dữ liệu")
                if data.get("items"):
                    self.lbl_chat_status.setText(f"✅ Đã tải danh sách {kind_label}.")
                else:
                    self.lbl_chat_status.setText(f"ℹ️ Chưa có {kind_label} nào được gửi.")
            else:
                self.lbl_chat_status.setText(
                    "❌ Lỗi tải danh sách tệp tin: " + str(data.get("error"))
                )

        elif action == "delete_conversation_result":
            if data.get("ok"):
                partner = data.get("partner")
                # Nếu đang mở đoạn chat vừa xóa -> clear màn hình
                if partner and self.current_partner_username == partner:
                    self.current_partner_username = None
                    self.le_to_user.clear()
                    self.chat_list.clear()
                    self._update_info_panel(None)
                self.lbl_chat_status.setText("✅ Đã xóa đoạn chat.")
                self.request_conversations()
            else:
                self.lbl_chat_status.setText(
                    "❌ Xóa đoạn chat thất bại: " + str(data.get("error"))
                )

        elif action == "update_avatar_result":
            if data.get("ok"):
                avatar_b64 = data.get("avatar_b64")
                self._set_current_user_avatar_from_b64(avatar_b64)
                self.lbl_auth_status.setText("✅ Cập nhật avatar thành công")
            else:
                self.lbl_auth_status.setText(
                    "❌ Cập nhật avatar thất bại: " + str(data.get("error"))
                )

        elif action == "avatar_changed":
            # Khi bất kỳ user nào đổi avatar
            uname = data.get("username")
            avatar_b64 = data.get("avatar_b64")
            if not uname:
                return

            # Cập nhật trong danh sách conversation
            for conv in self.conversations:
                if conv.get("partner_username") == uname:
                    conv["avatar_b64"] = avatar_b64

            # Nếu chính mình
            if uname == self.current_username:
                self._set_current_user_avatar_from_b64(avatar_b64)

            # Nếu đang mở đoạn chat với user đó
            if self.current_partner_username == uname:
                self._update_info_panel(uname)

        elif action == "delete_group_result":
            if data.get("ok"):
                conv_id = int(data.get("conversation_id") or 0)
                # Nếu đang mở đúng group -> clear UI
                if self.current_group_id == conv_id:
                    self.current_group_id = None
                    self.chat_list.clear()
                    self.le_to_user.clear()
                    self.current_group_is_owner = False
                    self._update_group_buttons_state()
                    self._update_info_panel(None)
                self.lbl_chat_status.setText("✅ Đã xóa nhóm.")
                self.request_conversations()
            else:
                self.lbl_chat_status.setText("❌ Xóa nhóm thất bại: " + str(data.get("error")))

        elif action == "group_deleted":
            # Thông báo này do server broadcast tới thành viên để họ cập nhật sidebar/UI
            conv_id = int(data.get("conversation_id") or 0)
            # Nếu đang mở đúng group -> clear
            if self.current_group_id == conv_id:
                self.current_group_id = None
                self.chat_list.clear()
                self.le_to_user.clear()
                self.current_group_is_owner = False
                self._update_group_buttons_state()
                self._update_info_panel(None)
            # Yêu cầu load lại danh sách conversation để sidebar cập nhật
            self.request_conversations()
            self.lbl_chat_status.setText("⚠️ Một nhóm đã bị xóa, sidebar đã được cập nhật.")

    # ---------- UTILS ----------

    def _update_info_panel(self, partner_username: str | None):
        """
        Cập nhật panel bên phải: avatar, tên, @username của người đang chat.
        Dùng cho chat 1-1, không phải group.
        """
        self.current_group_is_owner = False  # reset về false khi không ở group

        # Nút cho 1-1: có "Xóa đoạn chat", không có "Rời nhóm"
        if hasattr(self, "btn_leave_group"):
            self.btn_leave_group.setVisible(False)
        if hasattr(self, "btn_delete_conversation"):
            self.btn_delete_conversation.setVisible(True)
            self.btn_delete_conversation.setText("Xóa đoạn chat")

        if not partner_username:
            self.lbl_partner_name.setText("Chưa chọn đoạn chat")
            self.lbl_partner_username.setText("")
            avatar = self.default_avatar_large or self.avatar_large
            if avatar and not avatar.isNull():
                self.lbl_partner_avatar.setPixmap(avatar)
            return


        display = partner_username
        avatar_b64: str | None = None

        for conv in self.conversations:
            if conv.get("partner_username") == partner_username:
                display = conv.get("partner_display_name") or partner_username
                avatar_b64 = conv.get("avatar_b64") or conv.get("partner_avatar_url")
                break

        self.lbl_partner_name.setText(display)
        self.lbl_partner_username.setText(f"@{partner_username}")

        avatar_pix: QPixmap | None = None
        if avatar_b64:
            try:
                raw = base64.b64decode(avatar_b64)
                pix = QPixmap()
                if pix.loadFromData(raw) and not pix.isNull():
                    avatar_pix = self._make_round_avatar(pix, 80)
            except Exception:
                avatar_pix = None

        if avatar_pix is None:
            avatar_pix = self.default_avatar_large or self.avatar_large

        if avatar_pix and not avatar_pix.isNull():
            self.lbl_partner_avatar.setPixmap(avatar_pix)

    def _update_group_info_panel(self, conv_id: int):
        """
        Cập nhật info panel cho group: tên, avatar, hiển thị nút phù hợp.
        """
        # tìm conversation trong cache
        conv = None
        for it in (self.conversations or []):
            if it.get("is_group") and int(it.get("conversation_id") or 0) == int(conv_id):
                conv = it
                break

        # Tên nhóm
        gname = f"Nhóm #{conv_id}"
        if conv:
            title = (conv.get("title") or "").strip()
            # nếu server trả "[Group] Name" thì loại bỏ prefix
            if title.startswith("[Group]"):
                gname = title[len("[Group]"):].strip()
            elif title:
                gname = title

        if hasattr(self, "lbl_partner_name"):
            self.lbl_partner_name.setText(gname)
        if hasattr(self, "lbl_partner_username"):
            self.lbl_partner_username.setText(f"#{conv_id}")

        # Avatar nhóm
        avatar_b64 = None
        if conv:
            avatar_b64 = conv.get("avatar_b64") or conv.get("group_avatar") or None

        avatar_pix = None
        if avatar_b64:
            try:
                raw = base64.b64decode(avatar_b64)
                pix = QPixmap()
                if pix.loadFromData(raw) and not pix.isNull():
                    avatar_pix = self._make_round_avatar(pix, 80)
            except Exception:
                avatar_pix = None

        if avatar_pix is None:
            avatar_pix = self.default_avatar_large or self.avatar_large

        if avatar_pix and not avatar_pix.isNull() and hasattr(self, "lbl_partner_avatar"):
            self.lbl_partner_avatar.setPixmap(avatar_pix)

        # Hiển thị nút: rời nhóm luôn có, xóa nhóm tùy owner (server sẽ kiểm tra quyền)
        if hasattr(self, "btn_leave_group"):
            self.btn_leave_group.setVisible(True)
        if hasattr(self, "btn_delete_conversation"):
            self.btn_delete_conversation.setVisible(True)
            self.btn_delete_conversation.setText("Xóa nhóm")

        # cập nhật trạng thái nút theo cờ current_group_is_owner
        self._update_group_buttons_state()

    def _update_group_buttons_state(self):
        """
        Hiển thị/ẩn các nút trong info panel dựa vào self.current_group_id / self.current_group_is_owner.
        """
        is_group_open = bool(getattr(self, "current_group_id", None))
        is_owner = bool(getattr(self, "current_group_is_owner", False))

        if hasattr(self, "btn_leave_group"):
            self.btn_leave_group.setVisible(is_group_open)
        if hasattr(self, "btn_delete_conversation"):
            # nếu đang mở group, đổi text thành 'Xóa nhóm'
            if is_group_open:
                self.btn_delete_conversation.setVisible(True)
                self.btn_delete_conversation.setText("Xóa nhóm" if is_owner else "Xóa nhóm")
            else:
                # 1-1: hiện nút xóa đoạn chat
                self.btn_delete_conversation.setVisible(True)
                self.btn_delete_conversation.setText("Xóa đoạn chat")

    def _prefill_attachments_from_chat(self, kind: str) -> int:
        if not hasattr(self, "chat_list") or not hasattr(self, "list_attachments"):
            return 0
        kind = (kind or "").lower()
        entries = []
        if kind == "links":
            for idx in range(self.chat_list.count() - 1, -1, -1):
                item = self.chat_list.item(idx)
                if not item:
                    continue
                data = item.data(Qt.ItemDataRole.UserRole) or {}
                text = data.get("content") or ""
                url = self._extract_first_url(text)
                if not url:
                    continue
                entries.append({
                    "id": data.get("id"),
                    "msg_type": "link",
                    "content": url,
                    "path": None,
                })
                if len(entries) >= 20:
                    break
        else:
            allowed_map = {"media": {"image", "video"}, "files": {"file"}}
            allowed = allowed_map.get(kind)
            if not allowed:
                return 0
            for idx in range(self.chat_list.count() - 1, -1, -1):
                item = self.chat_list.item(idx)
                if not item:
                    continue
                data = item.data(Qt.ItemDataRole.UserRole) or {}
                msg_kind = (data.get("kind") or "").lower()
                if msg_kind not in allowed:
                    continue
                path = data.get("path") or ""
                entries.append({
                    "id": data.get("id"),
                    "msg_type": msg_kind,
                    "content": os.path.basename(path) or msg_kind.upper(),
                    "path": path,
                })
                if len(entries) >= 20:
                    break

        if not entries:
            return 0

        self.list_attachments.clear()
        for entry in reversed(entries):
            prefix = "🔗"
            if entry["msg_type"] == "image":
                prefix = "🖼"
            elif entry["msg_type"] == "video":
                prefix = "🎬"
            elif entry["msg_type"] == "file":
                prefix = "📎"
            line = f"{prefix} [Hiện tại] #{entry['id'] or '?'}: {entry['content']}"
            item = QListWidgetItem(line)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list_attachments.addItem(item)
        self.list_attachments.setVisible(True)
        self.list_attachments.scrollToTop()
        return len(entries)

    def _extract_first_url(self, text: str) -> str | None:
        if not text:
            return None
        match = re.search(r"(https?://\S+)", text)
        return match.group(1).rstrip(").,") if match else None

    def _open_link(self, url: str):
        if not url:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⚠️ Link không hợp lệ")
            return
        if not url.startswith(("http://", "https://")):
            url = "http://" + url
        if not QDesktopServices.openUrl(QUrl(url)):
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("❌ Không mở được liên kết")

    def _get_user_avatar_pixmap(self, username: str, size: int) -> QPixmap | None:
        """
        Lấy QPixmap avatar tròn cho username với kích thước size.
        Tìm trong cache conversations -> decode base64 -> cache.
        """
        if not username:
            return None
        key = (username, int(size))
        if key in getattr(self, "_user_avatar_cache", {}):
            return self._user_avatar_cache[key]

        # tìm avatar trong conversations list (partner_avatar_url / avatar_b64)
        b64 = None
        for conv in (self.conversations or []):
            if conv.get("partner_username") == username:
                b64 = conv.get("avatar_b64") or conv.get("partner_avatar_url")
                break

        if b64:
            try:
                raw = base64.b64decode(b64)
                pix = QPixmap()
                if pix.loadFromData(raw) and not pix.isNull():
                    avatar = self._make_round_avatar(pix, size)
                    self._user_avatar_cache[key] = avatar
                    return avatar
            except Exception:
                pass

        # fallback: dùng default avatar đã load
        fallback = self.default_avatar_small or self.avatar_small or QPixmap()
        avatar = self._make_round_avatar(fallback, size) if not fallback.isNull() else QPixmap()
        self._user_avatar_cache[key] = avatar
        return avatar

    def _on_group_avatar_clicked(self, event):
        """
        Mouse click lên avatar nhóm → gọi handler thay đổi avatar nhóm.
        Đặt method này làm lbl_partner_avatar.mousePressEvent.
        """
        try:
            if event and hasattr(event, "button") and event.button() == Qt.MouseButton.LeftButton:
                self.on_change_group_avatar_clicked()
        except Exception:
            # im lặng nếu lỗi
            pass

    def on_show_attachments(self, kind: str):
        """
        kind: 'media' | 'files' | 'links'
        Gửi yêu cầu server trả danh sách tin nhắn loại đó
        giữa current_user và current_partner.
        """
        if not self.current_username:
            self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return

        partner = self.current_partner_username or self.le_to_user.text().strip()
        if not self.current_group_id and not partner:
            self.lbl_chat_status.setText("⚠️ Chưa chọn đoạn chat")
            return

        prefilled = self._prefill_attachments_from_chat(kind)
        if not prefilled and hasattr(self, "list_attachments"):
            self.list_attachments.clear()
            self.list_attachments.addItem("⏳ Đang lấy dữ liệu từ server...")
            self.list_attachments.setVisible(True)
            self.list_attachments.scrollToTop()

        target_label = f"nhóm #{self.current_group_id}" if self.current_group_id else partner
        kind_label = {
            "media": "ảnh / video",
            "files": "tệp",
            "links": "liên kết",
        }.get(kind, "dữ liệu")

        if not self.sock:
            if prefilled:
                self.lbl_chat_status.setText("⚠️ Mất kết nối server – đang hiển thị dữ liệu hiện có.")
            else:
                self.lbl_chat_status.setText("⚠️ Mất kết nối server")
            return

        if prefilled:
            self.lbl_chat_status.setText(
                f"🔎 Đã hiển thị tạm {prefilled} mục, tiếp tục đồng bộ {kind_label} từ {target_label}..."
            )
        else:
            self.lbl_chat_status.setText(f"⏳ Đang lấy {kind_label} từ {target_label}...")

        if self.current_group_id:
            pkt = make_packet("list_attachments", {
                "username": self.current_username,
                "conversation_id": self.current_group_id,
                "filter": kind,
            })
        else:
            pkt = make_packet("list_attachments", {
                "username": self.current_username,
                "partner": partner,
                "filter": kind,
            })
        try:
            self.sock.sendall(pkt)
        except OSError as e:
            self.lbl_chat_status.setText(f"❌ Lỗi gửi yêu cầu: {e}")

    def on_send_image_clicked(self):
        if not self.current_username:
            self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return

        # allow group or private
        partner = self.current_partner_username
        if not partner and not self.current_group_id:
            self.lbl_chat_status.setText("⚠️ Hãy chọn người hoặc nhóm để gửi ảnh")
            return

        filepath, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn ảnh gửi",
            "",
            "Ảnh (*.png *.jpg *.jpeg *.gif)"
        )
        if not filepath:
            return

        try:
            with open(filepath, "rb") as f:
                raw = f.read()
        except Exception as e:
            self.lbl_chat_status.setText(f"❌ Không đọc được ảnh: {e}")
            return

        b64 = base64.b64encode(raw).decode("ascii")

        if self.current_group_id:
            pkt = make_packet("send_group_image", {
                "from": self.current_username,
                "conversation_id": self.current_group_id,
                "filename": os.path.basename(filepath),
                "data": b64
            })
        else:
            pkt = make_packet("send_image", {      # private as before
                "from": self.current_username,
                "to": partner,
                "filename": os.path.basename(filepath),
                "data": b64
            })

        try:
            self.sock.sendall(pkt)
        except Exception as e:
            self.lbl_chat_status.setText(f"❌ Lỗi gửi ảnh: {e}")

    def on_send_file_clicked(self):
        """
        Bấm nút 📎 -> chọn file bất kỳ và gửi.
        Hỗ trợ cả 1-1 và group.
        """
        if not getattr(self, "current_username", None):
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return

        # allow sending to group or private
        if not getattr(self, "current_partner_username", None) and not getattr(self, "current_group_id", None):
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⚠️ Hãy chọn người hoặc nhóm để gửi file")
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file gửi",
            ""
        )
        if not path:
            return

        # Gửi kiểu 'file' (send_file wrapper xử lý gửi group/private)
        try:
            self.send_file(path, "file")
        except Exception as e:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"❌ Lỗi gửi file: {e}")

    def on_send_video_clicked(self):
        """
        Bấm nút 🎬 -> chọn video và gửi. Hỗ trợ cả 1-1 và group.
        """
        if not getattr(self, "current_username", None):
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return

        # allow sending to group or private
        if not getattr(self, "current_partner_username", None) and not getattr(self, "current_group_id", None):
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⚠️ Hãy chọn người hoặc nhóm để gửi video")
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn video gửi",
            "",
            "Video (*.mp4 *.mov *.avi *.mkv)"
        )
        if not path:
            return

        try:
            self.send_file(path, "video")
        except Exception as e:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"❌ Lỗi gửi video: {e}")


    def _connect_to_server(self):
        """
        Tạo socket, kết nối tới server và chạy NetworkThread.
        """
        # Nếu đã có kết nối cũ thì dừng/đóng
        if getattr(self, "net_thread", None):
            try:
                self.net_thread.stop()
            except Exception:
                pass
            self.net_thread = None

        if getattr(self, "sock", None):
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

        try:
            # Tạo socket TCP và kết nối
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((SERVER_HOST, SERVER_PORT))

            # Thread đọc dữ liệu từ server
            self.net_thread = NetworkThread(self.sock)
            self.net_thread.received.connect(self.on_server_message)
            self.net_thread.start()

            # Cập nhật UI trạng thái
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText("✅ Đã kết nối server")
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("✅ Đã kết nối server")
        except Exception as e:
            # Nếu không kết nối được, đảm bảo tài nguyên được thu dọn
            self.sock = None
            self.net_thread = None
            if getattr(self, "lbl_auth_status", None):
                self.lbl_auth_status.setText(f"❌ Không kết nối được server: {e}")
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⚠️ Mất kết nối server")

    def on_create_group_clicked(self):
        """
        Bấm nút 'Tạo nhóm' -> hỏi tên nhóm -> gửi request lên server.
        """
        if not getattr(self, "current_username", None):
            QMessageBox.warning(self, "Thông báo", "Đăng nhập rồi mới tạo nhóm.")
            return

        name, ok = QInputDialog.getText(self, "Tạo nhóm", "Nhập tên nhóm:")
        if not ok or not name.strip():
            return
        group_name = name.strip()

        if not getattr(self, "sock", None):
            QMessageBox.warning(self, "Lỗi", "Mất kết nối server.")
            return

        pkt = make_packet("create_group", {
            "owner": self.current_username,
            "name": group_name,
        })
        try:
            self.sock.sendall(pkt)
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"⏳ Đang tạo nhóm '{group_name}'...")
        except OSError as e:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"❌ Lỗi gửi yêu cầu tạo nhóm: {e}")

    def on_leave_group_clicked(self):
        """
        Nút 'Rời nhóm' trong info panel.
        """
        if not getattr(self, "current_username", None):
            QMessageBox.warning(self, "Thông báo", "Đăng nhập trước.")
            return
        if not getattr(self, "current_group_id", None):
            QMessageBox.information(
                self,
                "Thông báo",
                "Chỉ rời được khi đang mở một nhóm, không phải chat 1-1."
            )
            return
        if not getattr(self, "sock", None):
            QMessageBox.warning(self, "Lỗi", "Mất kết nối server.")
            return

        ans = QMessageBox.question(
            self,
            "Rời nhóm",
            "Bạn có chắc muốn rời nhóm hiện tại?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        pkt = make_packet("leave_group", {
            "by": self.current_username,
            "conversation_id": self.current_group_id,
        })
        try:
            self.sock.sendall(pkt)
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⏳ Đang rời nhóm...")
        except OSError as e:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"❌ Lỗi gửi yêu cầu rời nhóm: {e}")

    # --------- NEW: add/join group handlers ----------
    def on_add_user_to_group(self, username: str):
        """
        Được gọi khi chọn 'Thêm vào nhóm hiện tại' từ context menu sidebar.
        Gửi yêu cầu add member lên server.
        """
        if not getattr(self, "current_username", None):
            QMessageBox.warning(self, "Thông báo", "Đăng nhập trước.")
            return

        if not getattr(self, "current_group_id", None):
            QMessageBox.information(self, "Thông báo", "Không có nhóm đang mở.")
            return

        # Nếu muốn hạn chế chỉ owner được thêm, có thể kiểm tra:
        if not getattr(self, "current_group_is_owner", False):
            # cho phép client gửi nhưng thông báo; server sẽ kiểm tra quyền thực sự
            ans = QMessageBox.question(
                self,
                "Thêm thành viên",
                "Bạn không phải chủ nhóm. Bạn vẫn muốn yêu cầu thêm người này vào nhóm?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return

        if not getattr(self, "sock", None):
            QMessageBox.warning(self, "Lỗi", "Mất kết nối server.")
            return

        pkt = make_packet("add_group_member", {
            "conversation_id": self.current_group_id,
            "username": username,
            "by": self.current_username,
        })
        try:
            self.sock.sendall(pkt)
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"⏳ Đang thêm {username} vào nhóm...")
        except OSError as e:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"❌ Lỗi gửi yêu cầu thêm: {e}")

    def on_join_group_requested(self, group_name: str):
        """
        Khi user nhấn Enter trong ô search với text không khớp user nào:
        dùng làm yêu cầu 'join group' (vì sidebar.emit tên nhóm).
        """
        if not getattr(self, "current_username", None):
            QMessageBox.warning(self, "Thông báo", "Đăng nhập trước.")
            return

        name = (group_name or "").strip()
        if not name:
            return

        if not getattr(self, "sock", None):
            QMessageBox.warning(self, "Lỗi", "Mất kết nối server.")
            return

        pkt = make_packet("join_group", {
            "group_name": name,
            "username": self.current_username,
        })
        try:
            self.sock.sendall(pkt)
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"⏳ Đang yêu cầu tham gia nhóm '{name}'...")
        except OSError as e:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText(f"❌ Lỗi gửi yêu cầu tham gia: {e}")

    def on_chat_attachment_open(self, path: str, kind: str):
        """
        Xử lý khi user double-click một attachment trong chat_list.
        kind: 'image' | 'video' | 'file'
        path: đường dẫn tệp trên máy (server/storage/...)
        """
        if not path:
            if getattr(self, "lbl_chat_status", None):
                self.lbl_chat_status.setText("⚠️ Đường dẫn file không hợp lệ")
            return

        # image -> preview
        if kind == "image":
            if os.path.exists(path):
                try:
                    self.show_image_preview(path)
                except Exception as e:
                    QMessageBox.warning(self, "Lỗi", f"Không mở ảnh: {e}")
            else:
                QMessageBox.warning(self, "Lỗi", "File ảnh không tồn tại.")
            return

        # video -> player
        if kind == "video":
            if os.path.exists(path):
                try:
                    self.show_video_player(path)
                except Exception as e:
                    QMessageBox.warning(self, "Lỗi", f"Không phát video: {e}")
            else:
                QMessageBox.warning(self, "Lỗi", "File video không tồn tại.")
            return

        # file -> lưu về máy
        if kind == "file":
            # path có thể là đường dẫn server/storage/files/..., gợi ý tên file là basename
            try:
                suggested = os.path.basename(path) or None
                self._save_file_from_server(path, suggested_name=suggested)
            except Exception as e:
                QMessageBox.warning(self, "Lỗi", f"Không lưu file: {e}")
            return

        # fallback
        QMessageBox.information(self, "Thông báo", "Loại file không được hỗ trợ.")

    def _handle_attachments_result(self, data: dict):
        """
        Xử lý kết quả từ server khi yêu cầu danh sách attachments (media/files/links).
        Hiển thị danh sách vào list_attachments hoặc thông báo lỗi/trạng thái.
        """
        if not data.get("ok"):
            self.lbl_chat_status.setText("❌ Lỗi tải danh sách tệp tin: " + str(data.get("error")))
            return

        items = data.get("items") or []
        filter_kind = data.get("filter") or ""

        # clear current list
        self.list_attachments.clear()

        if not items:
            empty_text = "Không có dữ liệu."
            if filter_kind == "media":
                empty_text = "Chưa có ảnh / video nào được gửi."
            elif filter_kind == "files":
                empty_text = "Chưa có file nào được gửi."
            elif filter_kind == "links":
                empty_text = "Chưa có link nào được gửi."
            self.list_attachments.addItem(empty_text)
        else:
            for it in items:
                msg_id = it.get("id")
                content = it.get("content") or ""
                path = it.get("path") or ""
                msg_type = (it.get("msg_type") or "").lower()

                # xử lý riêng cho links: hiển thị URL thực sự
                if filter_kind == "links":
                    link_url = self._extract_first_url(content) or content
                    msg_type = "link"
                    content = link_url

                short = content if len(content) <= 60 else content[:57] + "..."
                prefix = "•"
                if filter_kind == "media":
                    prefix = "🖼"
                elif filter_kind == "files":
                    prefix = "📎"
                elif filter_kind == "links":
                    prefix = "🔗"
                line = f"{prefix} #{msg_id}: {short}"

                item = QListWidgetItem(line)
                item.setData(Qt.ItemDataRole.UserRole, {
                    "id": msg_id,
                    "msg_type": msg_type,
                    "content": content,
                    "path": path,
                })
                self.list_attachments.addItem(item)

        self.list_attachments.setVisible(True)
        self.list_attachments.scrollToTop()

    def on_attachments_result(self, data: dict):
        """
        Khi nhận được kết quả danh sách tệp tin từ server:
        - Nếu có lỗi, hiển thị thông báo lỗi.
        - Nếu không có dữ liệu, hiển thị thông báo tương ứng.
        - Nếu có dữ liệu, hiển thị vào list_attachments.
        """
        action = data.get("action")
        if action == "list_attachments":
            self._handle_attachments_result(data)
        # có thể thêm xử lý cho các action khác nếu cần thiết
