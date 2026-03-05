import os
import time
import re
import requests
from urllib.parse import urlparse, unquote

try:
    from bs4 import BeautifulSoup
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    print("Required packages are missing. Please run:")
    print("pip install selenium beautifulsoup4 webdriver-manager requests")
    exit(1)

# Paths — resolved relative to this script's location, works on any OS/user
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(SCRIPT_DIR, "modlist.html")
MODS_DIR = os.path.join(SCRIPT_DIR, "mods")


def get_versioned_download_url(driver, mod_base_url, mc_version):
    """
    Navigate to the mod's file list filtered by mc_version and return the
    direct /download URL for the first (newest) matching file.
    Returns None if no file is found for that version.
    """
    files_url = f"{mod_base_url.rstrip('/')}/files/all?version={mc_version}"
    print(f"  Checking files list: {files_url}")
    driver.get(files_url)

    # Wait up to 15 s for at least one file row to appear
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "a[href*='/files/']")
            )
        )
    except Exception:
        print(f"  ⚠  Timed out waiting for file list on {files_url}")
        return None

    # Parse the rendered page
    soup = BeautifulSoup(driver.page_source, "html.parser")

    # Look for file-row links: href is like /minecraft/mc-mods/<slug>/files/<id>
    file_links = [
        a["href"] for a in soup.find_all("a", href=True)
        if re.search(r"/minecraft/mc-mods/.+/files/\d+$", a["href"])
    ]

    if not file_links:
        print(f"  ⚠  No files found for version {mc_version}.")
        return None

    # The first link is the newest file for that version
    first_file_path = file_links[0]
    if first_file_path.startswith("http"):
        download_url = first_file_path + "/download"
    else:
        download_url = "https://www.curseforge.com" + first_file_path + "/download"

    return download_url


def download_file_via_selenium(driver, download_page_url, mods_dir):
    """
    Navigate to the CurseForge /download page, wait for the redirect to the
    actual CDN URL, then download the .jar file using requests with the
    browser's cookies (to pass Cloudflare).
    Returns the filename on success, or None on failure.
    """
    driver.get(download_page_url)

    # CurseForge shows a 5-second countdown then redirects to the CDN.
    # Wait up to 20 s for the URL to change to the CDN domain.
    cdn_domains = ["edge.forgecdn.net", "mediafilez.forgecdn.net", "media.forgecdn.net"]
    cdn_url = None

    for _ in range(40):  # poll every 0.5 s for up to 20 s
        current = driver.current_url
        if any(domain in current for domain in cdn_domains):
            cdn_url = current
            break
        time.sleep(0.5)

    if cdn_url is None:
        # Fallback: check if the page source has a direct CDN link
        soup = BeautifulSoup(driver.page_source, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(domain in href for domain in cdn_domains):
                cdn_url = href
                break

    if cdn_url is None:
        print("  ✗ Could not find CDN download URL.")
        return None

    # Extract filename from the CDN URL
    parsed = urlparse(cdn_url)
    filename = unquote(os.path.basename(parsed.path))
    if not filename:
        filename = "unknown_mod.jar"

    filepath = os.path.join(mods_dir, filename)

    # Grab cookies from Selenium session for requests
    session = requests.Session()
    for cookie in driver.get_cookies():
        session.cookies.set(cookie["name"], cookie["value"])

    # Download
    print(f"  ⬇  Downloading {filename} ...")
    try:
        resp = session.get(cdn_url, stream=True, timeout=60,
                           headers={"User-Agent": driver.execute_script("return navigator.userAgent;")})
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        print(f"  ✓  Saved {filename} ({size_mb:.1f} MB)")
        return filename
    except Exception as e:
        print(f"  ✗ Download failed: {e}")
        return None


def main():
    # --- Ask the user for a Minecraft version ---
    mc_version = input("Enter the Minecraft version to download mods for (e.g. 1.20.1): ").strip()
    if not mc_version:
        print("No version entered. Exiting.")
        return

    print(f"\nWill download mods for Minecraft {mc_version}\n")

    # Ensure mods directory exists (version-specific sub-folder)
    mods_dir = os.path.join(MODS_DIR, mc_version)
    if not os.path.exists(mods_dir):
        os.makedirs(mods_dir)
        print(f"Created directory: {mods_dir}")

    # Read the HTML file
    if not os.path.exists(HTML_FILE):
        print(f"Error: {HTML_FILE} not found!")
        return

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Parse HTML for links
    soup = BeautifulSoup(html_content, "html.parser")
    mod_entries = [
        (a.get_text(strip=True), a["href"])
        for a in soup.find_all("a", href=True)
        if "curseforge.com/minecraft/mc-mods/" in a["href"]
    ]

    print(f"Found {len(mod_entries)} mods to download.\n")
    if not mod_entries:
        return

    # Setup Selenium
    print("Setting up Chrome driver...")
    options = Options()
    # We don't need Chrome's built-in downloader; we use requests instead.
    options.add_experimental_option("prefs", {
        "download.prompt_for_download": False,
        "safebrowsing.enabled": True,
    })

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    succeeded = []
    failed = []

    for idx, (mod_name, mod_url) in enumerate(mod_entries, 1):
        print(f"\n[{idx}/{len(mod_entries)}] {mod_name}")
        download_url = get_versioned_download_url(driver, mod_url, mc_version)

        if download_url is None:
            failed.append(mod_name)
            continue

        print(f"  ↳ Download page: {download_url}")
        filename = download_file_via_selenium(driver, download_url, mods_dir)

        if filename:
            succeeded.append(mod_name)
        else:
            failed.append(mod_name)

    driver.quit()

    print(f"\n{'='*50}")
    print(f"✅ Successfully downloaded {len(succeeded)}/{len(mod_entries)} mods")
    print(f"   Saved to: {mods_dir}")

    if failed:
        print(f"\n⚠  The following {len(failed)} mod(s) failed or had no files for {mc_version}:")
        for name in failed:
            print(f"   - {name}")


if __name__ == "__main__":
    main()
