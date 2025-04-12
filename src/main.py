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
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = current_dir
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

# --- 导入包模块 ---
try:
    from image_processor import config, utils, log_utils, state, core, ui
except ImportError as e:
     print(f"Error importing package modules: {e}", file=sys.stderr)
     # ... (错误处理保持不变)
     sys.exit(1)

# --- 辅助函数：处理子进程返回的日志 ---
# (log_processor_messages 函数保持不变，这里省略以减少篇幅)
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

            # 处理特殊的占位符 [[key]] (逻辑不变)
            processed_message_key = message_key_or_raw
            if isinstance(message_key_or_raw, str) and '[[' in message_key_or_raw:
                import re
                placeholder = re.search(r'\[\[(.*?)\]\]', message_key_or_raw)
                if placeholder:
                    text_key = placeholder.group(1)
                    try:
                        replacement_text = get_text_func(text_key)
                        processed_message_key = message_key_or_raw.replace(f'[[{text_key}]]', replacement_text)
                    except KeyError:
                         logger.warning(f"Missing text key '{text_key}' used in placeholder: {message_key_or_raw}")
                         processed_message_key = message_key_or_raw.replace(f'[[{text_key}]]', f'[MissingKey:{text_key}]')

            # 尝试使用 get_text 获取翻译文本，或直接格式化 (逻辑不变)
            formatted_message = ""
            try:
                formatted_message = get_text_func(processed_message_key, **kwargs)
            except KeyError:
                if isinstance(processed_message_key, str) and '{' in processed_message_key:
                    try:
                        formatted_message = processed_message_key.format(**kwargs)
                    except Exception as fmt_e:
                        formatted_message = f"RAW LOG FORMAT ERROR [{level_str}]: {processed_message_key} | {kwargs} | {fmt_e}"
                else:
                    formatted_message = f"RAW LOG [{level_str}]: {processed_message_key} | {kwargs}"
            except Exception as text_err:
                 formatted_message = f"LOG PROCESSING ERROR [{level_str}]: {processed_message_key} | {kwargs} | Error: {text_err}"

            # 记录到全局 logger (添加文件名前缀)
            log_prefix = ""
            file_path_context = context_kwargs.get('path') or kwargs.get('path')
            if file_path_context:
                 log_prefix = f"[{os.path.basename(file_path_context)}] "
            elif 'filename' in kwargs:
                 log_prefix = f"[{kwargs['filename']}] "

            logger.log(level, f"{log_prefix}{formatted_message}")

            # 如果需要，记录到目录日志
            if to_dir_log:
                dir_path = context_kwargs.get('dir_path') # core.py 现在应该提供这个
                if dir_path:
                    log_utils.log_to_directory(logger, dir_path, dir_log_file_name_template, level_str, formatted_message)
                else:
                    # 警告现在应该不会出现了，除非 core.py 又改错了
                    logger.warning(f"Could not determine directory path for directory log (dir_path missing in context): {formatted_message}")

        except Exception as log_proc_err:
            logger.error(f"Error processing log entry: {log_entry}. Error: {log_proc_err}", exc_info=True)


# --- 主程序 ---
# 修改：添加 num_workers_override 参数
def main_runner(root_folder, num_workers_override=None):
    """主执行函数，协调整个处理流程（并发版本）"""
    # 1. 选择语言
    selected_language = ui.select_language()
    utils.set_language(selected_language)
    get_text = utils.get_text

    # 2. 初始化全局日志
    logger = log_utils.setup_global_logger()
    if not logger:
        try:
            print(get_text("log_setup_fail", path=config.GLOBAL_LOG_FILE_PATH, error="Logger setup failed"), file=sys.stderr)
        except Exception as e:
             print(f"Critical Error: Logger setup failed. Cannot get text ({e}). Cannot continue.", file=sys.stderr)
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
        logger.critical(f"Internal Error: Invalid processing mode '{mode}' selected.")
        sys.exit(1)


    # 5. 准备并发处理
    start_time = time.time()
    root_folder_norm = os.path.normpath(root_folder)

    logger.info(get_text("task_start", mode_name=mode_name))
    logger.info(get_text("target_folder", folder=root_folder_norm))
    logger.info(get_text("supported_types", extensions=', '.join(config.SUPPORTED_EXTENSIONS)))
    logger.info(get_text("state_file_info", state_file=dir_state_file_name, log_file=dir_log_file_name))

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
        set_methods = ('__contains__', '__iter__', 'add', 'update', '__len__', 'remove', 'discard', 'clear', 'pop', 'issubset', 'issuperset', 'union', 'intersection', 'difference')
        BaseManager.register('SharedSet', set, exposed=set_methods)
        BaseManager.register('Lock', multiprocessing.Lock)
        manager = BaseManager()
        manager.start()
        logger.info("Multiprocessing manager started and SharedSet type registered.")
    except Exception as manager_err:
        logger.critical(f"Failed to start multiprocessing manager or register SharedSet: {manager_err}", exc_info=True)
        sys.exit(1)

    dir_states = {}

    # --- 收集任务 ---
    # (收集任务逻辑保持不变，这里省略以减少篇幅)
    tasks_by_dir = defaultdict(list)
    logger.info("Scanning directories and collecting tasks...")
    try:
        for subdir, _, files in os.walk(root_folder_norm):
            subdir_norm = os.path.normpath(subdir)

            image_files_in_dir = [f for f in files if os.path.splitext(f)[1].lower() in config.SUPPORTED_EXTENSIONS]
            if not image_files_in_dir:
                continue

            if subdir_norm not in dir_states:
                dir_state_file_path = os.path.join(subdir_norm, dir_state_file_name)
                initial_processed_set = state.load_processed_files_from_dir(logger, dir_state_file_path)
                dir_states[subdir_norm] = {
                    'processed_set': manager.SharedSet(initial_processed_set),
                    'lock': manager.Lock() # 直接创建 Lock 代理
                }
                logger.debug(get_text("dir_processed_count", subdir=subdir_norm, state_file=dir_state_file_name, count=len(initial_processed_set)))

            current_dir_state = dir_states[subdir_norm]
            processed_set_proxy = current_dir_state['processed_set']
            lock_proxy = current_dir_state['lock']
            dir_state_file_path = os.path.join(subdir_norm, dir_state_file_name)

            for filename in image_files_in_dir:
                is_temp_or_meta = False
                if filename.endswith((".compress_temp", ".webp_temp")):
                     is_temp_or_meta = True
                elif filename == dir_state_file_name or filename == dir_log_file_name:
                     is_temp_or_meta = True
                elif mode == 'webp' and (filename == config.INPLACE_DIR_LOG_FILE_NAME or filename == config.INPLACE_DIR_STATE_FILE_NAME):
                     is_temp_or_meta = True
                elif mode == 'inplace' and (filename == config.WEBP_DIR_LOG_FILE_NAME or filename == config.WEBP_DIR_STATE_FILE_NAME):
                     is_temp_or_meta = True
                if is_temp_or_meta:
                    continue
                if mode == 'webp' and os.path.splitext(filename)[1].lower() == '.webp':
                    continue

                file_path_norm = os.path.normpath(os.path.join(subdir_norm, filename))

                if not os.path.isfile(file_path_norm):
                    logger.warning(f"Path is not a valid file during task collection: {file_path_norm}. Skipping.")
                    continue

                task_args = [
                    file_path_norm,
                    processed_set_proxy,
                    dir_state_file_path,
                    dir_log_file_name,
                ]
                if mode == 'webp':
                    task_args.extend([user_params['webp_quality'], user_params['webp_lossless'], lock_proxy])
                elif mode == 'inplace':
                    task_args.extend([user_params['quality'], user_params['png_optimize'], lock_proxy])

                tasks_by_dir[subdir_norm].append({'func': process_func_ref, 'args': task_args})

    except Exception as e:
        logger.critical(f"Error during directory scan and task collection: {e}", exc_info=True)
        if manager: manager.shutdown()
        sys.exit(1)

    tasks_to_submit = []
    for subdir, tasks in tasks_by_dir.items():
        for task in tasks:
            tasks_to_submit.append({'task': task, 'dir': subdir})

    total_tasks = len(tasks_to_submit)
    if total_tasks == 0:
         logger.info("No image files found to process in the specified directory and its subdirectories.")
         end_time = time.time()
         duration = end_time - start_time
         logger.info(get_text("task_end", mode_name=mode_name))
         logger.info(get_text("summary_processed", count=0))
         # ... (rest of summary)
         logger.info(get_text("summary_duration", duration=duration))
         logger.info(get_text("summary_global_log", path=config.GLOBAL_LOG_FILE_PATH))
         if manager: manager.shutdown()
         sys.exit(0)

    logger.info(f"Collected {total_tasks} tasks to process across {len(tasks_by_dir)} directories.")

    # --- 并发执行任务 ---
    # 修改：计算默认 worker 数 (CPU核心数-1)，并允许命令行覆盖
    num_workers = 0
    try:
        cpu_cores = os.cpu_count()
        if cpu_cores:
            # 默认使用核心数-1，最少为1
            default_workers = max(1, cpu_cores - 1)
            logger.info(f"Detected {cpu_cores} CPU cores. Defaulting to {default_workers} workers.")
        else:
            default_workers = 4 # Fallback if cpu_count returns None
            logger.info(f"Could not detect CPU cores, defaulting to {default_workers} workers.")
    except NotImplementedError:
         default_workers = 4 # Fallback if os.cpu_count() is not implemented
         logger.info(f"CPU count detection not implemented, defaulting to {default_workers} workers.")

    # 检查命令行参数是否覆盖默认值
    if num_workers_override is not None and num_workers_override > 0:
        num_workers = num_workers_override
        logger.info(f"Using {num_workers} workers based on command line argument.")
    else:
        num_workers = default_workers
        logger.info(f"Using default {num_workers} workers.")


    processed_count_in_loop = 0
    futures_map = {}
    processed_dirs_set = set()

    try:
        # 使用计算出的 num_workers
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            logger.info(f"Submitting {total_tasks} tasks to the process pool...")
            for i, task_info in enumerate(tasks_to_submit):
                task = task_info['task']
                future = executor.submit(task['func'], *task['args'])
                futures_map[future] = {'index': i, 'dir': task_info['dir'], 'file_path': task['args'][0]}

            logger.info("All tasks submitted. Waiting for results...")
            # (处理结果的循环保持不变，这里省略)
            for future in as_completed(futures_map):
                processed_count_in_loop += 1
                task_info = futures_map[future]
                file_path = task_info['file_path']
                dir_path = task_info['dir']

                if processed_count_in_loop % 50 == 0 or processed_count_in_loop == total_tasks:
                    logger.info(f"Progress: {processed_count_in_loop}/{total_tasks} tasks completed.")

                try:
                    result = future.result(timeout=300)

                    if result.get('log_messages'):
                        log_processor_messages(logger, get_text, dir_log_file_name, result['log_messages'])

                    status = result.get('status', 'error')
                    original_size = result.get('original_size')
                    output_size = result.get('output_size')

                    if original_size is not None:
                        total_original_size_bytes += original_size

                    if status == 'success':
                        total_processed_in_session += 1
                        processed_dirs_set.add(dir_path)
                        if output_size is not None:
                            total_output_size_bytes += output_size
                        else:
                             logger.warning(f"Successful task for {file_path} returned None output_size.")
                    elif status == 'skipped':
                        total_skipped_in_session += 1
                        if output_size is not None:
                            logger.warning(f"Skipped file {file_path} but received output size {output_size}. Ignoring size.")
                    else: # status == 'error'
                        total_errors_in_session += 1
                        processed_dirs_set.add(dir_path)
                        if output_size is not None:
                            total_output_size_bytes += output_size
                        error_details = result.get('error_details', 'Unknown error from worker')
                        logger.error(f"Failed to process {file_path}: {error_details}")

                except TimeoutError:
                     logger.error(f"Task for {file_path} timed out after 300 seconds.")
                     total_errors_in_session += 1
                     processed_dirs_set.add(dir_path)
                except Exception as exc:
                    total_errors_in_session += 1
                    processed_dirs_set.add(dir_path)
                    logger.critical(f"Error retrieving result for task on {file_path}: {exc}", exc_info=True)


    except KeyboardInterrupt:
        logger.warning(get_text("user_interrupt_process"))
        print(f"\n{get_text('user_interrupt_process')} - Shutting down process pool...")
    except Exception as e:
        logger.critical(get_text("unexpected_error_process"), exc_info=True)
        print(f"\n{get_text('unexpected_error_process')}: {e}")
    finally:
         if manager:
             logger.debug("Shutting down multiprocessing manager...")
             try:
                 manager.shutdown()
             except Exception as manager_shutdown_err:
                  logger.error(f"Error shutting down manager: {manager_shutdown_err}")


    # --- 任务结束统计 ---
    # (统计逻辑保持不变，这里省略)
    end_time = time.time()
    duration = end_time - start_time
    processed_dirs_count = len(processed_dirs_set)

    logger.info(f"Finished processing loop. Handled {processed_count_in_loop}/{total_tasks} tasks.")
    logger.info(get_text("task_end", mode_name=mode_name))
    logger.info(get_text("summary_processed", count=total_processed_in_session))
    logger.info(get_text("summary_skipped", count=total_skipped_in_session))
    logger.info(get_text("summary_dirs_processed", count=processed_dirs_count))
    logger.info(get_text("summary_errors", count=total_errors_in_session))

    total_original_size_mb = total_original_size_bytes / (1024 * 1024)
    total_output_size_mb = total_output_size_bytes / (1024 * 1024)
    logger.info(get_text("summary_size_before", size=total_original_size_mb))
    logger.info(get_text("summary_size_after", size=total_output_size_mb))

    if total_original_size_bytes > 0:
        if total_processed_in_session > 0 or (total_errors_in_session > 0 and total_output_size_bytes > 0):
            if total_output_size_bytes < total_original_size_bytes:
                try:
                    size_reduction_percent = ((total_original_size_bytes - total_output_size_bytes) / total_original_size_bytes) * 100
                    logger.info(get_text("summary_reduction", percent=size_reduction_percent))
                except ZeroDivisionError:
                     logger.warning("Division by zero error during reduction calculation.")
            elif total_output_size_bytes > 0 :
                 logger.info("Total output size did not decrease compared to estimated original size.")
            else:
                 logger.info(get_text("summary_no_output"))
        elif total_skipped_in_session > 0 and total_processed_in_session == 0 and total_errors_in_session == 0:
             logger.info("No new files processed or encountered errors (only skipped). Size reduction not applicable.")
        else:
             logger.info("Original size available but no files were processed, skipped, or errored.")
    elif total_tasks > 0:
         logger.info("Total original size is zero. Cannot calculate reduction.")
    else:
         logger.info("No tasks were run. Size reduction not applicable.")

    logger.info(get_text("summary_duration", duration=duration))
    global_log_path_for_summary = os.path.join(config.RUN_STATE_DIR, os.path.basename(config.GLOBAL_LOG_FILE_PATH))
    logger.info(get_text("summary_global_log", path=global_log_path_for_summary))
    logger.info(get_text("summary_dir_log", mode_name=mode_name, log_file=dir_log_file_name))
    logger.info(get_text("summary_dir_state", mode_name=mode_name, state_file=dir_state_file_name))


# --- 脚本入口 ---
if __name__ == "__main__":
    utils.set_language('zh')
    parser = argparse.ArgumentParser(
        description=utils.get_text("argparse_description"),
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "root_folder",
        help=utils.get_text("argparse_folder_help")
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        help="Number of worker processes to use (default: CPU cores - 1)" # 更新帮助文本
    )
    args = parser.parse_args()

    if not os.path.isdir(args.root_folder):
        print(utils.get_text("error_invalid_path", path=args.root_folder), file=sys.stderr)
        sys.exit(1)

    # --- 执行主函数 ---
    # 修改：将 args.workers 传递给 main_runner
    main_runner(root_folder=args.root_folder, num_workers_override=args.workers)