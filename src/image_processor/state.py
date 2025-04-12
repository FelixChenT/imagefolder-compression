# -*- coding: utf-8 -*-
import os
import logging
from .utils import get_text # 导入 get_text

def load_processed_files_from_dir(logger, state_file_path):
    """从指定目录的状态文件中加载已处理的文件名集合"""
    processed = set()
    if os.path.exists(state_file_path):
        try:
            with open(state_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    processed.add(line.strip())
            if logger:
                # 使用 get_text 获取日志消息
                logger.debug(get_text("log_load_state_success", path=state_file_path, count=len(processed)))
        except Exception as e:
            if logger:
                # 使用 get_text 获取日志消息
                logger.error(get_text("log_load_state_fail", path=state_file_path, error=e))
            else:
                 # Fallback if logger is not available
                 print(f"Error loading state file {state_file_path}: {e}", file=sys.stderr)
    return processed

def save_processed_file_to_dir(logger, state_file_path, original_file_name):
    """将已处理的文件名追加到指定目录的状态文件中"""
    try:
        # 确保状态文件所在的目录存在
        os.makedirs(os.path.dirname(state_file_path), exist_ok=True)
        with open(state_file_path, 'a', encoding='utf-8') as f:
            f.write(original_file_name + '\n')
    except Exception as e:
        if logger:
            # 使用 get_text 获取日志消息
            logger.error(get_text("log_save_state_fail", path=state_file_path, filename=original_file_name, error=e))
        else:
            # Fallback if logger is not available
            print(f"Error saving state to {state_file_path} for {original_file_name}: {e}", file=sys.stderr)