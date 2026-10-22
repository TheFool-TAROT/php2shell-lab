#!/usr/bin/env python3
"""批量发送一次带 PHP_SESSION_UPLOAD_PROGRESS 的 multipart 请求，观察目标是否走 session 上传进度路径。

安全约束：
  * 只发送一个**无害**的 progress 字段 + 一个 4 字节文件字段；
  * 不包含任何对象/序列化 payload，不触发 __wakeup/__destruct；
  * 默认只允许私网/回环目标；对公网目标必须显式加 --authorized。

用法：
  python3 probe_upload_progress.py -i targets.txt -o result.csv [--authorized]
  python3 probe_upload_progress.py -u http://127.0.0.1:8101/hello.php
"""
from __future__ import annotations
import argparse, csv, ipaddress, socket, ssl, sys, time, uuid
from urllib.parse import urlparse
import urllib.request, urllib.error

BOUNDARY = "----probe" + uuid.uuid4().hex[:12]
UA = "Mozilla/5.0 (compatible; upload-progress-check/1.0)"

def build_body() -> bytes:
    parts = [
        f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"PHP_SESSION_UPLOAD_PROGRESS\"\r\n\r\nprobe\r\n",
        f"--{BOUNDARY}\r\nContent-Disposition: form-data; name=\"f\"; filename=\"p.txt\"\r\nContent-Type: text/plain\r\n\r\nAB\r\n",
        f"--{BOUNDARY}--\r\n",
    ]
    return "".join(parts).encode()

def is_private_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for fam, _, _, _, sa in infos:
        try:
            ip = ipaddress.ip_address(sa[0])
        except ValueError:
            continue
        if not (ip.is_private or ip.is_loopback or ip.is_link_local):
            return False
    return True

def request(url: str, method="GET", body=None, cookie=None, timeout=8):
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    headers = {"User-Agent": UA}
    if body is not None:
        headers["Content-Type"] = f"multipart/form-data; boundary={BOUNDARY}"
    if cookie:
        headers["Cookie"] = cookie
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.status, dict(r.headers), r.read(512), (time.time() - t0) * 1000
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), b"", (time.time() - t0) * 1000
    except Exception as e:
        return 0, {}, str(e).encode()[:100], (time.time() - t0) * 1000

def probe(url: str, authorized: bool, timeout: float):
    host = urlparse(url).hostname or ""
    if not authorized and not is_private_host(host):
        return {"url": url, "verdict": "SKIP(not authorized)", "base": "", "trig": "", "delta_ms": "", "cookie": ""}

    st0, hd0, _, ms0 = request(url, "GET", timeout=timeout)
    cookie = ""
    for k, v in hd0.items():
        if k.lower() == "set-cookie" and "PHPSESSID" in v:
            cookie = v.split(";")[0]
    st1, hd1, body1, ms1 = request(url, "POST", build_body(), cookie or None, timeout)
    fresh = any(k.lower() == "set-cookie" and "PHPSESSID" in v for k, v in hd1.items())

    verdict = "NO-RESPONSE"
    if st1 == 200:
        verdict = "OK"
    elif st1 in (400, 413, 500, 501):
        verdict = f"HTTP{st1}"
    elif st1 == 0:
        verdict = "CONN-FAIL"

    return {"url": url, "verdict": verdict, "base": st0, "trig": st1,
            "delta_ms": int(ms1), "cookie": "yes" if (cookie or fresh) else "no"}

def main():
    ap = argparse.ArgumentParser(description="PHP upload-progress 无害探针（只发 progress 字段，不发 payload）")
    ap.add_argument("-u", "--url")
    ap.add_argument("-i", "--input", help="每行一个 URL")
    ap.add_argument("-o", "--output", default="probe-result.csv")
    ap.add_argument("--authorized", action="store_true", help="确认目标在授权范围内（允许公网目标）")
    ap.add_argument("--timeout", type=float, default=8.0)
    a = ap.parse_args()

    targets = []
    if a.url: targets.append(a.url.strip())
    if a.input:
        targets += [l.strip() for l in open(a.input) if l.strip() and not l.startswith("#")]
    if not targets:
        ap.error("需要 -u 或 -i")

    rows = [probe(u, a.authorized, a.timeout) for u in targets]
    with open(a.output, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["url", "verdict", "base", "trig", "delta_ms", "cookie"])
        w.writeheader(); w.writerows(rows)
    for r in rows:
        print(f"{r['url']:50s} {r['verdict']:20s} base={r['base']} trig={r['trig']} {r['delta_ms']}ms session_cookie={r['cookie']}")
    ok = sum(1 for r in rows if r["verdict"] == "OK")
    print(f"\n[*] 共 {len(rows)} 个目标，HTTP 200 = {ok}，结果写入 {a.output}")

if __name__ == "__main__":
    main()
