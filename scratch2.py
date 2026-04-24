import asyncio
import pandas as pd
from playwright.async_api import async_playwright
import re
from io import StringIO

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        print("Navigating...")
        await page.goto("https://38nguk.in/sports/archery", wait_until="networkidle")
        await page.wait_for_selector(".styles_cardMainContainer__rQzdE")
        cards = await page.query_selector_all(".styles_cardMainContainer__rQzdE")
        
        for card in cards:
            buttons = await card.query_selector_all("button")
            for btn in buttons:
                text = await btn.inner_text()
                if "fixture" in text.lower():
                    print("Clicking fixture...")
                    current_url = page.url
                    await btn.scroll_into_view_if_needed()
                    await btn.click()
                    await page.wait_for_function(f"() => window.location.href !== '{current_url}'")
                    await page.wait_for_load_state("networkidle")
                    
                    try:
                        print("Clicking LEADERBOARD...")
                        lb = page.locator("a, button, div").filter(has_text=re.compile(r"^\s*leaderboard\s*$", re.I)).first
                        await lb.wait_for(timeout=5000)
                        await lb.click()
                        await page.wait_for_load_state("networkidle")
                    except Exception as e:
                        print("Failed to click LEADERBOARD:", e)
                    
                    print("Counting tables...")
                    html = await page.content()
                    dfs = pd.read_html(StringIO(html))
                    print(f"Found {len(dfs)} tables")
                    if dfs:
                        df = dfs[0]
                        print("Columns:", df.columns.tolist())
                        print("Head:")
                        print(df.head())
                    
                    await browser.close()
                    return

if __name__ == "__main__":
    asyncio.run(main())
