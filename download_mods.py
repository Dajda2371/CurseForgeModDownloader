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

# Mod loader name -> CurseForge gameVersionTypeId
LOADERS = {
    "forge": 1,
    "fabric": 4,
    "neoforge": 6,
}


def get_versioned_file_url(driver, mod_base_url, mc_version, loader_id):
    """
    Navigate to the mod's file list filtered by mc_version + loader,
    find the first (newest) file row, and return its download page URL.
    Returns None if no file is found.
    """
    files_url = (
        f"{mod_base_url.rstrip('/')}/files/all"
        f"?page=1&pageSize=20&version={mc_version}"
        f"&gameVersionTypeId={loader_id}&showAlphaFiles=hide"
    )
    print(f"  Checking: {files_url}")
    driver.get(files_url)

    # Wait up to 15 s for file rows to load
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "a.file-row-details")
            )
        )
    except Exception:
        # Maybe there's a "No Results" message
        try:
            no_results = driver.find_element(By.XPATH, "//*[contains(text(),'No Results')]")
            if no_results:
                print(f"  ⚠  No files found for this version/loader.")
                return None
        except Exception:
            pass
        print(f"  ⚠  Timed out waiting for file list.")
        return None

    # Find the first file row link
    try:
        first_file_link = driver.find_element(By.CSS_SELECTOR, "a.file-row-details")
        file_href = first_file_link.get_attribute("href")
    except Exception:
        print(f"  ⚠  Could not find any file row link.")
        return None

    if not file_href:
        print(f"  ⚠  File row link has no href.")
        return None

    # Convert /files/<id> to /download/<id> for the download page
    download_url = file_href.replace("/files/", "/download/")
    return download_url


def download_mod(driver, download_page_url, mods_dir):
    """
    Navigate to the CurseForge /download/<id> page, wait for the JS redirect
    to the actual CDN URL, then download the .jar using requests.
    Returns the filename on success, or None on failure.
    """
    driver.get(download_page_url)

    # CurseForge shows a 5-second countdown then redirects to the CDN.
    cdn_domains = ["edge.forgecdn.net", "mediafilez.forgecdn.net", "media.forgecdn.net"]
    cdn_url = None

    # Poll for up to 20 seconds for the redirect to the CDN
    for _ in range(40):
        current = driver.current_url
        if any(domain in current for domain in cdn_domains):
            cdn_url = current
            break
        time.sleep(0.5)

    # Fallback: look for a direct CDN link in the page source
    if cdn_url is None:
        soup = BeautifulSoup(driver.page_source, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(domain in href for domain in cdn_domains):
                cdn_url = href
                break

    # Second fallback: check for a data attribute or span with the URL
    if cdn_url is None:
        page_source = driver.page_source
        cdn_match = re.search(r'https?://(?:edge|mediafilez|media)\.forgecdn\.net/[^\s"\'<>]+', page_source)
        if cdn_match:
            cdn_url = cdn_match.group(0)

    if cdn_url is None:
        print("  ✗ Could not find CDN download URL after waiting.")
        return None

    # Extract filename from the CDN URL
    parsed = urlparse(cdn_url)
    filename = unquote(os.path.basename(parsed.path))
    if not filename:
        filename = "unknown_mod.jar"

    filepath = os.path.join(mods_dir, filename)

    # Grab cookies from Selenium session
    session = requests.Session()
    for cookie in driver.get_cookies():
        session.cookies.set(cookie["name"], cookie["value"])

    user_agent = driver.execute_script("return navigator.userAgent;")

    print(f"  ⬇  Downloading {filename} ...")
    try:
        resp = session.get(
            cdn_url, stream=True, timeout=120,
            headers={"User-Agent": user_agent, "Referer": "https://www.curseforge.com/"}
        )
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        print(f"  ✓  Saved {filename} ({size_mb:.2f} MB)")
        return filename
    except Exception as e:
        print(f"  ✗ Download failed: {e}")
        return None


def main():
    # --- Ask the user for Minecraft version ---
    mc_version = input("Enter the Minecraft version (e.g. 1.20.1): ").strip()
    if not mc_version:
        print("No version entered. Exiting.")
        return

    # --- Ask for mod loader ---
    print("\nAvailable mod loaders:")
    print("  1) Forge")
    print("  2) Fabric")
    print("  3) NeoForge")
    loader_choice = input("Choose mod loader [1/2/3] (default: 1 - Forge): ").strip()

    loader_map = {"1": "forge", "2": "fabric", "3": "neoforge", "": "forge"}
    loader_name = loader_map.get(loader_choice, "forge")
    loader_id = LOADERS[loader_name]

    print(f"\n→ Minecraft {mc_version} / {loader_name.capitalize()} (gameVersionTypeId={loader_id})\n")

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

    # Parse HTML for mod links
    soup = BeautifulSoup(html_content, "html.parser")
    mod_entries = [
        (a.get_text(strip=True), a["href"])
        for a in soup.find_all("a", href=True)
        if "curseforge.com/minecraft/mc-mods/" in a["href"]
    ]

    print(f"Found {len(mod_entries)} mods to download.\n")
    if not mod_entries:
        return

    # Setup Selenium (visible Chrome to bypass Cloudflare)
    print("Setting up Chrome driver...")
    options = Options()
    options.add_experimental_option("prefs", {
        "download.prompt_for_download": False,
        "safebrowsing.enabled": True,
    })

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    # First, visit curseforge.com to get past any Cloudflare challenge
    print("Warming up browser (Cloudflare)...")
    driver.get("https://www.curseforge.com/minecraft/mc-mods")
    time.sleep(5)

    succeeded = []
    failed = []

    for idx, (mod_name, mod_url) in enumerate(mod_entries, 1):
        print(f"\n[{idx}/{len(mod_entries)}] {mod_name}")

        download_page_url = get_versioned_file_url(driver, mod_url, mc_version, loader_id)
        if download_page_url is None:
            failed.append(mod_name)
            continue

        print(f"  ↳ Download page: {download_page_url}")
        filename = download_mod(driver, download_page_url, mods_dir)

        if filename:
            succeeded.append(mod_name)
        else:
            failed.append(mod_name)

    driver.quit()

    print(f"\n{'='*50}")
    print(f"✅ Downloaded {len(succeeded)}/{len(mod_entries)} mods")
    print(f"   Saved to: {mods_dir}")

    if failed:
        print(f"\n⚠  {len(failed)} mod(s) failed or had no files for {mc_version}/{loader_name.capitalize()}:")
        for name in failed:
            print(f"   - {name}")


if __name__ == "__main__":
    main()
