from x5use import daemon_server
import asyncio
asyncio.run(daemon_server.run_daemon())


# # 停止 daemon
# qqbrowser-skill daemon_stop
#
# # 或者手动清理端口
# netstat -ano | findstr ":8765 :8766"
# taskkill /PID <进程ID> /F