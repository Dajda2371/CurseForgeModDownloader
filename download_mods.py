import os
import time
import re
import glob

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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(SCRIPT_DIR, "modlist.html")
MODS_DIR = os.path.join(SCRIPT_DIR, "mods")

LOADERS = {
    "forge": 1,
    "fabric": 4,
    "neoforge": 6,
}


def dismiss_cookie_bar(driver):
    """Click the cookie consent button if it exists."""
    try:
        driver.execute_script("""
            var btn = document.getElementById('cookiebar-ok');
            if (btn) { btn.click(); }
            document.querySelectorAll('button, a').forEach(function(el) {
                if ((el.textContent || '').trim() === 'Got it') el.click();
            });
        """)
    except Exception:
        pass


def wait_for_downloads(mods_dir, timeout=30):
    """Wait until no .crdownload files remain."""
    for _ in range(timeout):
        if not glob.glob(os.path.join(mods_dir, "*.crdownload")):
            return True
        time.sleep(1)
    return False


def download_mod(driver, mod_url, mc_version, loader_id, mods_dir):
    """
    1. Open filtered files page
    2. Click first file row → file detail page
    3. Click the big orange Download button → download page
    4. Chrome downloads the file
    """

    # ── Step 1: Open filtered files page ──
    files_url = (
        f"{mod_url.rstrip('/')}/files/all"
        f"?page=1&pageSize=20&version={mc_version}"
        f"&gameVersionTypeId={loader_id}&showAlphaFiles=hide"
    )
    print(f"  1. Opening files list...")
    driver.get(files_url)

    # Wait for file rows using WebDriverWait (more robust than polling with JS)
    dismiss_cookie_bar(driver)
    try:
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.file-row-details"))
        )
    except Exception:
        # The CSS selector may not work if the page uses different rendering.
        # Try JavaScript as fallback.
        time.sleep(5)
        dismiss_cookie_bar(driver)

    # Try to get the first file row href via JavaScript
    file_href = driver.execute_script("""
        // Method 1: specific class
        var rows = document.querySelectorAll('a.file-row-details');
        if (rows.length > 0) return rows[0].getAttribute('href');

        // Method 2: look for links in the file list area matching the pattern
        var all = document.querySelectorAll('a[href]');
        for (var i = 0; i < all.length; i++) {
            var h = all[i].getAttribute('href') || '';
            // Only match file detail links, skip /files/all and /files/create etc.
            if (/\\/files\\/\\d+$/.test(h) && h.includes('/mc-mods/')) {
                // Check this is in the main content area (not sidebar)
                var rect = all[i].getBoundingClientRect();
                if (rect.width > 100 && rect.top > 200) {
                    return h;
                }
            }
        }
        return null;
    """)

    if not file_href:
        # Last resort: dump some debug info
        no_results = driver.execute_script(
            "return document.body.innerText.includes('No Results');"
        )
        if no_results:
            print(f"  ⚠  No files for {mc_version}.")
        else:
            # Print what classes ARE on the page for debugging
            debug = driver.execute_script("""
                var links = document.querySelectorAll('a[href*="/files/"]');
                var info = [];
                for (var i = 0; i < Math.min(links.length, 5); i++) {
                    info.push(links[i].className + ' -> ' + links[i].getAttribute('href'));
                }
                return info.join(' | ');
            """)
            print(f"  ⚠  file-row-details not found. Links with /files/: {debug}")
            print(f"     URL: {driver.current_url}")
        return False

    # Make absolute
    if not file_href.startswith("http"):
        file_page_url = "https://www.curseforge.com" + file_href
    else:
        file_page_url = file_href

    print(f"  2. File detail: {file_page_url}")

    # ── Step 2: Open file detail page ──
    driver.get(file_page_url)
    dismiss_cookie_bar(driver)

    # Wait for the Download button
    try:
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.btn-cta"))
        )
    except Exception:
        time.sleep(5)
        dismiss_cookie_bar(driver)

    # Get the download button href via JavaScript
    download_href = driver.execute_script("""
        // Method 1: btn-cta class (the big orange button)
        var btns = document.querySelectorAll('a.btn-cta');
        for (var i = 0; i < btns.length; i++) {
            var h = btns[i].getAttribute('href') || '';
            if (h.includes('/download/') || h.includes('/download')) {
                return h;
            }
        }

        // Method 2: any link with /download/ + digits
        var links = document.querySelectorAll('a[href*="/download/"]');
        for (var i = 0; i < links.length; i++) {
            var h = links[i].getAttribute('href');
            if (/\\/download\\/\\d+/.test(h)) return h;
        }

        // Method 3: look for "Download" text in visible buttons
        var all = document.querySelectorAll('a, button');
        for (var i = 0; i < all.length; i++) {
            var txt = (all[i].textContent || '').trim();
            if (txt === 'Download' && all[i].offsetParent !== null) {
                var h = all[i].getAttribute('href');
                if (h) return h;
                // If it's a button without href, click it
                all[i].click();
                return '__clicked__';
            }
        }
        return null;
    """)

    if not download_href:
        print(f"  ⚠  Download button not found on {driver.current_url}")
        return False

    # Count files before download
    files_before = set(os.listdir(mods_dir))

    if download_href == '__clicked__':
        print(f"  3. Clicked Download button directly")
    else:
        if not download_href.startswith("http"):
            download_url = "https://www.curseforge.com" + download_href
        else:
            download_url = download_href
        print(f"  3. Downloading: {download_url}")
        driver.get(download_url)

    # ── Step 3: Wait for download ──
    time.sleep(10)
    wait_for_downloads(mods_dir, timeout=30)

    # Report new files
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

    # ── Chrome setup with anti-detection ──
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

    # Warm up: visit a CurseForge page to pass Cloudflare
    print("Warming up browser...")
    driver.get("https://www.curseforge.com")
    time.sleep(10)
    dismiss_cookie_bar(driver)

    # ── Process each mod ──
    succeeded = 0
    failed = []

    for idx, (mod_name, mod_url) in enumerate(mod_entries, 1):
        print(f"\n[{idx}/{len(mod_entries)}] {mod_name}")
        ok = download_mod(driver, mod_url, mc_version, loader_id, mods_dir_abs)
        if ok:
            succeeded += 1
        else:
            failed.append(mod_name)

    # Final cleanup
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
