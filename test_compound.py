import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Navigate directly to the leaderboard page for Compound Women Team
        url = "https://37nationalgamesgoa.in/sports/archery/leaderboard?sport=archery&eventId=533&sportId=45&stages=leaderboard,elimination&eventType=team"
        await page.goto(url, wait_until="networkidle")
        
        try:
            await page.wait_for_selector("div.row", timeout=15000)
            await page.wait_for_timeout(2000)
            html = await page.content()
            with open("compound_women_team.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("Saved HTML")
        except Exception as e:
            print("Error:", e)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
