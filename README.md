# Image Processor

A tool to process images in a directory by compressing or converting to WebP format. Uses directory-level state files for resumable processing.

## Features

- **Processing Modes:**
  - **Compress Original Format:** Compresses JPEG, PNG, BMP, TIFF files. Sets JPEG quality and PNG optimization. Uses separate quality for large JPEGs. Preserves EXIF and ICC profiles. Converts RGBA JPEGs to RGB.
  - **Convert to WebP:** Converts JPEG, PNG, BMP, TIFF to WebP. Sets WebP quality and lossless mode. Uses lossless for PNG/BMP/TIFF unless specified.
- **Recursive Processing:** Processes target directory and subdirectories.
- **Resumable:** Uses state file (`.processed_files_*.log`) to track completed files.
- **Logging:** Creates global log (`run_state/compression.log`) and directory logs (`_folder_*.log`).
- **Languages:** Chinese (default) and English.
- **Configuration:** Settings in `src/image_processor/config.py`.

## Requirements

- Python 3.7+
- Pillow library

## Installation

1. Clone repository:
   ```bash
   git clone <repository_url>
   cd image_processor_project
   ```

2. Create virtual environment:
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # macOS/Linux:
   source venv/bin/activate
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

Run from project directory:

```bash
python src/main.py /path/to/images
```

Select:
- Language
- Processing mode
- Mode parameters

Example:
```bash
python src/main.py "D:\Images"
```

## Configuration

Edit settings in:
```
src/image_processor/config.py
```

## License

MIT License - See LICENSE file
