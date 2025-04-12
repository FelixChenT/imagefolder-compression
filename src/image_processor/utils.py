# -*- coding: utf-8 -*-
import sys
from . import config # 使用相对导入

# --- 模块级变量存储选择的语言 ---
_selected_language = 'zh' # 默认中文

def set_language(lang_code):
    """设置全局使用的语言"""
    global _selected_language
    if lang_code in config.texts:
        _selected_language = lang_code
    else:
        # 在设置语言时，如果语言无效，则使用默认语言打印警告
        print(f"Warning: Invalid language code '{lang_code}' provided. Using default '{_selected_language}'.", file=sys.stderr)
        # 不改变 _selected_language，保持默认值

def get_text(key, **kwargs):
    """根据已设置的语言获取文本，并支持格式化"""
    # 使用模块级的 _selected_language
    text_template = config.texts[_selected_language].get(key, f"MISSING_TEXT[{key}]")
    try:
        return text_template.format(**kwargs)
    except KeyError as e:
        # 尝试使用默认语言获取格式化错误消息
        warning_msg = f"Warning: Missing key '{e}' for text template '{key}' in language '{_selected_language}'"
        print(warning_msg, file=sys.stderr)
        # 返回原始模板和错误提示，避免程序因文本缺失而崩溃
        return text_template + f" (Format Error: Missing {e})"
    except Exception as e:
         # 尝试使用默认语言获取格式化错误消息
        warning_msg = f"Warning: Error formatting text '{key}' in language '{_selected_language}': {e}"
        print(warning_msg, file=sys.stderr)
        return text_template + " (Format Error)"