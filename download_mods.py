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

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(SCRIPT_DIR, "modlist.html")
MODS_DIR = os.path.join(SCRIPT_DIR, "mods")

LOADERS = {
    "forge": 1,
    "fabric": 4,
    "neoforge": 6,
}


def dismiss_cookie_bar(driver):
    """Click the 'Got it' cookie consent button if it exists."""
    try:
        driver.execute_script("""
            var btn = document.getElementById('cookiebar-ok');
            if (btn) btn.click();
            // Also try by text
            var buttons = document.querySelectorAll('button, a');
            for (var i = 0; i < buttons.length; i++) {
                var t = (buttons[i].textContent || '').trim();
                if (t === 'Got it' || t === 'Accept') {
                    buttons[i].click();
                    break;
                }
            }
        """)
    except Exception:
        pass


def wait_for_downloads(mods_dir, timeout=30):
    """Wait until no .crdownload files remain."""
    for _ in range(timeout):
        downloading = glob.glob(os.path.join(mods_dir, "*.crdownload"))
        if not downloading:
            return True
        time.sleep(1)
    return False


def download_mod(driver, mod_url, mc_version, loader_id, mods_dir):
    """
    Flow:
    1. Open filtered files page → e.g. /files/all?version=1.20.1&gameVersionTypeId=1...
    2. Click the first file row (a.file-row-details) → goes to /files/<id>
    3. On file detail page, click the big orange Download button (a.btn-cta) → goes to /download/<id>
    4. CurseForge countdown page auto-downloads the file via Chrome
    """
    # ── Step 1: Open the filtered files page ──
    files_url = (
        f"{mod_url.rstrip('/')}/files/all"
        f"?page=1&pageSize=20&version={mc_version}"
        f"&gameVersionTypeId={loader_id}&showAlphaFiles=hide"
    )
    print(f"  1. Opening files list...")
    driver.get(files_url)

    # Poll until a.file-row-details appears (up to 20 s)
    file_href = None
    for _ in range(20):
        time.sleep(1)
        dismiss_cookie_bar(driver)
        file_href = driver.execute_script("""
            var rows = document.querySelectorAll('a.file-row-details');
            if (rows.length > 0) {
                return rows[0].getAttribute('href');
            }
            return null;
        """)
        if file_href:
            break

    if not file_href:
        no_results = driver.execute_script(
            "return document.body.innerText.includes('No Results');"
        )
        if no_results:
            print(f"  ⚠  No files for version {mc_version}.")
        else:
            print(f"  ⚠  File rows did not appear. Page: {driver.current_url}")
        return False

    # Make the href absolute
    if not file_href.startswith("http"):
        file_page_url = "https://www.curseforge.com" + file_href
    else:
        file_page_url = file_href

    print(f"  2. Opening file detail: {file_page_url}")

    # ── Step 2: Navigate to the file detail page ──
    driver.get(file_page_url)

    # Poll until the orange Download button (a.btn-cta) appears (up to 20 s)
    download_href = None
    for _ in range(20):
        time.sleep(1)
        dismiss_cookie_bar(driver)
        download_href = driver.execute_script("""
            // The big orange download button has class 'btn-cta'
            var btns = document.querySelectorAll('a.btn-cta');
            for (var i = 0; i < btns.length; i++) {
                var text = (btns[i].textContent || '').trim().toLowerCase();
                var href = btns[i].getAttribute('href') || '';
                if (text.includes('download') || href.includes('/download/')) {
                    return btns[i].getAttribute('href');
                }
            }
            // Fallback: look for any link whose href contains /download/ + digits
            var links = document.querySelectorAll('a[href*="/download/"]');
            for (var i = 0; i < links.length; i++) {
                var href = links[i].getAttribute('href');
                if (/\\/download\\/\\d+/.test(href)) {
                    return href;
                }
            }
            return null;
        """)
        if download_href:
            break

    if not download_href:
        print(f"  ⚠  Could not find the Download button on {driver.current_url}")
        return False

    # Make the download URL absolute
    if not download_href.startswith("http"):
        download_url = "https://www.curseforge.com" + download_href
    else:
        download_url = download_href

    # ── Step 3: Count files before, then navigate to the download page ──
    files_before = set(os.listdir(mods_dir))

    print(f"  3. Downloading: {download_url}")
    driver.get(download_url)

    # Wait for the 5-second countdown + download to complete
    time.sleep(10)
    wait_for_downloads(mods_dir, timeout=30)

    # ── Step 4: Report ──
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

    # ── Setup Chrome ──
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
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": mods_dir_abs,
    })

    # Warm up & dismiss cookie bar
    print("Warming up browser (Cloudflare)...")
    driver.get("https://www.curseforge.com")
    time.sleep(8)
    dismiss_cookie_bar(driver)

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

    all_files = [f for f in os.listdir(mods_dir_abs) if not f.endswith(".crdownload")]
    print(f"\n{'='*50}")
    print(f"✅ Done! {len(all_files)} file(s) in: {mods_dir_abs}")

    if failed:
        print(f"\n⚠  {len(failed)} mod(s) had issues:")
        for name in failed:
            print(f"   - {name}")


if __name__ == "__main__":
    main()
