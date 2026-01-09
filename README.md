# EOG VIIRS Nighttime Light Downloader

A robust, high-performance Python script designed to download **VIIRS Nighttime Light data** from the [Earth Observation Group (EOG)](https://eogdata.mines.edu/) at Colorado School of Mines.

This tool solves common challenges when downloading large datasets from EOG, such as session timeouts, authentication complexities, and network interruptions.

## Key Features

- **🔐 Automatic Authentication**: Handles EOG's OAuth2 login flow automatically (Password Grant or Browser Flow simulation).
- **🔄 Session Keep-Alive**: Intelligently detects session expirations (401/403/503 errors) and re-authenticates in the background without crashing the script.
- **⏯️ Resumable Downloads**: Supports HTTP Range headers to resume interrupted downloads from where they left off.
- **🚀 Multi-threading**: Downloads multiple files in parallel to maximize bandwidth usage.
- **🔍 Smart Filtering**:
  - Recursively crawls the monthly directory structure.
  - **Directory Filter**: Skips `vcmslcfg` folders, focusing on `vcmcfg`.
  - **File Filter**: Downloads only `.tif.gz` compressed files.
  - **Product Filter**: Specifically targets `avg_rade9h` (average radiance) and `cf_cvg` (cloud-free coverages) files, excluding masked or other intermediate versions.

## Requirements

- Python 3.6+
- `requests`
- `beautifulsoup4`
- `tqdm`

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/eog-nightlight-downloader.git
   cd eog-nightlight-downloader
   ```

2. Install dependencies:
   ```bash
   pip install requests beautifulsoup4 tqdm
   ```

## Usage

1. Open `EOGNighttimeLightDownload.py`.
2. Configure your EOG credentials (optional but recommended for automation). You can set them via Environment Variables or modify the script:

   ```python
   # In EOGNighttimeLightDownload.py
   USERNAME = "your_email@example.com"
   PASSWORD = "your_password"
   ```

   *Alternatively, the script will prompt you for credentials if left blank.*

3. Run the script:
   ```bash
   python EOGNighttimeLightDownload.py
   ```

4. The script will:
   - Authenticate with EOG.
   - Scan the directory structure starting from `2012` (or configured base URL).
   - Filter out unwanted files.
   - Start downloading files to `./eog_downloads`.

## Configuration

You can modify the `Configuration` section in the script to change targets:

- `BASE_URL`: The starting URL for scanning (default: Monthly VIIRS data).
- `MAX_WORKERS`: Number of concurrent download threads (default: 4).

## Disclaimer

This tool is for research and educational purposes. Please ensure you comply with EOG's [Data Use Policy](https://eogdata.mines.edu/products/dmsp/#download). Data copyright belongs to the Earth Observation Group, Payne Institute for Public Policy, Colorado School of Mines.
