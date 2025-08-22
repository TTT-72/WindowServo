#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pyaudio
import json
import vosk
import threading
import time
import os

class VoskSTTEngine:
    """Vosk音声認識エンジンのコアクラス"""
    
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
        
        # 状態管理
        self.is_initialized = False
        self.is_listening = False
        self.is_running = False
        
        # タイマー機能
        self.auto_stop_timer = None
        self.auto_stop_duration = None  # 秒数（Noneなら無制限）
        
        # 音声関連
        self.model = None
        self.recognizer = None
        self.audio_interface = None
        self.stream = None
        self.audio_thread = None
        
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
            
            self.stream = self.audio_interface.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size,
                input_device_index=None
            )
            
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
        """
        コールバック関数の設定
        
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
        self.auto_stop_duration = seconds
    
    def _auto_stop_callback(self):
        """自動停止のコールバック"""
        if self.is_listening:
            self._log(f"自動停止: {self.auto_stop_duration}秒経過")
            self.stop_listening()
    
    def start_listening(self):
        """音声認識開始"""
        if not self.is_initialized:
            raise RuntimeError("エンジンが初期化されていません")
        
        if self.is_listening:
            self._log("認識実行中")
            return
        
        self.is_listening = True
        self.is_running = True
        
        # 認識器をリセット
        self.recognizer = vosk.KaldiRecognizer(self.model, self.sample_rate)
        
        # 音声処理スレッド開始
        self.audio_thread = threading.Thread(target=self._audio_processing_loop, daemon=True)
        self.audio_thread.start()
        
        # 自動停止タイマーの設定
        if self.auto_stop_duration:
            self.auto_stop_timer = threading.Timer(self.auto_stop_duration, self._auto_stop_callback)
            self.auto_stop_timer.start()
            self._log(f"自動停止タイマー開始: {self.auto_stop_duration}秒")
        
        self._log("音声認識開始")
        if self.on_status_change:
            self.on_status_change("listening_started")
    
    def stop_listening(self):
        """音声認識停止"""
        if not self.is_listening:
            return
        
        self.is_listening = False
        
        # 自動停止タイマーをキャンセル
        if self.auto_stop_timer and self.auto_stop_timer.is_alive():
            self.auto_stop_timer.cancel()
            self.auto_stop_timer = None
        
        # 最終結果を取得
        if self.recognizer:
            try:
                final_result = json.loads(self.recognizer.FinalResult())
                if final_result.get('text') and self.on_complete_result:
                    self.on_complete_result(final_result['text'])
            except Exception as e:
                if self.on_error:
                    self.on_error(f"最終結果取得エラー: {e}")
        
        self._log("音声認識停止")
        if self.on_status_change:
            self.on_status_change("listening_stopped")
    
    def _audio_processing_loop(self):
        """音声処理メインループ（別スレッドで実行）"""
        try:
            while self.is_running and self.is_listening:
                try:
                    # 音声データを読み取り
                    data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                    
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
                    error_msg = f"音声処理エラー: {e}"
                    self._log(error_msg)
                    if self.on_error:
                        self.on_error(error_msg)
                    break
                    
        except Exception as e:
            error_msg = f"音声処理ループエラー: {e}"
            self._log(error_msg)
            if self.on_error:
                self.on_error(error_msg)
    
    def cleanup(self):
        """リソースの解放"""
        self._log("リソース解放中...")
        
        self.is_running = False
        self.is_listening = False
        
        # スレッドの終了を待機
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=1)
        
        # 音声リソースの解放
        if self.stream:
            try:
                self.stream.stop_stream()
                self.stream.close()
            except:
                pass
        
        if self.audio_interface:
            try:
                self.audio_interface.terminate()
            except:
                pass
        
        self._log("リソース解放完了")
        if self.on_status_change:
            self.on_status_change("cleaned_up")
    
    def __enter__(self):
        """コンテキストマネージャー"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """コンテキストマネージャー"""
        self.cleanup()