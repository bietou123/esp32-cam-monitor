#!/usr/bin/env python3
"""ESP32-CAM 反向代理 + 移动端 UI。

摄像头固件的 Web UI 在 80 口、MJPEG 流在 81 口；本代理把两者合并到同一端口，
并提供暗色悬浮 dock（补光灯 / 拍照 / 画质 / 全屏）。

配置全部走环境变量：
  CAM_HOST        摄像头局域网地址，默认 192.168.1.50
  CAM_HTTP_PORT   摄像头 HTTP 端口，默认 80
  CAM_STREAM_PORT 摄像头流端口，默认 81
  CAM_AUTH_USER   可选，Basic Auth 用户名
  CAM_AUTH_PASS   可选，Basic Auth 密码；两项都设置才会启用鉴权
  LISTEN_PORT     本代理监听端口，默认 8090
  LISTEN_HOST     本代理监听地址，默认 ::（双栈）
"""
import http.server, socketserver, socket, urllib.request, base64, os

CAM = os.environ.get("CAM_HOST", "192.168.1.50")
CAM_HTTP_PORT = int(os.environ.get("CAM_HTTP_PORT", "80"))
CAM_STREAM_PORT = int(os.environ.get("CAM_STREAM_PORT", "81"))
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8090"))
LISTEN_HOST = os.environ.get("LISTEN_HOST", "::")

_user = os.environ.get("CAM_AUTH_USER", "")
_pass = os.environ.get("CAM_AUTH_PASS", "")
AUTH = None
if _user and _pass:
    AUTH = "Basic " + base64.b64encode(("%s:%s" % (_user, _pass)).encode()).decode()

INDEX = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>ESP32-CAM 监控</title>
<style>
:root{--bg:#0b0d10;--panel:rgba(22,26,31,.72);--on:#f59e0b}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);overflow:hidden;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif;color:#e5e7eb;
 -webkit-user-select:none;user-select:none}
.wrap{position:fixed;inset:0;display:flex;align-items:center;justify-content:center}
#v{width:100%;height:100%;object-fit:contain;display:block;background:#000}
.topbar{position:fixed;top:0;left:0;right:0;display:flex;align-items:center;gap:9px;
 padding:14px 18px;padding-top:max(14px,env(safe-area-inset-top));
 background:linear-gradient(180deg,rgba(0,0,0,.55),transparent);z-index:10;pointer-events:none}
.dot{width:9px;height:9px;border-radius:50%;background:#22c55e;box-shadow:0 0 8px #22c55e;animation:pulse 2s infinite}
.dot.off{background:#ef4444;box-shadow:0 0 8px #ef4444;animation:none}
@keyframes pulse{50%{opacity:.35}}
.title{font-size:15px;font-weight:600;letter-spacing:.4px}
.sub{font-size:11px;color:#9ca3af;margin-left:2px}
.ld{position:fixed;inset:0;display:flex;flex-direction:column;gap:14px;align-items:center;justify-content:center;
 color:#94a3b8;font-size:14px;z-index:5;background:var(--bg)}
.spin{width:34px;height:34px;border:3px solid rgba(148,163,184,.25);border-top-color:#94a3b8;border-radius:50%;animation:sp .8s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
.dock{position:fixed;left:50%;transform:translateX(-50%);bottom:max(22px,env(safe-area-inset-bottom));
 display:flex;gap:8px;padding:9px 12px;background:var(--panel);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
 border:1px solid rgba(255,255,255,.09);border-radius:20px;z-index:10;box-shadow:0 10px 34px rgba(0,0,0,.55)}
.btn{display:flex;flex-direction:column;align-items:center;gap:5px;border:0;background:transparent;color:#cbd5e1;
 font-size:11px;cursor:pointer;padding:8px 12px;border-radius:14px;transition:.15s;min-width:60px}
.btn:active{transform:scale(.92)}
.btn:hover{background:rgba(255,255,255,.07);color:#fff}
.btn svg{width:25px;height:25px}
.btn.active{color:var(--on)}
.btn.active svg{filter:drop-shadow(0 0 7px var(--on))}
.toast{position:fixed;left:50%;top:64px;transform:translateX(-50%);background:rgba(0,0,0,.78);
 color:#fff;font-size:13px;padding:8px 16px;border-radius:20px;z-index:20;opacity:0;transition:.25s;pointer-events:none}
.toast.show{opacity:1}
</style></head>
<body>
<div class="topbar"><span class="dot" id="dot"></span><span class="title">ESP32-CAM</span><span class="sub" id="sub">直播</span></div>
<div class="wrap"><img id="v" src="/stream" alt=""></div>
<div class="ld" id="ld"><div class="spin"></div><div id="ldtxt">连接中…</div></div>
<div class="toast" id="toast"></div>
<div class="dock">
 <button class="btn" id="ledBtn" onclick="toggleLed()">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6M10 21.5h4M12 2.5a6.5 6.5 0 0 0-4 11.6V16.5h8V14.1A6.5 6.5 0 0 0 12 2.5z"/></svg>
  <span id="ledTxt">补光灯</span></button>
 <button class="btn" onclick="snap()">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="3.8"/></svg>
  <span>拍照</span></button>
 <button class="btn" onclick="cycleQ()">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M7 12h10M10 18h4"/></svg>
  <span id="qTxt">画质</span></button>
 <button class="btn" onclick="fs()">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/></svg>
  <span>全屏</span></button>
</div>
<script>
var img=document.getElementById('v'),ld=document.getElementById('ld'),dot=document.getElementById('dot'),sub=document.getElementById('sub');
var ledOn=false;
function toast(t){var e=document.getElementById('toast');e.textContent=t;e.classList.add('show');clearTimeout(e._t);e._t=setTimeout(function(){e.classList.remove('show')},1400)}
img.onload=function(){ld.style.display='none';dot.classList.remove('off');sub.textContent='直播'};
img.onerror=function(){ld.style.display='flex';document.getElementById('ldtxt').textContent='重连中…';dot.classList.add('off');sub.textContent='断开';setTimeout(function(){img.src='/stream?'+Date.now()},1500)};
function toggleLed(){ledOn=!ledOn;fetch('/control?var=led_intensity&val='+(ledOn?255:0));
 document.getElementById('ledBtn').classList.toggle('active',ledOn);
 document.getElementById('ledTxt').textContent=ledOn?'已开':'补光灯';toast(ledOn?'补光灯 开':'补光灯 关')}
function snap(){var a=document.createElement('a');a.href='/capture?'+Date.now();a.download='cam_'+Date.now()+'.jpg';document.body.appendChild(a);a.click();a.remove();toast('已保存快照')}
var QP=[{n:'流畅',fs:5,q:16},{n:'标准',fs:8,q:12},{n:'高清',fs:10,q:10}];
var qi=0;
function applyQ(){var p=QP[qi];document.getElementById('qTxt').textContent=p.n;
 fetch('/control?var=framesize&val='+p.fs).then(function(){return fetch('/control?var=quality&val='+p.q)}).then(function(){setTimeout(function(){img.src='/stream?'+Date.now()},500)})}
function cycleQ(){qi=(qi+1)%QP.length;applyQ();toast('画质：'+QP[qi].n)}
function fs(){var w=document.querySelector('.wrap');var rf=w.requestFullscreen||w.webkitRequestFullscreen;if(!document.fullscreenElement&&!document.webkitFullscreenElement){if(rf)rf.call(w)}else{(document.exitFullscreen||document.webkitExitFullscreen).call(document)}}
fetch('/status').then(function(r){return r.json()}).then(function(s){
 if(s){if(s.led_intensity>0){ledOn=true;document.getElementById('ledBtn').classList.add('active');document.getElementById('ledTxt').textContent='已开'}
 var m={5:0,8:1,10:2};if(s.framesize in m){qi=m[s.framesize];document.getElementById('qTxt').textContent=QP[qi].n}}
}).catch(function(){});
</script></body></html>"""
INDEX_BYTES = INDEX.encode("utf-8")

class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def _auth(self):
        if AUTH is None:          # 未配置用户名密码 -> 不鉴权（公网暴露前务必启用）
            return True
        if self.headers.get("Authorization") != AUTH:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Camera"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        return True
    def do_GET(self):
        if not self._auth():
            return
        p = self.path.split("?")[0]
        if p == "/" or p == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(INDEX_BYTES)))
            self.end_headers()
            self.wfile.write(INDEX_BYTES)
            return
        if p == "/stream":
            self._stream("http://%s:%d/stream" % (CAM, CAM_STREAM_PORT))
            return
        if p in ("/capture", "/status", "/control", "/xclk", "/reg", "/greg", "/pll", "/resolution"):
            self._simple("http://%s:%d%s" % (CAM, CAM_HTTP_PORT, self.path))
            return
        self.send_error(404)
    def _stream(self, url):
        try:
            r = urllib.request.urlopen(url, timeout=10)
        except Exception:
            self.send_error(502)
            return
        self.send_response(200)
        self.send_header("Content-Type", r.headers.get("Content-Type", "multipart/x-mixed-replace;boundary=123456789000000000000987654321"))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            while True:
                b = r.read(8192)
                if not b:
                    break
                self.wfile.write(b)
        except Exception:
            pass
        finally:
            try:
                r.close()
            except Exception:
                pass
    def _simple(self, url):
        try:
            r = urllib.request.urlopen(url, timeout=10)
            data = r.read()
        except Exception:
            self.send_error(502)
            return
        self.send_response(200)
        self.send_header("Content-Type", r.headers.get("Content-Type", "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
    def log_message(self, *a):
        pass

class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
    address_family = socket.AF_INET6 if ":" in LISTEN_HOST else socket.AF_INET
    daemon_threads = True
    def server_bind(self):
        if self.address_family == socket.AF_INET6:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)  # 双栈
        super().server_bind()

if __name__ == "__main__":
    if AUTH is None:
        print("警告：未设置 CAM_AUTH_USER / CAM_AUTH_PASS，代理无鉴权；公网暴露前请启用")
    S((LISTEN_HOST, LISTEN_PORT), H).serve_forever()
