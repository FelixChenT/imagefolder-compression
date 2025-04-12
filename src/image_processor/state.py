# image_processor/state.py
# -- coding: utf-8 --

import os
import logging
import sys # 添加 sys 导入，以便在 logger 不可用时打印到 stderr
from .utils import get_text # 导入 get_text

def load_processed_files_from_dir(logger, state_file_path):
    """从指定目录的状态文件中加载已处理的文件名集合"""
    processed = set()
    if os.path.exists(state_file_path):
        try:
            # 使用 'utf-8-sig' 来处理可能存在的 BOM (Byte Order Mark)
            with open(state_file_path, 'r', encoding='utf-8-sig') as f:
                for line in f:
                    cleaned_line = line.strip()
                    if cleaned_line: # 确保只添加非空行
                        processed.add(cleaned_line)
            if logger:
                # 使用 get_text 获取日志消息 (假设 logger 存在时 get_text 可用)
                try:
                    log_msg = get_text("log_load_state_success", path=state_file_path, count=len(processed))
                    logger.debug(log_msg)
                except Exception as text_err:
                    logger.error(f"Failed to get text for log_load_state_success: {text_err}")
        except Exception as e:
            if logger:
                # 使用 get_text 获取日志消息
                try:
                    log_msg = get_text("log_load_state_fail", path=state_file_path, error=e)
                    logger.error(log_msg)
                except Exception as text_err:
                     logger.error(f"Failed to get text for log_load_state_fail: {text_err}. Original error: {e}")
            else:
                # Fallback if logger is not available
                print(f"Error loading state file {state_file_path}: {e}", file=sys.stderr)
    return processed

# 修改：添加 lock 参数，logger 变为可选
def save_processed_file_to_dir(logger, state_file_path, original_file_name, lock=None):
    """
    将已处理的文件名追加到指定目录的状态文件中。
    使用锁来确保并发写入安全。
    logger 参数变为可选，因为子进程不直接记录错误。
    """
    if not original_file_name: # 防止写入空行
        if logger:
            # 使用 get_text 记录警告
            try:
                warn_msg = get_text("state_save_empty_warn", path=state_file_path)
                logger.warning(warn_msg)
            except Exception as text_err:
                 logger.warning(f"Attempted to save empty filename to state file {state_file_path}. Text error: {text_err}")
        return

    try:
        # 确保状态文件所在的目录存在
        dir_name = os.path.dirname(state_file_path)
        if dir_name: # 确保目录名不为空（例如在根目录下）
             os.makedirs(dir_name, exist_ok=True)

        # 如果提供了锁，则在写入前获取锁
        if lock:
            lock.acquire()

        try:
            with open(state_file_path, 'a', encoding='utf-8') as f:
                f.write(original_file_name + '\n')
        finally:
            # 确保在任何情况下都释放锁
            if lock:
                lock.release()

    except Exception as e:
        # 子进程不方便记录日志，依赖主进程通过返回值捕获问题
        # 但如果 logger 存在（例如在主进程中直接调用），则记录错误
        if logger:
            # 使用 get_text 获取日志消息
            try:
                err_msg = get_text("log_save_state_fail", path=state_file_path, filename=original_file_name, error=e)
                logger.error(err_msg)
            except Exception as text_err:
                logger.error(f"Failed to get text for log_save_state_fail: {text_err}. Original error saving state for {original_file_name} to {state_file_path}: {e}")
        else:
            # Fallback if logger is not available during direct call
            print(f"Error saving state to {state_file_path} for {original_file_name}: {e}", file=sys.stderr)
        # 抛出异常，以便调用者（如 core 函数）知道状态保存失败
        raise