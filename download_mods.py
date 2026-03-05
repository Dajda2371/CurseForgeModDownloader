import os
import time
import re
import glob

try:
    from bs4 import BeautifulSoup
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError:
    print("Required packages are missing. Please run:")
    print("pip install selenium beautifulsoup4 webdriver-manager")
    exit(1)

# Paths — resolved relative to this script's location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(SCRIPT_DIR, "modlist.html")
MODS_DIR = os.path.join(SCRIPT_DIR, "mods")

LOADERS = {
    "forge": 1,
    "fabric": 4,
    "neoforge": 6,
}


def wait_for_downloads(mods_dir, timeout=30):
    """Wait until no .crdownload files remain (Chrome finished downloading)."""
    for _ in range(timeout):
        downloading = glob.glob(os.path.join(mods_dir, "*.crdownload"))
        if not downloading:
            return True
        time.sleep(1)
    return False


def download_mod(driver, mod_url, mc_version, loader_id, mods_dir):
    """
    1. Navigate to the mod's version-filtered files page.
    2. Find the first file row using the 'file-row-details' class (table rows only).
    3. Navigate to /download/<file-id> to trigger the download.
    Returns True on success, False on failure.
    """
    # Step 1: Go to the filtered files page
    files_url = (
        f"{mod_url.rstrip('/')}/files/all"
        f"?page=1&pageSize=20&version={mc_version}"
        f"&gameVersionTypeId={loader_id}&showAlphaFiles=hide"
    )
    print(f"  Opening files page...")
    driver.get(files_url)

    # Step 2: Poll for file-row-details links (these are ONLY in the table,
    # not in the sidebar). Wait up to 20 seconds.
    file_href = None
    for attempt in range(20):
        time.sleep(1)
        file_href = driver.execute_script("""
            // ONLY target links with the 'file-row-details' class —
            // these only exist inside the file list table rows.
            var rows = document.querySelectorAll('a.file-row-details');
            if (rows.length > 0) {
                return rows[0].getAttribute('href');
            }
            return null;
        """)
        if file_href:
            break

    if not file_href:
        # Check if the page says "No Results"
        has_no_results = driver.execute_script(
            "return document.body.innerText.includes('No Results');"
        )
        if has_no_results:
            print(f"  ⚠  No files for {mc_version} on this mod.")
        else:
            print(f"  ⚠  Could not find file rows (page may not have loaded).")
            print(f"     URL: {driver.current_url}")
        return False

    print(f"  ↳ Found file: {file_href}")

    # Step 3: Extract file ID and build the download URL
    # file_href looks like /minecraft/mc-mods/<slug>/files/<file-id>
    file_id_match = re.search(r'/files/(\d+)$', file_href)
    if not file_id_match:
        print(f"  ⚠  Could not extract file ID from {file_href}")
        return False

    file_id = file_id_match.group(1)
    # Build the /download/<id> URL using the mod's base URL
    slug_match = re.search(r'/mc-mods/([^/]+)', file_href)
    slug = slug_match.group(1) if slug_match else ""
    download_url = f"https://www.curseforge.com/minecraft/mc-mods/{slug}/download/{file_id}"

    # Step 4: Count files before download
    files_before = set(os.listdir(mods_dir))

    # Step 5: Navigate to the download page (triggers 5-second countdown)
    print(f"  ⬇  Downloading: {download_url}")
    driver.get(download_url)

    # Wait for the countdown + actual download
    time.sleep(10)
    wait_for_downloads(mods_dir, timeout=30)

    # Step 6: Check if a new file appeared
    files_after = set(os.listdir(mods_dir))
    new_files = {f for f in (files_after - files_before) if not f.endswith(".crdownload")}

    if new_files:
        for f in new_files:
            size_mb = os.path.getsize(os.path.join(mods_dir, f)) / (1024 * 1024)
            print(f"  ✓  Saved: {f} ({size_mb:.2f} MB)")
        return True
    else:
        print(f"  ⏳ Download may still be in progress...")
        return True


def main():
    mc_version = input("Enter the Minecraft version (e.g. 1.20.1): ").strip()
    if not mc_version:
        print("No version entered. Exiting.")
        return

    print("\nAvailable mod loaders:")
    print("  1) Forge")
    print("  2) Fabric")
    print("  3) NeoForge")
    loader_choice = input("Choose mod loader [1/2/3] (default: 1 - Forge): ").strip()

    loader_map = {"1": "forge", "2": "fabric", "3": "neoforge", "": "forge"}
    loader_name = loader_map.get(loader_choice, "forge")
    loader_id = LOADERS[loader_name]

    print(f"\n→ Minecraft {mc_version} / {loader_name.capitalize()}\n")

    mods_dir = os.path.join(MODS_DIR, mc_version)
    os.makedirs(mods_dir, exist_ok=True)
    mods_dir_abs = os.path.abspath(mods_dir)

    if not os.path.exists(HTML_FILE):
        print(f"Error: {HTML_FILE} not found!")
        return

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")
    mod_entries = [
        (a.get_text(strip=True), a["href"])
        for a in soup.find_all("a", href=True)
        if "curseforge.com/minecraft/mc-mods/" in a["href"]
    ]

    print(f"Found {len(mod_entries)} mods to download.\n")
    if not mod_entries:
        return

    # Setup Chrome — with anti-detection flags
    print("Setting up Chrome driver...")
    options = Options()
    prefs = {
        "download.default_directory": mods_dir_abs,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    # Hide the webdriver flag from JS detection
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    # Configure download via CDP
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": mods_dir_abs,
    })

    # Warm up — pass Cloudflare
    print("Warming up browser (Cloudflare)...")
    driver.get("https://www.curseforge.com")
    time.sleep(8)

    succeeded = 0
    failed = []

    for idx, (mod_name, mod_url) in enumerate(mod_entries, 1):
        print(f"\n[{idx}/{len(mod_entries)}] {mod_name}")

        ok = download_mod(driver, mod_url, mc_version, loader_id, mods_dir_abs)
        if ok:
            succeeded += 1
        else:
            failed.append(mod_name)

    # Final wait
    print("\nWaiting for remaining downloads...")
    wait_for_downloads(mods_dir_abs, timeout=30)

    driver.quit()

    all_files = [f for f in os.listdir(mods_dir_abs)
                 if not f.endswith(".crdownload")]

    print(f"\n{'='*50}")
    print(f"✅ Done! {len(all_files)} file(s) in: {mods_dir_abs}")

    if failed:
        print(f"\n⚠  {len(failed)} mod(s) had no files for {mc_version}/{loader_name.capitalize()}:")
        for name in failed:
            print(f"   - {name}")


if __name__ == "__main__":
    main()
