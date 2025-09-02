#include <ESP32Servo.h> //ESP32Servo by Kevin Harrington
#include <ArduinoJson.h> // ArduinoJsonライブラリをインクルード
#include <EEPROM.h> // 電源を切ってもデータが消えない不揮発性メモリー

const int rainsnsrPin = 3;  // 雨センサーが接続されているピン (GPIO3, ConnectorA)
const int motorPin = 4;     // サーボモーターが接続されているピン (GPIO4, ConnectorB)

// EEPROM設定
#define EEPROM_SIZE 512    // EEPROM使用サイズ（バイト）
#define ANGLE_ADDRESS 0    // 角度データの保存アドレス
#define MAGIC_ADDRESS 4    // マジックナンバーの保存アドレス（初回起動判定用）
#define MAGIC_NUMBER 0xABCD1234  // 初期化済みを示すマジックナンバー

Servo myservo;
unsigned long startTime;         //プログラム開始時刻や処理開始時刻を記録
int currentAngle = 0;            // 現在の角度
int targetAngle = 0;             // 目標角度
bool motorRunning = false;      //サーボモーターが動作中かどうかを示すフラグ(テスト用強制停止、再度復旧用)
unsigned long lastMoveTime = 0; //最後にサーボモーターを動かした時刻を記録
const int moveInterval = 50;    // ミリ秒（動作速度）

// 緊急停止フラグ
bool emergencyStop = false;

// 雨センサー関連
int threshold = 1500;           // 水あり/なしのしきい値。この値より小さいと「雨あり」と判定。
int dryThreshold = 4000;        // 雨が止んだ判定のしきい値。この値以上で「雨が完全に止んだ」と判定。
bool wasRaining = false;        // 前回のループで雨が降っていたかどうかを記録する変数。
bool rainSensorActive = true;   // 雨センサーが有効かどうか
bool rainDetected = false;      // 雨が検知されたかどうか

// 設定: 角度の値をここで簡単に変更できます
const int MAX_WINDOW_ANGLE = 112;  // 窓の最大開度（この値を変更するだけで全体に反映されます）
const int MIN_WINDOW_ANGLE = 0;    // 窓の最小開度（通常は0度)

// 窓の状態定義（パーセンテージ）
const int WINDOW_CLOSED_PERCENT = 0;    // 完全に閉まった状態 (0%)
const int WINDOW_HALF_PERCENT = 50;     // 半開き状態 (50%)
const int WINDOW_OPEN_PERCENT = 100;    // 完全に開いた状態 (100%)

// 窓の状態定義（角度） - MAX_WINDOW_ANGLEから自動計算
const int WINDOW_CLOSED = MIN_WINDOW_ANGLE;                                  // 完全に閉まった状態
const int WINDOW_HALF = MIN_WINDOW_ANGLE + (MAX_WINDOW_ANGLE * 50 / 100);    // 半開き状態（50%）
const int WINDOW_OPEN = MAX_WINDOW_ANGLE;                                    // 完全に開いた状態

/**
 * @brief EEPROMから前回の角度を読み込む
 * @return 保存されている角度値（無効な場合は-1）
 */
int loadAngleFromEEPROM() {
  // マジックナンバーをチェック
  uint32_t magic = 0;
  EEPROM.get(MAGIC_ADDRESS, magic);
  
  if (magic != MAGIC_NUMBER) {
    Serial.println("EEPROM未初期化 - デフォルト値を使用");
    return -1; // 未初期化
  }
  
  int savedAngle = 0;
  EEPROM.get(ANGLE_ADDRESS, savedAngle);
  
  // 角度の範囲チェック
  if (savedAngle < MIN_WINDOW_ANGLE || savedAngle > MAX_WINDOW_ANGLE) {
    Serial.println("EEPROM角度データが無効 - デフォルト値を使用");
    return -1; // 無効な値
  }
  
  Serial.println("EEPROM読み込み成功: " + String(savedAngle) + "度");
  return savedAngle;
}

/**
 * @brief 現在の角度をEEPROMに保存
 * @param angle 保存する角度
 */
void saveAngleToEEPROM(int angle) {
  // 角度の範囲チェック
  if (angle < MIN_WINDOW_ANGLE || angle > MAX_WINDOW_ANGLE) {
    Serial.println("EEPROM保存エラー: 角度が範囲外 (" + String(angle) + "度)");
    return;
  }
  
  // 現在保存されている値と同じ場合は書き込みをスキップ（フラッシュ寿命保護）
  int currentSaved = 0;
  EEPROM.get(ANGLE_ADDRESS, currentSaved);
  
  if (currentSaved == angle) {
    return; // 既に同じ値が保存されている
  }
  
  // 角度を保存
  EEPROM.put(ANGLE_ADDRESS, angle);
  
  // マジックナンバーを保存（初期化済みマーク）
  uint32_t magic = MAGIC_NUMBER;
  EEPROM.put(MAGIC_ADDRESS, magic);
  
  // EEPROM書き込み実行
  if (EEPROM.commit()) {
    Serial.println("EEPROM保存完了: " + String(angle) + "度");
  } else {
    Serial.println("EEPROM保存エラー");
  }
}

/**
 * @brief EEPROM初期化（デバッグ用）
 */
void clearEEPROM() {
  for (int i = 0; i < EEPROM_SIZE; i++) {
    EEPROM.write(i, 0xFF);
  }
  EEPROM.commit();
  Serial.println("EEPROM初期化完了");
}

/**
 * @brief 目的の物理的な開度パーセンテージ（0-100）を受け取り、
 * サーボモーターに実際にコマンドすべき補正されたパーセンテージを計算します。
 *
 * 観測データ（指示50%->実際40%、指示60%->実際50%、指示80%->実際75%、指示100%->実際100%）に基づき、
 * 線形補正式: command = (actual + 25) * 0.8 を適用します。
 *
 * ただし、0%と100%は特別扱いして補正なしで返します（境界値保護）。
 *
 * @param desiredActualPercent ユーザーが意図する物理的な窓の開度パーセンテージ (0-100)。
 * @return サーボに指示すべき補正されたパーセンテージ (0-100)。
 */
float getCommandPercent(int desiredActualPercent) {
  // 境界値の特別処理
  if (desiredActualPercent == 0) {
    return 0.0; // 完全に閉じる場合は補正なし
  }
  if (desiredActualPercent == 100) {
    return 100.0; // 完全に開く場合は補正なし
  }
  
  // 中間値の補正計算
  float adjustedCommandPercent = (desiredActualPercent + 25.0) * 0.8;

  // コマンドパーセンテージが0%未満または100%を超える場合は範囲内に制限
  if (adjustedCommandPercent > 100.0) {
    adjustedCommandPercent = 100.0;
  }
  if (adjustedCommandPercent < 0.0) {
    adjustedCommandPercent = 0.0;
  }
  return adjustedCommandPercent;
}

void recordPosition(String action, int current, int target) {
  unsigned long currentTime = millis();
  unsigned long elapsedTime = currentTime - startTime;
  
  Serial.print(elapsedTime);
  Serial.print("ms,");
  Serial.print(action);
  Serial.print(",");
  Serial.print(current);
  Serial.print("度,");
  Serial.print(target);
  Serial.println("度");
}

void startMovement(int newTarget) {
  // 緊急停止中は新しい動作を開始しない
  if (emergencyStop) {
    Serial.println("★★★ システム停止中 ★★★");
    Serial.println("動作を開始できません。'resume' または 'r' で復旧してください。");
    return;
  }
  
  if (newTarget < MIN_WINDOW_ANGLE) newTarget = MIN_WINDOW_ANGLE;
  if (newTarget > MAX_WINDOW_ANGLE) newTarget = MAX_WINDOW_ANGLE; // 最大値を設定値に制限
  
  if (newTarget != currentAngle) {
    targetAngle = newTarget;
    motorRunning = true;
    
    String windowState = "";
    if (targetAngle == WINDOW_CLOSED) windowState = "完全に閉める (0%)";
    else if (targetAngle == WINDOW_HALF) windowState = "半分開ける (50%)";
    else if (targetAngle == WINDOW_OPEN) windowState = "完全に開ける (100%)";
    else {
      // 角度からパーセンテージを逆算
      int percent = map(targetAngle, MIN_WINDOW_ANGLE, MAX_WINDOW_ANGLE, 0, 100);
      windowState = "指定位置(" + String(percent) + "%, " + String(targetAngle) + "度)まで移動";
    }
    
    recordPosition("移動開始: " + windowState, currentAngle, targetAngle);
  } else {
    Serial.println("既に目標位置にいます: " + String(currentAngle) + "度");
  }
}

void executeClose100(String reason) {
  // close100コマンドを実行（完全に閉める = 0%開度）
  int newTarget = MIN_WINDOW_ANGLE; // 完全に閉じた位置
  
  Serial.println(reason + " → close100実行: 現在" + String(currentAngle) + "度から" + String(newTarget) + "度(完全に閉じる)まで移動");
  startMovement(newTarget);
}

//@brief 緊急停止機能 - 現在の動作を即座に停止
void executeEmergencyStop() {
  // モーターの動作を即座に停止
  motorRunning = false;
  targetAngle = currentAngle; // 目標角度を現在の角度に設定
  emergencyStop = true; // 緊急停止状態を維持
  
  // 現在位置でサーボを固定
  myservo.write(currentAngle);
  
  // 緊急停止位置をEEPROMに保存
  saveAngleToEEPROM(currentAngle);
  
  recordPosition("【緊急停止】", currentAngle, currentAngle);
  Serial.println("★★★ 緊急停止実行 - 現在位置で停止しました ★★★");
  Serial.println("現在位置: " + String(currentAngle) + "度");
  Serial.println("★★★ システム停止中 - 'resume' または 'r' で復旧してください ★★★");
}

//システム復旧機能 - 緊急停止状態から復帰
void executeResume() {
  if (emergencyStop) {
    emergencyStop = false;
    motorRunning = false;
    
    recordPosition("【システム復旧】", currentAngle, currentAngle);
    Serial.println("★★★ システム復旧完了 - 通常動作可能になりました ★★★");
    Serial.println("現在位置: " + String(currentAngle) + "度");
    Serial.println("コマンド受付再開:");
    Serial.println("  - 雨センサー自動制御: 再開");
    Serial.println("  - 手動コマンド: 受付可能");
    Serial.println("  - 緊急停止: stop/s で再度停止可能");
  } else {
    Serial.println("システムは既に正常動作中です。");
  }
}

// 雨センサー関連の関数群（windowServo0から完全に移植）
void checkRainSensor() {
  // 緊急停止中は雨センサーも停止
  if (emergencyStop) {
    return;
  }
  
  // 雨センサーが有効でない場合は処理しない
  if (!rainSensorActive) {
    return;
  }
  
  int value = analogRead(rainsnsrPin); // 雨センサーからのアナログ値を読み取る
  
  // センサー値がしきい値より小さい場合、雨が降っていると判断
  if (value < threshold) {
    // シリアルモニターにセンサー値を表示（雨検知時のみ）
    Serial.print("雨センサー値: ");
    Serial.print(value);
    Serial.print(" (センサー状態: ");
    Serial.print(rainSensorActive ? "有効" : "無効");
    Serial.println(")");
    
    // 現在雨が降っていて、かつ前回のループでは雨が降っていなかった場合（雨が降り始めた瞬間）
    if (!wasRaining) {
      Serial.println("★★★ 雨検知！自動でclose100実行 ★★★");
      delay(3000);  //センサーディレイ
      executeClose100("雨検知");
      wasRaining = true; // 雨が降っている状態に更新
      rainDetected = true; // 雨が検知されたことを記録
      
      // 雨センサーを一時的に無効化
      rainSensorActive = false;
      Serial.println("★★★ 雨センサー一時停止 - 音声認識コマンドのみ受付 ★★★");
      Serial.println("（センサー値が4000以上になったら自動で雨センサー再開します）");
    } else {
      Serial.println("雨継続中");
    }
  }
  // センサー値がしきい値以上の場合、雨が降っていないと判断
  else {
    // 通常時（雨が降っていない時）はシリアル出力を抑制
    // 雨が降り始めた時と止んだ時のみ重要なメッセージを表示
    
    // 現在雨が降っておらず、かつ前回のループでは雨が降っていた場合（雨が止んだ瞬間）
    if (wasRaining) {
      Serial.print("雨が弱くなりました（センサー値: ");
      Serial.print(value);
      Serial.println("） - 完全な乾燥待ち");
      wasRaining = false; // 雨が降っていない状態に更新
      // rainDetected は維持（完全乾燥まで音声操作優先を継続）
    }
  }
}

void checkRainSensorReactivation() {
  // 雨センサーが無効で、かつ雨が検知されていた場合のみチェック
  if (!rainSensorActive && rainDetected) {
    int value = analogRead(rainsnsrPin);
    
    // センサー値が4000以上（雨が完全に止んだ）の場合
    if (value >= dryThreshold) {
      // 雨センサーを再有効化
      rainSensorActive = true;
      rainDetected = false;
      wasRaining = false;
      Serial.println("★★★ 雨センサー再開 - 再び雨検知可能になりました ★★★");
      Serial.print("現在のセンサー値: ");
      Serial.print(value);
      Serial.println(" (完全に乾燥状態を確認)");
    } else {
      // まだ雨センサー値が低い場合は音声操作優先を継続
      static unsigned long lastDryCheck = 0;
      if (millis() - lastDryCheck >= 5000) { // 5秒ごとに状態を報告
        Serial.print("音声操作優先モード継続中 - センサー値: ");
        Serial.print(value);
        Serial.print(" (乾燥判定には");
        Serial.print(dryThreshold);
        Serial.println("以上が必要)");
        lastDryCheck = millis();
      }
    }
  }
}

void clearSerialBuffer() {
  // シリアルバッファを完全にクリア
  while (Serial.available()) {
    Serial.read();
  }
}

void processStringCommand(String command) {
  command.trim(); // 空白文字を削除
  command.toLowerCase(); // 小文字に変換
  
  if (command.length() > 0) {
    // デバッグ用：受信したコマンドを表示
    Serial.println("受信コマンド: '" + command + "' (長さ: " + String(command.length()) + ")");
    
    // EEPROM関連コマンドの追加
    if (command == "eeprom_clear") {
      clearEEPROM();
      return;
    }
    
    if (command == "eeprom_status") {
      int savedAngle = loadAngleFromEEPROM();
      if (savedAngle >= 0) {
        Serial.println("EEPROM保存済み角度: " + String(savedAngle) + "度");
      } else {
        Serial.println("EEPROM未初期化または無効なデータ");
      }
      Serial.println("現在角度: " + String(currentAngle) + "度");
      return;
    }
    
    // 緊急停止コマンドの最優先チェック
    if (command == "stop" || command == "s") {
      executeEmergencyStop();
      return;
    }
    
    // 復旧コマンドのチェック
    if (command == "resume" || command == "r") {
      executeResume();
      return;
    }
    
    // 単一文字や意味のない入力を無視（緊急停止以外）
    if (command.length() == 1 && command != "s") {
      Serial.println("無効な入力: 単一文字 '" + command + "' は無視されました");
      Serial.println("有効なコマンド: open0~open100, close0~close100, 0~100, stop, s");
      return;
    }
    
    // 英字のみで構成された無効なコマンドをチェック
    bool isAllAlpha = true;
    bool hasValidCommand = false;
    
    // 有効なコマンドの開始パターンをチェック
    if (command.startsWith("open") || command.startsWith("close")) {
      hasValidCommand = true;
    } else {
      // 数値のみかチェック
      for (int i = 0; i < command.length(); i++) {
        if (!isdigit(command[i])) {
          isAllAlpha = false;
          break;
        }
      }
      if (isAllAlpha && command.toInt() >= 0 && command.toInt() <= 100) {
        hasValidCommand = true;
      }
    }
    
    // 無効なアルファベットのみのコマンドを検出
    if (!hasValidCommand && command != "stop" && command != "s") {
      Serial.println("エラー: 無効なコマンド '" + command + "'");
      Serial.println("有効なコマンド:");
      Serial.println("  open0~open100  : 窓を指定開度%まで開ける（絶対位置）");
      Serial.println("  close0~close100: 窓を指定閉度%まで閉める（絶対位置）");
      Serial.println("  0~100          : 絶対位置指定(%）");
      Serial.println("  stop または s  : 緊急停止");
      Serial.println("  eeprom_clear   : EEPROM初期化");
      Serial.println("  eeprom_status  : EEPROM状態確認");
      return;
    }
    
    // コマンドの解析
    if (command.startsWith("open")) {
      // "open"コマンドの処理
      String percentStr = command.substring(4); // "open"の後の数値を取得
      
      // 数値部分の検証
      if (percentStr.length() == 0) {
        Serial.println("エラー: open後に数値が必要です (例: open50)");
        return;
      }
      
      // 数値のみかチェック
      for (int i = 0; i < percentStr.length(); i++) {
        if (!isdigit(percentStr[i])) {
          Serial.println("エラー: open後は数値のみ指定してください '" + percentStr + "'");
          return;
        }
      }
      
      int percentValue = percentStr.toInt();
      
      if (percentValue >= 0 && percentValue <= 100) {
        // openコマンドは絶対位置指定
        // ユーザーが意図する物理的な絶対開度パーセンテージをgetCommandPercentで補正し、
        // その後、補正されたパーセンテージを角度に変換します。
        float correctedPercent = getCommandPercent(percentValue);
        int newTarget = map(correctedPercent, 0, 100, MIN_WINDOW_ANGLE, MAX_WINDOW_ANGLE);
        
        Serial.println("コマンド実行: open" + String(percentValue) + "% → 絶対位置" + String(newTarget) + "度まで移動 (補正: " + String(correctedPercent, 1) + "%)");
        startMovement(newTarget);
      } else {
        Serial.println("エラー: 無効なopen値 '" + percentStr + "'");
        Serial.println("有効な範囲: open0 ~ open100");
      }
      
    } else if (command.startsWith("close")) {
      // "close"コマンドの処理
      String percentStr = command.substring(5); // "close"の後の数値を取得
      
      // 数値部分の検証
      if (percentStr.length() == 0) {
        Serial.println("エラー: close後に数値が必要です (例: close50)");
        return;
      }
      
      // 数値のみかチェック
      for (int i = 0; i < percentStr.length(); i++) {
        if (!isdigit(percentStr[i])) {
          Serial.println("エラー: close後は数値のみ指定してください '" + percentStr + "'");
          return;
        }
      }
      
      int percentValue = percentStr.toInt();
      
      if (percentValue >= 0 && percentValue <= 100) {
        // closeコマンドも絶対位置指定
        // close50 = 50%閉じた状態 = 50%開いた状態として解釈
        int openPercent = 100 - percentValue; // close50 → open50相当
        float correctedPercent = getCommandPercent(openPercent);
        int newTarget = map(correctedPercent, 0, 100, MIN_WINDOW_ANGLE, MAX_WINDOW_ANGLE);
        
        Serial.println("コマンド実行: close" + String(percentValue) + "% → 絶対位置" + String(newTarget) + "度(" + String(openPercent) + "%開度) (補正: " + String(correctedPercent, 1) + "%)");
        startMovement(newTarget);
      } else {
        Serial.println("エラー: 無効なclose値 '" + percentStr + "'");
        Serial.println("有効な範囲: close0 ~ close100");
      }
      
    } else {
      // 従来の数値コマンド（絶対位置指定）の処理
      // 数値のみかどうかを再度確認
      bool isNumeric = true;
      for (int i = 0; i < command.length(); i++) {
        if (!isdigit(command[i])) {
          isNumeric = false;
          break;
        }
      }
      
      if (isNumeric) {
        int percentValue = command.toInt();
        if (percentValue >= 0 && percentValue <= 100) {
          // ユーザーが意図する物理的な絶対位置パーセンテージをgetCommandPercentで補正し、
          // その後、補正されたパーセンテージを角度に変換します。
          float correctedPercent = getCommandPercent(percentValue);
          int newTarget = map(correctedPercent, 0, 100, MIN_WINDOW_ANGLE, MAX_WINDOW_ANGLE);
          Serial.println("コマンド実行: " + String(percentValue) + "% → 絶対位置" + String(newTarget) + "度 (補正: " + String(correctedPercent, 1) + "%)");
          startMovement(newTarget);
        } else {
          Serial.println("エラー: 範囲外の数値 '" + command + "'");
          Serial.println("有効な範囲: 0~100");
        }
      } else {
        Serial.println("エラー: 認識できないコマンド '" + command + "'");
        Serial.println("有効なコマンド:");
        Serial.println("  open0~open100  : 窓を指定開度%まで開ける（絶対位置）");
        Serial.println("  close0~close100: 窓を指定閉度%まで閉める（絶対位置）");
        Serial.println("  0~100          : 絶対位置指定(%）");
        Serial.println("  stop または s  : 緊急停止");
        Serial.println("  resume または r: システム復旧");
        Serial.println("  eeprom_clear   : EEPROM初期化");
        Serial.println("  eeprom_status  : EEPROM状態確認");
      }
    }
  }
}

void processCommand() {
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n'); // シリアルから1行読み取り
    command.trim(); // 前後の空白・改行を削除
    
    Serial.print("受信コマンド: ");
    Serial.println(command);
    
    // コマンドが空でないことを確認
    if (command.length() == 0) {
      Serial.println("空のコマンドです");
      return;
    }
    processStringCommand(command);
  }
}

void updateMotorPosition() {
  if (motorRunning && !emergencyStop) { // 緊急停止中は動作しない
    unsigned long currentTime = millis();
    
    // 指定された間隔でモーターを動かす
    if (currentTime - lastMoveTime >= moveInterval) {
      // 目標角度に向かって1度ずつ移動
      if (currentAngle < targetAngle) {
        currentAngle++;
      } else if (currentAngle > targetAngle) {
        currentAngle--;
      }
      
      // サーボモーターに角度を送信
      myservo.write(currentAngle);
      lastMoveTime = currentTime;
      
      // 目標角度に到達したかチェック
      if (currentAngle == targetAngle) {
        motorRunning = false;
        
        // 移動完了時にEEPROMに角度を保存
        saveAngleToEEPROM(currentAngle);
        
        String finalState = "";
        if (currentAngle == WINDOW_CLOSED) finalState = "完全に閉まりました (0%)";
        else if (currentAngle == WINDOW_HALF) finalState = "半分開きました (50%)";
        else if (currentAngle == WINDOW_OPEN) finalState = "完全に開きました (100%)";
        else {
          int percent = map(currentAngle, MIN_WINDOW_ANGLE, MAX_WINDOW_ANGLE, 0, 100);
          finalState = "指定位置に到達しました (" + String(percent) + "%, " + String(currentAngle) + "度)";
        }
        
        recordPosition("移動完了: " + finalState, currentAngle, targetAngle);
        Serial.println("待機中... (現在位置: " + String(currentAngle) + "度)");
      }
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(rainsnsrPin, INPUT); // 雨センサーピンを入力として設定
  
  // EEPROM初期化
  if (!EEPROM.begin(EEPROM_SIZE)) {
    Serial.println("EEPROM初期化失敗");
    return;
  }
  
  myservo.attach(motorPin);
  startTime = millis();
  
  Serial.println("雨センサー連携窓制御システム開始 (EEPROM対応版)");
  Serial.println("機能:");
  Serial.println("  - 雨検知時: 自動でclose100実行 → その後雨センサー一時停止");
  Serial.println("  - センサー値4000以上で完全乾燥判定 → 雨センサー再開");
  Serial.println("  - AI/ラズパイコマンド: JSONまたは文字列コマンド");
  Serial.println("  - 最大開度: " + String(MAX_WINDOW_ANGLE) + "度 (100%)");
  Serial.println("  - **サーボモーターの動きが調整されました！**");
  Serial.println("  - ★★★ 緊急停止機能追加 ★★★"); 
  Serial.println("  - ★★★ EEPROM機能追加 - 前回位置を記憶 ★★★");
  
  // EEPROMから前回の角度を読み込み
  int savedAngle = loadAngleFromEEPROM();
  
  if (savedAngle >= 0) {
    // 前回の位置が見つかった場合
    Serial.println("前回位置を復元: " + String(savedAngle) + "度");
    currentAngle = savedAngle;
    targetAngle = savedAngle;
    
    // サーボを前回の位置にゆっくり設定（急激な動きを避ける）
    myservo.write(currentAngle);
    delay(1000); // サーボが位置に到達するまで待機
    
    recordPosition("前回位置復元", currentAngle, currentAngle);
  } else {
    // 前回の位置が見つからない場合（初回起動など）
    Serial.println("初回起動またはEEPROMリセット - 閉位置で初期化");
    currentAngle = WINDOW_CLOSED;
    targetAngle = WINDOW_CLOSED;
    
    myservo.write(WINDOW_CLOSED);
    delay(1000); // サーボが位置に到達するまで待機
    
    // 初期位置をEEPROMに保存
    saveAngleToEEPROM(currentAngle);
    recordPosition("システム初期化", currentAngle, currentAngle);
  }
  
  Serial.println("コマンド:");
  Serial.println("  open0~100: 窓を指定した開度%まで開ける（絶対位置）");
  Serial.println("  close0~100: 窓を指定した閉度%まで閉める（絶対位置）");
  Serial.println("  0~100    : 絶対位置指定（0%=閉, 100%=全開" + String(MAX_WINDOW_ANGLE) + "度）");
  Serial.println("  stop     : ★ 緊急停止 - 現在の動作を即座に停止 ★");
  Serial.println("  s        : ★ 緊急停止 (短縮コマンド) ★");
  Serial.println("  resume   : ★ システム復旧 - 緊急停止状態から復帰 ★");
  Serial.println("  r        : ★ システム復旧 (短縮コマンド) ★");
  Serial.println("  eeprom_clear   : ★ EEPROM初期化 ★");
  Serial.println("  eeprom_status  : ★ EEPROM状態確認 ★");
  Serial.println("時刻,動作,現在角度,目標角度");
  Serial.println("--------------------------------");
}
  
void loop() {
  // 雨センサーの再有効化チェック（最優先）
  checkRainSensorReactivation();
  
  // 雨センサーをチェック（雨センサーが有効な場合のみ）
  static unsigned long lastSensorCheck = 0;
  if (millis() - lastSensorCheck >= 1000) { // 1秒ごとにチェック
    checkRainSensor();
    lastSensorCheck = millis();
  }
  
  // シリアル通信からのコマンド
  processCommand();
  
  // モーターの位置を更新
  updateMotorPosition();
  
  delay(5); // 短い遅延でシステムの応答性を保つ
}