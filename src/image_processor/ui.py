# -*- coding: utf-8 -*-
import sys
import os
import multiprocessing
from . import config # 相对导入配置
from .utils import get_text # 相对导入 get_text

def select_language():
    """提示用户选择语言, Enter 使用默认值 (中文)。返回选择的语言代码 ('zh' 或 'en')"""
    default_lang_code = 'zh' # 默认中文
    while True:
        # 初始提示固定用中文格式显示选项和默认值
        prompt = config.texts['zh']['select_language']
        try:
            choice = input(prompt).strip()
            if choice == '1':
                print(config.texts['zh']["language_selected"]) # 用中文确认
                return 'zh'
            elif choice == '2':
                print(config.texts['en']["language_selected"]) # 用英文确认
                return 'en'
            elif choice == '': # Enter 使用默认值
                print(config.texts[default_lang_code]["language_selected"]) # 用默认语言确认
                return default_lang_code
            else:
                # 无效选择提示也用默认中文显示
                print(config.texts['zh']["invalid_choice_language"])
        except (EOFError, KeyboardInterrupt):
             # 使用 get_text 获取中断提示，但需要先设置默认语言，否则可能出错
             # 假设此时语言尚未设置，使用默认语言的文本
             print(f"\n{config.texts[default_lang_code]['user_interrupt']}", file=sys.stderr)
             sys.exit(1) # 用户中断，退出程序

def get_processing_mode():
    """交互式获取用户处理模式, Enter 使用默认值 (WebP)。返回模式标识符 ('inplace' 或 'webp')"""
    default_mode_code = 'webp'
    mode_map = {'1': 'inplace', '2': 'webp'}
    while True:
        # 使用 get_text 获取当前语言的提示
        prompt = get_text("select_mode")
        try:
            choice = input(prompt).strip().lower()
            if choice in mode_map:
                return mode_map[choice]
            elif choice == '': # Enter 使用默认值
                return default_mode_code
            else:
                print(get_text("invalid_choice_mode")) # 使用当前语言提示无效
        except (EOFError, KeyboardInterrupt):
             print(f"\n{get_text('user_interrupt')}", file=sys.stderr) # 使用当前语言提示中断
             sys.exit(1)

def get_inplace_parameters():
    """交互式获取原格式压缩模式参数。返回包含参数的字典。"""
    params = {}
    # 获取 JPEG 质量
    while True:
        try:
            prompt = get_text("prompt_jpeg_quality", default=config.INPLACE_DEFAULT_COMPRESSION_QUALITY)
            quality_input = input(prompt).strip()
            quality = int(quality_input) if quality_input else config.INPLACE_DEFAULT_COMPRESSION_QUALITY
            if 1 <= quality <= 95:
                params['quality'] = quality
                break
            else:
                print(get_text("error_invalid_quality_jpeg"))
        except ValueError:
            print(get_text("error_invalid_number"))
        except (EOFError, KeyboardInterrupt):
             print(f"\n{get_text('user_interrupt')}", file=sys.stderr)
             sys.exit(1)

    # 获取 PNG 优化选项
    while True:
        try:
            default_optimize_char = 'y' if config.INPLACE_DEFAULT_PNG_OPTIMIZE else 'n'
            prompt = get_text("prompt_png_optimize", default=default_optimize_char)
            optimize_input = input(prompt).lower().strip()
            if optimize_input == 'y':
                params['png_optimize'] = True
                break
            elif optimize_input == 'n':
                params['png_optimize'] = False
                break
            elif optimize_input == '': # Enter 使用默认值
                params['png_optimize'] = config.INPLACE_DEFAULT_PNG_OPTIMIZE
                break
            else:
                print(get_text("error_invalid_yn"))
        except (EOFError, KeyboardInterrupt):
             print(f"\n{get_text('user_interrupt')}", file=sys.stderr)
             sys.exit(1)
    return params

def get_webp_parameters():
    """交互式获取 WebP 模式参数。返回包含参数的字典。"""
    params = {}
    # 获取 WebP 质量
    while True:
        try:
            prompt = get_text("prompt_webp_quality", default=config.WEBP_DEFAULT_QUALITY)
            quality_input = input(prompt).strip()
            quality = int(quality_input) if quality_input else config.WEBP_DEFAULT_QUALITY
            if 0 <= quality <= 100:
                params['webp_quality'] = quality
                break
            else:
                print(get_text("error_invalid_quality_webp"))
        except ValueError:
            print(get_text("error_invalid_number"))
        except (EOFError, KeyboardInterrupt):
             print(f"\n{get_text('user_interrupt')}", file=sys.stderr)
             sys.exit(1)

    # 获取 WebP 无损选项
    while True:
        try:
            default_lossless_char = 'y' if config.WEBP_DEFAULT_LOSSLESS else 'n'
            prompt = get_text("prompt_webp_lossless", default=default_lossless_char)
            lossless_input = input(prompt).lower().strip()
            if lossless_input == 'y':
                params['webp_lossless'] = True
                break
            elif lossless_input == 'n':
                params['webp_lossless'] = False
                break
            elif lossless_input == '': # Enter 使用默认值
                params['webp_lossless'] = config.WEBP_DEFAULT_LOSSLESS
                break
            else:
                print(get_text("error_invalid_yn"))
        except (EOFError, KeyboardInterrupt):
             print(f"\n{get_text('user_interrupt')}", file=sys.stderr)
             sys.exit(1)
    return params

def get_num_workers():
    """交互式获取用户希望使用的并发工作进程数。返回进程数。"""
    suggested_workers = config.DEFAULT_WORKERS
    fallback_workers = 4 # 如果无法检测核心数，使用的备用值

    print(get_text("calculating_workers")) # 使用 get_text
    try:
        cpu_cores = os.cpu_count()
        if cpu_cores:
            # 建议使用核心数-1，最少为1
            suggested_workers = max(1, cpu_cores - 1)
            print(get_text("detected_cores", cpu_cores=cpu_cores)) # 使用 get_text
            print(get_text("suggested_workers", workers=suggested_workers)) # 使用 get_text
        else:
            suggested_workers = fallback_workers # 使用备用值
            print(get_text("error_cpu_count", fallback=fallback_workers)) # 使用 get_text
    except NotImplementedError:
         suggested_workers = fallback_workers # 使用备用值
         print(get_text("error_cpu_count_unsupported", fallback=fallback_workers)) # 使用 get_text

    while True:
        try:
            prompt = get_text("prompt_num_workers", suggested=suggested_workers)
            workers_input = input(prompt).strip()
            if workers_input == '':
                num_workers = suggested_workers # 用户按 Enter，使用建议值
                break
            else:
                num_workers = int(workers_input)
                if num_workers == 0: # 0 表示自动，也使用建议值
                    num_workers = suggested_workers
                    break
                elif num_workers > 0:
                    break # 用户输入了有效的正整数
                else:
                    print(get_text("error_invalid_worker_count")) # 输入了负数
        except ValueError:
            print(get_text("error_invalid_number")) # 输入的不是数字
        except (EOFError, KeyboardInterrupt):
             print(f"\n{get_text('user_interrupt')}", file=sys.stderr)
             sys.exit(1)

    print(get_text("using_workers", workers=num_workers)) # 使用 get_text 确认最终值
    return num_workers