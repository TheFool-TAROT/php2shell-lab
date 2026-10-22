# PHP2Shell 复现笔记 — CVE-2026-109618 / CVE-2026-109619

> 2026-10 的两个 PHP 核心漏洞。这个仓库只做一件事：把"能打到什么程度、卡在哪里"讲清楚，不吹也不藏。
> 所有测试都在自有靶机上完成，仓库不含任何真实目标清单。
> [中文](#中文) · [English](#english)

---

## 中文

### 结论先放前面

- **109618**：官方镜像（`php:8.5.11-apache`）上可以稳定打出未授权 RCE，8.5.11 四次四中，8.4.26 和 8.3.35 各一次一中。换自编译构建（哪怕 configure 参数和官方一模一样）全部失败。它吃的是**构建布局**，不是版本号。
- **109619**：我们打通的是"请求启动期解码会话"这条路径。8.1 到 8.5 都能触发，**与构建和 SAPI 无关**，但要求 `opcache.preload` 里有可用的类，并且会话里得出现这个类的对象（或者攻击者能把对象注入进去）。
- 修复版（8.5.12 / 8.4.27 / 8.3.36 / 8.2.35）两条链都不成立。

### 八版本矩阵

同一份代码、同一套配置，只换 PHP 版本：

| 分支 | 未修复 | 结果 | 已修复 | 结果 |
|---|---|---|---|---|
| 8.5 | 8.5.11 | 执行 | 8.5.12 | 不执行 |
| 8.4 | 8.4.26 | 执行 | 8.4.27 | 不执行 |
| 8.3 | 8.3.35 | 执行 | 8.3.36 | 不执行 |
| 8.2 | 8.2.34 | 执行 | 8.2.35 | 不执行 |
| 8.1 | 8.1.34（EOL） | 执行 | — | 官方无修复 |

### 109618 是怎么打通的

补丁前的 `_zend_hash_str_add_or_update_i()` 有个顺序问题：先把 `nNumUsed` 和 `nNumOfElements` 加上去，再去分配 key。key 分配一旦因为内存超限失败，这个桶就被"算进去了，但没初始化"。

请求销毁时 PHP 遍历所有计数内的桶。那个空桶里是上一次分配残留的字节，如果攻击者能控制这些字节，就能让它看起来像一个数组，数组的析构回调就会被调用。把回调指到 `system()`，参数指向命令字符串，命令就执行了。

公开链的步骤大致是：

1. 发一个约 3.5MB 的表单，字段形状类似 `=<伪造结构>&a=1&<超长字段名>[x]=1`；
2. 超长字段名让 key 的第二次分配撞上 `memory_limit`，OOM 打断插入；
3. 关闭阶段把残留桶当成数组，触发析构回调。

需要的条件：`memory_limit` 不是 -1（默认配置就满足）、能触发 OOM 的请求体、以及最麻烦的一条——绕过 ASLR。公开实现用 `PHPSESSID` cookie 把堆地址泄露出来。

我们实测的结果：官方镜像四次四中，自编译构建零中，`stage1_n` 从 700 扫到 980 共 281 组参数全 miss。所以这条链对目标构建很挑。

### 109619 的三条路径

我们实际验证过的有三条，能打的程度不一样：

**A. 启动期解码会话（主推）**

`session.upload_progress` 会让 PHP 在处理请求启动阶段解码会话，那时候 RINIT 还没跑。未修复版本会按真实类实例化会话里的对象，于是 `__wakeup` / `__destruct` 在脚本被编译之前就执行了。

复现只需要三步：preload 里定义一个带魔术方法的类；准备一个包含该类对象的 session 文件；发一次带 `PHP_SESSION_UPLOAD_PROGRESS` 的 multipart 请求。

前置条件：`opcache.preload` 有这个类（Symfony、Laravel Octane 这类生产部署常开 preload），会话里有对象（Symfony 的安全令牌天然满足）。

**B. 跨 handler 对象注入**

默认的 `php` 序列化器在写 session 时只拒绝 key 里的 `|`，其它字节原样落盘；解码时在第一个 `|` 处切开，后半段交给 `unserialize()`。

所以如果目标有一个走 `php_serialize` 的写入点（应用配置，或者 CGI/FPM 下的 `.user.ini`），把进度字段的名字设成 `x|O:6:"PrePwn":...`，落盘后是一个合法的 php_serialize 结构；再用默认 `php` handler 的页面去读，第一个 `|` 之后正好是我们的序列化对象，对象就被创建了。

这条路径的好处是对象由攻击者构造，不需要应用配合。坏处是必须存在 handler 不一致的两个目录。

**C. BG(serialize) 残留**

第一次请求让 session 编码在 `php_hash_environment()` 里 OOM，`BG(serialize)` 留下悬垂指针；第二次请求复用它，worker 直接 SIGSEGV。

这条只在 PHP 内置服务器（`php -S`）上复现，Apache mod_php 和 php-fpm 都不行，实战价值有限，写进来主要是为了让机制记录完整。

### 环境要求

- Debian 12/13 x86_64，Apache 2.4 + prefork（mod_php 路线），或 nginx + php-fpm
- PHP 8.2.34 / 8.3.35 / 8.4.26 / 8.5.11（未修复），或 8.1 及以下
- 复现 109619-A：`opcache.enable=1` + `opcache.preload` 指向一个定义了目标类的脚本
- 复现 109619-B：一个 `php_serialize` 写入点和一个默认 `php` 读取点，两者共用同一个 `session.save_path`
- Docker（可选，用来跑官方镜像做 109618 对照）


### 仓库里附带的 PoC（都是自研，非第三方）

| 文件 | 作用 | 需要什么 |
|---|---|---|
| `poc/poc_109619_wakeup.py` | 发一次带 `PHP_SESSION_UPLOAD_PROGRESS` 的 multipart，触发启动期解码 | 靶机侧 preload 有类 + 会话里有对象 |
| `poc/poc_109619_inject.py` | 跨 handler 对象注入（投毒 → 触发 → 取证明） | 一个 `php_serialize` 写点 + 一个默认 `php` 读点 |
| `poc/poc_109618_signal.py` | 109618 可达性判定：只看有没有启动期 OOM | 无需前置，一次中等体积 POST |
| `poc/probe_upload_progress.py` | 批量无损探针（版本 + upload-progress 可达性） | 无 |
| `scripts/demo_wakeup.sh` | 一键在本机搭出 109619-A 环境并复现 | root、Apache、未修复版本模块 |
| `scripts/matrix_8versions.sh` | 八个版本的差分矩阵 | 预先编好各版本模块 |


实测（本机 cli-server，8.5.11）：

```
$ python3 poc/poc_109618_signal.py --url http://127.0.0.1:8211/hello.php --size 3
[*] POST http://127.0.0.1:8211/hello.php (3.0 MB) -> 200
[+] 命中启动期 OOM：
    Allowed memory size of 8388608 bytes exhausted (tried to allocate 3145729 bytes) in Unknown
```

同一条命令打 Apache mod_php 就没有这个回应——同样的版本，不同的 SAPI，行为不一样，这也是为什么"只看版本号"不够。

没有附带 109618 的利用实现——那是第三方代码，README 里给了出处；我们只提供"可达性判定"。

### 快速复现

见 [`docs/reproduce.md`](docs/reproduce.md)，或者直接跑：

```bash
# 109619-A：启动期 __wakeup
sudo bash scripts/demo_wakeup.sh

# 八版本矩阵（需要先准备好各版本模块）
sudo bash scripts/matrix_8versions.sh
```


### 关于 OOM 的大小：不同环境差很多

判定 109618 是否可达时，最容易踩的坑是"以为固定 3MB 就能触发"。实际不是。

同一个 8.5.11，我们在三种环境下量到的行为：

| 环境 | 3MB 请求体 | 12 / 20MB |
|---|---|---|
| 官方 `php:8.5.11-apache`（`memory_limit=8M`） | OOM，`tried to allocate 3145729` | — |
| 自编译 8.5.11 + Apache mod_php（同样 8M） | 200，没有 OOM | 仍然没有可见 OOM |
| 自编译 8.5.11 + cli-server（同样 8M） | OOM | — |

决定阈值的有四个东西：`memory_limit` 的大小、解析时的基线占用（扩展、preload 都算）、解析器对字段的复制放大倍数（SAPI 和版本相关）、以及 `post_max_size` 给的上界——body 超过 `post_max_size` 会被提前拒绝，反而不会 OOM。

所以探测要从下往上扫。`poc_109618_signal.py` 提供了自适应模式：

```bash
python3 poc/poc_109618_signal.py --url http://127.0.0.1/index.php --adaptive --max-size 64
```

从 1MB 起按 1、2、4、8、16、32、64 递增，命中就停；连接异常也停，避免把目标打挂。本机 cli-server（8M）实测阈值落在 2MB：

```
[*] POST ... (1 MB) -> 200
[*] POST ... (2 MB) -> 200
[+] 命中启动期 OOM：
    Allowed memory size of 8388608 bytes exhausted (tried to allocate 2097153 bytes) in Unknown
```

负结果不代表安全：可能 `memory_limit` 很大、可能解析放大不够、也可能被前置规则挡住。另外，真正的利用比"能 OOM"还要挑——它要求 OOM 恰好发生在字段名 key 分配的那一刻，这也是公开链的参数绑构建的原因。


### 用 Docker 起靶场

`lab/` 下是一个可直接跑的最小环境：官方 `php:8.5.11-apache` 镜像 + preload gadget + 一个把对象写进会话的 `login.php`。

直接拉现成的（约 173MB）：

```bash
docker run -d --name lab-vuln  -p 127.0.0.1:18080:80 thefooltarot/php2shell-lab:vuln-8.5.11
docker run -d --name lab-fixed -p 127.0.0.1:18081:80 thefooltarot/php2shell-lab:fixed-8.5.12
```

也可以自己构建：

```bash
cd lab
docker compose up -d --build          # 8.5.11 → 127.0.0.1:18080，8.5.12 → 127.0.0.1:18081
```

复现（容器内已验证）：

```bash
SID=$(curl -s http://127.0.0.1:18080/login.php | awk '{print $3}')
python3 ../poc/poc_109619_wakeup.py --url http://127.0.0.1:18080/index.php --sid "$SID" --authorized
docker exec <container> cat /tmp/proof.txt
```

```
pid=20
uid=33(www-data) gid=33(www-data) groups=33(www-data)
```

把端口换成 18081 就是修复版的负对照，`proof.txt` 不会出现。

已发布到 Docker Hub：

| 镜像 | 说明 |
|---|---|
| `thefooltarot/php2shell-lab:vuln-8.5.11` | 未修复版本，可触发 |
| `thefooltarot/php2shell-lab:fixed-8.5.12` | 修复版本，负对照 |
| `thefooltarot/php2shell-lab:latest` | 同 vuln-8.5.11 |

改完之后重新发布：

```bash
docker build --build-arg PHP_IMAGE=php:8.5.11-apache -t thefooltarot/php2shell-lab:vuln-8.5.11 lab/
docker push thefooltarot/php2shell-lab:vuln-8.5.11
```

注意：这是**故意脆弱**的镜像，只用于本地或隔离环境，不要暴露到公网。

### 几条边界（都是实测撞出来的，不是猜的）

1. 请求启动阶段**不会触发 autoload**。我们在 preload 里注册 `spl_autoload_register`，session 里放一个未定义类的对象，8.5.11 上什么都没发生。所以类必须真的在 preload 阶段被定义，装个 composer autoload 不算。
2. 默认 `php` handler 的 key 不能含 `|`，值永远是 PHP 自己序列化的结果，单 handler 下没有对象注入点。
3. 109618 的堆整形参数绑定构建。同版本、不同构建，打不通。
4. `fatal_error_backtraces` 的跨请求残留，窗口在 `init_executor` 之前，也就是攻击者输入还没被解析的时候，外部够不着。我们试了四种制造残留的方法，ASAN 零报告。
5. `BG(serialize)` 残留只在 cli-server 存活。

### 防御

升级是唯一完整的修复。过渡期可以：`memory_limit=-1` 加前置请求体限制（对 109618）；`session.upload_progress.enabled=0`，8.5 上再加 `fatal_error_backtraces=0`（对 109619）。这些只是降低暴露面，不修漏洞。

监控上，109618 成功利用时 worker 不会崩、返回 200、应用日志干净，唯一痕迹是错误日志里一条 `Allowed memory size ... in Unknown on line 0`。

### 声明

仓库里的脚本只用于自有环境或明确授权的测试。不包含任何真实目标、扫描结果或单位信息。

---

## English

### TL;DR

- **109618** gives unauthenticated RCE on the official `php:8.5.11-apache` image (4/4 runs; 8.4.26 and 8.3.35 also work). It fails on every self-built PHP we tried, including a build with the exact configure flags from the official image. The exploit depends on the build layout, not the version string.
- **109619** — the path we reproduced is the pre-RINIT session decode. It works on 8.1 through 8.5, independent of build and SAPI, but needs a class defined in `opcache.preload` and an object of that class in the session (or a way to inject one).
- Both chains die on 8.5.12 / 8.4.27 / 8.3.36 / 8.2.35.

### 109618 in one paragraph

Before the patch, `_zend_hash_str_add_or_update_i()` incremented the bucket counters before allocating the key. If that allocation fails (OOM), the bucket is counted but never initialised. During request shutdown PHP walks every counted bucket and treats it as a PHP value. The leftover bytes can be shaped into a fake array whose destructor callback is called — point it at `system()` and the worker runs a command. The public chain needs a request sized so the key allocation fails at the right moment, plus an ASLR bypass (the published one leaks through the `PHPSESSID` cookie).

### 109619: three paths, different reach

**A. Session decode at request startup.** `session.upload_progress` makes PHP decode the session before RINIT. On unpatched builds the objects are instantiated with their real classes, so `__wakeup` / `__destruct` run before the script is compiled. Requirements: a class defined in preload, an object of that class in the session, and one multipart request.

**B. Cross-handler object injection.** The default `php` serializer only rejects `|` inside keys; everything else is written verbatim. If the target has one write path using `php_serialize` and one read path using the default `php` handler, an attacker can smuggle a serialized object into the session without any application cooperation.

**C. Stale `BG(serialize)`.** First request OOMs inside the session encoder, leaving a dangling pointer; the second request reuses it and the worker segfaults. Only reproducible on PHP's built-in server (`php -S`) — mod_php and php-fpm don't hit it.


### OOM size is environment-specific

A fixed 3 MB body is not a universal trigger. On the same 8.5.11 with `memory_limit=8M`, we measured: official image → OOM at 3 MB; self-built mod_php → no OOM even at 20 MB; cli-server → OOM. The threshold depends on `memory_limit`, baseline memory at parse time, the parser's copy amplification (SAPI- and version-specific), and `post_max_size` as an upper bound — a body larger than `post_max_size` gets rejected before allocation, so it never reaches the OOM path.

Probe upward instead of guessing: `poc_109618_signal.py --adaptive` walks 1, 2, 4, 8, 16, 32, 64 MB and stops on the first hit (or on a connection error). A negative result does not mean the target is safe.


### Docker lab

`lab/` builds a minimal vulnerable environment from the official `php:8.5.11-apache` image: a preload gadget, a trivial page, and a `login.php` that stores the object in the session.

Published images (173 MB each):

```bash
docker run -d --name lab-vuln  -p 127.0.0.1:18080:80 thefooltarot/php2shell-lab:vuln-8.5.11
docker run -d --name lab-fixed -p 127.0.0.1:18081:80 thefooltarot/php2shell-lab:fixed-8.5.12
```

Or build it yourself with `cd lab && docker compose up -d --build`.

Trigger with `poc/poc_109619_wakeup.py`, then read `/tmp/proof.txt` inside the container. The 8.5.12 container produces nothing, which is the negative control.

The image is intentionally vulnerable. Keep it local — do not publish it to a public host.

### Boundaries we hit

1. No autoload during request startup — the class must be defined at preload time.
2. The default `php` handler cannot carry an injected object.
3. 109618's heap grooming parameters are build-specific.
4. The `fatal_error_backtraces` residue window sits before any request data is parsed.
5. `BG(serialize)` residue only survives on cli-server.

### Reproduce

See [`docs/reproduce.md`](docs/reproduce.md). Scripts live in `scripts/` and default to loopback targets.

### Disclaimer

For authorized testing only. No target lists, scan results, or organizational data are included.
