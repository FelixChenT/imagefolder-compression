# -*- coding: utf-8 -*-
import os
import time
import traceback
from PIL import Image, UnidentifiedImageError

# 使用相对导入来获取配置、工具函数和日志/状态函数
from . import config
from .utils import get_text
from .log_utils import log_to_directory
from .state import save_processed_file_to_dir

# --- 核心压缩逻辑 (原格式压缩模式) ---
def compress_image_inplace(logger, image_path_raw, processed_in_dir_set, dir_state_file,
                           dir_log_file_name, quality, png_optimize):
    """
    压缩单个图片文件并替换原文件 (保留原始格式)。
    返回: (True, original_size, compressed_size) 或 (False, original_size/None, compressed_size/None)
    """
    image_path = os.path.normpath(image_path_raw)
    dir_path = os.path.dirname(image_path)
    file_name = os.path.basename(image_path)

    # 1. 检查是否已处理
    if file_name in processed_in_dir_set:
        logger.debug(get_text("compress_skip_processed", state_file=os.path.basename(dir_state_file), path=image_path))
        return False, None, None # 跳过，返回 None 大小

    # 2. 记录开始处理日志
    logger.info(get_text("compress_start_path", path=image_path))
    log_to_directory(logger, dir_path, dir_log_file_name, "info", "compress_start", filename=file_name)

    # 3. 获取原始大小
    original_size = None # 初始化为 None
    try:
        original_size = os.path.getsize(image_path)
        original_size_mb = original_size / (1024 * 1024)
        # 使用 f-string 结合 get_text
        logger.info(f"{image_path} - {get_text('compress_file_size', size=original_size_mb)}")
        log_to_directory(logger, dir_path, dir_log_file_name, "info", "compress_file_size", filename=file_name, size=original_size_mb)
    except OSError as e:
        logger.error(get_text("compress_get_size_fail_path", path=image_path, error=e))
        log_to_directory(logger, dir_path, dir_log_file_name, "error", "compress_get_size_fail", filename=file_name, error=e)
        return False, None, None # 获取大小失败，返回 None

    # 4. 定义临时文件路径
    temp_path = os.path.join(dir_path, f"{file_name}.compress_temp")
    compressed_size = None # 初始化为 None

    # 5. 打开、处理、保存到临时文件
    try:
        with Image.open(image_path) as img:
            logger.debug(get_text("compress_open_success", path=image_path))
            original_format = img.format
            if not original_format:
                ext_lower = os.path.splitext(image_path)[1].lower()
                # 从 config 导入 SUPPORTED_EXTENSIONS 来构建映射可能更健壮，但当前方式也可行
                format_map = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.bmp': 'BMP', '.tif': 'TIFF', '.tiff': 'TIFF'}
                original_format = format_map.get(ext_lower)
                if not original_format:
                    logger.warning(get_text("compress_format_unknown_path", path=image_path, ext=ext_lower))
                    log_to_directory(logger, dir_path, dir_log_file_name, "warning", "compress_format_unknown", filename=file_name, ext=ext_lower)
                    return False, original_size, None # 无法确定格式，返回原始大小

            logger.debug(get_text("compress_format_identified", format=original_format, path=image_path))

            save_options = {'format': original_format}
            img_to_save = img
            current_jpeg_quality = quality # 使用传入的 quality

            # 检查是否是大文件 (仅对 JPEG)
            is_large_file = original_size_mb > config.INPLACE_LARGE_FILE_THRESHOLD_MB
            if original_format == 'JPEG' and is_large_file:
                current_jpeg_quality = config.INPLACE_LARGE_FILE_COMPRESSION_QUALITY
                # 使用 f-string 结合 get_text
                logger.info(f"{image_path} - {get_text('compress_large_file', threshold=config.INPLACE_LARGE_FILE_THRESHOLD_MB, quality=current_jpeg_quality)}")
                log_to_directory(logger, dir_path, dir_log_file_name, "info", "compress_large_file_log", filename=file_name, threshold=config.INPLACE_LARGE_FILE_THRESHOLD_MB, quality=current_jpeg_quality)

            # 根据格式设置保存选项
            if original_format == 'JPEG':
                save_options['quality'] = current_jpeg_quality
                save_options['optimize'] = True # 对 JPEG 也启用优化
                # 保留元数据
                icc_profile = img.info.get('icc_profile')
                if icc_profile: save_options['icc_profile'] = icc_profile
                exif = img.info.get('exif')
                if exif: save_options['exif'] = exif
                # 处理 RGBA -> RGB for JPEG
                if img.mode == 'RGBA':
                    logger.debug(get_text("compress_rgba_to_rgb", path=image_path))
                    log_to_directory(logger, dir_path, dir_log_file_name, "debug", "compress_rgba_to_rgb_log", filename=file_name)
                    # 创建白色背景并粘贴 RGBA 图像
                    rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                    try:
                        # 使用 alpha 通道作为 mask
                        rgb_img.paste(img, mask=img.split()[3])
                        img_to_save = rgb_img
                    except IndexError:
                         logger.warning(f"Could not get alpha channel for RGBA to RGB conversion for {image_path}, saving as is (might fail).")
                         # 尝试直接保存 RGBA (Pillow 可能会处理或报错)
                         pass # Let Pillow handle it, might raise error later
            elif original_format == 'PNG':
                save_options['optimize'] = png_optimize # 使用传入的 png_optimize
            # 其他格式 (BMP, TIFF) 通常没有太多压缩选项，直接保存
            else:
                 logger.debug(get_text("compress_default_save", format=original_format, path=image_path))

            # 保存到临时文件
            img_to_save.save(temp_path, **save_options)

        logger.debug(get_text("compress_save_temp_success", path=temp_path))

        # 6. 检查临时文件
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            logger.error(get_text("compress_temp_invalid_path", path=temp_path, original_path=image_path))
            log_to_directory(logger, dir_path, dir_log_file_name, "error", "compress_temp_invalid", filename=file_name)
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError as clean_err:
                    logger.error(get_text("compress_temp_clean_fail", path=temp_path, error=clean_err))
            return False, original_size, None # 临时文件无效，返回原始大小

        compressed_size = os.path.getsize(temp_path)

        # 7. 删除原图
        try:
            os.remove(image_path)
            logger.debug(get_text("compress_remove_original_success", path=image_path))
        except OSError as e:
            logger.error(get_text("compress_remove_original_fail_path", path=image_path, error=e, temp_path=temp_path))
            log_to_directory(logger, dir_path, dir_log_file_name, "error", "compress_remove_original_fail",
                             filename=file_name, error=e, temp_filename=os.path.basename(temp_path))
            # 删除原图失败，这是一个关键问题，但压缩文件已生成
            # 返回 False 表示操作未完全成功，但返回两个大小用于统计
            return False, original_size, compressed_size

        # 8. 重命名临时文件
        try:
            os.rename(temp_path, image_path) # 重命名回原文件名
            compressed_size_mb = compressed_size / (1024 * 1024)
            # original_size_mb 之前已计算
            reduction_percent = ((original_size - compressed_size) / original_size) * 100 if original_size > 0 else 0
            logger.info(get_text("compress_rename_success_path", path=image_path, orig_mb=original_size_mb, comp_mb=compressed_size_mb))
            log_to_directory(logger, dir_path, dir_log_file_name, "info", "compress_rename_success",
                             filename=file_name, orig_mb=original_size_mb, comp_mb=compressed_size_mb, percent=reduction_percent)
        except OSError as e:
            # 重命名失败，原图已被删除！这是最坏的情况
            logger.critical(get_text("compress_rename_fail_path", temp_path=temp_path, path=image_path, error=e))
            log_to_directory(logger, dir_path, dir_log_file_name, "critical", "compress_rename_fail",
                             temp_filename=os.path.basename(temp_path), filename=file_name, error=e)
            # 返回 False，但返回两个大小
            return False, original_size, compressed_size

        # 9. 记录处理成功状态
        save_processed_file_to_dir(logger, dir_state_file, file_name)
        processed_in_dir_set.add(file_name) # 更新内存中的集合
        return True, original_size, compressed_size # 完全成功

    # --- 异常处理 ---
    except UnidentifiedImageError:
        logger.error(get_text("compress_unidentified_path", path=image_path))
        log_to_directory(logger, dir_path, dir_log_file_name, "error", "compress_unidentified", filename=file_name)
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except OSError: logger.warning(get_text("compress_unidentified_clean_fail", path=temp_path))
        return False, original_size, None # 失败，返回原始大小
    except (IOError, OSError) as e:
        logger.error(get_text("compress_io_error_path", path=image_path, error=e))
        log_to_directory(logger, dir_path, dir_log_file_name, "error", "compress_io_error", filename=file_name, error=e)
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except OSError as clean_err: logger.error(get_text("compress_unexpected_error_clean_fail", path=temp_path, error=clean_err))
        return False, original_size, None # 失败，返回原始大小
    except Exception as e:
        tb_str = traceback.format_exc()
        logger.critical(get_text("compress_unexpected_error_path", path=image_path, error=e), exc_info=True)
        log_to_directory(logger, dir_path, dir_log_file_name, "critical", "compress_unexpected_error",
                         filename=file_name, error=str(e), traceback=tb_str) # 传递 str(e)
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except OSError as clean_err: logger.error(get_text("compress_unexpected_error_clean_fail", path=temp_path, error=clean_err))
        return False, original_size, None # 失败，返回原始大小


# --- 核心转换逻辑 (WebP 模式 - 原地替换) ---
def convert_to_webp_inplace(logger, image_path_raw, processed_in_dir_set, dir_state_file,
                            dir_log_file_name, quality, use_lossless):
    """
    将单个图片文件转换为 WebP 格式并替换原文件。
    返回: (True, original_size, webp_size) 或 (False, original_size/None, webp_size/None)
    """
    image_path = os.path.normpath(image_path_raw)
    dir_path = os.path.dirname(image_path)
    file_name = os.path.basename(image_path)
    base_name, _ = os.path.splitext(file_name)
    webp_file_name = base_name + ".webp"
    webp_output_path = os.path.join(dir_path, webp_file_name)

    # 1. 检查是否已处理 (使用原始文件名检查)
    if file_name in processed_in_dir_set:
        logger.debug(get_text("convert_skip_processed", state_file=os.path.basename(dir_state_file), path=image_path))
        return False, None, None

    # 2. 记录开始转换日志
    logger.info(get_text("convert_start_path", path=image_path, webp_path=webp_output_path))
    log_to_directory(logger, dir_path, dir_log_file_name, "info", "convert_start", filename=file_name, webp_filename=webp_file_name)

    # 3. 获取原始大小
    original_size = None
    try:
        original_size = os.path.getsize(image_path)
        original_size_mb = original_size / (1024 * 1024)
        logger.info(f"{image_path} - {get_text('convert_original_size', size=original_size_mb)}")
        log_to_directory(logger, dir_path, dir_log_file_name, "info", "convert_original_size", filename=file_name, size=original_size_mb)
    except OSError as e:
        logger.error(get_text("convert_get_size_fail_path", path=image_path, error=e))
        log_to_directory(logger, dir_path, dir_log_file_name, "error", "convert_get_size_fail", filename=file_name, error=e)
        return False, None, None

    # 4. 定义临时文件路径
    # 临时文件放在目标 WebP 文件名后面加后缀，避免与可能已存在的同名 WebP 文件冲突
    temp_path = webp_output_path + ".webp_temp"
    webp_size = None

    # 5. 打开、处理、保存为 WebP 到临时文件
    try:
        with Image.open(image_path) as img:
            logger.debug(get_text("convert_open_success", path=image_path))

            webp_save_options = {}
            webp_save_options['quality'] = quality

            # 确定是否使用无损模式
            # 优先级：用户强制 > 特定格式倾向 > 默认有损
            original_format_from_ext = os.path.splitext(image_path)[1].lower()
            original_format_from_img = img.format # Pillow 读取的格式
            # 倾向无损的格式
            lossless_prone_formats = ['PNG', 'BMP', 'TIFF']
            lossless_prone_extensions = ['.png', '.bmp', '.tif', '.tiff']

            effective_lossless = use_lossless or \
                                 (original_format_from_img and original_format_from_img.upper() in lossless_prone_formats) or \
                                 (not original_format_from_img and original_format_from_ext in lossless_prone_extensions)

            webp_save_options['lossless'] = effective_lossless
            log_lossless_mode = get_text("convert_lossless") if effective_lossless else get_text("convert_lossy")

            logger.info(get_text("convert_webp_options", quality=quality, mode=log_lossless_mode, path=webp_output_path))
            log_to_directory(logger, dir_path, dir_log_file_name, "info", "convert_webp_options_log",
                             filename=file_name, webp_filename=webp_file_name, quality=quality, mode=log_lossless_mode)

            # 保留元数据 (WebP 支持 EXIF 和 ICC Profile)
            icc_profile = img.info.get('icc_profile')
            if icc_profile: webp_save_options['icc_profile'] = icc_profile
            exif = img.info.get('exif')
            if exif: webp_save_options['exif'] = exif

            # 保存到临时 WebP 文件
            img.save(temp_path, 'WEBP', **webp_save_options)

        logger.debug(get_text("convert_save_temp_success", path=temp_path))

        # 6. 检查临时 WebP 文件
        if not os.path.exists(temp_path) or os.path.getsize(temp_path) == 0:
            logger.error(get_text("convert_temp_invalid_path", path=temp_path, original_path=image_path))
            log_to_directory(logger, dir_path, dir_log_file_name, "error", "convert_temp_invalid", filename=file_name)
            if os.path.exists(temp_path):
                try: os.remove(temp_path)
                except OSError as clean_err: logger.error(get_text("convert_temp_clean_fail", path=temp_path, error=clean_err))
            return False, original_size, None

        webp_size = os.path.getsize(temp_path)

        # 7. 删除原图
        try:
            os.remove(image_path)
            logger.debug(get_text("convert_remove_original_success", path=image_path))
        except OSError as e:
            logger.error(get_text("convert_remove_original_fail_path", path=image_path, error=e, temp_path=temp_path))
            log_to_directory(logger, dir_path, dir_log_file_name, "error", "convert_remove_original_fail",
                             filename=file_name, error=e, temp_filename=os.path.basename(temp_path))
            return False, original_size, webp_size # 返回 False，但包含两个 size

        # 8. 重命名临时文件为最终的 WebP 文件名
        try:
            # 如果目标 webp 文件已存在 (例如上次运行失败留下的)，先尝试删除
            if os.path.exists(webp_output_path):
                 logger.warning(f"Target WebP file {webp_output_path} already exists. Attempting to overwrite.")
                 try:
                     os.remove(webp_output_path)
                 except OSError as del_err:
                      logger.error(f"Failed to remove existing target WebP file {webp_output_path}: {del_err}. Cannot rename.")
                      # 不能重命名，这是关键错误，原文件已删
                      logger.critical(get_text("convert_rename_fail_path", temp_path=temp_path, webp_path=webp_output_path, error=f"Cannot remove existing file: {del_err}"))
                      log_to_directory(logger, dir_path, dir_log_file_name, "critical", "convert_rename_fail",
                                       temp_filename=os.path.basename(temp_path), webp_filename=webp_file_name, error=f"Cannot remove existing file: {del_err}")
                      return False, original_size, webp_size


            os.rename(temp_path, webp_output_path)
            webp_size_mb = webp_size / (1024 * 1024)
            # original_size_mb 已计算
            reduction_percent = ((original_size - webp_size) / original_size) * 100 if original_size > 0 else 0
            logger.info(get_text("convert_rename_success_path", path=image_path, webp_path=webp_output_path,
                                 orig_mb=original_size_mb, webp_mb=webp_size_mb))
            log_to_directory(logger, dir_path, dir_log_file_name, "info", "convert_rename_success",
                             filename=file_name, webp_filename=webp_file_name,
                             orig_mb=original_size_mb, webp_mb=webp_size_mb, percent=reduction_percent)
        except OSError as e:
            logger.critical(get_text("convert_rename_fail_path", temp_path=temp_path, webp_path=webp_output_path, error=e))
            log_to_directory(logger, dir_path, dir_log_file_name, "critical", "convert_rename_fail",
                             temp_filename=os.path.basename(temp_path), webp_filename=webp_file_name, error=e)
            return False, original_size, webp_size # 返回 False，但包含两个 size

        # 9. 记录处理成功状态 (使用原始文件名记录)
        save_processed_file_to_dir(logger, dir_state_file, file_name)
        processed_in_dir_set.add(file_name) # 更新内存集合
        return True, original_size, webp_size # 完全成功

    # --- 异常处理 ---
    except UnidentifiedImageError:
        logger.error(get_text("convert_unidentified_path", path=image_path))
        log_to_directory(logger, dir_path, dir_log_file_name, "error", "convert_unidentified", filename=file_name)
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except OSError: logger.warning(get_text("convert_unidentified_clean_fail", path=temp_path))
        return False, original_size, None
    except (IOError, OSError) as e:
        logger.error(get_text("convert_io_error_path", path=image_path, error=e))
        log_to_directory(logger, dir_path, dir_log_file_name, "error", "convert_io_error", filename=file_name, error=e)
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except OSError as clean_err: logger.error(get_text("convert_unexpected_error_clean_fail", path=temp_path, error=clean_err))
        return False, original_size, None
    except ValueError as e: # Pillow 保存 WebP 时可能因选项或模式问题抛出 ValueError
        logger.error(get_text("convert_value_error_path", webp_path=webp_output_path, error=e))
        log_to_directory(logger, dir_path, dir_log_file_name, "error", "convert_value_error", webp_filename=webp_file_name, error=str(e))
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except OSError: logger.warning(get_text("convert_value_error_clean_fail", path=temp_path))
        return False, original_size, None
    except Exception as e:
        tb_str = traceback.format_exc()
        logger.critical(get_text("convert_unexpected_error_path", path=image_path, error=e), exc_info=True)
        log_to_directory(logger, dir_path, dir_log_file_name, "critical", "convert_unexpected_error",
                         filename=file_name, error=str(e), traceback=tb_str)
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except OSError as clean_err: logger.error(get_text("convert_unexpected_error_clean_fail", path=temp_path, error=clean_err))
        return False, original_size, None