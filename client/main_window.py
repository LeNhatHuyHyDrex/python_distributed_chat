import socket
import base64
import os
import shutil
from pathlib import Path
from typing import Any

from PyQt6.QtGui import QPixmap, QPainter, QPainterPath, QDesktopServices
from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtWidgets import (
    QMainWindow, QMessageBox, QFileDialog,
    QDialog, QVBoxLayout, QLabel, QListWidgetItem,
    QHBoxLayout, QPushButton, QSlider
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

        partner = self.current_partner_username
        if not partner:
            self.lbl_chat_status.setText("⚠️ Hãy chọn người để gửi")
            return

        try:
            with open(path, "rb") as f:
                raw = f.read()
        except:
            self.lbl_chat_status.setText("❌ Không đọc được file")
            return

        b64 = base64.b64encode(raw).decode("ascii")

        pkt = make_packet("send_file", {
            "from": self.current_username,
            "to": partner,
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

        # Dựng UI
        setup_chatwindow_ui(self)

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
        # Auth
        self.btn_login.clicked.connect(self.on_login_clicked)
        self.btn_register.clicked.connect(self.on_register_clicked)
        self.btn_show_login.clicked.connect(
            lambda: self.auth_stack.setCurrentIndex(0)
        )
        self.btn_show_register.clicked.connect(
            lambda: self.auth_stack.setCurrentIndex(1)
        )

        # Chat
        self.btn_send.clicked.connect(self.on_send_clicked)
        self.le_message.returnPressed.connect(self.on_send_clicked)
        if hasattr(self, "btn_send_image"):
            self.btn_send_image.clicked.connect(self.on_send_image_clicked)
        if hasattr(self, "btn_send_file"):
            self.btn_send_file.clicked.connect(self.on_send_file_clicked)
        if hasattr(self, "btn_send_video"):
            self.btn_send_video.clicked.connect(self.on_send_video_clicked)

        self.btn_logout.clicked.connect(self.on_logout_clicked)
        self.btn_broadcast.clicked.connect(self.on_broadcast_clicked)

        # Xóa tin nhắn 1 cái (context menu)
        self.chat_list.delete_requested.connect(self.on_delete_from_context)
         # Double click vào bubble file / video / ảnh
        self.chat_list.attachment_open_requested.connect(
            self.on_chat_attachment_open
        )
        # Sidebar chọn đoạn chat + search
        self.sidebar.conversation_selected.connect(
            self.on_sidebar_conversation_selected
        )
        try:
            self.sidebar.search_text_changed.connect(
                self.on_sidebar_search_changed
            )
        except AttributeError:
            pass

        # Nút "Xóa đoạn chat" bên info panel
        if hasattr(self, "btn_delete_conversation"):
            self.btn_delete_conversation.clicked.connect(
                self.on_delete_conversation_clicked
            )
                # 3 nút Ảnh/Video, File, Link bên phải
        if hasattr(self, "btn_media"):
            self.btn_media.clicked.connect(
                lambda: self.on_show_attachments("media")
            )
        if hasattr(self, "btn_files"):
            self.btn_files.clicked.connect(
                lambda: self.on_show_attachments("files")
            )
        if hasattr(self, "btn_links"):
            self.btn_links.clicked.connect(
                lambda: self.on_show_attachments("links")
            )


        # Click vào avatar profile để đổi ảnh
        if hasattr(self, "lbl_profile_avatar") and hasattr(self.lbl_profile_avatar, "clicked"):
            try:
                self.lbl_profile_avatar.clicked.connect(
                    self.on_change_profile_avatar_clicked
                )
            except Exception:
                pass
                # Click vào 1 item trong danh sách Ảnh/Video/File/Link để xem chi tiết
        if hasattr(self, "list_attachments"):
            try:
                # double-click trong panel Ảnh/Video/File/Link mới mở
                self.list_attachments.itemDoubleClicked.connect(self.on_attachment_clicked)
            except Exception:
                pass



    # ---------- NETWORK ----------

    # ---------- NETWORK ----------

    def _connect_to_server(self):
        """Tạo socket, kết nối tới server và chạy NetworkThread."""
        # Nếu đã có kết nối cũ thì đóng lại cho chắc
        if self.net_thread:
            try:
                self.net_thread.stop()
            except Exception:
                pass
            self.net_thread = None

        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

        try:
            # Tạo socket TCP
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((SERVER_HOST, SERVER_PORT))

            # Thread đọc dữ liệu từ server
            self.net_thread = NetworkThread(self.sock)
            self.net_thread.received.connect(self.on_server_message)
            self.net_thread.start()

            self.lbl_auth_status.setText("✅ Đã kết nối server")
            self.lbl_chat_status.setText("✅ Đã kết nối server")
        except Exception as e:
            self.sock = None
            self.net_thread = None
            self.lbl_auth_status.setText(f"❌ Không kết nối được server: {e}")
            self.lbl_chat_status.setText("⚠️ Mất kết nối server")


    # ---------- CLIENT -> SERVER ----------

    def on_login_clicked(self):
        if not self.sock:
            self.lbl_auth_status.setText("❌ Chưa kết nối được server")
            return
        username = self.le_login_username.text().strip()
        password = self.le_login_password.text().strip()
        if not username or not password:
            self.lbl_auth_status.setText("⚠️ Nhập username và password")
            return
        pkt = make_packet("login", {"username": username, "password": password})
        try:
            self.sock.sendall(pkt)
        except OSError as e:
            self.lbl_auth_status.setText(f"❌ Lỗi gửi gói tin: {e}")

    def on_register_clicked(self):
        if not self.sock:
            self.lbl_auth_status.setText("❌ Chưa kết nối được server")
            return
        username = self.le_reg_username.text().strip()
        display_name = self.le_reg_display.text().strip() or username
        pw1 = self.le_reg_pw1.text().strip()
        pw2 = self.le_reg_pw2.text().strip()
        if not username or not pw1 or not pw2:
            self.lbl_auth_status.setText("⚠️ Nhập đầy đủ thông tin đăng ký")
            return
        if pw1 != pw2:
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
            self.lbl_auth_status.setText(f"❌ Lỗi gửi gói tin: {e}")

    def on_change_profile_avatar_clicked(self):
        """
        Bấm vào avatar trên header -> chọn ảnh -> gửi server.
        """
        if not self.current_username:
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
            self.lbl_auth_status.setText(f"❌ Không đọc được file: {e}")
            return

        pix = QPixmap()
        if not (pix.loadFromData(raw) and not pix.isNull()):
            self.lbl_auth_status.setText("❌ File không phải ảnh hợp lệ")
            return

        img_b64 = base64.b64encode(raw).decode("ascii")
        # Preview ngay trên client
        self._set_current_user_avatar_from_b64(img_b64)

        if not self.sock:
            self.lbl_auth_status.setText("❌ Chưa kết nối được server")
            return

        pkt = make_packet("update_avatar", {
            "username": self.current_username,
            "image_b64": img_b64,
        })
        try:
            self.sock.sendall(pkt)
            self.lbl_auth_status.setText("⏳ Đang cập nhật avatar...")
        except OSError as e:
            self.lbl_auth_status.setText(f"❌ Lỗi gửi avatar: {e}")

    def on_send_clicked(self):
        if not self.current_username:
            self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return
        to_user = self.le_to_user.text().strip()
        content = self.le_message.text().strip()
        if not to_user or not content:
            return
        pkt = make_packet("send_text", {
            "from": self.current_username,
            "to": to_user,
            "content": content
        })
        try:
            self.sock.sendall(pkt)
            self.le_message.clear()
        except OSError as e:
            self.lbl_chat_status.setText(f"❌ Lỗi gửi tin nhắn: {e}")

    def on_load_history_clicked(self):
        if not self.current_username:
            self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return
        to_user = self.le_to_user.text().strip()
        if not to_user:
            self.lbl_chat_status.setText("⚠️ Hãy chọn một người để mở chat")
            return
        self.lbl_chat_status.setText(f"⏳ Đang tải lịch sử với {to_user}...")
        pkt = make_packet("load_history", {
            "from": self.current_username,
            "to": to_user
        })
        try:
            self.sock.sendall(pkt)
        except OSError as e:
            self.lbl_chat_status.setText(f"❌ Lỗi yêu cầu lịch sử: {e}")

    def on_logout_clicked(self):
        if not self.current_username:
            return
        username = self.current_username
        pkt = make_packet("logout", {"username": username})
        try:
            self.sock.sendall(pkt)
        except OSError:
            pass

        self.current_username = None
        self.current_display_name = None
        self.current_partner_username = None

        self.chat_list.clear()
        if hasattr(self.sidebar, "set_conversations"):
            self.sidebar.set_conversations([])
        if hasattr(self.sidebar, "set_search_results"):
            self.sidebar.set_search_results([])

        self.le_to_user.clear()
        self.lbl_user_info.setText("Chưa đăng nhập")
        self.lbl_chat_status.setText("Đã đăng xuất")
        self._set_current_user_avatar_from_b64(None)
        self._update_info_panel(None)

        self.main_stack.setCurrentWidget(self.login_panel)

    def on_broadcast_clicked(self):
        if not self.current_username:
            self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return
        pkt = make_packet("broadcast", {"message": "Thông báo từ server (test)!"})
        try:
            self.sock.sendall(pkt)
        except OSError as e:
            self.lbl_chat_status.setText(f"❌ Lỗi gửi broadcast: {e}")

    def on_delete_from_context(self, message_id: int):
        """
        Xóa 1 tin nhắn (chuột phải vào bubble -> Delete).
        """
        if not self.current_username:
            self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return
        to_user = self.le_to_user.text().strip()
        if not to_user:
            self.lbl_chat_status.setText("⚠️ Hãy mở một cuộc chat trước")
            return
        pkt = make_packet("delete_message", {
            "by": self.current_username,
            "partner": to_user,
            "message_id": message_id
        })
        try:
            self.sock.sendall(pkt)
        except OSError as e:
            self.lbl_chat_status.setText(f"❌ Lỗi gửi yêu cầu xóa: {e}")

    def on_delete_conversation_clicked(self):
        """
        Xử lý nút 'Xóa đoạn chat' trong info panel (bên phải).
        Xóa sạch lịch sử giữa 2 user và đoạn chat biến khỏi sidebar.
        """
        if not self.current_username:
            self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return
        partner = self.current_partner_username
        if not partner:
            self.lbl_chat_status.setText("⚠️ Chưa chọn đoạn chat để xóa")
            return

        ans = QMessageBox.question(
            self,
            "Xóa đoạn chat",
            f"Bạn có chắc muốn xóa toàn bộ tin nhắn với {partner}?\n"
            "Hành động này sẽ xóa lịch sử cho cả hai bên.",
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
            self.lbl_chat_status.setText(f"❌ Lỗi gửi yêu cầu xóa đoạn chat: {e}")

    def on_sidebar_conversation_selected(self, partner_username: str):
        """
        Khi click 1 item trong sidebar.
        """
        partner_username = (partner_username or "").strip()
        if not partner_username:
            return
        self.current_partner_username = partner_username
        self.le_to_user.setText(partner_username)

        if hasattr(self.sidebar, "set_active_username"):
            self.sidebar.set_active_username(partner_username)

        self._update_info_panel(partner_username)
        self.on_load_history_clicked()

    def on_sidebar_search_changed(self, text: str):
        """
        Khi gõ vào ô search ở sidebar -> gửi request search_users.
        """
        text = (text or "").strip()
        if not text:
            if hasattr(self.sidebar, "set_search_results"):
                self.sidebar.set_search_results([])
            return
        if not (self.sock and self.current_username):
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
        """
        Hỏi server danh sách các đoạn chat (để hiển thị sidebar).
        """
        if not (self.sock and self.current_username):
            return
        pkt = make_packet("list_conversations", {
            "username": self.current_username
        })
        try:
            self.sock.sendall(pkt)
        except OSError:
            pass

    # ---------- SERVER -> CLIENT ----------

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
        elif action == "incoming_file":
            sender = data.get("from")
            filename = data.get("filename")
            file_type = data.get("file_type")
            msg_id = data.get("message_id")

            base = Path(__file__).resolve().parents[1] / "server" / "storage"

            if file_type == "image":
                fpath = base / "images" / filename
                self.chat_list.add_image_bubble(
                    msg_id, sender, self.current_username, str(fpath)
                )

            elif file_type == "video":
                fpath = base / "videos" / filename
                self.chat_list.add_video_bubble(
                    msg_id, sender, self.current_username, str(fpath)
                )

            else:
                fpath = base / "files" / filename
                self.chat_list.add_file_bubble(
                    msg_id, sender, self.current_username, str(fpath)
                )

        elif action == "attachments_result":
            if not data.get("ok"):
                self.lbl_chat_status.setText(
                    "❌ Không lấy được danh sách: " + str(data.get("error"))
                )
                return

            filter_kind = data.get("filter")
            partner = data.get("partner")
            items = data.get("items", [])

            if not hasattr(self, "list_attachments"):
                return

            self.list_attachments.clear()

            if not items:
                empty_text = "Không có dữ liệu."
                if filter_kind == "media":
                    empty_text = "Chưa có ảnh / video nào."
                elif filter_kind == "files":
                    empty_text = "Chưa có file nào."
                elif filter_kind == "links":
                    empty_text = "Chưa có link nào."
                self.list_attachments.addItem(empty_text)
            else:
                base_dir = Path(__file__).resolve().parents[1]
                images_dir = base_dir / "server" / "storage" / "images"
                videos_dir = base_dir / "server" / "storage" / "videos"
                files_dir  = base_dir / "server" / "storage" / "files"

                for m in items:
                    msg_id = m.get("id")
                    created_at = m.get("created_at") or ""
                    msg_type = (m.get("msg_type") or "").lower()
                    content = m.get("content") or ""   # tên file hoặc link
                    short = content if len(content) <= 60 else content[:57] + "..."

                    prefix = "•"
                    if filter_kind == "media":
                        prefix = "🖼"
                    elif filter_kind == "files":
                        prefix = "📎"
                    elif filter_kind == "links":
                        prefix = "🔗"

                    line = f"{prefix} [{created_at}] #{msg_id}: {short}"
                    item = QListWidgetItem(line)

                    path = None
                    if msg_type == "image":
                        path = str(images_dir / content)
                    elif msg_type == "video":
                        path = str(videos_dir / content)
                    elif msg_type == "file":
                        path = str(files_dir / content)

                    item.setData(Qt.ItemDataRole.UserRole, {
                        "id": msg_id,
                        "msg_type": msg_type,
                        "content": content,
                        "path": path,
                    })
                    self.list_attachments.addItem(item)


            self.list_attachments.setVisible(True)
            self.list_attachments.scrollToTop()

            self.lbl_chat_status.setText(
                f"✅ Có {len(items)} mục trong '{filter_kind}' với {partner or ''}"
            )

        elif action == "send_file_result":
            if data.get("ok"):
                to_user = data.get("to")
                filename = data.get("filename")
                file_type = (data.get("file_type") or "file").lower()
                msg_id = data.get("message_id")

                base = Path(__file__).resolve().parents[1] / "server" / "storage"

                # Chỉ add bubble nếu hiện đang mở đúng đoạn chat
                if self.current_partner_username == to_user:
                    if file_type == "image":
                        fpath = base / "images" / filename
                        self.chat_list.add_image_bubble(
                            msg_id,
                            self.current_username,
                            self.current_username,
                            str(fpath),
                        )
                    elif file_type == "video":
                        fpath = base / "videos" / filename
                        self.chat_list.add_video_bubble(
                            msg_id,
                            self.current_username,
                            self.current_username,
                            str(fpath),
                        )
                    else:
                        fpath = base / "files" / filename
                        self.chat_list.add_file_bubble(
                            msg_id,
                            self.current_username,
                            self.current_username,
                            str(fpath),
                        )

                # Dù có đang mở hay không vẫn cập nhật sidebar
                self.request_conversations()
            else:
                self.lbl_chat_status.setText(
                    "❌ Gửi file thất bại: " + str(data.get("error"))
                )


        elif action == "send_image_result":
                    if data.get("ok"):
                        msg_id = data.get("message_id")
                        to_user = data.get("to")
                        filename = data.get("filename")

                        # đường dẫn ảnh nằm trong server/uploads
                        base_dir = Path(__file__).resolve().parents[1]
                        img_path = base_dir / "server" / "storage" / "images" / filename


                        if self.le_to_user.text().strip() == to_user:
                            self.chat_list.add_image_bubble(
                                msg_id,
                                self.current_username,
                                self.current_username,
                                str(img_path),
                            )
                        self.request_conversations()
                    else:
                        self.lbl_chat_status.setText(
                            "❌ Gửi ảnh thất bại: " + str(data.get("error"))
                        )

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
            else:
                self.lbl_auth_status.setText(f"❌ Đăng nhập thất bại: {data.get('error')}")

        elif action == "logout_result":
            # hiện tại logout_result chỉ confirm, mọi xử lý đã làm ở client
            pass

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
            if hasattr(self.sidebar, "set_conversations"):
                self.sidebar.set_conversations(self.conversations)
            # Nếu đang mở 1 partner thì update lại avatar của họ
            self._update_info_panel(self.current_partner_username)

        elif action == "search_users_result":
            if not data.get("ok"):
                return
            items = data.get("items", []) or []
            if hasattr(self.sidebar, "set_search_results"):
                self.sidebar.set_search_results(items)

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

    # ---------- UTILS ----------

    def _update_info_panel(self, partner_username: str | None):
        """
        Cập nhật panel bên phải: avatar, tên, @username của người đang chat.
        """
        # Khi chưa chọn đoạn chat -> text default + avatar default lớn
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

    # ---------- Qt lifecycle ----------

    def closeEvent(self, event):
        if self.net_thread is not None:
            self.net_thread.stop()
            self.net_thread.wait(500)
        super().closeEvent(event)
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
        if not partner:
            self.lbl_chat_status.setText("⚠️ Chưa chọn đoạn chat")
            return

        if not self.sock:
            self.lbl_chat_status.setText("⚠️ Mất kết nối server")
            return

        if kind == "media":
            self.lbl_chat_status.setText(f"⏳ Đang lấy ảnh & video với {partner}...")
        elif kind == "files":
            self.lbl_chat_status.setText(f"⏳ Đang lấy file với {partner}...")
        else:
            self.lbl_chat_status.setText(f"⏳ Đang lấy các link với {partner}...")

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

        partner = self.current_partner_username
        if not partner:
            self.lbl_chat_status.setText("⚠️ Hãy chọn người để gửi ảnh")
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

        pkt = make_packet("send_image", {      # 👈 dùng lại send_image
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
        """
        if not self.current_username:
            self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return

        partner = self.current_partner_username
        if not partner:
            self.lbl_chat_status.setText("⚠️ Hãy chọn người để gửi file")
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file gửi",
            ""
        )
        if not path:
            return

        # Gửi kiểu 'file'
        self.send_file(path, "file")

    def on_send_video_clicked(self):
        """
        Bấm nút 🎬 -> chọn video và gửi.
        """
        if not self.current_username:
            self.lbl_chat_status.setText("⚠️ Chưa đăng nhập")
            return

        partner = self.current_partner_username
        if not partner:
            self.lbl_chat_status.setText("⚠️ Hãy chọn người để gửi video")
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn video gửi",
            "",
            "Video (*.mp4 *.mov *.avi *.mkv)"
        )
        if not path:
            return

        # Gửi kiểu 'video'
        self.send_file(path, "video")
    def on_chat_attachment_open(self, path: str, kind: str):
        """
        Double click bubble trong khung chat.
        """
        if kind == "image":
            self.show_image_preview(path)
        elif kind == "video":
            self.show_video_player(path)
        elif kind == "file":
            self._save_file_from_server(path)
    def _open_link(self, url: str):
        if not url:
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "http://" + url
        QDesktopServices.openUrl(QUrl(url))
