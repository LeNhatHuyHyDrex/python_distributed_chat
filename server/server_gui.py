# server/server_gui.py

import sys
import socket
import json
import subprocess
import time
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel, QTextEdit,
    QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QComboBox, QListWidget, QListWidgetItem,QMessageBox, 
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal,QTimer

from common.config import SERVER_HOST, SERVER_PORT


# ================= NETWORK THREAD (NHẬN TIN TỪ SERVER) =================

class AdminNetworkThread(QThread):
    message_received = pyqtSignal(dict)
    disconnected = pyqtSignal(str)

    def __init__(self, sock: socket.socket, parent=None):
        super().__init__(parent)
        self.sock = sock

    def run(self):
        try:
            file = self.sock.makefile("r", encoding="utf-8")
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self.message_received.emit(msg)
        except Exception as e:
            self.disconnected.emit(str(e))
        finally:
            self.disconnected.emit("Kết nối tới server bị đóng.")


# ================= MAIN GUI =================

class ServerGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SERVER CONTROL PANEL - Mini Messenger")
        self.resize(950, 620)

        self.sock: socket.socket | None = None
        self.net_thread: AdminNetworkThread | None = None
        self.server_process: subprocess.Popen | None = None

        # ==== THEME TONE TÍM GRADIENT ====
        self.setStyleSheet("""
            QMainWindow {
                background: qlineargradient(
                    spread:pad, x1:0, y1:0, x2:1, y2:1,
                    stop:0 #3A1A6F, stop:0.5 #281248, stop:1 #140B2A
                );
                color: #EAE6FF;
            }

            QWidget {
                background-color: transparent;
                color: #EAE6FF;
            }

            QLabel {
                font-size: 14px;
                color: #EAE6FF;
            }

            QTextEdit {
                background-color: rgba(10, 10, 30, 0.65);
                border: 1px solid #4C2F8B;
                border-radius: 8px;
                padding: 8px;
                color: #EAE6FF;
                font-size: 14px;
            }
            QTextEdit:focus {
                border: 1px solid #6C4CC3;
            }

            QTableWidget {
                background-color: rgba(10, 10, 30, 0.8);
                gridline-color: #4C2F8B;
                color: #EAE6FF;
                selection-background-color: #4C2F8B;
                selection-color: #FFFFFF;
                border: 1px solid #4C2F8B;
            }
            QTableWidget QTableCornerButton::section {
                background-color: #2A155B;
                border: none;
            }

            QTableWidget QHeaderView::section {
                background-color: #2A155B;
                padding: 6px;
                font-weight: bold;
                border: none;
                color: #EAE6FF;
            }

            QListWidget {
                background-color: rgba(10, 10, 30, 0.8);
                border: 1px solid #4C2F8B;
                border-radius: 6px;
                color: #EAE6FF;
            }

            QComboBox {
                background-color: rgba(10, 10, 30, 0.8);
                border: 1px solid #4C2F8B;
                padding: 6px;
                border-radius: 6px;
                color: #EAE6FF;
            }
            QComboBox QAbstractItemView {
                background-color: #2A155B;
                selection-background-color: #4C2F8B;
            }

            QPushButton {
                background-color: #6C4CC3;
                border: none;
                padding: 8px 14px;
                border-radius: 6px;
                font-weight: bold;
                color: #FFFFFF;
            }
            QPushButton:hover {
                background-color: #8564E5;
            }
            QPushButton:pressed {
                background-color: #4C2F8B;
            }

            QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 0;
            }
            QScrollBar::handle:vertical {
                background: #6C4CC3;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #8564E5;
            }
            QScrollBar::add-line, QScrollBar::sub-line {
                height: 0px;
            }

            QTabWidget::pane {
                border: 2px solid #4C2F8B;
                border-radius: 10px;
                margin: 6px;
                background: qlineargradient(
                    spread:pad, x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(30, 15, 70, 0.9),
                    stop:1 rgba(10, 5, 30, 0.9)
                );
            }
            QTabBar::tab {
                background-color: rgba(255,255,255,0.05);
                padding: 10px 18px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                color: #EAE6FF;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #4C2F8B;
            }
            QTabBar::tab:hover {
                background-color: #6C4CC3;
            }
        """)

        # ====== MAIN LAYOUT ======
        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        # ====== TAB 1: ONLINE USERS ======
        tab_users = QWidget()
        layout_users = QVBoxLayout(tab_users)

        header_row = QHBoxLayout()
        lbl_title = QLabel("👥 Online Users")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: bold;")
        header_row.addWidget(lbl_title)
        header_row.addStretch(1)

        btn_refresh = QPushButton("Refresh")
        header_row.addWidget(btn_refresh)
        layout_users.addLayout(header_row)

        self.table_users = QTableWidget()
        self.table_users.setColumnCount(7)
        self.table_users.setHorizontalHeaderLabels(
            ["Username", "Display Name", "Login Time", "IP", "Status", "Kick", "Ban / Bỏ ban"]
)

        self.table_users.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table_users.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_users.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        layout_users.addWidget(self.table_users)
        tabs.addTab(tab_users, "Online Users")

        # ====== TAB 2: BROADCAST (user only) ======
        tab_bc = QWidget()
        layout_bc = QVBoxLayout(tab_bc)

        lbl_bc_title = QLabel("📢 Broadcast / Thông báo")
        lbl_bc_title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout_bc.addWidget(lbl_bc_title)

        layout_bc.addWidget(QLabel("Nội dung thông báo:"))
        self.txt_broadcast = QTextEdit()
        self.txt_broadcast.setPlaceholderText("Nhập thông báo gửi đến người dùng...")
        layout_bc.addWidget(self.txt_broadcast)

        # --- Gửi tất cả user ---
        row_all = QHBoxLayout()
        row_all.addWidget(QLabel("Gửi tới:"))
        self.cbb_target = QComboBox()
        self.cbb_target.addItems(["Tất cả user"])
        row_all.addWidget(self.cbb_target)
        self.btn_send_bc_all = QPushButton("Gửi")
        row_all.addWidget(self.btn_send_bc_all)
        row_all.addStretch(1)
        layout_bc.addLayout(row_all)

        # --- Gửi riêng từng user ---
        layout_bc.addWidget(QLabel("Gửi riêng tới một user:"))
        row_one = QHBoxLayout()
        self.cbb_single_user = QComboBox()
        self.cbb_single_user.setPlaceholderText("Chọn user...")
        row_one.addWidget(self.cbb_single_user)
        self.btn_send_bc_one = QPushButton("Gửi cho user")
        row_one.addWidget(self.btn_send_bc_one)
        row_one.addStretch(1)
        layout_bc.addLayout(row_one)

        # --- Gửi tới nhiều user ---
        layout_bc.addWidget(QLabel("Gửi tới nhiều user (chọn bên dưới):"))
        self.list_multi_users = QListWidget()
        self.list_multi_users.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout_bc.addWidget(self.list_multi_users, stretch=1)

        row_multi_btn = QHBoxLayout()
        self.btn_send_bc_multi = QPushButton("Gửi cho các user đã chọn")
        row_multi_btn.addStretch(1)
        row_multi_btn.addWidget(self.btn_send_bc_multi)
        layout_bc.addLayout(row_multi_btn)

        tabs.addTab(tab_bc, "Broadcast")

        # ====== TAB 3: LOGS ======
        tab_log = QWidget()
        layout_log = QVBoxLayout(tab_log)

        lbl_log_title = QLabel("📜 Server Logs")
        lbl_log_title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout_log.addWidget(lbl_log_title)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        layout_log.addWidget(self.txt_log)

        tabs.addTab(tab_log, "Logs")

        # ====== SIGNALS ======
        btn_refresh.clicked.connect(self.on_refresh_clicked)
        self.btn_send_bc_all.clicked.connect(self.on_send_broadcast_all)
        self.btn_send_bc_one.clicked.connect(self.on_send_broadcast_one)
        self.btn_send_bc_multi.clicked.connect(self.on_send_broadcast_multi)

        # ====== START SERVER + CONNECT ======
        self.start_server_background()
        self.connect_to_server()

        # ====== AUTO REFRESH ONLINE USERS ======
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(2000)   # 2000ms = 2 giây, thích thì chỉnh 1000
        self.refresh_timer.timeout.connect(self.on_refresh_clicked)
        self.refresh_timer.start()


    # ----------------- START SERVER_MAIN TỰ ĐỘNG -----------------
    def start_server_background(self):
        """
        Chạy server_main.py bằng `python -m server.server_main` từ root project.
        """
        try:
            project_root = os.path.dirname(os.path.dirname(__file__))
            self.server_process = subprocess.Popen(
                [sys.executable, "-m", "server.server_main"],
                cwd=project_root,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.log(f"Đã chạy server_main ở nền (cwd={project_root}).")
            time.sleep(1.0)  # chờ server lên
        except Exception as e:
            self.log(f"❌ Lỗi khi chạy server_main: {e}")
            self.server_process = None

    # ----------------- CONNECT TO SERVER -----------------
    def connect_to_server(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((SERVER_HOST, SERVER_PORT))
            self.log(f"✅ Kết nối server tại {SERVER_HOST}:{SERVER_PORT}")

            self.net_thread = AdminNetworkThread(self.sock)
            self.net_thread.message_received.connect(self.on_server_message)
            self.net_thread.disconnected.connect(self.on_server_disconnected)
            self.net_thread.start()

            # hỏi danh sách user online
            self.send_packet("admin_get_online_users", {})

        except OSError as e:
            self.log(f"❌ Không kết nối được server: {e}")
            self.sock = None

    def send_packet(self, action: str, data: dict):
        if not self.sock:
            self.log("⚠ Chưa kết nối server, không thể gửi gói tin.")
            return
        try:
            text = json.dumps({"action": action, "data": data}, ensure_ascii=False)
            self.sock.sendall((text + "\n").encode("utf-8"))
        except OSError as e:
            self.log(f"❌ Lỗi gửi gói tin: {e}")

    # ----------------- CẬP NHẬT UI ONLINE USERS -----------------
    def add_user_row(self, username: str, display_name: str,
                     login_time: str, ip: str, status: str, banned: bool):
        row = self.table_users.rowCount()
        self.table_users.insertRow(row)

        self.table_users.setItem(row, 0, QTableWidgetItem(username))
        self.table_users.setItem(row, 1, QTableWidgetItem(display_name))
        self.table_users.setItem(row, 2, QTableWidgetItem(login_time))
        self.table_users.setItem(row, 3, QTableWidgetItem(ip))
        self.table_users.setItem(row, 4, QTableWidgetItem(status))

        btn_kick = QPushButton("Kick")
        self.table_users.setCellWidget(row, 5, btn_kick)
        btn_kick.clicked.connect(lambda _, u=username: self.on_kick_clicked(u))

        if banned:
            btn_ban = QPushButton("Bỏ ban")
            btn_ban.setStyleSheet(
                "background-color: #f1c40f; color: #000000; "
                "font-weight: bold; border-radius: 6px; padding: 6px 12px;"
            )
            btn_ban.clicked.connect(lambda _, u=username: self.on_unban_clicked(u))
        else:
            btn_ban = QPushButton("Ban")
            btn_ban.setStyleSheet(
                "background-color: #e74c3c; color: #ffffff; "
                "font-weight: bold; border-radius: 6px; padding: 6px 12px;"
            )
            btn_ban.clicked.connect(lambda _, u=username: self.on_ban_clicked(u))

        self.table_users.setCellWidget(row, 6, btn_ban)



    def refresh_broadcast_user_targets(self):
        usernames: list[str] = []
        for row in range(self.table_users.rowCount()):
            item = self.table_users.item(row, 0)
            if item:
                uname = item.text().strip()
                if uname:
                    usernames.append(uname)

        # Combo 1 user
        self.cbb_single_user.clear()
        for u in usernames:
            self.cbb_single_user.addItem(u)

        # List multi user
        self.list_multi_users.clear()
        for u in usernames:
            it = QListWidgetItem(u)
            self.list_multi_users.addItem(it)

    # ----------------- BUTTON HANDLERS -----------------
    def on_kick_clicked(self, username: str):
        self.log(f"[ADMIN] Kick user: {username}")
        self.send_packet("admin_kick", {"username": username})

    def on_refresh_clicked(self):
        self.log("[ADMIN] Refresh online users")
        self.send_packet("admin_get_online_users", {})

    def on_send_broadcast_all(self):
        content = self.txt_broadcast.toPlainText().strip()
        if not content:
            self.log("⚠ Không có nội dung broadcast.")
            return
        self.log(f"[ADMIN] Broadcast tới TẤT CẢ USER: {content}")
        self.send_packet("admin_broadcast_all", {
            "message": content,
        })
        self.txt_broadcast.clear()

    def on_send_broadcast_one(self):
        content = self.txt_broadcast.toPlainText().strip()
        if not content:
            self.log("⚠ Không có nội dung broadcast.")
            return
        user = self.cbb_single_user.currentText().strip()
        if not user:
            self.log("⚠ Chưa chọn user để gửi riêng.")
            return
        self.log(f"[ADMIN] Broadcast riêng cho [{user}]: {content}")
        self.send_packet("admin_broadcast_user", {
            "username": user,
            "message": content,
        })
        self.txt_broadcast.clear()

    def on_send_broadcast_multi(self):
        content = self.txt_broadcast.toPlainText().strip()
        if not content:
            self.log("⚠ Không có nội dung broadcast.")
            return

        selected_users: list[str] = []
        for item in self.list_multi_users.selectedItems():
            uname = item.text().strip()
            if uname:
                selected_users.append(uname)

        if not selected_users:
            self.log("⚠ Chưa chọn user nào trong danh sách.")
            return

        self.log(f"[ADMIN] Broadcast cho các user {selected_users}: {content}")
        self.send_packet("admin_broadcast_multi", {
            "usernames": selected_users,
            "message": content,
        })
        self.txt_broadcast.clear()

    # ----------------- NHẬN TIN TỪ SERVER -----------------
    def on_server_message(self, msg: dict):
        action = msg.get("action")
        data = msg.get("data") or {}

        if action == "admin_online_users":
            users = data.get("users") or []
            self.table_users.setRowCount(0)

            # debug xem server gửi gì
            print("[DEBUG GUI] admin_online_users users =", users)

            for u in users:
                username = u.get("username") or ""
                display_name = u.get("display_name") or username
                login_time = u.get("login_time") or ""
                ip = u.get("ip") or ""
                status = (u.get("status") or "online").capitalize()
                banned = bool(u.get("banned"))

                self.add_user_row(username, display_name, login_time, ip, status, banned)

            self.refresh_broadcast_user_targets()
            self.log(f"[SERVER] Online users: {len(users)}")


        elif action == "admin_kick_result":
            if data.get("ok"):
                uname = data.get("username")
                self.log(f"[SERVER] Kick {uname} OK (bấm Refresh để cập nhật).")
                self.send_packet("admin_get_online_users", {})
            else:
                self.log(f"[SERVER] Kick fail: {data.get('error')}")
        elif action == "admin_ban_result":
            if data.get("ok"):
                uname = data.get("username")
                self.log(f"[SERVER] Ban {uname} OK.")
                self.send_packet("admin_get_online_users", {})
            else:
                self.log(f"[SERVER] Ban fail: {data.get('error')}")

        elif action == "admin_unban_result":
            if data.get("ok"):
                uname = data.get("username")
                self.log(f"[SERVER] Unban {uname} OK.")
                self.send_packet("admin_get_online_users", {})
            else:
                self.log(f"[SERVER] Unban fail: {data.get('error')}")
        else:
            self.log(f"[SERVER MSG] {action}: {data}")

    def on_server_disconnected(self, reason: str):
        self.log(f"⚠ Mất kết nối server: {reason}")
        self.sock = None

    # ----------------- CLOSE EVENT -----------------
    def closeEvent(self, event):
        # tắt server_main khi đóng GUI
        if self.server_process:
            try:
                self.server_process.terminate()
            except Exception:
                pass
        event.accept()

    # ----------------- LOG -----------------
    def log(self, text: str):
        now = datetime.now().strftime("%H:%M:%S")
        self.txt_log.append(f"[{now}] {text}")
    def on_ban_clicked(self, username: str):
        ret = QMessageBox.question(
            self,
            "Ban user",
            f"Bạn có chắc chắn muốn BAN user '{username}' không?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        self.log(f"[ADMIN] Ban user: {username}")
        self.send_packet("admin_ban", {"username": username})

    def on_unban_clicked(self, username: str):
        self.log(f"[ADMIN] Bỏ ban user: {username}")
        self.send_packet("admin_unban", {"username": username})

def main():
    app = QApplication(sys.argv)
    gui = ServerGUI()
    gui.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
