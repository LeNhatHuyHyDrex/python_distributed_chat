# client/call_window.py
import subprocess
import re
import sounddevice as sd
import numpy as np
import queue
import sys

from typing import List
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QEvent
from PyQt6.QtGui import QImage, QPixmap, QIcon, QColor, QResizeEvent
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QWidget, QFrame, QGraphicsDropShadowEffect
)

from .webrtc_session import WebRTCSession
from .network import make_packet

class CallWindow(QDialog):
    remote_frame_signal = pyqtSignal(object)
    local_frame_signal = pyqtSignal(object)

    def __init__(self, parent=None, mode="private", is_video=True, self_name="", peers=None, is_incoming=False, conv_id=None, partner_username=None):
        super().__init__(parent)
        self.main = parent
        self.mode = mode
        self.is_video = is_video
        self.self_name = self_name
        self.peers = peers or []
        self.is_incoming = is_incoming
        self.conv_id = conv_id
        self.partner_username = partner_username

        # Trạng thái
        self.is_mic_muted = False
        self.is_cam_muted = False

        self.setWindowTitle(f"Cuộc gọi với {self.partner_username or 'Nhóm'}")
        self.resize(1000, 700)
        # Set màu nền đen cho toàn bộ cửa sổ
        self.setStyleSheet("background-color: #000000;")

        # Kết nối Signal
        self.remote_frame_signal.connect(self.update_remote_video)
        self.local_frame_signal.connect(self.update_local_video)

        self.audio_queue = queue.Queue(maxsize=200) 
        self.audio_stream = None 

        self._build_ui()
        
        self.webrtc = WebRTCSession(self, is_video=is_video)
        self.restart_audio_stream()

    def _build_ui(self):
        # Container chính (để chứa các layer chồng lên nhau)
        self.container = QWidget(self)
        # Layout chính chỉ để set margin = 0
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)

        # --- LAYER 1: REMOTE VIDEO (NỀN) ---
        self.remote_video = QLabel(self.container)
        self.remote_video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.remote_video.setScaledContents(True)
        self.remote_video.setStyleSheet("background-color: #1c1c1c; color: #888; font-size: 16px;")
        self.remote_video.setText(f"Đang đợi video từ {self.partner_username}...")

        # --- LAYER 2: LOCAL VIDEO (PIP - Góc phải dưới) ---
        self.local_video = QLabel(self.container)
        self.local_video.setFixedSize(180, 240) # Tỉ lệ 3:4 hoặc 9:16
        self.local_video.setScaledContents(True)
        # Bo góc và viền nhẹ
        self.local_video.setStyleSheet("""
            background-color: #333; 
            border: 2px solid #444; 
            border-radius: 12px;
        """)
        # Thêm bóng đổ cho Local Video nổi lên
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 150))
        shadow.setOffset(0, 5)
        self.local_video.setGraphicsEffect(shadow)
        
        if not self.is_video:
            self.local_video.setVisible(False)

        # --- LAYER 3: TOP BAR (Mic/Loa selection) ---
        # Làm thanh mờ ở trên cùng
        self.top_bar = QFrame(self.container)
        self.top_bar.setStyleSheet("""
            QFrame {
                background-color: rgba(0, 0, 0, 100); 
                border-radius: 20px;
            }
            QLabel { color: white; font-weight: bold; background: transparent; }
            QComboBox {
                background-color: rgba(255, 255, 255, 0.1);
                color: white;
                border: 1px solid rgba(255,255,255,0.3);
                border-radius: 5px;
                padding: 2px 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #333;
                color: white;
            }
        """)
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(15, 8, 15, 8)
        
        self.cb_camera = QComboBox()
        self.cb_mic = QComboBox()
        self.cb_speaker = QComboBox()
        
        # Chỉ hiện ComboBox Camera nếu là Video Call
        if self.is_video:
            top_layout.addWidget(QLabel("📷"))
            top_layout.addWidget(self.cb_camera, 1)
            top_layout.addSpacing(10)
        
        top_layout.addWidget(QLabel("🎙️"))
        top_layout.addWidget(self.cb_mic, 1)
        top_layout.addSpacing(10)
        top_layout.addWidget(QLabel("🔊"))
        top_layout.addWidget(self.cb_speaker, 1)

        # --- LAYER 4: BOTTOM CONTROLS (Nút điều khiển) ---
        self.controls_bar = QFrame(self.container)
        self.controls_bar.setStyleSheet("""
            QFrame {
                background-color: transparent;
            }
            QPushButton {
                background-color: rgba(60, 60, 60, 0.9);
                border: none;
                border-radius: 28px; /* Hình tròn: 56px / 2 */
                min-width: 56px;
                min-height: 56px;
                font-size: 24px;
                color: white;
            }
            QPushButton:hover {
                background-color: rgba(90, 90, 90, 1);
            }
            QPushButton:pressed {
                background-color: rgba(120, 120, 120, 1);
            }
            /* Nút kết thúc màu đỏ */
            QPushButton#btn_end {
                background-color: #ff3b30;
            }
            QPushButton#btn_end:hover {
                background-color: #ff6058;
            }
            /* Nút trả lời màu xanh */
            QPushButton#btn_answer {
                background-color: #30d158;
            }
        """)
        
        ctrl_layout = QHBoxLayout(self.controls_bar)
        ctrl_layout.setSpacing(20)
        ctrl_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Nút Mic
        self.btn_toggle_mic = QPushButton("🎙️")
        self.btn_toggle_mic.setToolTip("Bật/Tắt Mic")
        self.btn_toggle_mic.clicked.connect(self.on_toggle_mic)
        ctrl_layout.addWidget(self.btn_toggle_mic)

        # Nút Camera (Chỉ hiện khi Video Call)
        self.btn_toggle_cam = QPushButton("📷")
        self.btn_toggle_cam.setToolTip("Bật/Tắt Camera")
        self.btn_toggle_cam.clicked.connect(self.on_toggle_cam)
        if self.is_video:
            ctrl_layout.addWidget(self.btn_toggle_cam)
        else:
            self.btn_toggle_cam.setVisible(False)

        # Nút Trả lời (chỉ hiện khi có cuộc gọi đến)
        self.btn_answer = QPushButton("📞")
        self.btn_answer.setObjectName("btn_answer")
        self.btn_answer.clicked.connect(self.on_answer_clicked)
        if not self.is_incoming:
            self.btn_answer.setVisible(False)
        else:
            ctrl_layout.addWidget(self.btn_answer)

        # Nút Kết thúc
        self.btn_end = QPushButton("❌") # Hoặc icon điện thoại gác máy
        self.btn_end.setObjectName("btn_end")
        self.btn_end.setToolTip("Kết thúc")
        self.btn_end.clicked.connect(self.on_end_clicked)
        ctrl_layout.addWidget(self.btn_end)

        # --- LOGIC RESIZE (Để giữ vị trí các layer) ---
        self.cb_speaker.currentIndexChanged.connect(self.restart_audio_stream)
        self.populate_devices()
        self.populate_speakers()
        if not self.is_video: self.cb_camera.setEnabled(False)

    def resizeEvent(self, event: QResizeEvent):
        """
        Hàm này được gọi mỗi khi cửa sổ thay đổi kích thước.
        Dùng để tính toán vị trí tuyệt đối (Absolute Positioning) cho các widget nổi.
        """
        w = self.width()
        h = self.height()

        # 1. Remote Video: Tràn màn hình
        self.remote_video.setGeometry(0, 0, w, h)

        # 2. Local Video: Góc phải dưới, cách lề 20px
        # Kích thước local video
        lw, lh = 180, 240 
        self.local_video.setGeometry(w - lw - 20, h - lh - 100, lw, lh) # Trừ 100px ở dưới để không che nút

        # 3. Top Bar: Ở trên cùng, căn giữa, cách lề trên 20px
        top_w = min(600, w - 40)
        top_h = 50
        self.top_bar.setGeometry((w - top_w) // 2, 20, top_w, top_h)

        # 4. Controls Bar: Ở dưới cùng, căn giữa, cách lề dưới 30px
        ctrl_w = min(400, w - 40)
        ctrl_h = 80
        self.controls_bar.setGeometry((w - ctrl_w) // 2, h - ctrl_h - 20, ctrl_w, ctrl_h)

        super().resizeEvent(event)

    # --- CÁC HÀM LOGIC XỬ LÝ ---

    def on_toggle_mic(self):
        self.is_mic_muted = not self.is_mic_muted
        if self.is_mic_muted:
            self.btn_toggle_mic.setText("🔇") # Icon Mic gạch chéo
            self.btn_toggle_mic.setStyleSheet("background-color: white; color: black;") # Đảo màu cho nổi bật
            self.webrtc.set_audio_enabled(False)
        else:
            self.btn_toggle_mic.setText("🎙️")
            self.btn_toggle_mic.setStyleSheet("background-color: rgba(60, 60, 60, 0.9); color: white;")
            self.webrtc.set_audio_enabled(True)

    def on_toggle_cam(self):
        self.is_cam_muted = not self.is_cam_muted
        if self.is_cam_muted:
            self.btn_toggle_cam.setText("🚫") # Icon Cam gạch chéo
            self.btn_toggle_cam.setStyleSheet("background-color: white; color: black;")
            self.webrtc.set_video_enabled(False)
            # Làm mờ local video
            self.local_video.setPixmap(QPixmap())
            self.local_video.setText("Camera Tắt")
            self.local_video.setStyleSheet("background-color: #000; color: white; border: 2px solid #444; border-radius: 12px; qproperty-alignment: AlignCenter;")
        else:
            self.btn_toggle_cam.setText("📷")
            self.btn_toggle_cam.setStyleSheet("background-color: rgba(60, 60, 60, 0.9); color: white;")
            self.webrtc.set_video_enabled(True)
            # Reset style local video
            self.local_video.setText("")
            self.local_video.setStyleSheet("background-color: #333; border: 2px solid #444; border-radius: 12px;")

    # ... (Phần dưới giữ nguyên logic cũ, chỉ sửa update_remote_video nếu cần) ...

    def populate_devices(self):
        self.cb_camera.clear()
        self.cb_mic.clear()
        self.cb_camera.addItem("Mặc định")
        self.cb_mic.addItem("Mặc định")
        try:
            proc = subprocess.run(["ffmpeg", "-list_devices", "true", "-f", "dshow", "-i", "dummy"], capture_output=True, text=True, encoding="utf-8")
            out = proc.stderr
            for line in out.splitlines():
                if "dshow @" in line and '"' in line:
                    m = re.search(r'"([^"]+)"', line)
                    if m:
                        name = m.group(1)
                        if "(video)" in line: self.cb_camera.addItem(name)
        except: pass
        try:
            devices = sd.query_devices()
            unique_mics = set()
            for d in devices:
                if d['max_input_channels'] > 0:
                    name = d['name']
                    if name not in unique_mics:
                        unique_mics.add(name)
                        self.cb_mic.addItem(name)
        except: pass

    def populate_speakers(self):
        self.cb_speaker.blockSignals(True)
        self.cb_speaker.clear()
        self.cb_speaker.addItem("Mặc định")
        try:
            devices = sd.query_devices()
            unique_spk = set()
            for i, d in enumerate(devices):
                if d['max_output_channels'] > 0:
                    name = d['name']
                    if name not in unique_spk:
                        unique_spk.add(name)
                        self.cb_speaker.addItem(f"{i}: {name}")
        except: pass
        self.cb_speaker.blockSignals(False)

    def audio_callback(self, outdata, frames, time, status):
        try:
            data = self.audio_queue.get_nowait()
            chunk_len = len(data)
            if chunk_len < len(outdata):
                outdata[:chunk_len] = data
                outdata[chunk_len:] = 0
            else:
                outdata[:] = data[:len(outdata)]
        except queue.Empty:
            outdata.fill(0)
        except Exception:
            outdata.fill(0)

    def restart_audio_stream(self):
        if self.audio_stream:
            self.audio_stream.stop()
            self.audio_stream.close()
            self.audio_stream = None

        spk_text = self.cb_speaker.currentText()
        device_id = None
        if ":" in spk_text:
            try: device_id = int(spk_text.split(":")[0])
            except: pass
        
        try:
            self.audio_stream = sd.OutputStream(
                samplerate=48000,
                channels=2, 
                dtype='int16',
                device=device_id,
                callback=self.audio_callback,
                blocksize=960 
            )
            self.audio_stream.start()
        except Exception as e:
            print(f"[Audio] ❌ Lỗi loa: {e}")

    def queue_audio_data(self, data_numpy):
        try:
            data = data_numpy.astype(np.int16)
            if data.ndim == 1: data = data.reshape(-1, 1)
            if data.shape[1] == 1: data = np.tile(data, (1, 2))
            self.audio_queue.put(data, block=False)
        except queue.Full: pass

    def get_selected_devices(self):
        cam = self.cb_camera.currentText() if self.cb_camera.currentIndex() > 0 else None
        mic = self.cb_mic.currentText() if self.cb_mic.currentIndex() > 0 else None
        return cam, mic

    def prepare_webrtc_devices(self):
        cam, mic = self.get_selected_devices()
        self.webrtc.camera_name = cam
        self.webrtc.mic_name = mic

    def update_remote_video(self, img_array):
        if not self.is_video: return
        self._safe_draw_frame(img_array, self.remote_video)

    def update_local_video(self, img_array):
        if not self.is_video: return
        if self.is_cam_muted: return
        self._safe_draw_frame(img_array, self.local_video)

    def _safe_draw_frame(self, img_array, target_label):
        if target_label is None or not target_label.isVisible(): return
        try:
            img_data = np.ascontiguousarray(img_array)
            h, w, ch = img_data.shape
            bytes_per_line = ch * w
            qimg = QImage(img_data.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()
            pix = QPixmap.fromImage(qimg)
            
            # Với remote video (full screen), ta để setScaledContents lo (nhưng aspect ratio có thể bị méo)
            # Nếu muốn giữ tỉ lệ chuẩn (có viền đen), dùng logic scale thủ công:
            if target_label == self.remote_video:
                target_label.setPixmap(pix) # Label đã setScaledContents(True)
            else:
                # Local video (PiP) thường cần fill đầy khung
                # Ở đây ta cứ setPixmap, Label sẽ tự scale
                target_label.setPixmap(pix)
        except Exception:
            pass

    def on_answer_clicked(self):
        self.btn_answer.setVisible(False)
        self.setWindowTitle("Đang kết nối...")
        self.prepare_webrtc_devices()
        reply = {"kind": "accept", "is_video": self.is_video, "to": self.partner_username}
        if self.mode == "group": reply["conversation_id"] = self.conv_id
        try:
            if self.main.sock: self.main.sock.sendall(make_packet("call_signal", reply))
        except: pass

    def on_end_clicked(self):
        try:
            data = {"kind": "bye", "is_video": self.is_video}
            if self.mode == "private": data["to"] = self.peers[0] if self.peers else None
            else: data["conversation_id"] = getattr(self.main, "current_group_id", None)
            if self.main.sock: self.main.sock.sendall(make_packet("call_signal", data))
        except: pass

        if self.audio_stream:
            self.audio_stream.stop()
            self.audio_stream.close()
        if self.webrtc:
            self.webrtc.close()
        self.accept()