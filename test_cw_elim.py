import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Navigate directly to the elimination page for Compound Women Team
        url = "https://37nationalgamesgoa.in/sports/archery/elimination?sport=archery&eventId=533&sportId=45&stages=leaderboard,elimination&eventType=team"
        await page.goto(url, wait_until="networkidle")
        
        try:
            await page.wait_for_selector("div.event-tile", timeout=15000)
            await page.wait_for_timeout(2000)
            html = await page.content()
            with open("compound_women_team_elimination.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("Saved elimination HTML")
            
            # Print text of first tile
            tile = await page.query_selector("div.event-tile")
            if tile:
                print("First tile text:", await tile.inner_text())
                print("First tile HTML:", await tile.evaluate("el => el.outerHTML"))
        except Exception as e:
            print("Error:", e)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
