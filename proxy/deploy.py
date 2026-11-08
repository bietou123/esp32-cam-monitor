#!/usr/bin/env python3
"""把 proxy.py 上传到局域网服务器并重启 systemd 服务。

只依赖 paramiko：pip install paramiko

环境变量（不写进代码，避免凭据入库）：
  NAS_HOST        目标主机，必填
  NAS_USER        SSH 用户名，默认 root
  NAS_PASSWORD    SSH 密码；也可用 SSH 密钥（设置 NAS_KEY 指向私钥文件）
  NAS_PORT        SSH 端口，默认 22
  REMOTE_PATH     远端 proxy.py 路径，默认 /opt/cam-proxy/proxy.py
  SERVICE         systemd 服务名，默认 cam-proxy
  TEST_USER/TEST_PASS  可选，服务启动后 curl 自测用的 Basic Auth

用法：
  NAS_HOST=192.168.1.10 NAS_USER=admin NAS_PASSWORD=*** python deploy.py
"""
import os
import sys
import time

import paramiko

HOST = os.environ.get("NAS_HOST", "")
PORT = int(os.environ.get("NAS_PORT", "22"))
USER = os.environ.get("NAS_USER", "root")
PASSWORD = os.environ.get("NAS_PASSWORD", "")
KEY = os.environ.get("NAS_KEY", "")
REMOTE_PATH = os.environ.get("REMOTE_PATH", "/opt/cam-proxy/proxy.py")
SERVICE = os.environ.get("SERVICE", "cam-proxy")
TEST_USER = os.environ.get("TEST_USER", "")
TEST_PASS = os.environ.get("TEST_PASS", "")

if not HOST:
    sys.exit("NAS_HOST is required")
if not PASSWORD and not KEY:
    sys.exit("set NAS_PASSWORD or NAS_KEY")

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
try:
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD or None,
                   key_filename=KEY or None, timeout=15)
except Exception as exc:  # noqa: BLE001
    sys.exit("ssh failed: %s" % exc)


def run(cmd, timeout=60):
    _, out, err = client.exec_command(cmd, timeout=timeout)
    return out.read().decode("utf-8", "ignore") + err.read().decode("utf-8", "ignore")


def sudo(cmd, timeout=60):
    if USER == "root":
        return run(cmd, timeout)
    if not PASSWORD:
        return run("sudo -n " + cmd, timeout)
    return run("echo %s | sudo -S %s" % (PASSWORD, cmd), timeout)


local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxy.py")
with open(local, "r", encoding="utf-8") as fh:
    content = fh.read()

remote_dir = os.path.dirname(REMOTE_PATH)
sudo("mkdir -p %s" % remote_dir)
sftp = client.open_sftp()
with sftp.open(REMOTE_PATH, "w") as fh:
    fh.write(content)
sftp.close()
print("uploaded ->", REMOTE_PATH)

print(sudo("systemctl restart %s" % SERVICE).strip())
time.sleep(2)
print("active:", sudo("systemctl is-active %s" % SERVICE).strip().splitlines()[0])
print(sudo("journalctl -u %s -n 5 --no-pager" % SERVICE).strip())

auth = ""
if TEST_USER and TEST_PASS:
    auth = "-u %s:%s " % (TEST_USER, TEST_PASS)
print(run("curl -s %s-o /dev/null -w 'index: %%{http_code} ct=%%{content_type} bytes=%%{size_download}\\n' "
          "--max-time 8 http://127.0.0.1:8090/" % auth).strip())
client.close()
