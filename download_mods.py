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


def wait_for_downloads(mods_dir, timeout=30):
    """Wait until no .crdownload files remain (Chrome is done downloading)."""
    for _ in range(timeout):
        downloading = glob.glob(os.path.join(mods_dir, "*.crdownload"))
        if not downloading:
            return True
        time.sleep(1)
    return False


def find_first_file_link(driver):
    """
    Use JavaScript to search ALL <a> elements on the page for one whose href
    matches /minecraft/mc-mods/<slug>/files/<numeric-id>.
    Returns the href string or None.
    """
    href = driver.execute_script("""
        var links = document.querySelectorAll('a[href]');
        for (var i = 0; i < links.length; i++) {
            var h = links[i].getAttribute('href');
            if (h && /\\/minecraft\\/mc-mods\\/.+\\/files\\/\\d+$/.test(h)) {
                return h;
            }
        }
        return null;
    """)
    return href


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
    os.makedirs(mods_dir, exist_ok=True)
    # Chrome needs an absolute path with forward slashes or escaped backslashes
    mods_dir_abs = os.path.abspath(mods_dir)

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

    # Setup Selenium with Chrome download configured
    print("Setting up Chrome driver...")
    options = Options()
    prefs = {
        "download.default_directory": mods_dir_abs,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    # Use CDP to ensure downloads go to the right directory (most reliable method)
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": mods_dir_abs,
    })

    # Warm up — visit CurseForge to pass Cloudflare
    print("Warming up browser (Cloudflare check)...")
    driver.get("https://www.curseforge.com/minecraft/mc-mods")
    time.sleep(8)

    succeeded = []
    failed = []

    for idx, (mod_name, mod_url) in enumerate(mod_entries, 1):
        print(f"\n[{idx}/{len(mod_entries)}] {mod_name}")

        # Build the files-page URL with all required params
        files_url = (
            f"{mod_url.rstrip('/')}/files/all"
            f"?page=1&pageSize=20&version={mc_version}"
            f"&gameVersionTypeId={loader_id}&showAlphaFiles=hide"
        )
        print(f"  Opening: {files_url}")
        driver.get(files_url)

        # Wait for the page to render (simple sleep is more reliable than selectors)
        time.sleep(8)

        # Use JavaScript to find the first file link
        file_href = find_first_file_link(driver)

        if not file_href:
            # Maybe the page hasn't loaded yet, wait a bit more
            time.sleep(5)
            file_href = find_first_file_link(driver)

        if not file_href:
            print(f"  ⚠  No files found for {mc_version}/{loader_name.capitalize()}.")
            # Debug: print what the page title says
            try:
                title = driver.title
                print(f"     Page title: {title}")
            except:
                pass
            failed.append(mod_name)
            continue

        # Build the download page URL: replace /files/ with /download/
        if file_href.startswith("http"):
            download_url = file_href.replace("/files/", "/download/")
        else:
            download_url = "https://www.curseforge.com" + file_href.replace("/files/", "/download/")

        print(f"  ↳ Navigating to: {download_url}")

        # Count files before download to detect new ones
        files_before = set(os.listdir(mods_dir))

        driver.get(download_url)

        # The download page has a 5-second countdown, then triggers the download.
        # Wait for the countdown + download to complete.
        time.sleep(10)

        # Wait for Chrome to finish writing (.crdownload disappears)
        wait_for_downloads(mods_dir, timeout=30)

        # Check what new file appeared
        files_after = set(os.listdir(mods_dir))
        new_files = files_after - files_before
        # Filter out .crdownload temp files
        new_files = {f for f in new_files if not f.endswith(".crdownload")}

        if new_files:
            for f in new_files:
                size_mb = os.path.getsize(os.path.join(mods_dir, f)) / (1024 * 1024)
                print(f"  ✓  Downloaded: {f} ({size_mb:.2f} MB)")
            succeeded.append(mod_name)
        else:
            print(f"  ⚠  Download might still be in progress or failed.")
            failed.append(mod_name)

    # Final wait for any stragglers
    print("\nWaiting for any remaining downloads to finish...")
    wait_for_downloads(mods_dir, timeout=30)

    driver.quit()

    # Final report
    all_files = [f for f in os.listdir(mods_dir) if not f.endswith(".crdownload")]
    print(f"\n{'='*50}")
    print(f"✅ Downloaded {len(succeeded)}/{len(mod_entries)} mods")
    print(f"   Folder: {mods_dir_abs}")
    print(f"   Files in folder: {len(all_files)}")

    if failed:
        print(f"\n⚠  {len(failed)} mod(s) had issues:")
        for name in failed:
            print(f"   - {name}")


if __name__ == "__main__":
    main()
