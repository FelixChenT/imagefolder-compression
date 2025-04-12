# src/main.py
# -- coding: utf-8 --

import os
import sys
import argparse
import time
import logging
import multiprocessing
from multiprocessing.managers import BaseManager
from concurrent.futures import ProcessPoolExecutor, as_completed, TimeoutError
from collections import defaultdict

# --- 动态调整 sys.path ---
# 假设 main.py 在 src 目录下，项目根目录是 src 的父目录
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
# 将项目根目录添加到 sys.path，以便可以 `from image_processor import ...`
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# 如果你的结构不同（例如 main.py 在项目根目录），请调整这里

# --- 导入包模块 ---
try:
    from image_processor import config, utils, log_utils, state, core, ui
except ImportError as e:
     # 尝试获取英文错误信息，因为此时多语言可能未设置
     print(f"Error importing package modules: {e}", file=sys.stderr)
     print("Ensure the script is run from the correct directory (e.g., the 'src' folder or project root)", file=sys.stderr)
     print(f"Current sys.path: {sys.path}", file=sys.stderr)
     sys.exit(1)

# --- 辅助函数：处理子进程返回的日志 ---
def log_processor_messages(logger, get_text_func, dir_log_file_name_template, messages):
    """处理从子进程返回的日志消息列表"""
    if not messages:
        return

    for log_entry in messages:
        try:
            # 解包日志条目，现在包含 context_kwargs
            level_str, message_key_or_raw, kwargs, to_dir_log, *context_kwargs_list = log_entry
            context_kwargs = context_kwargs_list[0] if context_kwargs_list else {}

            level = getattr(logging, level_str.upper(), logging.INFO)

            # 处理特殊的占位符 [[key]]
            processed_message_key = message_key_or_raw
            formatted_message = "" # 初始化为空字符串

            if isinstance(message_key_or_raw, str) and '[[' in message_key_or_raw:
                import re
                placeholder = re.search(r'\[\[(.*?)\]\]', message_key_or_raw)
                if placeholder:
                    text_key = placeholder.group(1)
                    try:
                        replacement_text = get_text_func(text_key)
                        # 使用 get_text 格式化包含占位符的整个消息
                        # 需要确保 kwargs 包含占位符 key 对应的值（如果需要的话）
                        # 或者，如果占位符只是简单的文本替换
                        temp_message = message_key_or_raw.replace(f'[[{text_key}]]', replacement_text)
                        # 再用 get_text 格式化替换后的字符串（如果它本身也是一个 key）
                        # 或者直接格式化包含替换文本的字符串
                        try:
                            # 尝试将替换后的结果作为 key 查找
                            formatted_message = get_text_func(temp_message, **kwargs)
                        except KeyError:
                            # 如果替换后的不是 key，尝试直接格式化
                            try:
                                formatted_message = temp_message.format(**kwargs)
                            except Exception as fmt_e:
                                formatted_message = f"RAW LOG FORMAT ERROR (Placeholder) [{level_str}]: {temp_message} | {kwargs} | {fmt_e}"
                                logger.warning(formatted_message) # 记录格式化错误
                    except KeyError:
                         # get_text_func 找不到占位符 key
                         missing_key_text = f'[MissingKey:{text_key}]'
                         temp_message = message_key_or_raw.replace(f'[[{text_key}]]', missing_key_text)
                         logger.warning(f"Missing text key '{text_key}' used in placeholder: {message_key_or_raw}")
                         # 尝试格式化带有缺失 key 提示的字符串
                         try:
                             formatted_message = temp_message.format(**kwargs)
                         except Exception as fmt_e:
                             formatted_message = f"RAW LOG FORMAT ERROR (Missing Placeholder Key) [{level_str}]: {temp_message} | {kwargs} | {fmt_e}"
                             logger.warning(formatted_message) # 记录格式化错误
                else:
                     # 没有找到 [[key]] 格式，按普通流程处理
                     processed_message_key = message_key_or_raw
            else:
                 processed_message_key = message_key_or_raw

            # 如果经过占位符处理后 formatted_message 仍为空，则按原逻辑处理
            if not formatted_message:
                try:
                    # 优先尝试作为 key 获取翻译和格式化
                    formatted_message = get_text_func(processed_message_key, **kwargs)
                except KeyError:
                    # 如果不是 key，尝试直接格式化（如果是字符串且含占位符）
                    if isinstance(processed_message_key, str) and '{' in processed_message_key:
                        try:
                            formatted_message = processed_message_key.format(**kwargs)
                        except Exception as fmt_e:
                            formatted_message = f"RAW LOG FORMAT ERROR [{level_str}]: {processed_message_key} | {kwargs} | {fmt_e}"
                            logger.warning(formatted_message) # 记录格式化错误
                    else:
                        # 既不是 key 也不是可格式化字符串，作为原始信息记录
                        formatted_message = f"RAW LOG [{level_str}]: {processed_message_key} | {kwargs}"
                except Exception as text_err:
                     # get_text 本身出错
                     formatted_message = f"LOG PROCESSING ERROR [{level_str}]: {processed_message_key} | {kwargs} | Error: {text_err}"
                     logger.error(formatted_message) # 记录处理错误

            # 记录到全局 logger (添加文件名前缀)
            log_prefix = ""
            # 尝试从 context 或 kwargs 获取路径信息
            file_path_context = context_kwargs.get('path') or kwargs.get('path')
            original_filename_context = result.get('original_filename') if 'result' in locals() else None # core 返回结果中可能有
            filename_kwarg = kwargs.get('filename')

            if file_path_context:
                 log_prefix = f"[{os.path.basename(file_path_context)}] "
            elif original_filename_context:
                 log_prefix = f"[{original_filename_context}] "
            elif filename_kwarg:
                 log_prefix = f"[{filename_kwarg}] "

            logger.log(level, f"{log_prefix}{formatted_message}")

            # 如果需要，记录到目录日志
            if to_dir_log:
                dir_path = context_kwargs.get('dir_path') # core.py 现在应该提供这个
                if dir_path:
                    log_utils.log_to_directory(logger, dir_path, dir_log_file_name_template, level_str, formatted_message)
                else:
                    # 这个警告理论上不应再出现
                    logger.warning(f"Could not determine directory path for directory log (dir_path missing in context): {formatted_message}")

        except Exception as log_proc_err:
            # 记录处理日志条目本身发生的错误
            logger.error(f"Error processing log entry: {log_entry}. Error: {log_proc_err}", exc_info=True)


# --- 主程序 ---
# 修改：移除 num_workers_override 参数
def main_runner(root_folder):
    """主执行函数，协调整个处理流程（并发版本）"""
    # 1. 选择语言
    selected_language = ui.select_language()
    utils.set_language(selected_language)
    get_text = utils.get_text # 获取设置语言后的 get_text 函数

    # 2. 初始化全局日志
    logger = log_utils.setup_global_logger()
    if not logger:
        # 尝试使用 get_text，如果失败则用英文硬编码
        try:
            print(get_text("log_setup_fail", path=config.GLOBAL_LOG_FILE_PATH, error="Logger setup failed"), file=sys.stderr)
        except Exception as e:
             print(f"Critical Error: Logger setup failed and cannot get text ({e}). Cannot continue.", file=sys.stderr)
        sys.exit(1)

    # 3. 选择处理模式
    mode = ui.get_processing_mode()
    mode_name = get_text('mode_webp') if mode == 'webp' else get_text('mode_inplace')
    logger.info(get_text("mode_selected", mode_name=mode_name))

    # 4. 获取对应模式的参数
    user_params = {}
    dir_state_file_name = ""
    dir_log_file_name = ""
    process_func_ref = None

    if mode == 'webp':
        user_params = ui.get_webp_parameters()
        dir_state_file_name = config.WEBP_DIR_STATE_FILE_NAME
        dir_log_file_name = config.WEBP_DIR_LOG_FILE_NAME
        process_func_ref = core.convert_to_webp_inplace
        webp_quality = user_params['webp_quality']
        webp_lossless = user_params['webp_lossless']
        lossless_mode_text = get_text("webp_config_lossless_forced") if webp_lossless else get_text("webp_config_lossless_auto")
        logger.info(get_text("webp_config", quality=webp_quality, lossless_mode=lossless_mode_text))
    elif mode == 'inplace':
        user_params = ui.get_inplace_parameters()
        dir_state_file_name = config.INPLACE_DIR_STATE_FILE_NAME
        dir_log_file_name = config.INPLACE_DIR_LOG_FILE_NAME
        process_func_ref = core.compress_image_inplace
        quality_inplace = user_params['quality']
        png_optimize_inplace = user_params['png_optimize']
        png_optimize_text = get_text("inplace_png_optimize_enabled") if png_optimize_inplace else get_text("inplace_png_optimize_disabled")
        logger.info(get_text("inplace_config",
                             quality=quality_inplace,
                             large_threshold=config.INPLACE_LARGE_FILE_THRESHOLD_MB,
                             large_quality=config.INPLACE_LARGE_FILE_COMPRESSION_QUALITY,
                             png_optimize=png_optimize_text))
    else:
        # 使用 get_text 记录内部错误
        logger.critical(get_text("unexpected_error_process") + f" - Invalid mode: {mode}")
        sys.exit(1)

    # 5. 获取并发工作进程数 (新增)
    num_workers = ui.get_num_workers() # 调用 UI 函数获取

    # 6. 准备并发处理
    start_time = time.time()
    root_folder_norm = os.path.normpath(root_folder)

    logger.info(get_text("task_start", mode_name=mode_name))
    logger.info(get_text("target_folder", folder=root_folder_norm))
    logger.info(get_text("supported_types", extensions=', '.join(config.SUPPORTED_EXTENSIONS)))
    logger.info(get_text("state_file_info", state_file=dir_state_file_name, log_file=dir_log_file_name))
    # 记录使用的进程数
    logger.info(get_text("using_workers", workers=num_workers))

    # 初始化统计变量
    total_processed_in_session = 0
    total_skipped_in_session = 0
    total_errors_in_session = 0
    total_original_size_bytes = 0
    total_output_size_bytes = 0
    processed_dirs_count = 0
    manager = None

    # --- 注册 set 和 lock 类型并启动 Manager ---
    try:
        # 确保在使用 BaseManager 前初始化 multiprocessing 上下文（尤其是在 macOS 或 Windows 上）
        # multiprocessing.set_start_method('fork') # 或者 'spawn', 'forkserver' 根据需要和平台
        # 注意：set_start_method 只能调用一次，通常在 if __name__ == "__main__": 块的开始处

        set_methods = ('__contains__', '__iter__', 'add', 'update', '__len__', 'remove', 'discard', 'clear', 'pop', 'issubset', 'issuperset', 'union', 'intersection', 'difference')
        # 确保这些类型在使用前注册
        if not hasattr(BaseManager, 'SharedSet'):
             BaseManager.register('SharedSet', set, exposed=set_methods)
        if not hasattr(BaseManager, 'Lock'):
             BaseManager.register('Lock', multiprocessing.Lock)

        manager = BaseManager()
        manager.start()
        logger.info(get_text("manager_start_success"))
    except Exception as manager_err:
        logger.critical(get_text("manager_start_fail", error=manager_err), exc_info=True)
        sys.exit(1)

    dir_states = {} # 存储每个目录的状态 { 'processed_set': SharedSetProxy, 'lock': LockProxy }

    # --- 收集任务 ---
    tasks_by_dir = defaultdict(list)
    logger.info(get_text("task_collect_scan"))
    try:
        for subdir, _, files in os.walk(root_folder_norm):
            subdir_norm = os.path.normpath(subdir)

            # 过滤出支持的图片文件
            image_files_in_dir = [f for f in files if os.path.splitext(f)[1].lower() in config.SUPPORTED_EXTENSIONS]
            if not image_files_in_dir:
                continue # 没有图片文件，跳过此目录

            # 为该目录加载或创建状态
            if subdir_norm not in dir_states:
                dir_state_file_path = os.path.join(subdir_norm, dir_state_file_name)
                initial_processed_set = state.load_processed_files_from_dir(logger, dir_state_file_path)
                # 使用 manager 创建共享对象
                try:
                    shared_set = manager.SharedSet(initial_processed_set)
                    shared_lock = manager.Lock()
                    dir_states[subdir_norm] = {
                        'processed_set': shared_set,
                        'lock': shared_lock
                    }
                    # 使用 get_text 记录加载的条目数
                    logger.debug(get_text("dir_processed_count", subdir=subdir_norm, state_file=dir_state_file_name, count=len(initial_processed_set)))
                except Exception as manager_create_err:
                     logger.error(f"Failed to create shared objects for directory {subdir_norm}: {manager_create_err}")
                     continue # 跳过此目录的处理

            current_dir_state = dir_states[subdir_norm]
            processed_set_proxy = current_dir_state['processed_set']
            lock_proxy = current_dir_state['lock']
            dir_state_file_path = os.path.join(subdir_norm, dir_state_file_name) # 状态文件路径

            # 遍历目录中的图片文件，创建任务
            for filename in image_files_in_dir:
                # 跳过临时文件、状态文件和日志文件
                is_temp_or_meta = False
                if filename.endswith((".compress_temp", ".webp_temp")):
                     is_temp_or_meta = True
                elif filename == dir_state_file_name or filename == dir_log_file_name:
                     is_temp_or_meta = True
                # 跳过其他模式的日志/状态文件
                elif mode == 'webp' and (filename == config.INPLACE_DIR_LOG_FILE_NAME or filename == config.INPLACE_DIR_STATE_FILE_NAME):
                     is_temp_or_meta = True
                elif mode == 'inplace' and (filename == config.WEBP_DIR_LOG_FILE_NAME or filename == config.WEBP_DIR_STATE_FILE_NAME):
                     is_temp_or_meta = True

                if is_temp_or_meta:
                    continue

                # WebP 模式下跳过 .webp 文件本身
                if mode == 'webp' and os.path.splitext(filename)[1].lower() == '.webp':
                    # 可以选择记录跳过日志
                    # logger.debug(get_text("skip_webp_self", path=os.path.join(subdir_norm, filename)))
                    continue

                file_path_norm = os.path.normpath(os.path.join(subdir_norm, filename))

                # 确保是文件而不是目录（尽管 os.walk 通常只返回文件）
                if not os.path.isfile(file_path_norm):
                    logger.warning(get_text("task_collect_skip_not_file", path=file_path_norm))
                    continue

                # 构建任务参数列表
                task_args = [
                    file_path_norm,
                    processed_set_proxy, # 传递共享集合代理
                    dir_state_file_path, # 传递状态文件路径
                    dir_log_file_name,   # 传递目录日志文件名模板
                ]
                # 根据模式添加特定参数
                if mode == 'webp':
                    task_args.extend([user_params['webp_quality'], user_params['webp_lossless'], lock_proxy]) # 传递锁代理
                elif mode == 'inplace':
                    task_args.extend([user_params['quality'], user_params['png_optimize'], lock_proxy]) # 传递锁代理

                # 将任务添加到字典中
                tasks_by_dir[subdir_norm].append({'func': process_func_ref, 'args': task_args})

    except Exception as e:
        logger.critical(get_text("task_collect_error", error=e), exc_info=True)
        if manager: manager.shutdown()
        sys.exit(1)

    # 将所有任务收集到一个列表中以便提交
    tasks_to_submit = []
    for subdir, tasks in tasks_by_dir.items():
        for task in tasks:
            # 添加目录信息，方便后续处理结果
            tasks_to_submit.append({'task': task, 'dir': subdir})

    total_tasks = len(tasks_to_submit)
    if total_tasks == 0:
         logger.info(get_text("no_tasks_found"))
         end_time = time.time()
         duration = end_time - start_time
         logger.info(get_text("task_end", mode_name=mode_name))
         logger.info(get_text("summary_processed", count=0))
         logger.info(get_text("summary_skipped", count=0))
         logger.info(get_text("summary_dirs_processed", count=0))
         logger.info(get_text("summary_errors", count=0))
         logger.info(get_text("summary_size_before", size=0.0))
         logger.info(get_text("summary_size_after", size=0.0))
         logger.info(get_text("summary_duration", duration=duration))
         global_log_path_for_summary = os.path.join(config.RUN_STATE_DIR, os.path.basename(config.GLOBAL_LOG_FILE_PATH))
         logger.info(get_text("summary_global_log", path=global_log_path_for_summary))
         if manager: manager.shutdown()
         sys.exit(0)

    logger.info(get_text("task_collect_success", count=total_tasks, dirs=len(tasks_by_dir)))

    # --- 并发执行任务 ---
    processed_count_in_loop = 0
    futures_map = {} # 存储 future 到任务信息的映射
    processed_dirs_set = set() # 记录实际处理过的目录

    try:
        # 使用从 UI 获取的 num_workers
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            logger.info(get_text("submitting_tasks", count=total_tasks))
            for i, task_info in enumerate(tasks_to_submit):
                task = task_info['task']
                # 提交任务到进程池
                future = executor.submit(task['func'], *task['args'])
                # 存储 future 和相关信息，用于后续结果处理
                futures_map[future] = {'index': i, 'dir': task_info['dir'], 'file_path': task['args'][0]} # args[0] is file_path

            logger.info(get_text("tasks_submitted"))

            # 处理已完成的任务
            for future in as_completed(futures_map):
                processed_count_in_loop += 1
                task_info = futures_map[future]
                file_path = task_info['file_path']
                dir_path = task_info['dir']

                # 定期打印进度
                if processed_count_in_loop % 50 == 0 or processed_count_in_loop == total_tasks:
                    logger.info(get_text("progress_update", done=processed_count_in_loop, total=total_tasks))

                try:
                    # 获取任务结果，设置超时（例如 5 分钟）
                    result = future.result(timeout=300) # 300 秒超时

                    # 处理子进程返回的日志消息
                    if result.get('log_messages'):
                        log_processor_messages(logger, get_text, dir_log_file_name, result['log_messages'])

                    # 根据结果更新统计数据
                    status = result.get('status', 'error')
                    original_size = result.get('original_size')
                    output_size = result.get('output_size')

                    # 累加原始大小（仅在非跳过时估算）
                    if original_size is not None and status != 'skipped':
                        total_original_size_bytes += original_size

                    if status == 'success':
                        total_processed_in_session += 1
                        processed_dirs_set.add(dir_path) # 记录处理过的目录
                        if output_size is not None:
                            total_output_size_bytes += output_size
                        else:
                             # 理论上成功应该有输出大小，记录警告
                             logger.warning(f"Successful task for {file_path} returned None output_size.")
                    elif status == 'skipped':
                        total_skipped_in_session += 1
                        # 跳过的文件理论上不应有 output_size，如果 core 返回了，记录警告
                        if output_size is not None:
                            logger.warning(f"Skipped file {file_path} but received output size {output_size}. Ignoring size.")
                    else: # status == 'error' or 未知状态
                        total_errors_in_session += 1
                        processed_dirs_set.add(dir_path) # 出错也算处理过此目录
                        # 错误情况下，如果 core 返回了 output_size (例如重命名失败前的大小)，也累加
                        if output_size is not None:
                             total_output_size_bytes += output_size
                        error_details = result.get('error_details', 'Unknown error from worker')
                        # 使用 get_text 记录失败信息
                        logger.error(get_text("task_failed", path=file_path, details=error_details))

                except TimeoutError:
                     logger.error(get_text("task_timeout", timeout=300, path=file_path))
                     total_errors_in_session += 1
                     processed_dirs_set.add(dir_path) # 超时也算处理过此目录
                except Exception as exc:
                    # 获取结果时发生其他异常
                    logger.critical(get_text("task_result_error", path=file_path, error=exc), exc_info=True)
                    total_errors_in_session += 1
                    processed_dirs_set.add(dir_path) # 异常也算处理过此目录


    except KeyboardInterrupt:
        logger.warning(get_text("user_interrupt_process"))
        # 使用 get_text 打印中断信息
        print(f"\n{get_text('user_interrupt_process')} - Shutting down process pool...")
        # executor 会在 with 块结束时自动 shutdown，但 manager 需要手动关闭
    except Exception as e:
        # 捕获 ProcessPoolExecutor 启动或运行中的其他意外错误
        logger.critical(get_text("unexpected_error_process") + f": {e}", exc_info=True)
        print(f"\n{get_text('unexpected_error_process')}: {e}")
    finally:
         if manager:
             logger.debug("Shutting down multiprocessing manager...")
             try:
                 manager.shutdown()
             except Exception as manager_shutdown_err:
                  logger.error(get_text("manager_shutdown_error", error=manager_shutdown_err))


    # --- 任务结束统计 ---
    end_time = time.time()
    duration = end_time - start_time
    processed_dirs_count = len(processed_dirs_set) # 使用集合大小统计实际处理目录数

    logger.info(get_text("finished_processing_loop", done=processed_count_in_loop, total=total_tasks))
    logger.info(get_text("task_end", mode_name=mode_name))
    logger.info(get_text("summary_processed", count=total_processed_in_session))
    logger.info(get_text("summary_skipped", count=total_skipped_in_session))
    logger.info(get_text("summary_dirs_processed", count=processed_dirs_count))
    logger.info(get_text("summary_errors", count=total_errors_in_session))

    # 计算和显示体积变化
    total_original_size_mb = total_original_size_bytes / (1024 * 1024)
    total_output_size_mb = total_output_size_bytes / (1024 * 1024)
    logger.info(get_text("summary_size_before", size=total_original_size_mb))
    logger.info(get_text("summary_size_after", size=total_output_size_mb))

    # 计算减少百分比，处理各种情况
    if total_original_size_bytes > 0:
        # 只有在有成功处理或错误但有输出体积时才计算减少比例
        if total_processed_in_session > 0 or (total_errors_in_session > 0 and total_output_size_bytes > 0):
            if total_output_size_bytes < total_original_size_bytes:
                try:
                    size_reduction_percent = ((total_original_size_bytes - total_output_size_bytes) / total_original_size_bytes) * 100
                    logger.info(get_text("summary_reduction", percent=size_reduction_percent))
                except ZeroDivisionError:
                     logger.warning(get_text("size_reduction_error_zero")) # 使用 get_text
            elif total_output_size_bytes > 0 :
                 logger.info(get_text("size_no_decrease")) # 使用 get_text
            else: # total_output_size_bytes 为 0 或 None
                 logger.info(get_text("summary_no_output")) # 使用 get_text
        # 如果只有跳过的文件
        elif total_skipped_in_session > 0 and total_processed_in_session == 0 and total_errors_in_session == 0:
             logger.info(get_text("size_reduction_na_skipped")) # 使用 get_text
        else: # 有原始大小，但没有处理、跳过或错误（理论上不太可能发生）
             logger.info(get_text("size_reduction_na_other")) # 使用 get_text
    elif total_tasks > 0: # 有任务但原始大小为0
         logger.info(get_text("size_reduction_na_zero_orig")) # 使用 get_text
    else: # 没有任务运行
         logger.info(get_text("size_reduction_na_no_tasks")) # 使用 get_text

    logger.info(get_text("summary_duration", duration=duration))
    # 确保日志路径正确显示
    global_log_path_for_summary = os.path.join(config.RUN_STATE_DIR, os.path.basename(config.GLOBAL_LOG_FILE_PATH))
    logger.info(get_text("summary_global_log", path=global_log_path_for_summary))
    logger.info(get_text("summary_dir_log", mode_name=mode_name, log_file=dir_log_file_name))
    logger.info(get_text("summary_dir_state", mode_name=mode_name, state_file=dir_state_file_name))


# --- 脚本入口 ---
if __name__ == "__main__":
    # 尽早设置 multiprocessing start method (如果需要，特别是 macOS/Windows)
    # try:
    #     multiprocessing.set_start_method('fork') # 或者 'spawn'
    # except RuntimeError:
    #     pass # 可能已经被设置

    # 设置默认语言以用于 argparse 帮助信息
    utils.set_language('zh') # 默认中文

    parser = argparse.ArgumentParser(
        description=utils.get_text("argparse_description"),
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "root_folder",
        help=utils.get_text("argparse_folder_help")
    )
    # 移除 --workers 参数，因为现在通过 UI 获取
    # parser.add_argument(
    #     "-w", "--workers",
    #     type=int,
    #     help="Number of worker processes to use (default: CPU cores - 1)"
    # )
    args = parser.parse_args()

    if not os.path.isdir(args.root_folder):
        # 使用 get_text 打印路径错误
        print(get_text("error_invalid_path", path=args.root_folder), file=sys.stderr)
        sys.exit(1)

    # --- 执行主函数 ---
    # 不再传递 args.workers
    main_runner(root_folder=args.root_folder)