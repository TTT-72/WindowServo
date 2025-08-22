def load_config():
    # 設定ファイル
    config = {
        'auto_stop_seconds': 8,  # 4秒で自動停止（Noneで無効）
        'esp32_serial': {
            'enabled': True,
            'port': None,  # 自動検出
            'baudrate': 115200,
            'target': 'final'
        },
    	'openai_api': {
        	'enabled': True,
        	'api_key': 'hogehoge',  # APIキー・ダミー
        	'model': 'gpt-5-mini',  # または 'gpt-4'
        	'target': 'final',  # 'partial', 'final', 'complete', 'all'
        	'system_prompt': "あなたは窓開閉を行うIoT機器の判断AIです。テキストから窓のopen/closeと、どの程度open/closeするかを判断。json形式で開閉をaction・開閉度合い(％)をdegreeで返答してください。マイク精度が不良のため、窓開閉に一見関係しない文字列であれば音的に近いもので再解釈してjson化してください。"
        },
        'file_output': {
            'enabled': True,  # Trueに変更するとファイル出力有効
            'path': '/home/pi/vosk/stt_results.json',
            'target': 'final',
            'format': 'json'
        }
    }
    return config