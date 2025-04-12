# -*- coding: utf-8 -*-
import os
import sys
import argparse
import time
import logging # 只导入 logging 模块本身

# 使用相对导入来引入包内的模块
from image_processor import config
from image_processor import utils
from image_processor import log_utils
from image_processor import state
from image_processor import core
from image_processor import ui

# --- 主程序 ---
def main_runner(root_folder):
    """主执行函数，协调整个处理流程"""
    # 1. 选择语言 (需要在日志设置前完成，因为日志设置可能需要打印消息)
    # select_language 返回语言代码 'zh' 或 'en'
    selected_language = ui.select_language()
    # 设置全局语言，以便 get_text 能正确工作
    utils.set_language(selected_language)

    # 使用 get_text 获取文本 (现在可以安全使用)
    get_text = utils.get_text

    # 2. 初始化全局日志
    # setup_global_logger 返回 logger 实例或 None
    logger = log_utils.setup_global_logger()
    if not logger:
        # 如果日志设置失败，尝试用 get_text 打印错误，否则用硬编码英文
        try:
            print(get_text("log_setup_fail", path=config.GLOBAL_LOG_FILE_PATH, error="Logger setup failed"), file=sys.stderr)
        except Exception: # Fallback if get_text itself fails
             print(f"Critical Error: Logger setup failed at {config.GLOBAL_LOG_FILE_PATH}. Cannot continue.", file=sys.stderr)
        sys.exit(1) # 日志是关键，设置失败则退出

    # 3. 选择处理模式
    # get_processing_mode 返回 'inplace' 或 'webp'
    mode = ui.get_processing_mode()

    # 获取用户友好的模式名称用于日志和显示
    mode_name = get_text('mode_webp') if mode == 'webp' else get_text('mode_inplace')
    logger.info(get_text("mode_selected", mode_name=mode_name))

    # 4. 获取对应模式的参数
    user_params = {}
    dir_state_file_name = ""
    dir_log_file_name = ""
    process_function = None

    if mode == 'webp':
        user_params = ui.get_webp_parameters() # 从 ui 模块获取参数
        dir_state_file_name = config.WEBP_DIR_STATE_FILE_NAME # 从 config 获取
        dir_log_file_name = config.WEBP_DIR_LOG_FILE_NAME     # 从 config 获取
        process_function = core.convert_to_webp_inplace      # 从 core 获取
        # 日志记录 WebP 配置
        webp_quality = user_params['webp_quality']
        webp_lossless = user_params['webp_lossless']
        lossless_mode_text = get_text("webp_config_lossless_forced") if webp_lossless else get_text("webp_config_lossless_auto")
        logger.info(get_text("webp_config", quality=webp_quality, lossless_mode=lossless_mode_text))

    elif mode == 'inplace':
        user_params = ui.get_inplace_parameters() # 从 ui 模块获取参数
        dir_state_file_name = config.INPLACE_DIR_STATE_FILE_NAME # 从 config 获取
        dir_log_file_name = config.INPLACE_DIR_LOG_FILE_NAME     # 从 config 获取
        process_function = core.compress_image_inplace        # 从 core 获取
        # 日志记录原格式压缩配置
        quality_inplace = user_params['quality']
        png_optimize_inplace = user_params['png_optimize']
        png_optimize_text = get_text("inplace_png_optimize_enabled") if png_optimize_inplace else get_text("inplace_png_optimize_disabled")
        logger.info(get_text("inplace_config",
                             quality=quality_inplace,
                             large_threshold=config.INPLACE_LARGE_FILE_THRESHOLD_MB, # 从 config 获取
                             large_quality=config.INPLACE_LARGE_FILE_COMPRESSION_QUALITY, # 从 config 获取
                             png_optimize=png_optimize_text))

    # 5. 开始处理流程
    start_time = time.time()
    root_folder_norm = os.path.normpath(root_folder)

    logger.info(get_text("task_start", mode_name=mode_name))
    logger.info(get_text("target_folder", folder=root_folder_norm))
    logger.info(get_text("supported_types", extensions=', '.join(config.SUPPORTED_EXTENSIONS))) # 从 config 获取
    logger.info(get_text("state_file_info", state_file=dir_state_file_name, log_file=dir_log_file_name))

    # 初始化统计变量
    total_processed_in_session = 0
    total_skipped_in_session = 0
    total_errors_in_session = 0
    total_original_size_bytes = 0
    total_output_size_bytes = 0
    processed_dirs = set()

    # --- 递归遍历并处理 ---
    try:
        for subdir, _, files in os.walk(root_folder_norm):
            logger.debug(get_text("scanning_dir", mode_name=mode_name, subdir=subdir))

            # 过滤出支持的图片文件
            image_files_in_dir = [f for f in files if os.path.splitext(f)[1].lower() in config.SUPPORTED_EXTENSIONS]
            if not image_files_in_dir:
                continue # 没有图片文件，跳过此目录

            # 加载此目录的处理状态
            dir_state_file_path = os.path.join(subdir, dir_state_file_name)
            # 调用 state 模块的函数，传入 logger
            processed_in_dir = state.load_processed_files_from_dir(logger, dir_state_file_path)
            logger.debug(get_text("dir_processed_count", subdir=subdir, state_file=dir_state_file_name, count=len(processed_in_dir)))

            files_processed_in_this_dir_session = 0
            for filename in image_files_in_dir:
                # 忽略临时文件和日志/状态文件 (从 config 获取文件名)
                if filename.endswith((".compress_temp", ".webp_temp")) or \
                   filename in [config.INPLACE_DIR_LOG_FILE_NAME, config.INPLACE_DIR_STATE_FILE_NAME,
                                config.WEBP_DIR_LOG_FILE_NAME, config.WEBP_DIR_STATE_FILE_NAME]:
                    continue

                # WebP 模式下，跳过 .webp 文件自身
                if mode == 'webp' and os.path.splitext(filename)[1].lower() == '.webp':
                    logger.debug(get_text("skip_webp_self", path=os.path.join(subdir, filename)))
                    continue

                file_path_norm = os.path.normpath(os.path.join(subdir, filename))

                # 检查文件是否存在（可能在遍历过程中被移动或删除）
                if not os.path.exists(file_path_norm):
                    logger.warning(f"File listed during scan no longer exists: {file_path_norm}. Skipping.")
                    continue

                # 检查文件是否是真实的文件而不是目录（虽然 os.walk 通常只列出文件）
                if not os.path.isfile(file_path_norm):
                    logger.warning(f"Path listed during scan is not a file: {file_path_norm}. Skipping.")
                    continue


                success = False
                original_size = None
                output_size = None
                try:
                    # 调用 core 模块的处理函数，传入 logger 和其他参数
                    if mode == 'webp':
                        success, original_size, output_size = process_function(
                            logger, file_path_norm, processed_in_dir, dir_state_file_path,
                            dir_log_file_name, user_params['webp_quality'], user_params['webp_lossless']
                        )
                    elif mode == 'inplace':
                         success, original_size, output_size = process_function(
                            logger, file_path_norm, processed_in_dir, dir_state_file_path,
                            dir_log_file_name, user_params['quality'], user_params['png_optimize']
                        )
                except Exception as e:
                    # 捕获调用处理函数本身时发生的未预料异常
                    logger.critical(get_text("unhandled_exception", path=file_path_norm, error=e), exc_info=True)
                    total_errors_in_session += 1
                    # 尝试获取原始大小用于统计，即使处理失败
                    try:
                        if os.path.exists(file_path_norm): # 检查文件是否还存在
                           original_size = os.path.getsize(file_path_norm)
                    except OSError:
                        original_size = 0 # 获取大小失败，计为0

                # --- 统计 ---
                # original_size 和 output_size 可能为 None 或 0
                if original_size is not None:
                    total_original_size_bytes += original_size

                if success:
                    total_processed_in_session += 1
                    files_processed_in_this_dir_session += 1
                    processed_dirs.add(subdir)
                    if output_size is not None:
                        total_output_size_bytes += output_size
                # 如果处理函数返回 False，表示处理失败或跳过
                # 需要区分是“已处理跳过”还是“处理中出错”
                elif filename in processed_in_dir: # 如果在状态文件中，说明是跳过
                    total_skipped_in_session += 1
                    # 如果是跳过，理论上不应该有 output_size，但以防万一
                    if output_size is not None:
                        logger.warning(f"Skipped file {file_path_norm} but received an output size {output_size}. Ignoring size.")
                else: # 不在状态文件中且 success=False，说明是处理错误
                    total_errors_in_session += 1
                    # 错误情况下，output_size 可能是压缩/转换后的文件大小（如果重命名失败）
                    # 或者为 None。无论如何都加到总输出大小中（如果存在）
                    if output_size is not None:
                        total_output_size_bytes += output_size


            if files_processed_in_this_dir_session > 0:
                logger.info(get_text("dir_process_complete", subdir=subdir, count=files_processed_in_this_dir_session, mode_name=mode_name))

    except KeyboardInterrupt:
        logger.warning(get_text("user_interrupt_process"))
        print(f"\n{get_text('user_interrupt_process')}") # 也打印到控制台
    except Exception as e:
        logger.critical(get_text("unexpected_error_process"), exc_info=True)
        print(f"\n{get_text('unexpected_error_process')}: {e}") # 也打印到控制台

    # --- 任务结束统计 ---
    end_time = time.time()
    duration = end_time - start_time
    logger.info(get_text("task_end", mode_name=mode_name))
    logger.info(get_text("summary_processed", count=total_processed_in_session))
    logger.info(get_text("summary_skipped", count=total_skipped_in_session))
    logger.info(get_text("summary_dirs_processed", count=len(processed_dirs)))
    logger.info(get_text("summary_errors", count=total_errors_in_session))

    total_original_size_mb = total_original_size_bytes / (1024 * 1024)
    total_output_size_mb = total_output_size_bytes / (1024 * 1024)
    logger.info(get_text("summary_size_before", size=total_original_size_mb))
    logger.info(get_text("summary_size_after", size=total_output_size_mb))

    # 计算减少百分比的逻辑保持不变
    if total_original_size_bytes > 0 and total_processed_in_session > 0: # 确保有处理成功的文件
        # 仅基于成功处理的文件计算减少比例可能更准确，但这需要更复杂的追踪
        # 当前计算的是所有输入和所有输出（包括失败留下的）的总体积变化
        if total_output_size_bytes < total_original_size_bytes: # 确保体积是减少的
             try:
                 size_reduction_percent = ((total_original_size_bytes - total_output_size_bytes) / total_original_size_bytes) * 100
                 logger.info(get_text("summary_reduction", percent=size_reduction_percent))
             except ZeroDivisionError:
                  logger.info(get_text("summary_no_output")) # 避免除零错误
        else:
             logger.info("Total output size did not decrease compared to estimated original size.")

    elif total_processed_in_session == 0 and total_errors_in_session == 0 and total_skipped_in_session > 0:
         logger.info("No new files processed in this session (all previously processed or skipped).")
    elif total_processed_in_session == 0 and total_errors_in_session > 0:
         logger.info(get_text("summary_no_output"))
    else: # total_original_size_bytes <= 0
         logger.info("No processable files found or total original size is zero.")


    logger.info(get_text("summary_duration", duration=duration))
    logger.info(get_text("summary_global_log", path=config.GLOBAL_LOG_FILE_PATH))
    logger.info(get_text("summary_dir_log", mode_name=mode_name, log_file=dir_log_file_name))
    logger.info(get_text("summary_dir_state", mode_name=mode_name, state_file=dir_state_file_name))


# --- 脚本入口 ---
if __name__ == "__main__":
    # 确保可以找到 image_processor 包
    # 如果从项目根目录运行 `python src/main.py ...`，src 目录通常会自动添加到 sys.path
    # 如果从 src 目录运行 `python main.py ...`，相对导入也能工作
    # 如果以模块方式运行 `python -m src.main ...`，这通常是更推荐的方式

    # --- 命令行参数解析 ---
    # 使用 utils.get_text 来获取描述和帮助文本 (需要先设置一个默认语言)
    utils.set_language('zh') # 设置默认中文用于解析器文本
    parser = argparse.ArgumentParser(
        description=utils.get_text("argparse_description"),
        formatter_class=argparse.RawTextHelpFormatter # 保持格式
    )
    parser.add_argument(
        "root_folder",
        help=utils.get_text("argparse_folder_help")
    )
    args = parser.parse_args()

    # --- 验证根目录 ---
    if not os.path.isdir(args.root_folder):
        # 使用 get_text 获取错误消息
        print(utils.get_text("error_invalid_path", path=args.root_folder), file=sys.stderr)
        sys.exit(1)

    # --- 执行主函数 ---
    # 将主逻辑封装在 main_runner 函数中
    main_runner(root_folder=args.root_folder)