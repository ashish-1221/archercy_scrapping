import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Navigate to Compound Women TEAM leaderboard
        url = "https://37nationalgamesgoa.in/sports/archery/leaderboard?sport=archery&eventId=533&sportId=45&stages=leaderboard,elimination&eventType=team"
        await page.goto(url, wait_until="networkidle")
        
        print("Waiting 5s for data to load...")
        await page.wait_for_timeout(5000)
        
        await page.screenshot(path="cw_team.png", full_page=True)
        print("Screenshot saved to cw_team.png")
        
        # Show all text on page
        text = await page.evaluate("() => document.body.innerText")
        print("\n--- PAGE TEXT ---")
        print(text[:3000])
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
