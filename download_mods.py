import os
import time
import re
from urllib.parse import urlparse

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
    print("pip install selenium beautifulsoup4 webdriver-manager")
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
    # e.g. https://www.curseforge.com/minecraft/mc-mods/supplementaries/files/all?version=1.20.1
    files_url = f"{mod_base_url.rstrip('/')}/files/all?version={mc_version}"
    print(f"  Checking files list: {files_url}")
    driver.get(files_url)

    # Wait up to 15 s for at least one file row to appear.
    # CurseForge renders rows inside an <a> whose href contains "/files/<numeric-id>"
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
    # Build absolute URL and append /download
    if first_file_path.startswith("http"):
        download_url = first_file_path + "/download"
    else:
        download_url = "https://www.curseforge.com" + first_file_path + "/download"

    return download_url


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
    # CurseForge is behind Cloudflare, so we use a real visible Chrome window.
    print("Setting up Chrome driver...")
    options = Options()
    prefs = {
        "download.default_directory": mods_dir,
        "download.prompt_for_download": False,
        "directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    failed = []

    for idx, (mod_name, mod_url) in enumerate(mod_entries, 1):
        print(f"[{idx}/{len(mod_entries)}] {mod_name}")
        download_url = get_versioned_download_url(driver, mod_url, mc_version)

        if download_url is None:
            failed.append(mod_name)
            continue

        print(f"  ↳ Downloading: {download_url}")
        try:
            driver.get(download_url)
            # CurseForge shows a 5-second countdown before the download starts.
            # Wait 10 s so we don't race ahead to the next mod.
            time.sleep(10)
        except Exception as e:
            print(f"  ✗ Failed: {e}")
            failed.append(mod_name)

    print("\nWaiting 20 seconds for any remaining downloads to finish...")
    time.sleep(20)

    driver.quit()

    print("\n✅ Done! Check the mods folder:")
    print(f"   {mods_dir}")

    if failed:
        print(f"\n⚠  The following {len(failed)} mod(s) had no files for {mc_version}:")
        for name in failed:
            print(f"   - {name}")


if __name__ == "__main__":
    main()
