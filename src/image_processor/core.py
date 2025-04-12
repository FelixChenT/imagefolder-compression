# image_processor/core.py
# -- coding: utf-8 --

import os
import time
import traceback
from PIL import Image, UnidentifiedImageError
import sys # 用于可能的 fallback 输出

# 使用相对导入来获取配置
from . import config
# 不再直接从 core 调用 get_text 或 log_utils
# 导入 state 中的函数，但调用将在本文件中进行
from .state import save_processed_file_to_dir

# --- 辅助函数：安全删除文件 ---
def _safe_remove(file_path):
    """尝试删除文件，忽略不存在错误，返回是否成功以及错误消息（如果失败）"""
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
        return True, None
    except OSError as e:
        # 返回错误信息，让调用者记录日志
        err_msg = f"Failed to remove {file_path}: {e}"
        return False, err_msg

# --- 核心压缩逻辑 (原格式压缩模式) ---
# 修改：移除 logger，添加 lock，返回包含结果和日志信息的字典
def compress_image_inplace(image_path_raw, processed_in_dir_set, dir_state_file,
                           dir_log_file_name, quality, png_optimize, lock):
    """
    压缩单个图片文件并替换原文件 (保留原始格式)。
    在并发环境中使用，不直接记录日志，而是返回结果和日志消息。
    需要传入 multiprocessing.Lock 用于状态文件写入。
    返回: 字典 {'status': 'success'/'skipped'/'error',
                 'original_size': int/None,
                 'output_size': int/None,
                 'log_messages': [(level, message_key_or_raw, kwargs, to_dir_log, context_kwargs)],
                 'error_details': str/None,
                 'original_filename': str,
                 'file_path': str}
    """
    image_path = os.path.normpath(image_path_raw)
    dir_path = os.path.dirname(image_path)
    file_name = os.path.basename(image_path)
    # log_messages 存储待记录的日志信息 (level_str, key_or_raw, kwargs, write_to_dir_log_bool, context_kwargs)
    log_messages = []
    result = {
        'status': 'error', # 默认失败
        'original_size': None,
        'output_size': None,
        'log_messages': log_messages,
        'error_details': None,
        'original_filename': file_name,
        'file_path': image_path
    }
    # 定义上下文信息，主要是路径，方便后续添加日志时引用
    context = {'path': image_path, 'dir_path': dir_path}

    # 1. 检查是否已处理
    if file_name in processed_in_dir_set:
        # 确保传递 context
        log_messages.append(('debug', "compress_skip_processed", {'state_file': os.path.basename(dir_state_file), 'path': image_path}, False, context))
        result['status'] = 'skipped'
        return result

    # 2. 记录开始处理日志
    # 确保传递 context
    log_messages.append(('info', "compress_start_path", {'path': image_path}, False, context))
    log_messages.append(('info', "compress_start", {'filename': file_name}, True, context))

    # 3. 获取原始大小
    original_size = None
    original_size_mb = 0
    try:
        original_size = os.path.getsize(image_path)
        original_size_mb = original_size / (1024 * 1024)
        # 确保传递 context
        log_messages.append(('info', "compress_file_size", {'size': original_size_mb}, False, context))
        log_messages.append(('info', "compress_file_size", {'filename': file_name, 'size': original_size_mb}, True, context))
        result['original_size'] = original_size
    except OSError as e:
        # 确保传递 context
        log_messages.append(('error', "compress_get_size_fail_path", {'path': image_path, 'error': e}, False, context))
        log_messages.append(('error', "compress_get_size_fail", {'filename': file_name, 'error': e}, True, context))
        result['error_details'] = f"Cannot get original size: {e}"
        return result

    # 4. 定义临时文件路径
    pid = os.getpid()
    timestamp = int(time.time() * 1000)
    temp_suffix = f".{timestamp}_{pid}.compress_temp"
    temp_path = os.path.join(dir_path, f"{file_name}{temp_suffix}")
    compressed_size = None

    # 5. 打开、处理、保存到临时文件
    img_to_save = None
    try:
        with Image.open(image_path) as img:
            # 确保传递 context
            log_messages.append(('debug', "compress_open_success", {'path': image_path}, False, context))
            original_format = img.format
            if not original_format:
                ext_lower = os.path.splitext(image_path)[1].lower()
                format_map = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.bmp': 'BMP', '.tif': 'TIFF', '.tiff': 'TIFF'}
                original_format = format_map.get(ext_lower)
                if not original_format:
                    # 确保传递 context
                    log_messages.append(('warning', "compress_format_unknown_path", {'path': image_path, 'ext': ext_lower}, False, context))
                    log_messages.append(('warning', "compress_format_unknown", {'filename': file_name, 'ext': ext_lower}, True, context))
                    result['error_details'] = f"Unknown format extension: {ext_lower}"
                    return result

            # 确保传递 context
            log_messages.append(('debug', "compress_format_identified", {'format': original_format, 'path': image_path}, False, context))

            save_options = {'format': original_format}
            img_to_save = img
            current_jpeg_quality = quality

            is_large_file = original_size_mb > config.INPLACE_LARGE_FILE_THRESHOLD_MB
            if original_format == 'JPEG' and is_large_file:
                current_jpeg_quality = config.INPLACE_LARGE_FILE_COMPRESSION_QUALITY
                # 确保传递 context
                log_messages.append(('info', "compress_large_file", {'threshold': config.INPLACE_LARGE_FILE_THRESHOLD_MB, 'quality': current_jpeg_quality}, False, context))
                log_messages.append(('info', "compress_large_file_log", {'filename': file_name, 'threshold': config.INPLACE_LARGE_FILE_THRESHOLD_MB, 'quality': current_jpeg_quality}, True, context))

            if original_format == 'JPEG':
                save_options['quality'] = current_jpeg_quality
                save_options['optimize'] = True
                icc_profile = img.info.get('icc_profile')
                if icc_profile: save_options['icc_profile'] = icc_profile
                exif = img.info.get('exif')
                if exif: save_options['exif'] = exif
                if img.mode in ('RGBA', 'P'):
                     has_transparency = 'transparency' in img.info
                     if img.mode == 'RGBA' or (img.mode == 'P' and has_transparency) :
                        # 确保传递 context
                        log_messages.append(('debug', "compress_rgba_to_rgb", {'path': image_path}, False, context))
                        log_messages.append(('debug', "compress_rgba_to_rgb_log", {'filename': file_name}, True, context))
                        try:
                            img_to_save = img.convert('RGB')
                        except Exception as convert_err:
                             # 确保传递 context
                             log_messages.append(('warning', f"Could not convert image {image_path} to RGB: {convert_err}", {}, False, context))
                             img_to_save = img
            elif original_format == 'PNG':
                save_options['optimize'] = png_optimize
            else:
                 # 确保传递 context
                 log_messages.append(('debug', "compress_default_save", {'format': original_format, 'path': image_path}, False, context))

            img_to_save.save(temp_path, **save_options)
        # 确保传递 context
        log_messages.append(('debug', "compress_save_temp_success", {'path': temp_path}, False, context))

        # 6. 检查临时文件
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            # 确保传递 context
            log_messages.append(('error', "compress_temp_invalid_path", {'path': temp_path, 'original_path': image_path}, False, context))
            log_messages.append(('error', "compress_temp_invalid", {'filename': file_name}, True, context))
            result['error_details'] = "Invalid temp file created"
            removed, rm_msg = _safe_remove(temp_path)
            # 确保传递 context
            if not removed: log_messages.append(('error', "compress_temp_clean_fail", {'path': temp_path, 'error': rm_msg}, False, context))
            return result

        compressed_size = os.path.getsize(temp_path)
        result['output_size'] = compressed_size

        # 7. 删除原图
        removed, rm_msg = _safe_remove(image_path)
        if not removed:
            # 确保传递 context
            log_messages.append(('error', "compress_remove_original_fail_path", {'path': image_path, 'error': rm_msg, 'temp_path': temp_path}, False, context))
            log_messages.append(('error', "compress_remove_original_fail", {'filename': file_name, 'error': rm_msg, 'temp_filename': os.path.basename(temp_path)}, True, context))
            result['error_details'] = f"Failed to remove original file: {rm_msg}"
            return result
        else:
            # 确保传递 context
             log_messages.append(('debug', "compress_remove_original_success", {'path': image_path}, False, context))

        # 8. 重命名临时文件
        try:
            os.rename(temp_path, image_path)
            compressed_size_mb = compressed_size / (1024 * 1024)
            reduction_percent = ((original_size - compressed_size) / original_size) * 100 if original_size > 0 else 0
            # 确保传递 context
            log_messages.append(('info', "compress_rename_success_path", {'path': image_path, 'orig_mb': original_size_mb, 'comp_mb': compressed_size_mb}, False, context))
            log_messages.append(('info', "compress_rename_success", {'filename': file_name, 'orig_mb': original_size_mb, 'comp_mb': compressed_size_mb, 'percent': reduction_percent}, True, context))
        except OSError as e:
            # 确保传递 context
            log_messages.append(('critical', "compress_rename_fail_path", {'temp_path': temp_path, 'path': image_path, 'error': e}, False, context))
            log_messages.append(('critical', "compress_rename_fail", {'temp_filename': os.path.basename(temp_path), 'filename': file_name, 'error': e}, True, context))
            result['error_details'] = f"CRITICAL: Failed to rename temp file {temp_path} to {image_path} after deleting original: {e}. MANUAL INTERVENTION NEEDED!"
            return result

        # 9. 记录处理成功状态
        try:
            save_processed_file_to_dir(None, dir_state_file, file_name, lock)
        except Exception as state_save_e:
             # 确保传递 context
             log_messages.append(('error', "log_save_state_fail", {'path': dir_state_file, 'filename': file_name, 'error': state_save_e}, False, context))
             result['error_details'] = f"File processed but failed to save state: {state_save_e}"
             return result

        result['status'] = 'success'
        return result

    # --- 异常处理 ---
    except UnidentifiedImageError as e:
        # 确保传递 context
        log_messages.append(('error', "compress_unidentified_path", {'path': image_path}, False, context))
        log_messages.append(('error', "compress_unidentified", {'filename': file_name}, True, context))
        result['error_details'] = f"UnidentifiedImageError: {e}"
        removed, rm_msg = _safe_remove(temp_path)
        # 确保传递 context
        if not removed: log_messages.append(('warning', "compress_unidentified_clean_fail", {'path': temp_path, 'error': rm_msg}, False, context))
        return result
    except (IOError, OSError) as e:
        # 确保传递 context
        log_messages.append(('error', "compress_io_error_path", {'path': image_path, 'error': e}, False, context))
        log_messages.append(('error', "compress_io_error", {'filename': file_name, 'error': e}, True, context))
        result['error_details'] = f"IO/OS Error during processing: {e}"
        removed, rm_msg = _safe_remove(temp_path)
        # 确保传递 context
        if not removed: log_messages.append(('error', "compress_unexpected_error_clean_fail", {'path': temp_path, 'error': rm_msg}, False, context))
        return result
    except Exception as e:
        tb_str = traceback.format_exc()
        # 确保传递 context
        log_messages.append(('critical', "compress_unexpected_error_path", {'path': image_path, 'error': e}, False, context))
        log_messages.append(('critical', "compress_unexpected_error", {'filename': file_name, 'error': str(e), 'traceback': tb_str}, True, context))
        result['error_details'] = f"Unexpected Error: {e}\n{tb_str}"
        removed, rm_msg = _safe_remove(temp_path)
        # 确保传递 context
        if not removed: log_messages.append(('error', "compress_unexpected_error_clean_fail", {'path': temp_path, 'error': rm_msg}, False, context))
        return result
    finally:
        if 'img' in locals() and hasattr(img, 'close'):
            try: img.close()
            except Exception: pass
        if img_to_save and hasattr(img_to_save, 'close') and img_to_save is not img:
             try: img_to_save.close()
             except Exception: pass


# --- 核心转换逻辑 (WebP 模式 - 原地替换) ---
# 修改：移除 logger，添加 lock，返回包含结果和日志信息的字典
def convert_to_webp_inplace(image_path_raw, processed_in_dir_set, dir_state_file,
                            dir_log_file_name, quality, use_lossless, lock):
    """
    将单个图片文件转换为 WebP 格式并替换原文件。
    在并发环境中使用，不直接记录日志，而是返回结果和日志消息。
    需要传入 multiprocessing.Lock 用于状态文件写入。
    返回: 字典 {'status': 'success'/'skipped'/'error',
                 'original_size': int/None,
                 'output_size': int/None, # WebP 文件大小
                 'log_messages': [(level, message_key_or_raw, kwargs, to_dir_log, context_kwargs)],
                 'error_details': str/None,
                 'original_filename': str,
                 'file_path': str}
    """
    image_path = os.path.normpath(image_path_raw)
    dir_path = os.path.dirname(image_path)
    file_name = os.path.basename(image_path)
    base_name, _ = os.path.splitext(file_name)
    webp_file_name = base_name + ".webp"
    webp_output_path = os.path.join(dir_path, webp_file_name)
    log_messages = []
    result = {
        'status': 'error',
        'original_size': None,
        'output_size': None,
        'log_messages': log_messages,
        'error_details': None,
        'original_filename': file_name,
        'file_path': image_path
    }
    # 定义上下文信息
    context = {'path': image_path, 'dir_path': dir_path, 'webp_path': webp_output_path}

    # 1. 检查是否已处理
    if file_name in processed_in_dir_set:
        # 确保传递 context
        log_messages.append(('debug', "convert_skip_processed", {'state_file': os.path.basename(dir_state_file), 'path': image_path}, False, context))
        result['status'] = 'skipped'
        return result

    # 2. 记录开始转换日志
    # 确保传递 context
    log_messages.append(('info', "convert_start_path", {'path': image_path, 'webp_path': webp_output_path}, False, context))
    log_messages.append(('info', "convert_start", {'filename': file_name, 'webp_filename': webp_file_name}, True, context))

    # 3. 获取原始大小
    original_size = None
    original_size_mb = 0
    try:
        original_size = os.path.getsize(image_path)
        original_size_mb = original_size / (1024 * 1024)
        # 确保传递 context
        log_messages.append(('info', "convert_original_size", {'size': original_size_mb}, False, context))
        log_messages.append(('info', "convert_original_size", {'filename': file_name, 'size': original_size_mb}, True, context))
        result['original_size'] = original_size
    except OSError as e:
        # 确保传递 context
        log_messages.append(('error', "convert_get_size_fail_path", {'path': image_path, 'error': e}, False, context))
        log_messages.append(('error', "convert_get_size_fail", {'filename': file_name, 'error': e}, True, context))
        result['error_details'] = f"Cannot get original size: {e}"
        return result

    # 4. 定义临时文件路径
    pid = os.getpid()
    timestamp = int(time.time() * 1000)
    temp_suffix = f".{timestamp}_{pid}.webp_temp"
    temp_path = webp_output_path + temp_suffix
    webp_size = None

    # 5. 打开、处理、保存为 WebP 到临时文件
    img_to_save = None
    try:
        with Image.open(image_path) as img:
            # 确保传递 context
            log_messages.append(('debug', "convert_open_success", {'path': image_path}, False, context))

            webp_save_options = {'quality': quality}

            original_format_from_ext = os.path.splitext(image_path)[1].lower()
            original_format_from_img = img.format
            lossless_prone_formats = ['PNG', 'BMP', 'TIFF']
            lossless_prone_extensions = ['.png', '.bmp', '.tif', '.tiff']

            effective_lossless = use_lossless or \
                                 (original_format_from_img and original_format_from_img.upper() in lossless_prone_formats) or \
                                 (not original_format_from_img and original_format_from_ext in lossless_prone_extensions)

            webp_save_options['lossless'] = effective_lossless
            log_lossless_mode_key = "convert_lossless" if effective_lossless else "convert_lossy"

            # 确保传递 context
            log_messages.append(('info', "convert_webp_options", {'quality': quality, 'mode': f'[[{log_lossless_mode_key}]]', 'path': webp_output_path}, False, context))
            log_messages.append(('info', "convert_webp_options_log", {'filename': file_name, 'webp_filename': webp_file_name, 'quality': quality, 'mode': f'[[{log_lossless_mode_key}]]'}, True, context))

            icc_profile = img.info.get('icc_profile')
            if icc_profile: webp_save_options['icc_profile'] = icc_profile
            exif = img.info.get('exif')
            if exif: webp_save_options['exif'] = exif

            img_to_save = img
            if img.mode == 'P':
                 try:
                     # 确保传递 context
                     log_messages.append(('debug', f"Converting P mode image {image_path} to RGBA for WebP", {}, False, context))
                     img_to_save = img.convert('RGBA')
                 except Exception:
                     try:
                         # 确保传递 context
                         log_messages.append(('debug', f"Converting P mode image {image_path} to RGB for WebP", {}, False, context))
                         img_to_save = img.convert('RGB')
                     except Exception as convert_err:
                          # 确保传递 context
                          log_messages.append(('warning', f"Could not convert P mode image {image_path} for WebP: {convert_err}", {}, False, context))
                          img_to_save = img
            elif img.mode == 'LA':
                 # 确保传递 context
                 log_messages.append(('debug', f"Converting LA mode image {image_path} to RGBA for WebP", {}, False, context))
                 img_to_save = img.convert('RGBA')
            elif img.mode not in ('RGB', 'RGBA'):
                 try:
                     # 确保传递 context
                     log_messages.append(('debug', f"Converting {img.mode} mode image {image_path} to RGB for WebP", {}, False, context))
                     img_to_save = img.convert('RGB')
                 except Exception as convert_err:
                     # 确保传递 context
                     log_messages.append(('warning', f"Could not convert {img.mode} mode image {image_path} to RGB for WebP: {convert_err}", {}, False, context))
                     img_to_save = img

            img_to_save.save(temp_path, 'WEBP', **webp_save_options)
        # 确保传递 context
        log_messages.append(('debug', "convert_save_temp_success", {'path': temp_path}, False, context))

        # 6. 检查临时 WebP 文件
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            # 确保传递 context
            log_messages.append(('error', "convert_temp_invalid_path", {'path': temp_path, 'original_path': image_path}, False, context))
            log_messages.append(('error', "convert_temp_invalid", {'filename': file_name}, True, context))
            result['error_details'] = "Invalid temp WebP file created"
            removed, rm_msg = _safe_remove(temp_path)
            # 确保传递 context
            if not removed: log_messages.append(('error', "convert_temp_clean_fail", {'path': temp_path, 'error': rm_msg}, False, context))
            return result

        webp_size = os.path.getsize(temp_path)
        result['output_size'] = webp_size

        # 7. 删除原图
        removed, rm_msg = _safe_remove(image_path)
        if not removed:
            # 确保传递 context
            log_messages.append(('error', "convert_remove_original_fail_path", {'path': image_path, 'error': rm_msg, 'temp_path': temp_path}, False, context))
            log_messages.append(('error', "convert_remove_original_fail", {'filename': file_name, 'error': rm_msg, 'temp_filename': os.path.basename(temp_path)}, True, context))
            result['error_details'] = f"Failed to remove original file: {rm_msg}"
            return result
        else:
             # 确保传递 context
             log_messages.append(('debug', "convert_remove_original_success", {'path': image_path}, False, context))

        # 8. 重命名临时文件为最终的 WebP 文件名
        try:
            if os.path.exists(webp_output_path):
                 # 确保传递 context
                 log_messages.append(('warning', f"Target WebP file exists, attempting overwrite: {webp_output_path}", {}, False, context))
                 removed, rm_msg = _safe_remove(webp_output_path)
                 if not removed:
                      # 确保传递 context
                      log_messages.append(('error', f"Failed to remove existing target WebP: {webp_output_path}: {rm_msg}", {}, False, context))
                      log_messages.append(('critical', "convert_rename_fail_path", {'temp_path': temp_path, 'webp_path': webp_output_path, 'error': f"Cannot remove existing file: {rm_msg}"}, False, context))
                      log_messages.append(('critical', "convert_rename_fail", {'temp_filename': os.path.basename(temp_path), 'webp_filename': webp_file_name, 'error': f"Cannot remove existing file: {rm_msg}"}, True, context))
                      result['error_details'] = f"CRITICAL: Cannot remove existing target file {webp_output_path}. Original deleted! Manual intervention needed!"
                      return result

            os.rename(temp_path, webp_output_path)
            webp_size_mb = webp_size / (1024 * 1024)
            reduction_percent = ((original_size - webp_size) / original_size) * 100 if original_size > 0 else 0
            # 确保传递 context
            log_messages.append(('info', "convert_rename_success_path", {'path': image_path, 'webp_path': webp_output_path, 'orig_mb': original_size_mb, 'webp_mb': webp_size_mb}, False, context))
            log_messages.append(('info', "convert_rename_success", {'filename': file_name, 'webp_filename': webp_file_name, 'orig_mb': original_size_mb, 'webp_mb': webp_size_mb, 'percent': reduction_percent}, True, context))
        except OSError as e:
            # 确保传递 context
            log_messages.append(('critical', "convert_rename_fail_path", {'temp_path': temp_path, 'webp_path': webp_output_path, 'error': e}, False, context))
            log_messages.append(('critical', "convert_rename_fail", {'temp_filename': os.path.basename(temp_path), 'webp_filename': webp_file_name, 'error': e}, True, context))
            result['error_details'] = f"CRITICAL: Failed to rename temp file {temp_path} to {webp_output_path} after deleting original: {e}. MANUAL INTERVENTION NEEDED!"
            return result

        # 9. 记录处理成功状态
        try:
            save_processed_file_to_dir(None, dir_state_file, file_name, lock)
        except Exception as state_save_e:
             # 确保传递 context
             log_messages.append(('error', "log_save_state_fail", {'path': dir_state_file, 'filename': file_name, 'error': state_save_e}, False, context))
             result['error_details'] = f"File converted but failed to save state: {state_save_e}"
             return result

        result['status'] = 'success'
        return result

    # --- 异常处理 ---
    except UnidentifiedImageError as e:
        # 确保传递 context
        log_messages.append(('error', "convert_unidentified_path", {'path': image_path}, False, context))
        log_messages.append(('error', "convert_unidentified", {'filename': file_name}, True, context))
        result['error_details'] = f"UnidentifiedImageError: {e}"
        removed, rm_msg = _safe_remove(temp_path)
        # 确保传递 context
        if not removed: log_messages.append(('warning', "convert_unidentified_clean_fail", {'path': temp_path, 'error': rm_msg}, False, context))
        return result
    except (IOError, OSError) as e:
        # 确保传递 context
        log_messages.append(('error', "convert_io_error_path", {'path': image_path, 'error': e}, False, context))
        log_messages.append(('error', "convert_io_error", {'filename': file_name, 'error': e}, True, context))
        result['error_details'] = f"IO/OS Error during conversion: {e}"
        removed, rm_msg = _safe_remove(temp_path)
        # 确保传递 context
        if not removed: log_messages.append(('error', "convert_unexpected_error_clean_fail", {'path': temp_path, 'error': rm_msg}, False, context))
        return result
    except ValueError as e:
        # 确保传递 context
        log_messages.append(('error', "convert_value_error_path", {'webp_path': webp_output_path, 'error': e}, False, context))
        log_messages.append(('error', "convert_value_error", {'webp_filename': webp_file_name, 'error': str(e)}, True, context))
        result['error_details'] = f"ValueError on saving WebP (unsupported mode/options?): {e}"
        removed, rm_msg = _safe_remove(temp_path)
        # 确保传递 context
        if not removed: log_messages.append(('warning', "convert_value_error_clean_fail", {'path': temp_path, 'error': rm_msg}, False, context))
        return result
    except Exception as e:
        tb_str = traceback.format_exc()
        # 确保传递 context
        log_messages.append(('critical', "convert_unexpected_error_path", {'path': image_path, 'error': e}, False, context))
        log_messages.append(('critical', "convert_unexpected_error", {'filename': file_name, 'error': str(e), 'traceback': tb_str}, True, context))
        result['error_details'] = f"Unexpected Error: {e}\n{tb_str}"
        removed, rm_msg = _safe_remove(temp_path)
        # 确保传递 context
        if not removed: log_messages.append(('error', "convert_unexpected_error_clean_fail", {'path': temp_path, 'error': rm_msg}, False, context))
        return result
    finally:
        if 'img' in locals() and hasattr(img, 'close'):
            try: img.close()
            except Exception: pass
        if img_to_save and hasattr(img_to_save, 'close') and img_to_save is not img:
             try: img_to_save.close()
             except Exception: pass