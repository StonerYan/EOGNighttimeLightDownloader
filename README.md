# EOG VIIRS Nighttime Light Downloader

A robust, high-performance Python script designed to download **VIIRS Nighttime Light data** from the [Earth Observation Group (EOG)](https://eogdata.mines.edu/) at Colorado School of Mines.

This tool solves common challenges when downloading large datasets from EOG, such as session timeouts, authentication complexities, and network interruptions.

## Key Features

- **🔐 Automatic Authentication**: Handles EOG's OAuth2 login flow automatically (Password Grant or Browser Flow simulation).
- **🔄 Session Keep-Alive & Auto-Retry**: 
  - Intelligently detects session expirations (401/403/503) and re-authenticates.
  - Automatically rebuilds broken connections (RemoteDisconnected).
  - Uses exponential backoff and jitter to prevent server overload.
- **💾 Smart Caching**: Saves the scanned file list to `eog_files_cache.json`. On subsequent runs, you can skip the time-consuming directory scanning process.
- **🔁 Loop-Until-Success**: Implements a "clean-up" loop. If some downloads fail in the first round, the script automatically retries only the failed files in subsequent rounds until all files are successfully downloaded.
- **⏯️ Resumable Downloads**: Supports HTTP Range headers to resume interrupted downloads from where they left off.
- **🚀 Multi-threading**: Downloads multiple files in parallel to maximize bandwidth usage.
- **🔍 Smart Filtering**:
  - Recursively crawls the monthly directory structure.
  - **Directory Filter**: Skips `vcmslcfg` folders, focusing on `vcmcfg`.
  - **File Filter**: Downloads only `.tif.gz` compressed files.
  - **Product Filter**: Specifically targets `avg_rade9h` (average radiance) and `cf_cvg` (cloud-free coverages) files.

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

4. **Workflow**:
   - **Authentication**: Logs in to EOG.
   - **Scanning**: Scans directories (or loads from `eog_files_cache.json` if available).
   - **Downloading**: Starts multi-threaded download.
   - **Retrying**: If any files fail, it enters a retry loop until 100% completion.

## Configuration

You can modify the `Configuration` section in the script to change targets:

- `BASE_URL`: The starting URL for scanning (default: Monthly VIIRS data).
- `MAX_WORKERS`: Number of concurrent download threads (default: 4).

## Disclaimer

This tool is for research and educational purposes. Please ensure you comply with EOG's Data Use Policy. Data copyright belongs to the Earth Observation Group, Payne Institute for Public Policy, Colorado School of Mines.
