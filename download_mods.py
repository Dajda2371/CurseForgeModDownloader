import os
import time
import re
from urllib.parse import urlparse

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
HTML_FILE = r"c:\Users\David\Downloads\Dračovňák\modlist.html"
MODS_DIR = r"c:\Users\David\Downloads\Dračovňák\mods"

def main():
    # Ensure mods directory exists
    if not os.path.exists(MODS_DIR):
        os.makedirs(MODS_DIR)
        print(f"Created directory: {MODS_DIR}")

    # Read the HTML file
    if not os.path.exists(HTML_FILE):
        print(f"Error: {HTML_FILE} not found!")
        return

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Parse HTML for links
    soup = BeautifulSoup(html_content, "html.parser")
    links = [a.get("href") for a in soup.find_all("a", href=True)]
    
    # Filter only CurseForge mod links
    curseforge_links = [link for link in links if "curseforge.com/minecraft/mc-mods/" in link]
    
    print(f"Found {len(curseforge_links)} mods to download.")
    if not curseforge_links:
        return

    # Setup Selenium (CurseForge blocks simple requests/cURL because of Cloudflare protection)
    # We use a real browser to bypass it and automate the 5-second wait.
    print("Setting up Chrome driver...")
    options = Options()
    prefs = {
        "download.default_directory": MODS_DIR,
        "download.prompt_for_download": False,
        "directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    options.add_experimental_option("prefs", prefs)
    # Note: Running headless might trigger Cloudflare's anti-bot check, so we keep the browser visible.
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    # Download each mod
    for url in curseforge_links:
        # CurseForge initiates download automatically on the /download page
        download_url = url if url.endswith("/download") else f"{url}/download"
        print(f"Starting download for: {url}")
        
        try:
            driver.get(download_url)
            # Wait for the file to download. Curseforge has a 5-second countdown.
            # We wait 8 seconds to be safe before moving to the next tab.
            time.sleep(8) 
            
        except Exception as e:
            print(f"Failed to load {download_url}: {e}")

    print("Waiting 15 seconds for all ongoing downloads to finish...")
    time.sleep(15)
    
    driver.quit()
    print("Finished downloading mods! Check the mods folder.")

if __name__ == "__main__":
    main()
