# -*- coding: utf-8 -*-
import os
import sys
import logging
import logging.handlers
import time
from . import config
from .utils import get_text # 导入 get_text

# 全局 logger 实例，由 setup_global_logger 初始化
# 其他模块可以通过 get_logger() 获取，或者直接从 main 传递
_logger = None

def setup_global_logger():
    """设置全局日志记录器"""
    global _logger
    # 确保 RUN_STATE_DIR 存在
    try:
        os.makedirs(config.RUN_STATE_DIR, exist_ok=True)
    except OSError as e:
         # 如果创建目录失败，这是一个严重问题，可能无法写入日志
         print(f"Fatal Error: Could not create run state directory '{config.RUN_STATE_DIR}': {e}", file=sys.stderr)
         return None # 返回 None 表示设置失败

    logger_instance = logging.getLogger('GlobalImageProcessor')
    logger_instance.setLevel(logging.DEBUG) # 记录所有级别的日志到文件

    # 防止重复添加 handlers
    if logger_instance.hasHandlers():
        logger_instance.handlers.clear()

    # 文件处理器 (DEBUG level)
    try:
        log_file_path = config.GLOBAL_LOG_FILE_PATH
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path,
            encoding='utf-8',
            mode='a',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=20
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter('%(asctime)s - %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        file_handler.setFormatter(file_formatter)
        logger_instance.addHandler(file_handler)
    except Exception as e:
        # 尝试使用 get_text 获取错误消息，如果 utils 初始化失败，则使用硬编码英文
        try:
            err_msg = get_text("log_setup_fail", path=log_file_path, error=e)
        except NameError: # get_text 可能尚未完全可用
             err_msg = f"Error: Could not set up global log file handler at {log_file_path}: {e}"
        print(err_msg, file=sys.stderr)
        # 即使文件日志失败，仍然尝试设置控制台日志

    # 控制台处理器 (INFO level)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO) # 控制台只显示 INFO 及以上级别
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    console_handler.setFormatter(console_formatter)
    logger_instance.addHandler(console_handler)

    _logger = logger_instance # 将创建的实例赋给模块级变量
    return _logger

def get_logger():
    """获取全局 logger 实例"""
    # 如果 logger 未初始化，尝试初始化（虽然最好在 main 中显式调用 setup）
    if _logger is None:
        print("Warning: Global logger accessed before explicit setup. Attempting setup now.", file=sys.stderr)
        setup_global_logger()
    return _logger

def log_to_directory(logger, directory_path, log_file_name_template, level, message_key, **kwargs):
    """将翻译后的日志信息追加写入指定目录下的特定日志文件"""
    log_file = os.path.join(directory_path, log_file_name_template)
    try:
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        # 确保目录存在
        os.makedirs(directory_path, exist_ok=True)
        # 使用 utils.get_text 获取翻译后的消息
        translated_message = get_text(message_key, **kwargs)
        log_level_str = level.upper() if isinstance(level, str) else logging.getLevelName(level)

        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{timestamp} - {log_level_str} - {translated_message}\n")
    except Exception as e:
        # 如果写入目录日志失败，记录到全局日志
        if logger:
             # 使用 get_text 获取错误消息
             logger.error(get_text("log_dir_write_fail", path=log_file, error=e))
        else:
             # Fallback if global logger is not available
             print(f"Error writing to directory log {log_file}: {e}", file=sys.stderr)