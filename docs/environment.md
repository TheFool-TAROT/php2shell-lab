# 环境要求

## 基础

- Debian 12 或 13，x86_64
- Apache 2.4（prefork + mod_php）或 nginx + php-fpm
- PHP 8.2.34 / 8.3.35 / 8.4.26 / 8.5.11（未修复），或 8.1 及以下（EOL）

## 109619-A（启动期 `__wakeup`）

| 项 | 要求 |
|---|---|
| `opcache.enable` | 1 |
| `opcache.preload` | 指向定义了 gadget 类的脚本 |
| 会话 | `session.save_path` 可写，会话文件里包含该类的对象 |
| 请求 | 一次带 `PHP_SESSION_UPLOAD_PROGRESS` 的 multipart |
| 页面 | 任意 PHP 页面，**不需要**调用 `session_start()` |

## 109619-B（跨 handler 注入）

| 项 | 要求 |
|---|---|
| 写入点 | 使用 `session.serialize_handler=php_serialize`（应用配置，或 CGI/FPM 下的 `.user.ini`） |
| 读取点 | 使用默认 `php` handler |
| 会话存储 | 两个端点共用同一个 `session.save_path` |
| 其它 | `session.use_strict_mode=0`，`session.upload_progress.cleanup=Off` |

注意：`.user.ini` 只在 CGI/FPM 下生效，mod_php 不读。

## 109618

| 项 | 要求 |
|---|---|
| 构建 | 与公开 PoC 标定的构建一致（官方 docker 镜像最稳） |
| `memory_limit` | 有具体值，不能是 -1 |
| `post_max_size` | 大于请求体 |
| SAPI | 公开实现针对 Apache prefork + mod_php |
| ASLR | 需要泄露（公开实现走 `PHPSESSID` cookie） |

## 隔离建议

跑这些实验建议用一次性虚拟机或容器，别在日常办公机上做：实验会落 core、写会话文件、起本地服务。
