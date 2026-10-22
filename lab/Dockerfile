# 109619 复现靶场：官方 8.5.11 镜像 + preload gadget + 一个把对象写进会话的应用页
# 仅用于本地/授权环境
ARG PHP_IMAGE=php:8.5.11-apache
FROM ${PHP_IMAGE}

COPY php.ini /usr/local/etc/php/conf.d/zz-lab.ini
COPY preload.php /var/www/lab/preload.php
COPY www/ /var/www/html/

RUN chown -R www-data:www-data /var/www/html /var/www/lab
