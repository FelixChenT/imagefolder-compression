# Image Processor 🖼️

A versatile Python tool designed to efficiently compress images or convert them to the modern WebP format within a specified directory and its subdirectories. It features resumable processing, ensuring that you can pick up where you left off even if the process is interrupted.

## Why Use This Tool? ✨

*   **Save Storage Space:** Significantly reduce the file size of your images.
*   **Optimize for Web:** Generate smaller, faster-loading WebP images for websites.
*   **Batch Processing:** Handle large collections of images automatically.
*   **Resumable:** Don't worry about interruptions; the tool tracks processed files and resumes automatically.
*   **Flexible:** Choose between compressing existing formats or converting to WebP with adjustable quality settings.

## Key Features 🚀

*   **Two Processing Modes:**
    *   **Compress Original Format:** Optimizes JPEG, PNG, BMP, and TIFF files.
        *   Adjustable JPEG quality (with special handling for large files).
        *   Configurable PNG optimization level.
        *   Preserves EXIF and ICC profile data.
        *   Handles RGBA to RGB conversion for JPEGs.
    *   **Convert to WebP:** Converts JPEG, PNG, BMP, and TIFF images to WebP.
        *   Adjustable WebP quality.
        *   Option for lossless WebP conversion (default for PNG/BMP/TIFF).
*   **Recursive Operation:** Processes images in the target directory and all its subdirectories.
*   **State Management:** Uses state files (`.processed_files_*.log`) in each directory to track completed files, enabling resumable operations.
*   **Detailed Logging:**
    *   Global run log: `run_state/compression.log`
    *   Directory-specific logs: `_folder_*.log`
*   **Multi-language Support:** Interface available in Chinese (default) and English.
*   **Configurable:** Easily tweak processing parameters in `src/image_processor/config.py`.

## Requirements 📋

*   Python 3.7 or newer
*   Pillow library (Python Imaging Library fork)

## Installation ⚙️

1.  **Clone the Repository:**
    ```bash
    git clone <repository_url> # Replace <repository_url> with the actual URL
    cd image-processor # Or your project directory name
    ```

2.  **Set Up a Virtual Environment (Recommended):**
    ```bash
    # Create the environment
    python -m venv venv

    # Activate it:
    # Windows
    .venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## How to Use 💡

1.  **Navigate to the project's root directory** in your terminal (where `requirements.txt` is located).
2.  **Run the main script**, providing the path to the directory containing the images you want to process:
    ```bash
    python src/main.py "/path/to/your/image/directory"
    ```
    *Replace `/path/to/your/image/directory` with the actual path.*
3.  **Follow the interactive prompts** in your terminal to:
    *   Select the interface language.
    *   Choose the processing mode (Compress or Convert to WebP).
    *   Configure the parameters for the selected mode (e.g., quality settings).

The script will then start processing the images.



## Configuration 🔧

Advanced settings (like quality levels, log file locations, etc.) can be modified directly in the configuration file:

```
src/image_processor/config.py
```

## License 📄

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Contributing 🙏

Contributions are welcome! Please feel free to submit issues or pull requests.
