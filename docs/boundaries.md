# 五条边界：这条链在哪里停住

这份文档记录的是"试过、不行、原因是什么"。每条都有实测或源码依据，不是推测。

## 1. 请求启动阶段不触发 autoload

**做法**：在 `opcache.preload` 里注册一个 composer 风格的 `spl_autoload_register()`，session 里放一个"类还没被定义"的对象，触发启动期解码。

**结果**：8.5.11 上什么都没发生，8.5.12 上也没有。

**原因**：启动期解码不走 autoloader，类必须真的在 preload 阶段被定义（`require` 过或 `class_exists()` 过）。这就是为什么"目标装了 composer autoload"不等于可利用——Symfony/Laravel 的 preload 脚本会 preload 一批类，那批类才有用。

## 2. 默认 `php` handler 没有对象注入点

**做法**：把 `PHP_SESSION_UPLOAD_PROGRESS` 的值设成 `x|O:6:"PrePwn":...`，希望它落盘后成为合法的序列化数据。

**结果**：会话文件被写成 0 字节，写入失败。

**原因**：`ps_srlzr_encode_php`（`session.c`）只拒绝 key 里的 `|`，其它字节（`\n`、`{`、`}`、`;`、`:`、空格）都能原样落盘。但解码器在**第一个 `|`** 处切分，key 是前半段、value 是后半段，而 value 永远是 PHP 自己序列化出来的进度数组。攻击者能控制的只有 key 段，且 key 段不能含 `|`，所以没有地方放对象。

**推论**：单 handler 下这条路走不通；只有"写侧 `php_serialize` + 读侧 `php`"的 handler 不一致组合才行。

## 3. 109618 的堆整形参数绑定构建

**做法**：用公开实现对官方 `php:8.5.11-apache` 打，再对自编译 8.5.11 打；自编译版本包括 debug、非 debug、以及按官方镜像的 configure 参数重建的版本。

**结果**：官方镜像 4/4 成功；三个自编译版本全部 `HEAP_LEAK_FAILED`；把 `stage1_n` 从 700 扫到 980（281 组）也没命中。

**原因**：stage-1 的堆泄露依赖 167 字节载体在 chunk 内的精确偏移（`htdata`），这个偏移由构建决定。公开实现按镜像标定了 `0x690D8`（8.4/8.5）和 `0x6A0D8`（8.3），换构建就对不上。

**推论**：想打某个目标，先看它是官方镜像、发行版包还是自编译——版本号只是第一层筛选。

## 4. `fatal_error_backtraces` 的残留窗口在输入解析之前

**做法**：8.5.12 的修复把 `php_basic_early_rinit()` 插在 `zend_activate()` 之后、`php_hash_environment()` 之前，重置了 `EG(user_error_handler)`、`EG(last_fatal_error_backtrace)`、`EG(error_handling)` 等状态。我们逐项试了四种制造残留的方法：shutdown 函数里 fatal、析构里 fatal、关闭期 OOM、以及 `set_error_handler` + 70MB POST。

**结果**：ASAN 零报告；`error_get_last()` 在下一请求恒为 `null`。

**原因**：从源码顺序看，残留窗口在 `init_executor` 之前，那时候攻击者的输入还没被解析。Datadog 说的 "a configuration diagnostic in a later request reads that state before PHP initializes it"，指的正是这个初始化之前的窗口，实际可利用性依赖 fatal 恰好打断清理过程（竞态），不具备工程化价值。

## 5. `BG(serialize)` 残留只在 cli-server 存活

**做法**：按公开配方（32 字节会话 ID + 2MB filename）打三种 SAPI。

**结果**：
| SAPI | 结果 |
|---|---|
| cli-server (`php -S`) | 触发，第二次请求连接失败，服务器死 |
| Apache mod_php | 不触发，worker 存活 |
| php-fpm | 不触发（child 退出 70 被 master 重启，或 RINIT 已清状态） |

**原因**：这条路径要求 session 编码在 `php_hash_environment()` 里 OOM，且 `BG(serialize)` 的脏状态能活到下一次请求。mod_php 和 FPM 的关闭路径把它清掉了。

---

## 附：修复补丁覆盖的 7 类状态，我们全测过

| 状态 | 测试方式 | 结果 |
|---|---|---|
| `EG(user_error_handler)` | 设 handler + 启动期诊断 | 无 ASAN 命中 |
| `EG(last_fatal_error_backtrace)` | 四种制造残留 | 无 ASAN 命中 |
| `BG(serialize)` | OOM 后复用 | 仅 cli-server 崩 |
| `BG(unserialize)` | 解码 OOM 后复用 | 无 ASAN 命中 |
| `EG(error_handling)` / `user_error_handlers` | 多 handler + 70MB POST | 无 ASAN 命中 |
| `EG(user_exception_handler)` | set_exception_handler + 启动期 | 无 ASAN 命中 |
| URL 重写器（`php_url_scanner_early_rinit`） | 开 `trans_sid` 投毒 | 无 ASAN 命中 |

结论：只有一条在特定 SAPI 上成立，其余无法从外部稳定触发。
