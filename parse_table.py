import asyncio
from playwright.async_api import async_playwright
import pandas as pd
from io import StringIO

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        # The URL we found earlier
        url = "https://37nationalgamesgoa.in/sports/archery/leaderboard?sport=archery&eventId=532&sportId=45&stages=leaderboard,elimination&eventType=team"
        await page.goto(url, wait_until="networkidle")
        
        # Wait for table
        try:
            await page.wait_for_selector("table", timeout=15000)
        except Exception as e:
            print("Table not found:", e)
            html = await page.content()
            print(html[:500])
            await browser.close()
            return
            
        html = await page.content()
        frames = pd.read_html(StringIO(html))
        print(frames[0])
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
