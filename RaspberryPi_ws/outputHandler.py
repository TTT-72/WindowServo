#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import serial
import serial.tools.list_ports
import requests
import json
import time
import re
import logging
from typing import Optional, Dict, Any

class OutputHandler:
    """出力ハンドラーの基底クラス"""
    
    def send(self, text, metadata=None):
        """データを送信"""
        pass

class ConsoleOutputHandler(OutputHandler):
    """コンソール出力ハンドラー"""
    
    def __init__(self, show_partial: bool = False, show_final: bool = True):
        self.show_partial = show_partial
        self.show_final = show_final
    
    def send(self, text, metadata=None):
        """コンソールに出力"""
        try:
            msg_type = metadata.get('type', 'unknown') if metadata else 'unknown'
            timestamp = time.strftime("%H:%M:%S")
            
            if msg_type == 'partial' and self.show_partial:
                print(f"\r[{timestamp}] {text:<60}", end='', flush=True)
            elif msg_type == 'final' and self.show_final:
                print(f"\n[{timestamp}] {text}")
            elif msg_type == 'complete':
                print(f"\n[{timestamp}] 最終: {text}")
            
            return True
        except Exception:
            return False

class FileOutputHandler(OutputHandler):
    """ファイル出力ハンドラー"""
    
    def __init__(self, file_path, format='json'):
        """
        Args:
            file_path: 出力ファイルパス
            format: 出力フォーマット ('json', 'text', 'csv')
        """
        self.file_path = file_path
        self.format = format.lower()
    
    def send(self, text, metadata=None):
        """ファイルに保存"""
        try:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            
            if self.format == 'json':
                data = {
                    "timestamp": timestamp,
                    "text": text
                }
                if metadata:
                    data.update(metadata)
                
                with open(self.file_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(data, ensure_ascii=False) + '\n')
                    
            elif self.format == 'text':
                with open(self.file_path, 'a', encoding='utf-8') as f:
                    f.write(f"[{timestamp}] {text}\n")            
            return True
            
        except Exception as e:
            print(f"ファイル出力エラー: {e}")
            return False
        
class SimpleESP32Handler(OutputHandler):
    """デバッグ強化版ESP32シリアル通信ハンドラー"""
    
    def __init__(self, port: str = None, baudrate: int = 115200, debug: bool = True):
        """
        Args:
            port: シリアルポート（Noneの場合は自動検出）
            baudrate: ボーレート
            debug: デバッグ情報を表示するか
        """
        self.port = port
        self.baudrate = baudrate
        self.serial_connection = None
        self.is_connected = False
        self.debug = debug
        
        # 接続試行
        self._connect()
    
    @staticmethod
    def find_esp32_port():
        """ESP32らしきポートを自動検出"""
        esp32_keywords = ['CH340', 'CP2102', 'ESP32', 'serial', 'USB Serial', 'Arduino']
        
        print("[ESP32] 利用可能なシリアルポートを検索中...")
        available_ports = []
        
        for port_info in serial.tools.list_ports.comports():
            available_ports.append(f"  {port_info.device}: {port_info.description}")
            description = port_info.description.upper()
            for keyword in esp32_keywords:
                if keyword.upper() in description:
                    print(f"[ESP32] ESP32デバイス発見: {port_info.device} ({port_info.description})")
                    return port_info.device
        
        print("[ESP32] 利用可能なポート一覧:")
        for port in available_ports:
            print(port)
        print("[ESP32] ESP32らしきデバイスが見つかりませんでした")
        return None
    
    def _connect(self):
        """ESP32への接続"""
        if not self.port:
            self.port = self.find_esp32_port()
            if not self.port:
                print("[ESP32] エラー: ESP32デバイスが見つかりません")
                return False
        
        try:
            if self.debug:
                print(f"[ESP32] 接続試行: {self.port} @ {self.baudrate}bps")
            
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=2.0,  # タイムアウトを延長
                write_timeout=2.0  # 書き込みタイムアウトも設定
            )
            
            # 接続後少し待機
            time.sleep(0.5)
            
            if self.serial_connection.is_open:
                self.is_connected = True
                print(f"[ESP32] 接続成功: {self.port}")
                
                # テスト送信
                if self.debug:
                    self._test_connection()
                
                return True
            
        except Exception as e:
            print(f"[ESP32] 接続エラー: {e}")
            return False
    
    def _test_connection(self):
        """接続テスト"""
        try:
            print("[ESP32] 接続テスト中...")
            # バッファをクリア
            self.serial_connection.reset_input_buffer()
            self.serial_connection.reset_output_buffer()
            
            # テストコマンド送信
            test_command = "test\n"
            self.serial_connection.write(test_command.encode('ascii'))
            self.serial_connection.flush()
            
            print("[ESP32] 接続テスト完了")
            
        except Exception as e:
            print(f"[ESP32] 接続テストエラー: {e}")
    
    def parse_json_to_command(self, json_response: str) -> str:
        """LLMのJSON応答をESP32コマンド形式に変換
        
        例:
        '{"action":"close","degree":20}' → "close20"
        '{"action":"open","degree":45}' → "open45"
        """
        try:
            # JSON文字列から辞書に変換
            data = json.loads(json_response.strip())
            
            # actionとdegreeを取得
            action = str(data.get('action', 'move')).lower()
            degree = int(data.get('degree', 0))
            
            # ESP32形式のコマンドを生成
            command = f"{action}{degree}"
            print(f"加工内容{command}")
            
            if self.debug:
                print(f"[ESP32] JSON変換: {json_response} → {command}")
            return command
            
        except json.JSONDecodeError:
            print(f"[ESP32] JSON解析エラー: {json_response}")
            return "move0"  # デフォルトコマンド
        
        except Exception as e:
            print(f"[ESP32] コマンド変換エラー: {e}")
            return "move0"
    
    def send_command(self, command: str, encoding_list: list = ['ascii', 'utf-8']):
        """ESP32にコマンドを送信（複数エンコーディング対応）"""
        if not self.is_connected:
            print("[ESP32] エラー: デバイスが接続されていません")
            return False
        
        try:
            command = command.strip()
            if self.debug:
                print(f"[ESP32] 送信準備: '{command}'")
            
            # 複数の改行文字パターンで試行
            newline_patterns = ['\n', '\r\n', '\r']
            
            for encoding in encoding_list:
                for newline in newline_patterns:
                    try:
                        message = command + newline
                        
                        if self.debug:
                            print(f"[ESP32] 送信試行: エンコード={encoding}, 改行={repr(newline)}")
                        
                        # バッファクリア
                        self.serial_connection.reset_output_buffer()
                        
                        # 送信
                        encoded_message = message.encode(encoding)
                        bytes_written = self.serial_connection.write(encoded_message)
                        self.serial_connection.flush()
                        
                        if self.debug:
                            print(f"[ESP32] {bytes_written}バイト送信完了: {repr(encoded_message)}")
                        
                        # 成功した場合は終了
                        print(f"[ESP32] 送信成功: {command}")
                        return True
                        
                    except UnicodeEncodeError:
                        if self.debug:
                            print(f"[ESP32] エンコードエラー: {encoding}")
                        continue
                    except Exception as e:
                        if self.debug:
                            print(f"[ESP32] 送信エラー ({encoding}, {repr(newline)}): {e}")
                        continue
            
            print(f"[ESP32] 全ての送信パターンが失敗")
            return False
            
        except Exception as e:
            print(f"[ESP32] 送信エラー: {e}")
            return False
    
    def send_raw_bytes(self, command: str):
        """生のバイト送信（最終手段）"""
        if not self.is_connected:
            print("[ESP32] エラー: デバイスが接続されていません")
            return False
        
        try:
            # 手動でバイト列を作成
            message_bytes = bytes(command, 'ascii') + b'\n'
            
            print(f"[ESP32] RAW送信: {message_bytes}")
            
            self.serial_connection.reset_output_buffer()
            bytes_written = self.serial_connection.write(message_bytes)
            self.serial_connection.flush()
            
            print(f"[ESP32] RAW送信完了: {bytes_written}バイト")
            return True
            
        except Exception as e:
            print(f"[ESP32] RAW送信エラー: {e}")
            return False
    
    def test_manual_command(self, command: str = "open20"):
        """手動テストコマンド送信"""
        print(f"[ESP32] 手動テスト開始: '{command}'")
        
        # 方法1: 通常の送信
        print("[ESP32] === 方法1: 通常送信 ===")
        result1 = self.send_command(command)
        time.sleep(1)
        
        # 方法2: RAW送信
        print("[ESP32] === 方法2: RAW送信 ===")
        result2 = self.send_raw_bytes(command)
        time.sleep(1)
        
        print(f"[ESP32] テスト結果: 通常={result1}, RAW={result2}")
    
    def test_json_and_string_commands(self):
        """JSONと文字列形式両方をテスト"""
        print(f"[ESP32] === JSON & 文字列テスト開始 ===")
        
        # JSON形式テスト
        json_command = '{"action":"open","degree":30}'
        print(f"[ESP32] JSONテスト: {json_command}")
        result1 = self.send(json_command)
        time.sleep(2)
        
        # 文字列形式テスト  
        string_command = "open20"
        print(f"[ESP32] 文字列テスト: {string_command}")
        result2 = self.send(string_command)
        time.sleep(2)
        
        print(f"[ESP32] テスト結果: JSON={result1}, 文字列={result2}")
        print("[ESP32] === テスト終了 ===")
    
    def send(self, text, metadata=None):
        """
        OutputHandlerインターフェース実装。
        LLMからの多様な応答（JSON、文字列、JSONを含む文章）を適切に処理し、
        ESP32用のシンプルなコマンドに変換して送信する。
        """
        text = str(text).strip()
        
        if self.debug:
            print(f"[ESP32] 受信データ: '{text}'")

        command_to_send = None

        # 1. テキストからJSON部分を正規表現で抽出する試み
        # 例: 「はいどうぞ ```json\n{"action": "open", "degree": 90}\n```」のような応答に対応
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        
        if json_match:
            json_str = json_match.group(0)
            if self.debug:
                print(f"[ESP32] 抽出されたJSON候補: {json_str}")
            
            # 抽出したJSONをコマンドに変換
            command_to_send = self.parse_json_to_command(json_str)
        
        # 2. JSONとして処理できなかった場合、テキスト全体がコマンドかもしれない
        if not command_to_send or command_to_send == "move0":
             # "move0"はparse_json_to_commandが失敗した時のデフォルト値
            if self.debug and json_match:
                 print("[ESP32] JSON解析に失敗したため、受信テキストをそのままコマンドとして扱います。")
            command_to_send = text

        # 最終的なコマンドを送信
        if self.debug:
            print(f"[ESP32] 最終送信コマンド: '{command_to_send}'")
        
        # "move0" はエラー時のデフォルト値なので、送信しない方が安全な場合がある
        if command_to_send and command_to_send != "move0":
             return self.send_command(command_to_send)
        else:
             print("[ESP32] 有効なコマンドが生成されなかったため、送信をスキップします。")
             return False
    
    def cleanup(self):
        """リソース解放"""
        if self.serial_connection and self.serial_connection.is_open:
            try:
                self.serial_connection.close()
                print("[ESP32] シリアル接続を閉じました")
            except:
                pass
        self.is_connected = False

# 残りのクラスは変更なし（OpenAIAPIHandler, MultiOutputHandler, STTOutputManager）
# 省略...

class OpenAIAPIHandler(OutputHandler):
    """OpenAI API出力ハンドラー"""
    
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", esp32_handler: SimpleESP32Handler = None,
                 system_prompt: str = None, timeout: int = 30, retry_count: int = 3):
        """
        Args:
            api_key: OpenAI APIキー
            model: 使用するモデル名
            system_prompt: システムプロンプト
            timeout: リクエストタイムアウト秒数
            retry_count: リトライ回数
        """
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.timeout = timeout
        self.retry_count = retry_count
        self.esp32_handler = esp32_handler
        self.api_url = "https://api.openai.com/v1/chat/completions"
        
        # セッションを使い回してパフォーマンス向上
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })
    
    def send(self, text, metadata=None):
        """OpenAI APIにSTTデータを送信してレスポンスを取得"""
        
        # OpenAI API用のペイロード作成
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system", 
                    "content": self.system_prompt
                },
                {
                    "role": "user", 
                    "content": f"音声認識結果: {text}"
                }
            ],
        }
        
        # メタデータがある場合、システムプロンプトに追加情報として含める
        if metadata:
            context_info = f"\n\n追加情報:\n"
            if metadata.get('datetime'):
                context_info += f"- 時刻: {metadata['datetime']}\n"
            if metadata.get('type'):
                context_info += f"- 認識タイプ: {metadata['type']}\n"
            payload["messages"][0]["content"] += context_info
        
        # リトライ付きで送信
        for attempt in range(self.retry_count):
            try:
                response = self.session.post(
                    self.api_url,
                    json=payload,
                    timeout=self.timeout
                )
                
                if response.status_code == 200:
                    result = response.json()
                    ai_response = result['choices'][0]['message']['content']
                    total_tokens = result['usage']['total_tokens']
                    print(f"[OpenAI] 入力: {text[:30]}...")
                    print(f"[OpenAI] AI応答: {ai_response}")
                    print(f"[OpenAI] トークン数: {total_tokens}")
                    # ESP32にJSON応答を送信（自動で変換される）
                    if self.esp32_handler:
                        success = self.esp32_handler.send(ai_response)
                        if success:
                            print("[ESP32] コマンド送信成功")
                        else:
                            print("[ESP32] コマンド送信失敗")
                    return True
                    
                elif response.status_code == 401:
                    print(f"[OpenAI] 認証エラー: APIキーを確認してください")
                    return False
                    
                elif response.status_code == 429:
                    print(f"[OpenAI] レート制限エラー (試行 {attempt + 1}/{self.retry_count})")
                    
                else:
                    error_detail = ""
                    try:
                        error_info = response.json()
                        error_detail = error_info.get('error', {}).get('message', '')
                    except:
                        error_detail = response.text
                    
                    print(f"[OpenAI] API応答エラー: {response.status_code} - {error_detail}")
                    
            except requests.exceptions.Timeout:
                print(f"[OpenAI] 送信タイムアウト (試行 {attempt + 1}/{self.retry_count})")
                
            except requests.exceptions.RequestException as e:
                print(f"[OpenAI] 送信エラー: {e} (試行 {attempt + 1}/{self.retry_count})")
            
            except json.JSONDecodeError as e:
                print(f"[OpenAI] レスポンス解析エラー: {e}")
            
            # 最後の試行でなければ少し待機（レート制限対策）
            if attempt < self.retry_count - 1:
                wait_time = 2 ** attempt  # 指数バックオフ
                time.sleep(wait_time)
        
        print(f"[OpenAI] 送信失敗 (最大試行回数に達しました): {text[:30]}...")
        return False

class MultiOutputHandler(OutputHandler):
    """複数の出力ハンドラーを統合"""
    
    def __init__(self):
        self.handlers = []
    
    def add_handler(self, handler: OutputHandler):
        """出力ハンドラーを追加"""
        self.handlers.append(handler)
    
    def remove_handler(self, handler):
        """出力ハンドラーを削除"""
        if handler in self.handlers:
            self.handlers.remove(handler)
    
    def send(self, text, metadata=None):
        """全てのハンドラーに送信"""
        results = []
        
        for handler in self.handlers:
            try:
                result = handler.send(text, metadata)
                results.append(result)
            except Exception as e:
                print(f"ハンドラーエラー: {e}")
                results.append(False)
        
        # 一つでも成功すればTrue
        return any(results)

class STTOutputManager:
    """STT出力の管理クラス"""
    
    def __init__(self):
        self.partial_handler = MultiOutputHandler()
        self.final_handler = MultiOutputHandler()
        self.complete_handler = MultiOutputHandler()
        
        # デフォルトでコンソール出力を追加
        console_handler = ConsoleOutputHandler()
        self.partial_handler.add_handler(console_handler)
        self.final_handler.add_handler(console_handler)
        self.complete_handler.add_handler(console_handler)
    
    def add_partial_handler(self, handler):
        """部分結果用ハンドラーを追加"""
        self.partial_handler.add_handler(handler)
    
    def add_final_handler(self, handler):
        """文完成結果用ハンドラーを追加"""
        self.final_handler.add_handler(handler)
    
    def add_complete_handler(self, handler):
        """最終結果用ハンドラーを追加"""
        self.complete_handler.add_handler(handler)
    
    def add_file_handler(self, file_path, target='final', format='json'):
        """ファイルハンドラーを簡単追加"""
        file_handler = FileOutputHandler(file_path, format)
        
        if target == 'partial':
            self.add_partial_handler(file_handler)
        elif target == 'final':
            self.add_final_handler(file_handler)
        elif target == 'complete':
            self.add_complete_handler(file_handler)
        elif target == 'all':
            self.add_partial_handler(file_handler)
            self.add_final_handler(file_handler)
            self.add_complete_handler(file_handler)

    def add_openai_handler(self, api_key, target='final', model='gpt-4o-mini', system_prompt=None, esp32_handler=None):
        """OpenAI APIハンドラーを簡単追加"""
        openai_handler = OpenAIAPIHandler(
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            esp32_handler=esp32_handler
        )
        
        if target == 'partial':
            self.add_partial_handler(openai_handler)
        elif target == 'final':
            self.add_final_handler(openai_handler)
        elif target == 'complete':
            self.add_complete_handler(openai_handler)
        elif target == 'all':
            self.add_partial_handler(openai_handler)
            self.add_final_handler(openai_handler)
            self.add_complete_handler(openai_handler)
    
    def add_simple_esp32_handler(self, port=None, target='final', baudrate=115200):
        """シンプルなESP32ハンドラーを追加"""
        esp32_handler = SimpleESP32Handler(port=port, baudrate=baudrate)
    
        if esp32_handler.is_connected:
            if target == 'final':
                self.add_final_handler(esp32_handler)
            elif target == 'complete':
                self.add_complete_handler(esp32_handler)
        
            return esp32_handler
        else:
            print("[ESP32] ESP32ハンドラーの作成に失敗")
            return None

    def handle_partial_result(self, text):
        """部分結果の処理"""
        self.partial_handler.send(text, {'type': 'partial'})
    
    def handle_final_result(self, text):
        """文完成結果の処理"""
        self.final_handler.send(text, {'type': 'final'})
    
    def handle_complete_result(self, text):
        """最終結果の処理"""
        self.complete_handler.send(text, {'type': 'complete'})

# テスト用の関数を追加
def test_esp32_connection(port=None):
    """ESP32接続テスト用関数"""
    print("=== ESP32接続テスト開始 ===")
    
    esp32 = SimpleESP32Handler(port=port, debug=True)
    
    if esp32.is_connected:
        print("接続成功！手動テストを実行します...")
        
        # 基本テスト
        esp32.test_manual_command("open20")
        time.sleep(2)
        esp32.test_manual_command("close50")
        time.sleep(2)
        
        # JSON & 文字列テスト
        esp32.test_json_and_string_commands()
        
        esp32.cleanup()
    else:
        print("接続失敗")
    
    print("=== テスト終了 ===")

if __name__ == "__main__":
    # 単体テスト実行
    test_esp32_connection()