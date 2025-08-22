#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
from voskCore import VoskSTTEngine
from outputHandler import STTOutputManager, FileOutputHandler, OpenAIAPIHandler, SimpleESP32Handler
from STWconfig import load_config

class VoskSTTController:
    """Vosk音声認識システムのメインコントローラー"""
    
    def __init__(self, model_path: str, config: dict = None):
        """
        初期化
        
        Args:
            model_path: Voskモデルのパス
            config: 設定辞書
        """
        self.model_path = model_path
        self.config = config or {}
        
        # コンポーネントの初期化
        self.stt_engine = None
        self.output_manager = STTOutputManager()
        
        # 状態管理
        self.is_running = False
        
        # 設定から出力ハンドラーを追加
        self._setup_output_handlers()
    
    def _setup_output_handlers(self):
        """設定に基づいて出力ハンドラーを設定"""
        # ESP32出力設定
        esp32_handler = None
        esp32_config = self.config.get('esp32_serial', {})
        if esp32_config.get('enabled', False):
            esp32_handler = SimpleESP32Handler(
                port=esp32_config.get('port'),
                baudrate=esp32_config.get('baudrate', 115200),
                debug=esp32_config.get('debug', True)  # デバッグモード追加
            )
            if not esp32_handler.is_connected:
                esp32_handler = None  # 接続失敗時はNoneに戻す
            # if esp32_handler.is_connected:
                # OpenAI + ESP32統合ハンドラー作成
                # openai_esp32_handler = OpenAIAPIHandlerForESP32(
                #     api_key=self.config['openai_api']['api_key'],
                #     esp32_handler=esp32_handler
                # )
                # self.output_manager.add_final_handler(openai_esp32_handler)
        
        # ファイル出力設定
        file_config = self.config.get('file_output', {})
        if file_config.get('enabled', False):
            file_path = file_config.get('path', 'stt_results.json')
            target = file_config.get('target', 'final')
            format = file_config.get('format', 'json')
            print(f"ファイル出力設定: {file_path} (対象: {target}, 形式: {format})")
            self.output_manager.add_file_handler(file_path, target, format)

        # ChatGPTAPI設定
        openai_config = self.config.get('openai_api', {})
        if openai_config.get('enabled', False):
            api_key = openai_config.get('api_key')
            model = openai_config.get('model', 'gpt-5-mini')
            target = openai_config.get('target', 'final')
            system_prompt = openai_config.get('system_prompt')
            
            if api_key and api_key != 'your-openai-api-key-here':
                print(f"OpenAI API設定: {model} (対象: {target})")
                self.output_manager.add_openai_handler(
                    api_key=api_key,
                    target=target,
                    model=model,
                    system_prompt=system_prompt,
                    esp32_handler=esp32_handler
                )
            else:
                print("警告: OpenAI APIキーが設定されていません")

    def initialize(self):
        """STTエンジンの初期化"""
        try:
            print("STTエンジン初期化中...")
            self.stt_engine = VoskSTTEngine(self.model_path)
            
            # コールバック設定
            self.stt_engine.set_callbacks(
                on_partial=self.output_manager.handle_partial_result,
                on_final=self.output_manager.handle_final_result,
                on_complete=self.output_manager.handle_complete_result,
                on_error=self._handle_error,
                on_status=self._handle_status_change
            )
            
            print("初期化完了")
            return True
            
        except Exception as e:
            print(f"初期化失敗: {e}")
            return False
    
    def _handle_error(self, error_message: str):
        """エラーハンドリング"""
        print(f"$ エラー: {error_message}")
    
    def _handle_status_change(self, status: str):
        """ステータス変更のハンドリング"""
        status_messages = {
            'listening_started': '音声認識開始',
            'listening_stopped': '音声認識停止',
            'cleaned_up': 'リソース解放完了'
        }
        
        message = status_messages.get(status, f"状態変更: {status}")
        print(message)
    
    def show_devices(self):
        """オーディオデバイス一覧表示"""
        if not self.stt_engine:
            print("エンジンが初期化されていません")
            return
        
        devices = self.stt_engine.get_audio_devices()
        print("\n=== オーディオデバイス一覧 ===")
        for device in devices:
            print(f"[{device['index']}] {device['name']} (入力ch: {device['channels']})")
        print("================================\n")
    
    def show_config(self):
        """設定表示"""
        print("\n=== 現在の設定 ===")
        print(f"モデルパス: {self.model_path}")
        
        if self.config.get('file_output', {}).get('enabled'):
            file_out = self.config['file_output']
            print(f"ファイル出力: {file_out['path']} (対象: {file_out.get('target', 'final')})")

        if self.config.get('openai_api', {}).get('enabled'):
            openai = self.config['openai_api']
            api_key_display = openai.get('api_key', '')
            if len(api_key_display) > 10:
                api_key_display = api_key_display[:7] + '...'
            print(f"OpenAI API: {openai.get('model', 'gpt-5-mini')}")
        
        print("===================\n")
    
    def show_help(self):
        """ヘルプ表示"""
        help_text = """
=== Vosk音声認識システム ===

コマンド:
  [Enter]       : 音声認識開始/停止
  [Space+Enter] : 音声認識開始/停止  
  h + [Enter]   : このヘルプを表示
  d + [Enter]   : オーディオデバイス一覧を表示
  c + [Enter]   : 現在の設定を表示
  q + [Enter]   : プログラム終了

使い方:
1. Enterキーを押してリアルタイム認識開始
2. マイクに向かって話すと即座に認識結果が表示
3. 再度Enterキーを押して認識停止

======================================
        """
        print(help_text)
    
    def run_keyboard_trigger(self):
        """キーボードトリガーモードで実行"""
        if not self.stt_engine:
            print("$ エンジンが初期化されていません")
            return
        
        self.is_running = True
        self.show_help()
        print("準備完了！コマンドを入力してください:")
        
        try:
            while self.is_running:
                user_input = input().strip().lower()
                
                if user_input == '' or user_input == ' ':
                    # 音声認識のトグル
                    if self.stt_engine.is_listening:
                        self.stt_engine.stop_listening()
                    else:
                        self.stt_engine.start_listening()
                
                elif user_input == 'h':
                    self.show_help()
                
                elif user_input == 'd':
                    self.show_devices()
                
                elif user_input == 'c':
                    self.show_config()
                
                elif user_input == 'q':
                    print("プログラムを終了します...")
                    break
                
                else:
                    print(f"不明なコマンド: '{user_input}' (h + Enter でヘルプ)")
        
        except KeyboardInterrupt:
            print("\nCtrl+C で終了")
        
        finally:
            self.cleanup()
    
    def cleanup(self):
        """リソース解放"""
        self.is_running = False
        if self.stt_engine:
            self.stt_engine.cleanup()

def main():
    """メイン関数"""
    # Voskモデルのパス設定
    model_path = "/home/pi/vosk/vosk-model-small-ja-0.22"  # 実際のパスに変更してください
    
    # モデルの存在確認
    if not os.path.exists(model_path):
        print(f"Voskモデルが見つかりません: {model_path}")
        print("model_path変数を正しいパスに変更してください。")
        return 1
    
    # 設定読み込み
    config = load_config()
    
    try:
        # コントローラー初期化
        controller = VoskSTTController(model_path, config)
        
        if not controller.initialize():
            return 1
        
        # キーボードトリガーモードで実行
        controller.run_keyboard_trigger()
        
        return 0
        
    except Exception as e:
        print(f"予期しないエラー: {e}")
        return 1

if __name__ == "__main__":
    exit(main())