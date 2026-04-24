import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Navigate to Compound Women individual leaderboard
        url = "https://37nationalgamesgoa.in/sports/archery/leaderboard?sport=archery&eventId=530&sportId=45&stages=leaderboard,elimination&eventType=individual"
        await page.goto(url, wait_until="networkidle")
        
        print("Waiting 5s for data to load...")
        await page.wait_for_timeout(5000)
        
        await page.screenshot(path="cw_individual.png", full_page=True)
        print("Screenshot saved to cw_individual.png")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
