<?php
// 模拟真实应用：把对象写进会话（Symfony 的安全令牌就是这样）
session_start();
if (!isset($_SESSION['token'])) {
    $_SESSION['token'] = new DemoGadget();
}
echo "session ready: ", session_id(), "\n";
