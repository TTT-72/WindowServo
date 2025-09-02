# WindoWServoシステム
- 当システムは近年多発するゲリラ豪雨を雨センサーで感知し、自動で窓を閉めて室内を保護します。
- また合わせて音声によるハンズフリー操作を搭載し、手が離せない状況でも窓の開放をコントロールします。<br>
**ESP32**による雨感知とモーター制御による自動窓閉鎖機能。<br>
**RaspberryPi**に搭載したローカルAIによる音声認識とLLM-API(ChatGPT5mini-Chat Completions API)を組み合わせた、ファジーな命令でも動作する開放機能が特徴です。

---

## 使用技術

| 技術スタック | 詳細 |
| :--- | :--- |
| **ハードウェア** | **RaspberryPi4**<br>[**ESP32-CherryIoT**](images/ESP32.jpg) * 2 (学習教材として[**こちら**](https://github.com/DenkiJoshi/ESP32CherryIoT)の機器をお借りして使用しています。)<br>**USB Mic**(市販マイク)<br>**Crowtail Water Sensor 2.0**(抵抗値計測型水センサー)<br>**MicroServoSG90**(サーボモーター)<br>**Crowtail Button 2.0**(ボタンスイッチ)|
| **使用言語** | **Python3**<br>**Aruduino C++** |
| **使用AI・ローカルモデル** | **Vosk** |
| **使用AI・開発支援**<br>(コード生成支援) | **Claude Sonnet4**<br>**Gemini 2.5**<br>**Chat-GPT5** |
| **使用AI・API** | **OpenAI-API**(GPT5-mini, Chat Completions API) |

---

## 動作原理

このシステムはESP32が管轄する閉鎖機能部AとRaspberryPI4が管轄する開放機能部B、二つの動作を行います。

A.　雨センサーによる雨対策機能

    1.　雨(水分)を検知:

      　 抵抗値約580kΩ以下で雨が降ったと判断し、全閉動作のトリガーとする。
    
    2.　窓を閉鎖(サーボモーター制御):
  
      　 ESP内部で全閉動作を行う。今回はデモ用模型を用い、モーターの角度制御系もそれに合わせる形で実装。 
    
B.  音声認識による窓開放制御機能

    1.　音声認識:
        

      　　 


