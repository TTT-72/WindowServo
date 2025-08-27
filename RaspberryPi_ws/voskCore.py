#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pyaudio
import json
import vosk
import threading
import time
import os
import queue

class VoskSTTEngine:
    """Vosk音声認識エンジンのコアクラス(非同期化)"""
    
    def __init__(self, model_path, sample_rate=16000, chunk_size=4000):
        """
        初期化
        
        Args:
            model_path: Voskモデルのパス
            sample_rate: サンプリングレート (Hz)
            chunk_size: チャンクサイズ (bytes)
        """
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        
        # コールバック関数
        self.on_partial_result = None
        self.on_final_result = None
        self.on_complete_result = None
        self.on_error = None
        self.on_status_change = None
        
        # 状態管理（スレッドセーフ）
        self._state_lock = threading.RLock()  # 再帰可能ロック
        self.is_initialized = False
        self.is_listening = False
        self.is_running = False
        self._shutdown_requested = False
        
        # タイマー機能
        self.auto_stop_timer = None
        self.auto_stop_duration = None
        self._timer_lock = threading.Lock()
        
        # 音声関連
        self.model = None
        self.recognizer = None
        self.audio_interface = None
        self.stream = None
        self.audio_thread = None
        
        # スレッド間通信用
        self._stop_event = threading.Event()
        self._result_queue = queue.Queue()
        
        # 初期化実行
        self._initialize()
    
    def _initialize(self):
        """内部初期化処理"""
        try:
            self._log("Voskモデルを読み込み中...")
            if not os.path.exists(self.model_path):
                raise FileNotFoundError(f"モデルが見つかりません: {self.model_path}")
            
            self.model = vosk.Model(self.model_path)
            self.recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate)
            
            self._log("オーディオインターフェースを初期化中...")
            self.audio_interface = pyaudio.PyAudio()
            
            # 非ブロッキングストリーム設定
            self.stream = self.audio_interface.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                input_device_index=None,
                stream_callback=None  # コールバックは使用しない
            )
            
            # 変更 最初はストリームを停止しておく
            self.stream.stop_stream()

            with self._state_lock:
                self.is_initialized = True
            self._log("初期化完了")
            
        except Exception as e:
            error_msg = f"初期化エラー: {e}"
            self._log(error_msg)
            if self.on_error:
                self.on_error(error_msg)
            raise
    
    def _log(self, message: str):
        """ログ出力（デバッグ用）"""
        print(f"[VoskEngine] {message}")
    
    def set_callbacks(self, 
                     on_partial=None,
                     on_final=None, 
                     on_complete=None,
                     on_error=None,
                     on_status=None):
        """コールバック関数の設定
        Args:
            on_partial: 部分認識結果のコールバック
            on_final: 文完成時のコールバック  
            on_complete: 認識終了時の最終結果コールバック
            on_error: エラー時のコールバック
            on_status: ステータス変更時のコールバック
        """
        if on_partial:
            self.on_partial_result = on_partial
        if on_final:
            self.on_final_result = on_final
        if on_complete:
            self.on_complete_result = on_complete
        if on_error:
            self.on_error = on_error
        if on_status:
            self.on_status_change = on_status
    
    def get_audio_devices(self):
        """利用可能な音声入力デバイスのリストを取得"""
        devices = []
        if not self.audio_interface:
            return devices
        
        for i in range(self.audio_interface.get_device_count()):
            info = self.audio_interface.get_device_info_by_index(i)
            if info['maxInputChannels'] > 0:
                devices.append({
                    'index': i,
                    'name': info['name'],
                    'channels': info['maxInputChannels']
                })
        return devices
    
    def set_auto_stop_duration(self, seconds):
        """自動停止時間を設定（Noneで無効化）"""
        with self._timer_lock:
            self.auto_stop_duration = seconds
    
    def _auto_stop_callback(self):
        """自動停止のコールバック（スレッドセーフ版）"""
        with self._state_lock:
            if self.is_listening and not self._shutdown_requested:
                self._log(f"自動停止: {self.auto_stop_duration}秒経過")
                # 直接stop_listening()を呼ばず、フラグで制御
                self._stop_event.set()
    
    def start_listening(self):
        """音声認識開始（改善版）"""
        with self._state_lock:
            if not self.is_initialized:
                raise RuntimeError("エンジンが初期化されていません")
            
            if self.is_listening:
                self._log("認識実行中")
                return
            
            # 状態リセット
            self._shutdown_requested = False
            self._stop_event.clear()
            self.is_listening = True
            self.is_running = True
            
            # 認識器をリセット
            self.recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate)

            # 変更　オーディオストリームを再開
            if not self.stream.is_active():
                self.stream.start_stream()
        
        # 音声処理スレッド開始
        self.audio_thread = threading.Thread(target=self._audio_processing_loop, daemon=True)
        self.audio_thread.start()
        
        # 自動停止タイマーの設定（安全な方法で）
        with self._timer_lock:
            if self.auto_stop_duration:
                if self.auto_stop_timer and self.auto_stop_timer.is_alive():
                    self.auto_stop_timer.cancel()
                
                self.auto_stop_timer = threading.Timer(self.auto_stop_duration, self._auto_stop_callback)
                self.auto_stop_timer.start()
                self._log(f"自動停止タイマー開始: {self.auto_stop_duration}秒")
        
        self._log("音声認識開始")
        if self.on_status_change:
            self.on_status_change("listening_started")
    
    def stop_listening(self):
        """音声認識停止（改善版）"""
        with self._state_lock:
            if not self.is_listening:
                return
            
            self._shutdown_requested = True
            self.is_listening = False
            
            # 停止イベントを設定
            self._stop_event.set()
        # オーディオストリームを停止してバッファが溜まらないようにする
        if self.stream.is_active():
            self.stream.stop_stream()

        # 自動停止タイマーをキャンセル（安全に）
        with self._timer_lock:
            if self.auto_stop_timer and self.auto_stop_timer.is_alive():
                self.auto_stop_timer.cancel()
                self.auto_stop_timer = None
        
        # スレッドの終了を待機（タイムアウト付き）
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=2.0)  # 最大2秒待機
            
            if self.audio_thread.is_alive():
                self._log("警告: 音声スレッドが2秒以内に終了しませんでした")
        
        # 最終結果を安全に取得
        self._safe_get_final_result()
        
        self._log("音声認識停止")
        if self.on_status_change:
            self.on_status_change("listening_stopped")
    
    def _safe_get_final_result(self):
        """最終結果を安全に取得"""
        try:
            if self.recognizer:
                final_result = json.loads(self.recognizer.FinalResult())
                text = final_result.get('text', '').strip()
                if text and self.on_complete_result:
                    self.on_complete_result(text)
        except Exception as e:
            if self.on_error:
                self.on_error(f"最終結果取得エラー: {e}")
    
    def _audio_processing_loop(self):
        """音声処理メインループ（改善版）"""
        try:
            while True:
                # 停止チェック（0.1秒間隔で確認）
                if self._stop_event.wait(timeout=0.01):
                    self._log("停止イベント受信 - 音声処理ループ終了")
                    break
                
                with self._state_lock:
                    if not self.is_running or not self.is_listening or self._shutdown_requested:
                        break
                
                try:
                    # 非ブロッキング読み取り（available データのみ）
                    if self.stream.get_read_available() > 0:
                        frames_to_read = min(self.stream.get_read_available(), self.chunk_size)
                        data = self.stream.read(frames_to_read, exception_on_overflow=False)
                        
                        # 音声認識処理
                        if self.recognizer.AcceptWaveform(data):
                            # 完全な文が認識された
                            result = json.loads(self.recognizer.Result())
                            text = result.get('text', '').strip()
                            
                            if text and self.on_final_result:
                                self.on_final_result(text)
                        else:
                            # 部分的な認識結果
                            partial = json.loads(self.recognizer.PartialResult())
                            text = partial.get('partial', '').strip()
                            
                            if text and self.on_partial_result:
                                self.on_partial_result(text)
                                
                except Exception as e:
                    # I/Oエラーは非致命的として処理を継続
                    if "Input overflowed" not in str(e):
                        error_msg = f"音声処理エラー: {e}"
                        self._log(error_msg)
                        if self.on_error:
                            self.on_error(error_msg)
                        break
                    
        except Exception as e:
            error_msg = f"音声処理ループ致命的エラー: {e}"
            self._log(error_msg)
            if self.on_error:
                self.on_error(error_msg)
        finally:
            self._log("音声処理ループ終了")
    
    def cleanup(self):
        """リソースの解放（改善版）"""
        self._log("リソース解放中...")
        
        with self._state_lock:
            self._shutdown_requested = True
            self.is_running = False
            self.is_listening = False
        
        # 停止イベント設定
        self._stop_event.set()
        
        # タイマー停止
        with self._timer_lock:
            if self.auto_stop_timer and self.auto_stop_timer.is_alive():
                self.auto_stop_timer.cancel()
                self.auto_stop_timer = None
        
        # スレッドの終了を待機（タイムアウト付き）
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=3.0)
        
        # 音声リソースの解放
        if self.stream:
            try:
                if self.stream.is_active():
                    self.stream.stop_stream()
                self.stream.close()
            except Exception as e:
                self._log(f"ストリーム終了エラー（無視）: {e}")
        
        if self.audio_interface:
            try:
                self.audio_interface.terminate()
            except Exception as e:
                self._log(f"PyAudio終了エラー（無視）: {e}")
        
        self._log("リソース解放完了")
        if self.on_status_change:
            self.on_status_change("cleaned_up")
    
    def __enter__(self):
        """コンテキストマネージャー"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """コンテキストマネージャー"""
        self.cleanup()