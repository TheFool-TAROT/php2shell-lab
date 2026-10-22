<?php
/**
 * 复现用 gadget：类必须在 preload 阶段就定义好。
 * 启动期解码会话时，PHP 不会触发 autoload（实测），所以只装 composer 不够。
 */
class DemoGadget {
    public $a;
    public function __wakeup() {
        @file_put_contents('/tmp/proof.txt',
            "pid=" . getmypid() . "\n" . @shell_exec('id') . "\n", FILE_APPEND);
    }
}
