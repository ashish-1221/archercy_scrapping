import asyncio
from playwright.async_api import async_playwright
import pandas as pd
from io import StringIO
import re

BASE_URL = "https://37nationalgamesgoa.in/sports/archery"

async def safe_text(el):
    try:
        return (await el.inner_text()).strip()
    except:
        return ""

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.goto(BASE_URL, wait_until="networkidle")
        await page.wait_for_selector(".styles_cardMainContainer__rQzdE")
        cards = await page.query_selector_all(".styles_cardMainContainer__rQzdE")
        
        for i, card in enumerate(cards):
            event = await safe_text(await card.query_selector("p.defaultHeading"))
            if "team" in event.lower() or "mixed" in event.lower():
                print(f"[{i}] Event: {event}")
                buttons = await card.query_selector_all("button")
                for btn in buttons:
                    if "fixture" in (await safe_text(btn)).lower():
                        await btn.scroll_into_view_if_needed()
                        await btn.click()
                        await page.wait_for_load_state("networkidle")
                        print("Navigated to:", page.url)
                        
                        # Now we should be on the leaderboard page. Let's see if we have a table.
                        try:
                            # Sometimes we have to click a leaderboard tab if we are not on it
                            # Wait! When clicking fixture, it usually goes to leaderboard. Let's see.
                            await page.wait_for_selector("table", timeout=15000)
                            html = await page.content()
                            frames = pd.read_html(StringIO(html))
                            print(frames[0].head(10))
                        except Exception as e:
                            print("No table found:", e)
                            
                        await browser.close()
                        return

if __name__ == "__main__":
    asyncio.run(main())
