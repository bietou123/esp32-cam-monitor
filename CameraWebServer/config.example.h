#pragma once

// 复制本文件为 config.h 后填写；config.h 已在 .gitignore 中，不会被提交
#define WIFI_SSID "your-ssid"
#define WIFI_PASS "your-password"

// 可选：固定局域网 IP（便于反向代理和隧道固定指向）。
// 路由器 DHCP 保留地址同样能达到目的，二选一即可。
// #define USE_STATIC_IP
// #define STATIC_IP_OCTETS 192, 168, 1, 180
// #define GATEWAY_OCTETS   192, 168, 1, 1
// #define SUBNET_OCTETS    255, 255, 255, 0
// #define DNS1_OCTETS      192, 168, 1, 1
// #define DNS2_OCTETS      223, 5, 5, 5
