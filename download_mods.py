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
    2. Click on the first file row to open its detail page.
    3. Click the Download button on that page to trigger the download.
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
    time.sleep(10)

    # Step 2: Use JS to click the FIRST file row link to open the file detail page
    clicked_href = driver.execute_script("""
        var links = document.querySelectorAll('a[href]');
        for (var i = 0; i < links.length; i++) {
            var h = links[i].getAttribute('href');
            if (h && /\\/minecraft\\/mc-mods\\/.+\\/files\\/[0-9]+$/.test(h)) {
                links[i].click();
                return h;
            }
        }
        return null;
    """)

    if not clicked_href:
        # Retry once after waiting more
        time.sleep(5)
        clicked_href = driver.execute_script("""
            var links = document.querySelectorAll('a[href]');
            for (var i = 0; i < links.length; i++) {
                var h = links[i].getAttribute('href');
                if (h && /\\/minecraft\\/mc-mods\\/.+\\/files\\/[0-9]+$/.test(h)) {
                    links[i].click();
                    return h;
                }
            }
            return null;
        """)

    if not clicked_href:
        print(f"  ⚠  No file rows found on the page.")
        # Debug info
        title = driver.title
        url = driver.current_url
        print(f"     Page: {title}")
        print(f"     URL:  {url}")
        # Check if "No Results" is on the page
        has_no_results = driver.execute_script("""
            return document.body.innerText.includes('No Results');
        """)
        if has_no_results:
            print(f"     Page shows 'No Results' for this version/loader.")
        return False

    print(f"  ↳ Clicked file: {clicked_href}")

    # Step 3: Wait for the file detail page to load
    time.sleep(8)

    # Step 4: Count files before download
    files_before = set(os.listdir(mods_dir))

    # Step 5: Click the Download button on the file detail page
    # Look for a prominent download button/link
    download_clicked = driver.execute_script("""
        // Strategy 1: Look for a button/link with download-related class or text
        var candidates = document.querySelectorAll('a[href*="/download"], button');
        for (var i = 0; i < candidates.length; i++) {
            var el = candidates[i];
            var text = (el.textContent || el.innerText || '').trim().toLowerCase();
            var href = el.getAttribute('href') || '';
            // Match "Download" button but not "Downloads" count
            if ((text === 'download' || text === 'download file' || 
                 text.startsWith('download') && !text.includes('downloads')) &&
                el.offsetParent !== null) {
                el.click();
                return 'clicked: ' + text;
            }
            // Match href pointing to /download/<id>
            if (/\\/download\\/[0-9]+/.test(href) && el.offsetParent !== null) {
                el.click();
                return 'clicked href: ' + href;
            }
        }
        
        // Strategy 2: Look for any visible element containing just "Download"
        var allEls = document.querySelectorAll('a, button, span');
        for (var i = 0; i < allEls.length; i++) {
            var el = allEls[i];
            var text = (el.textContent || el.innerText || '').trim();
            if (text === 'Download' && el.offsetParent !== null) {
                el.click();
                return 'clicked element: ' + el.tagName;
            }
        }
        
        return null;
    """)

    if not download_clicked:
        print(f"  ⚠  Could not find Download button on file detail page.")
        print(f"     URL: {driver.current_url}")
        return False

    print(f"  ⬇  {download_clicked}")

    # Step 6: Wait for CurseForge's 5-second countdown + download
    time.sleep(10)
    wait_for_downloads(mods_dir, timeout=30)

    # Step 7: Check if a new file appeared
    files_after = set(os.listdir(mods_dir))
    new_files = {f for f in (files_after - files_before) if not f.endswith(".crdownload")}

    if new_files:
        for f in new_files:
            size_mb = os.path.getsize(os.path.join(mods_dir, f)) / (1024 * 1024)
            print(f"  ✓  Saved: {f} ({size_mb:.2f} MB)")
        return True
    else:
        # Might still be downloading, don't mark as failed yet
        print(f"  ⏳ Download may still be in progress...")
        return True  # optimistic


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
