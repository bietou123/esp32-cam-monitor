#include "esp_camera.h"
#include <WiFi.h>

// ===================
// Select camera model
// ===================
#define CAMERA_MODEL_AI_THINKER // Has PSRAM

#include "camera_pins.h"

// ===========================
// 本地配置（不入库）
// 复制 config.example.h 为 config.h 并填写
// ===========================
#if !__has_include("config.h")
#error "缺少 config.h：请把 config.example.h 复制为 config.h 并填写 WiFi 信息"
#endif
#include "config.h"

#ifdef USE_STATIC_IP
// 静态 IP 由 config.h 提供，便于反代/隧道固定指向
IPAddress local_IP(STATIC_IP_OCTETS);
IPAddress gateway(GATEWAY_OCTETS);
IPAddress subnet(SUBNET_OCTETS);
IPAddress dns1(DNS1_OCTETS);
IPAddress dns2(DNS2_OCTETS);
#endif

// 状态指示灯：复用补光灯(GPIO4)，与 app_httpd.cpp 的 LED_LEDC_CHANNEL 一致
#define STATUS_LED_CH 2
#define STATUS_LED_DUTY 50 // 闪烁亮度(0-255)，白灯很亮，调低些不刺眼

void startCameraServer();
void setupLedFlash(int pin);

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println();

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.frame_size = FRAMESIZE_UXGA;
  config.pixel_format = PIXFORMAT_JPEG; // for streaming
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.jpeg_quality = 12;
  config.fb_count = 1;

  // if PSRAM IC present, init with UXGA resolution and higher JPEG quality
  if (config.pixel_format == PIXFORMAT_JPEG) {
    if (psramFound()) {
      config.jpeg_quality = 10;
      config.fb_count = 2;
      config.grab_mode = CAMERA_GRAB_LATEST;
    } else {
      config.frame_size = FRAMESIZE_SVGA;
      config.fb_location = CAMERA_FB_IN_DRAM;
    }
  } else {
    config.frame_size = FRAMESIZE_240X240;
#if CONFIG_IDF_TARGET_ESP32S3
    config.fb_count = 2;
#endif
  }

  // camera init
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return;
  }

  sensor_t *s = esp_camera_sensor_get();
  if (s->id.PID == OV3660_PID) {
    s->set_vflip(s, 1);
    s->set_brightness(s, 1);
    s->set_saturation(s, -2);
  }
  if (config.pixel_format == PIXFORMAT_JPEG) {
    s->set_framesize(s, FRAMESIZE_VGA);
  }

#if defined(LED_GPIO_NUM)
  setupLedFlash(LED_GPIO_NUM);
#endif

  // ---- 静态 IP（可选）+ 连接 WiFi ----
#ifdef USE_STATIC_IP
  if (!WiFi.config(local_IP, gateway, subnet, dns1, dns2)) {
    Serial.println("STA Failed to configure static IP");
  }
#endif
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  Serial.print("Connecting to WiFi");
  int retry = 0;
  bool ledOn = false;
  while (WiFi.status() != WL_CONNECTED) {
    ledOn = !ledOn;
    ledcWrite(STATUS_LED_CH, ledOn ? STATUS_LED_DUTY : 0); // 连接中闪烁
    delay(300);
    Serial.print(".");
    if (++retry > 66) { // ~20s 连不上就重启再试
      Serial.println("\nWiFi connect timeout, restarting...");
      ESP.restart();
    }
  }
  ledcWrite(STATUS_LED_CH, 0); // 连上 -> 熄灭
  Serial.println("");
  Serial.println("WiFi connected");

  startCameraServer();

  Serial.print("Camera Ready! Use 'http://");
  Serial.print(WiFi.localIP());
  Serial.println("' to connect");
}

void loop() {
  static bool wasConnected = true;       // setup 末尾已连上
  static bool ledOn = false;
  static unsigned long lastReconnect = 0;

  if (WiFi.status() == WL_CONNECTED) {
    if (!wasConnected) {
      ledcWrite(STATUS_LED_CH, 0);       // 刚恢复连接 -> 熄灭(只写一次，之后不碰GPIO4，留给摄像头补光)
      wasConnected = true;
      Serial.println("WiFi reconnected");
    }
    delay(500);
  } else {
    wasConnected = false;
    ledOn = !ledOn;
    ledcWrite(STATUS_LED_CH, ledOn ? STATUS_LED_DUTY : 0); // 断开 -> 一直闪
    if (millis() - lastReconnect > 5000) {                 // 每5秒尝试重连
      Serial.println("WiFi lost, reconnecting...");
      WiFi.disconnect();
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      lastReconnect = millis();
    }
    delay(300);
  }
}
