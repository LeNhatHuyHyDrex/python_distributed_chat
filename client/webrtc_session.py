# client/webrtc_session.py

import asyncio
import threading
import av
import numpy as np
import traceback
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, RTCConfiguration, RTCIceServer, MediaStreamTrack
from aiortc.contrib.media import MediaPlayer, MediaRelay

# =========================================================================
# LỚP VỎ BỌC VIDEO (Để tắt camera = Gửi màn hình đen)
# =========================================================================
class MuteableVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, track):
        super().__init__()
        self.track = track
        self.muted = False # Cờ kiểm soát

    async def recv(self):
        # Luôn lấy frame từ camera thật để giữ đồng bộ thời gian (timestamps)
        frame = await self.track.recv()
        
        if self.muted:
            # Nếu đang Mute: Tạo màn hình đen
            # Cách nhanh nhất: Lấy mảng pixel, xóa về 0 (đen)
            img = frame.to_ndarray(format="rgb24")
            img.fill(0) # Tô đen toàn bộ
            
            # Tạo frame mới từ mảng đen
            new_frame = av.VideoFrame.from_ndarray(img, format="rgb24")
            new_frame.pts = frame.pts
            new_frame.time_base = frame.time_base
            return new_frame
        
        return frame

# =========================================================================
# LỚP VỎ BỌC AUDIO (Để tắt mic = Gửi âm thanh im lặng)
# =========================================================================
class MuteableAudioTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self, track):
        super().__init__()
        self.track = track
        self.muted = False

    async def recv(self):
        # Luôn lấy frame từ mic thật để giữ đồng bộ
        frame = await self.track.recv()
        
        if self.muted:
            # Nếu đang Mute: Xóa dữ liệu âm thanh về 0 (im lặng tuyệt đối)
            arr = frame.to_ndarray()
            arr.fill(0)
            
            # Tạo frame im lặng
            new_frame = av.AudioFrame.from_ndarray(arr, format=frame.format.name, layout=frame.layout.name)
            new_frame.sample_rate = frame.sample_rate
            new_frame.pts = frame.pts
            new_frame.time_base = frame.time_base
            return new_frame

        return frame

# =========================================================================
# CLASS CHÍNH
# =========================================================================
class WebRTCSession:
    def __init__(self, parent_window, is_video=True, camera_name=None, mic_name=None):
        self.parent = parent_window
        self.is_video = is_video
        self.camera_name = camera_name
        self.mic_name = mic_name

        stun_server = RTCIceServer(urls=["stun:stun.l.google.com:19302"])
        config = RTCConfiguration(iceServers=[stun_server])
        
        self.pc = RTCPeerConnection(configuration=config)
        self.relay = MediaRelay()

        self.local_video = None
        self.local_audio = None
        
        # Biến lưu trữ track vỏ bọc để điều khiển bật/tắt
        self.muteable_video = None
        self.muteable_audio = None
        
        self._local_video_track = None 

        self.audio_resampler = av.AudioResampler(format='s16', layout='stereo', rate=48000)

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self._setup_track_handlers()

        @self.pc.on("iceconnectionstatechange")
        async def on_ice_state_change():
            state = self.pc.iceConnectionState
            print(f"[WebRTC] 🧊 Trạng thái kết nối: {state}")

    # --- ĐIỀU KHIỂN BẬT/TẮT (GỌI TỪ BUTTON) ---
    def set_audio_enabled(self, enabled: bool):
        """Nếu enabled=False -> Mute (Gửi im lặng)"""
        if self.muteable_audio:
            self.muteable_audio.muted = not enabled
            print(f"[WebRTC] 🎙️ Mic Muted: {self.muteable_audio.muted}")
    
    def set_video_enabled(self, enabled: bool):
        """Nếu enabled=False -> Mute (Gửi màn hình đen)"""
        if self.muteable_video:
            self.muteable_video.muted = not enabled
            print(f"[WebRTC] 🎥 Camera Muted: {self.muteable_video.muted}")

    def _setup_track_handlers(self):
        @self.pc.on("track")
        async def on_track(track):
            print(f"[WebRTC] 📥 Nhận track từ đối phương: {track.kind}")
            
            if track.kind == "video":
                while True:
                    try:
                        frame = await track.recv()
                        img_array = frame.to_ndarray(format="rgb24")
                        
                        h, w, c = img_array.shape
                        if w > 800:
                            step = 3 if w > 1280 else 2
                            img_array = img_array[::step, ::step]

                        if hasattr(self.parent, "remote_frame_signal"):
                            self.parent.remote_frame_signal.emit(img_array)
                    except Exception:
                        break
            
            elif track.kind == "audio":
                while True:
                    try:
                        frame = await track.recv()
                        frames = self.audio_resampler.resample(frame)
                        for f in frames:
                            data_numpy = f.to_ndarray()
                            if data_numpy.ndim == 2 and data_numpy.shape[0] == 1:
                                data_numpy = data_numpy.reshape(-1, 2)
                            
                            if hasattr(self.parent, "queue_audio_data"):
                                self.parent.queue_audio_data(data_numpy)
                    except Exception:
                        break

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _async(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _consume_local_video(self):
        if not self._local_video_track: return
        while True:
            try:
                frame = await self._local_video_track.recv()
                img_array = frame.to_ndarray(format="rgb24")
                h, w, c = img_array.shape
                if w > 800:
                    step = 3 if w > 1280 else 2
                    img_array = img_array[::step, ::step]

                if hasattr(self.parent, "local_frame_signal"):
                    self.parent.local_frame_signal.emit(img_array)
            except Exception:
                break

    async def _setup_local_media(self):
        # ================== 1. CAMERA ==================
        if self.is_video:
            dev_name = self.camera_name if self.camera_name and self.camera_name != "Mặc định" else None
            options_strict = {"framerate": "30", "video_size": "640x480", "rtbufsize": "100M"}
            options_loose = {"rtbufsize": "100M"}

            # Mở Camera thật
            if not self.local_video:
                try:
                    src = f"video={dev_name}" if dev_name else "video=0"
                    self.local_video = MediaPlayer(src, format="dshow", options=options_strict)
                except: pass
            
            if not self.local_video and dev_name:
                try:
                    self.local_video = MediaPlayer(f"video={dev_name}", format="dshow", options=options_loose)
                except: pass

            # Nếu mở thành công -> Bọc vào lớp MuteableVideoTrack
            if self.local_video and self.local_video.video:
                print("[WebRTC] ✅ Camera OK -> Wrapping...")
                self.muteable_video = MuteableVideoTrack(self.local_video.video)
                
                # Dùng Relay để chia sẻ track (1 cho remote, 1 cho local preview)
                self.relay_video = self.relay.subscribe(self.muteable_video)
                
                self.pc.addTrack(self.relay_video)
                self._local_video_track = self.relay.subscribe(self.muteable_video) # Preview cũng sẽ bị đen nếu mute
                asyncio.ensure_future(self._consume_local_video())
            else:
                print("[WebRTC] ⚠️ Không mở được Camera -> RecvOnly")
                self.pc.addTransceiver("video", direction="recvonly")

        # ================== 2. MICROPHONE ==================
        dev_mic = self.mic_name if self.mic_name and self.mic_name != "Mặc định" else None
        
        # Mở Mic thật
        if not self.local_audio:
            if dev_mic:
                try: self.local_audio = MediaPlayer(f"audio={dev_mic}", format="dshow")
                except: pass
        
        if not self.local_audio:
            try: self.local_audio = MediaPlayer("audio=0", format="dshow")
            except: pass

        # Nếu mở thành công -> Bọc vào lớp MuteableAudioTrack
        if self.local_audio and self.local_audio.audio:
            print("[WebRTC] ✅ Mic OK -> Wrapping...")
            self.muteable_audio = MuteableAudioTrack(self.local_audio.audio)
            
            self.pc.addTrack(self.relay.subscribe(self.muteable_audio))
        else:
             print("[WebRTC] ⚠️ Không mở được Mic -> RecvOnly")
             self.pc.addTransceiver("audio", direction="recvonly")

    # --- SIGNALING ---
    def create_offer(self):
        async def _create():
            await self._setup_local_media()
            offer = await self.pc.createOffer()
            await self.pc.setLocalDescription(offer)
            await asyncio.sleep(1) 
            return self.pc.localDescription 
        try: return self._async(_create()).result()
        except: return None

    def create_answer(self):
        async def _answer():
            await self._setup_local_media()
            answer = await self.pc.createAnswer()
            await self.pc.setLocalDescription(answer)
            await asyncio.sleep(1)
            return self.pc.localDescription
        try: return self._async(_answer()).result()
        except: return None

    def set_remote(self, sdp, type_):
        async def _set():
            desc = RTCSessionDescription(sdp=sdp, type=type_)
            await self.pc.setRemoteDescription(desc)
        try: return self._async(_set()).result()
        except: pass
    
    def add_ice(self, candidate_dict):
        async def _add():
            cand = RTCIceCandidate(
                sdpMid=candidate_dict.get("sdpMid"),
                sdpMLineIndex=candidate_dict.get("sdpMLineIndex"),
                candidate=candidate_dict.get("candidate"),
            )
            await self.pc.addIceCandidate(cand)
        try: return self._async(_add()).result()
        except: pass

    def close(self):
        async def _close():
            if self.local_video:
                if self.local_video.video: self.local_video.video.stop()
                self.local_video = None
            if self.local_audio:
                if self.local_audio.audio: self.local_audio.audio.stop()
                self.local_audio = None
            if self._local_video_track: 
                self._local_video_track.stop()
            await self.pc.close()
            print("[WebRTC] ⏹️ Đã đóng kết nối.")
        try: return self._async(_close()).result()
        except: return None