import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote, urlparse, parse_qs
import sys
from tqdm import tqdm
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
import json

# User Credentials - FILL THESE IN
USERNAME = ""
PASSWORD = ""

# Configuration
BASE_URL = "https://eogdata.mines.edu/nighttime_light/monthly_notile/"
AUTH_BASE = "https://eogauth-new.mines.edu/realms/eog/protocol/openid-connect"
TOKEN_URL = f"{AUTH_BASE}/token"
AUTH_URL = f"{AUTH_BASE}/auth"
DEFAULT_CLIENT_ID = "eogdata-new-apache"
REDIRECT_URI = "https://eogdata.mines.edu/oauth2callback"
MAX_WORKERS = 4  # Number of concurrent downloads
CACHE_FILE = "eog_files_cache.json"

from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

class EOGAuthenticator:
    # ... (init and _create_session remain the same)
    def __init__(self, username, password, client_id=None, client_secret=None):
        self.username = username
        self.password = password
        self.client_id = client_id or DEFAULT_CLIENT_ID
        self.client_secret = client_secret
        self.lock = threading.Lock()
        self.session = self._create_session()

    def _create_session(self):
        """
        Create a new session with robust retry logic for connection stability.
        """
        session = requests.Session()
        
        # Configure robust retries for connection errors and server errors
        retries = Retry(
            total=10,
            backoff_factor=1,  # Wait 1s, 2s, 4s...
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS", "TRACE"]
        )
        
        adapter = HTTPAdapter(max_retries=retries)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def get(self, url, **kwargs):
        """
        Wrapper for session.get with automatic retry on 401/403/503 and Connection Errors.
        Enforces a default timeout if not provided.
        """
        retry_count = 0
        max_retries = 10  # Increased max retries
        base_delay = 5
        
        # Set default timeout (connect, read) if not provided to prevent hanging
        if 'timeout' not in kwargs:
            kwargs['timeout'] = (15, 60) # 15s connect, 60s read

        while retry_count < max_retries:
            try:
                # If streaming, we return the response object directly
                response = self.session.get(url, **kwargs)
                
                # Check if we were redirected to login page (which returns 200 OK)
                if response.url.startswith(AUTH_BASE):
                     tqdm.write("Detected redirect to login page. Session expired.")
                     fake_error = requests.exceptions.HTTPError("Session Expired")
                     fake_error.response = response
                     response.status_code = 401 
                     raise fake_error
                
                response.raise_for_status()
                return response

            except requests.exceptions.HTTPError as e:
                # ... (error handling remains similar, ensuring loops don't hang)
                status_code = e.response.status_code
                if status_code in [401, 403, 503]:
                    tqdm.write(f"Encountered {status_code} error. Attempting re-login/retry ({retry_count + 1}/{max_retries})...")
                    time.sleep(base_delay * (retry_count + 1) + (time.time() % 1))
                    with self.lock:
                        if self.login_and_get_session():
                            tqdm.write("Re-login successful. Retrying request...")
                        else:
                            tqdm.write("Re-login failed.")
                    retry_count += 1
                    continue
                else:
                    raise e

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, 
                    requests.exceptions.ChunkedEncodingError) as e:
                tqdm.write(f"Connection unstable: {e}. Rebuilding session and retrying ({retry_count + 1}/{max_retries})...")
                time.sleep(base_delay * (retry_count + 1) + (time.time() % 1))
                with self.lock:
                    tqdm.write("Rebuilding session...")
                    if self.login_and_get_session():
                         tqdm.write("Session rebuilt and re-authenticated.")
                    else:
                         tqdm.write("Session rebuild failed, will try current session anyway.")
                retry_count += 1
                continue
            
            except Exception as e:
                tqdm.write(f"Unexpected error: {e}. Retrying...")
                retry_count += 1
                time.sleep(base_delay)
                continue
                
        # If we exhausted retries, try one last time
        return self.session.get(url, **kwargs)

    # ... (login methods remain the same)
    def login_and_get_session(self):
        # Reset session to ensure clean state (clears old cookies/headers/connection pool)
        self.session = self._create_session()
        
        # Try direct password grant first (fastest)
        tqdm.write(f"Attempting direct login with client_id='{self.client_id}'...")
        if self._login_password_grant():
            tqdm.write("Direct login successful.")
            return True
        
        # If failed and no secret provided (public client), try browser flow
        if not self.client_secret:
            tqdm.write("Direct login failed. Attempting browser simulation flow...")
            return self._login_browser_flow()
        
        return False

    def _login_password_grant(self):
        payload = {
            'client_id': self.client_id,
            'username': self.username,
            'password': self.password,
            'grant_type': 'password'
        }
        if self.client_secret:
            payload['client_secret'] = self.client_secret
            
        try:
            response = self.session.post(TOKEN_URL, data=payload)
            if response.status_code == 200:
                token = response.json().get('access_token')
                self.session.headers.update({'Authorization': f'Bearer {token}'})
                return True
            else:
                tqdm.write(f"Direct login failed: {response.text}")
        except Exception as e:
            tqdm.write(f"Direct login error: {e}")
        return False

    def _login_browser_flow(self):
        try:
            # Step 1: Get the login page
            params = {
                'response_type': 'code',
                'client_id': self.client_id,
                'redirect_uri': REDIRECT_URI,
                'scope': 'openid email',
                'state': '12345' # Dummy state
            }
            r = self.session.get(AUTH_URL, params=params)
            r.raise_for_status()
            
            # Step 2: Parse form action
            soup = BeautifulSoup(r.text, 'html.parser')
            form = soup.find('form', id='kc-form-login')
            if not form:
                # Maybe already logged in? Check if we can access protected resource
                tqdm.write("Could not find login form. Checking if already authenticated...")
                return self._check_auth()
            
            action_url = form.get('action')
            if not action_url:
                action_url = r.url # Post to same URL if no action

            # Step 3: Post credentials
            login_data = {
                'username': self.username,
                'password': self.password,
                'credentialId': ''
            }
            
            # Add hidden fields
            for inp in form.find_all('input'):
                if inp.get('type') == 'hidden':
                    login_data[inp.get('name')] = inp.get('value')
            
            # Follow redirects automatically now to complete the flow (Keycloak -> App -> Original URL)
            r_post = self.session.post(action_url, data=login_data, allow_redirects=True)
            
            # Check for Keycloak errors in the final page content if we didn't redirect away
            if "kc-feedback-text" in r_post.text or "pf-c-alert__title" in r_post.text:
                soup_post = BeautifulSoup(r_post.text, 'html.parser')
                err = soup_post.find('span', class_='pf-c-alert__title')
                if err:
                    tqdm.write(f"Login Error: {err.get_text().strip()}")
                return False

            # Verify authentication by accessing the protected base URL
            return self._check_auth()

        except Exception as e:
            tqdm.write(f"Browser flow error: {e}")
            return False

    def _check_auth(self):
        try:
            r = self.session.get(BASE_URL)
            if r.status_code == 200:
                tqdm.write("Authentication verified.")
                return True
            tqdm.write(f"Authentication verification failed. Status code: {r.status_code}")
            return False
        except Exception as e:
            tqdm.write(f"Auth check error: {e}")
            return False

def get_files_and_dirs(url, authenticator):
    """
    Parse a directory listing URL to find files and subdirectories.
    """
    try:
        # Use authenticator.get() instead of session.get() to handle retries
        response = authenticator.get(url)
        if response.status_code != 200:
             response.raise_for_status()
    except Exception as e:
        tqdm.write(f"Failed to access {url}: {e}")
        return [], []

    soup = BeautifulSoup(response.text, 'html.parser')
    files = []
    dirs = []
    
    for link in soup.find_all('a'):
        href = link.get('href')
        # Skip parent directory links and query parameters
        if not href or href in ['../', './'] or href.startswith('?') or href.startswith('/'):
            continue
            
        full_url = urljoin(url, href)
        if href.endswith('/'):
            dirs.append(full_url)
        else:
            files.append(full_url)
            
    return files, dirs

def download_file(url, save_path, authenticator):
    """
    Download a single file with resume capability and progress bar.
    Returns True if successful (or skipped), False if failed.
    """
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    # Check if file exists to resume
    resume_header = {}
    file_mode = 'wb'
    existing_size = 0
    
    if os.path.exists(save_path):
        existing_size = os.path.getsize(save_path)
        resume_header = {'Range': f'bytes={existing_size}-'}
        file_mode = 'ab'

    try:
        # Initial request to check total size and support for range
        # Use authenticator.get() for robustness
        r = authenticator.get(url, stream=True, headers=resume_header, timeout=(15, 60))
        
        try:
            # If server returns 416 Range Not Satisfiable, maybe the file is already complete
            if r.status_code == 416:
                # Check total size from a fresh HEAD request (or GET)
                head_resp = authenticator.get(url, stream=False, timeout=(15, 60)) 
                total_size = int(head_resp.headers.get('content-length', 0))
                head_resp.close()
                
                if existing_size >= total_size:
                    tqdm.write(f"Skipping already completed file: {os.path.basename(save_path)}")
                    return True
                else:
                    # File on disk is larger than server? Re-download
                    tqdm.write(f"File corruption detected. Re-downloading: {save_path}")
                    os.remove(save_path)
                    existing_size = 0
                    resume_header = {}
                    file_mode = 'wb'
                    
                    # Close the 416 response before getting a new one
                    r.close()
                    # Re-request
                    r = authenticator.get(url, stream=True, timeout=(15, 60))

            r.raise_for_status()
            
            total_size = int(r.headers.get('content-length', 0))
            
            # If status is 206, it means partial content (resume supported)
            if r.status_code == 206:
                total_size += existing_size
            elif r.status_code == 200 and existing_size > 0:
                # Server doesn't support range, re-downloading from scratch
                tqdm.write(f"Server doesn't support resume for {os.path.basename(save_path)}. Re-downloading.")
                existing_size = 0
                file_mode = 'wb'

            desc = os.path.basename(save_path)
            if len(desc) > 30:
                desc = desc[:27] + "..."
            
            # If file is already complete
            if existing_size >= total_size and total_size > 0:
                 tqdm.write(f"Skipping already completed file: {os.path.basename(save_path)}")
                 return True

            with open(save_path, file_mode) as f, tqdm(
                desc=desc,
                total=total_size,
                initial=existing_size,
                unit='iB',
                unit_scale=True,
                unit_divisor=1024,
                leave=False # Don't leave progress bars to avoid clutter with threads
            ) as bar:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        size = f.write(chunk)
                        bar.update(size)
            return True
        finally:
            r.close()
                        
    except Exception as e:
        tqdm.write(f"Error downloading {url}: {e}")
        return False

def collect_files(url, base_save_dir, authenticator, all_files_list):
    """
    Recursively scan directories and collect all files to download.
    Filters applied:
    1. Skip 'vcmslcfg' directories (prefer 'vcmcfg').
    2. Only download .tif.gz files (skip .tif).
    3. Only download *.avg_rade9h.tif.gz and *.cf_cvg.tif.gz.
    """
    if not url.startswith(BASE_URL):
        return

    rel_path = unquote(url[len(BASE_URL):])
    rel_path = rel_path.lstrip('/')
    current_save_dir = os.path.join(base_save_dir, rel_path)
    
    tqdm.write(f"Scanning directory: {url}")
    files, dirs = get_files_and_dirs(url, authenticator)
    
    for file_url in files:
        filename = unquote(file_url.split('/')[-1])
        
        # Filter: Only .tif.gz
        if not filename.endswith('.tif.gz'):
            continue
            
        # Filter: Specific file types
        # Keep: *.avg_rade9h.tif.gz and *.cf_cvg.tif.gz
        # Exclude: *.cvg.tif.gz, *.avg_rade9h.masked.tif.gz, etc.
        if not (filename.endswith('.avg_rade9h.tif.gz') or filename.endswith('.cf_cvg.tif.gz')):
            continue

        save_path = os.path.join(current_save_dir, filename)
        all_files_list.append((file_url, save_path))
        
    for dir_url in dirs:
        # Check directory name to filter out unwanted folders like 'vcmslcfg'
        # dir_url ends with '/', so we strip it to get the name
        dir_name = unquote(dir_url.rstrip('/').split('/')[-1])
        
        if dir_name == 'vcmslcfg':
            tqdm.write(f"Skipping excluded directory: {dir_name}")
            continue
            
        collect_files(dir_url, base_save_dir, authenticator, all_files_list)

def main():
    print("=== EOG Data Downloader (Multi-threaded & Resume & Auto-Relogin & Cache) ===")
    print(f"Target URL: {BASE_URL}")
    print("-" * 50)
    
    # Use hardcoded credentials if available, otherwise fallback to env vars or input (optional)
    username = USERNAME or os.environ.get('EOG_USERNAME')
    password = PASSWORD or os.environ.get('EOG_PASSWORD')
    
    if not username or not password:
        print("Error: Please fill in USERNAME and PASSWORD at the top of the script.")
        username = input("Or enter Username (email) now: ")
        password = input("Enter Password now: ")
        if not username or not password:
            return

    # Default public client
    client_id = DEFAULT_CLIENT_ID
    client_secret = None 
    
    authenticator = EOGAuthenticator(username, password, client_id, client_secret)
    
    print("Initial authentication...")
    if not authenticator.login_and_get_session():
        print("Authentication failed. Exiting.")
        return

    save_dir = "./eog_downloads" # Default directory
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    save_dir = os.path.abspath(save_dir)
    print(f"Files will be saved to: {save_dir}")
    
    # Phase 1: Scan or Load Cache
    all_files_to_download = []
    
    if os.path.exists(CACHE_FILE):
        print(f"\nFound cache file '{CACHE_FILE}'.")
        choice = input("Use cached file list? (y/n) [y]: ").strip().lower()
        if choice in ('', 'y', 'yes'):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    # Cache format: list of [url, save_path]
                    all_files_to_download = cached_data
                print(f"Loaded {len(all_files_to_download)} files from cache.")
            except Exception as e:
                print(f"Error loading cache: {e}. Will rescan.")
    
    if not all_files_to_download:
        print("\nPhase 1: Scanning directory structure (this may take a while)...")
        collect_files(BASE_URL, save_dir, authenticator, all_files_to_download)
        
        # Deduplicate files (remove duplicate URLs/paths)
        # Convert list of lists/tuples to set of tuples for uniqueness
        unique_files = list(set(tuple(item) for item in all_files_to_download))
        if len(unique_files) < len(all_files_to_download):
            print(f"Removed {len(all_files_to_download) - len(unique_files)} duplicate entries.")
            all_files_to_download = unique_files
        
        # Save to cache
        try:
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(all_files_to_download, f, indent=2)
            print(f"Scan complete. Saved {len(all_files_to_download)} files to '{CACHE_FILE}'.")
        except Exception as e:
            print(f"Warning: Could not save cache: {e}")
    else:
         # Also deduplicate loaded cache just in case
         unique_files = list(set(tuple(item) for item in all_files_to_download))
         if len(unique_files) < len(all_files_to_download):
             print(f"Removed {len(all_files_to_download) - len(unique_files)} duplicate entries from cache.")
             all_files_to_download = unique_files

    # Phase 2: Download Loop
    print(f"\nPhase 2: Starting download of {len(all_files_to_download)} files with {MAX_WORKERS} threads...")
    print("Resume capability is enabled. Press Ctrl+C to stop safely.")
    
    pending_files = all_files_to_download
    round_num = 1
    
    try:
        while pending_files:
            print(f"\n--- Round {round_num}: Downloading {len(pending_files)} files ---")
            failed_files = []
            
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                # Map future to (url, path) so we know which one failed
                future_to_file = {
                    executor.submit(download_file, url, path, authenticator): (url, path)
                    for url, path in pending_files
                }
                
                for future in tqdm(as_completed(future_to_file), total=len(pending_files), desc=f"Round {round_num}"):
                    url, path = future_to_file[future]
                    try:
                        success = future.result()
                        if not success:
                            failed_files.append((url, path))
                    except Exception as e:
                        tqdm.write(f"Exception for {url}: {e}")
                        failed_files.append((url, path))
            
            if not failed_files:
                print("\nAll files downloaded successfully!")
                break
            
            print(f"\nRound {round_num} completed. {len(failed_files)} files failed or incomplete.")
            print("Retrying failed files in 5 seconds...")
            time.sleep(5)
            
            pending_files = failed_files
            round_num += 1
                
    except KeyboardInterrupt:
        print("\nDownload stopped by user.")
        sys.exit(0)
        
    print("\nAll downloads completed.")

if __name__ == "__main__":
    main()
