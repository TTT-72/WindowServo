def load_config():
    # 設定ファイル
    config = {
        'auto_stop_seconds': 8,  # ESP32制御に変更したためNoneに設定
        
        # 録音制御用ESP32設定（新規追加）
        'recording_controller': {
            'enabled': True,
            'port': '/dev/ttyACM1',# 自動検出
            'baudrate': 115200,
            'debug': True
        },
        
        # 窓制御用ESP32設定（既存）
        'esp32_serial': {
            'enabled': True,
            'port': '/dev/ttyACM0',# 自動検出
            'baudrate': 115200,
            'target': 'final'
        },
        
        'openai_api': {
            'enabled': True,
            'api_key': 'hogehoge',  # 実際のAPIキーに変更してください
            'model': 'gpt-5-mini',  # 正しいモデル名に修正
            'target': 'final',  # 'partial', 'final', 'complete', 'all'
            'system_prompt': "あなたは窓開閉を行うIoT機器の判断AIです。テキストから窓のopen/closeと、どの程度open/closeするかを判断。json形式で開閉をaction・開閉度合い(％)をdegreeで返答してください。マイク精度が不良のため、窓開閉に一見関係しない文字列であれば音的に近いもので再解釈してjson化してください。"
        },
        
        'file_output': {
            'enabled': True,
            'path': '/home/pi/vosk/stt_results.json',
            'target': 'final',
            'format': 'json'
        }
    }
    return config