@echo off
REM IndexDub 便捷运行脚本
REM 功能:
REM   1. 自动使用虚拟环境 Python (无需手动激活)
REM   2. 启用 HuggingFace 离线模式 (避免网络连接问题)
REM   3. 透传所有命令行参数

REM 设置 HuggingFace 离线模式 (使用本地缓存，避免 SSL 连接错误)
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1

REM 使用虚拟环境的 Python 运行 main.py
.venv\Scripts\python.exe main.py %*
