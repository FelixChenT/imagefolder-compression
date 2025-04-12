# image_processor/log_utils.py
# -- coding: utf-8 --

import os
import sys
import logging
import logging.handlers
import time
# 确保 get_text 在此模块加载时可用
# 这依赖于 main.py 中在调用 setup_global_logger 之前设置语言
from . import config
from .utils import get_text # 导入 get_text

# 全局 logger 实例，由 setup_global_logger 初始化
# 其他模块可以通过 get_logger() 获取，或者直接从 main 传递
_logger = None

def setup_global_logger():
    """设置全局日志记录器"""
    global _logger
    run_state_abs_path = config.RUN_STATE_DIR # 使用 config 中的相对路径
    global_log_abs_path = os.path.join(run_state_abs_path, os.path.basename(config.GLOBAL_LOG_FILE_PATH))

    # 确保 RUN_STATE_DIR 存在
    try:
        os.makedirs(run_state_abs_path, exist_ok=True)
    except OSError as e:
        # 如果创建目录失败，这是一个严重问题，可能无法写入日志
        # 此时 get_text 可能还不可用，使用硬编码的英文+中文提示
        fallback_msg = config.texts['en'].get("log_fallback_print", "Fatal Error: Could not create run state directory '{path}': {error}").format(path=run_state_abs_path, error=e)
        print(fallback_msg, file=sys.stderr)
        # 尝试中文
        try:
             fallback_msg_zh = config.texts['zh'].get("log_fallback_print", "致命错误：无法创建运行状态目录 '{path}': {error}").format(path=run_state_abs_path, error=e)
             print(fallback_msg_zh, file=sys.stderr)
        except Exception: pass
        return None # 返回 None 表示设置失败

    logger_instance = logging.getLogger('GlobalImageProcessor')
    # 避免重复创建 handlers
    if logger_instance.hasHandlers():
        # 如果已有 handlers，假设已经正确设置，直接返回
        return logger_instance

    logger_instance.setLevel(logging.DEBUG) # 记录所有级别的日志到文件

    # 文件处理器 (DEBUG level)
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            global_log_abs_path,
            encoding='utf-8',
            mode='a',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=20
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s [%(process)d:%(threadName)s] [%(name)s.%(funcName)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        logger_instance.addHandler(file_handler)
    except Exception as e:
        # 尝试使用 get_text 获取错误消息，如果 utils 初始化失败，则使用硬编码英文
        try:
            # 假设此时 get_text 应该可用了，因为语言已选择
            err_msg = get_text("log_setup_fail", path=global_log_abs_path, error=e)
        except NameError: # get_text 可能尚未完全可用
             err_msg = f"Error: Could not set up global log file handler at {global_log_abs_path}: {e}"
        except Exception as ge: # get_text 本身可能出错
             err_msg = f"Error setting up log handler at {global_log_abs_path}: {e}. Also failed to get text: {ge}"
        print(err_msg, file=sys.stderr)
        # 即使文件日志失败，仍然尝试设置控制台日志

    # 控制台处理器 (INFO level)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO) # 控制台只显示 INFO 及以上级别
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    console_handler.setFormatter(console_formatter)
    logger_instance.addHandler(console_handler)

    _logger = logger_instance # 将创建的实例赋给模块级变量
    # 初始化成功消息使用 logger 记录，此时 logger 应该可用了
    _logger.info(f"Global logger initialized. Log file: {global_log_abs_path}")
    return _logger

def get_logger():
    """获取全局 logger 实例"""
    global _logger
    if _logger is None:
        # 尝试使用 get_text 或英文回退
        try:
            warn_msg = get_text("log_warning_setup_ondemand")
        except Exception:
            warn_msg = "Warning: Global logger accessed before explicit setup. Attempting setup now."
        print(warn_msg, file=sys.stderr)

        setup_global_logger() # 尝试设置

        if _logger is None:
             try:
                 err_msg = get_text("log_error_setup_ondemand")
             except Exception:
                 err_msg = "Error: Failed to setup logger on demand."
             print(err_msg, file=sys.stderr)

             # 返回一个临时的、配置简单的 logger，避免程序崩溃
             temp_logger = logging.getLogger('FallbackLogger')
             if not temp_logger.hasHandlers():
                 temp_handler = logging.StreamHandler(sys.stderr)
                 temp_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
                 temp_handler.setFormatter(temp_formatter)
                 temp_logger.addHandler(temp_handler)
                 temp_logger.setLevel(logging.WARNING)
             return temp_logger
    return _logger

def log_to_directory(logger, directory_path, log_file_name_template, level_str, formatted_message):
    """
    将已格式化的日志信息追加写入指定目录下的特定日志文件。
    由主进程调用，接收格式化后的消息。
    """
    if not directory_path: # 确保目录不为空
        if logger: logger.warning(f"Directory path is empty for directory log: {formatted_message}")
        return # 无法写入日志

    log_file = os.path.join(directory_path, log_file_name_template)
    try:
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        # 确保目录存在
        os.makedirs(directory_path, exist_ok=True)

        log_level_str_upper = level_str.upper()

        with open(log_file, 'a', encoding='utf-8') as f:
            # 写入时间戳、级别和已格式化的消息
            f.write(f"{timestamp} - {log_level_str_upper} - {formatted_message}\n")
    except Exception as e:
        # 如果写入目录日志失败，记录到全局日志
        if logger:
             # 使用 get_text 获取错误消息
             try:
                 # 假设 logger 存在时，get_text 也可用
                 err_msg = get_text("log_dir_write_fail", path=log_file, error=e)
                 logger.error(err_msg)
             except Exception as ge:
                  logger.error(f"Failed to write to directory log {log_file}: {e}. Also failed to get text: {ge}")
        else:
             # Fallback if global logger is not available
             print(f"Error writing to directory log {log_file}: {e}", file=sys.stderr)