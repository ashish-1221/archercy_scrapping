import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Navigate to Compound Women individual leaderboard
        url = "https://37nationalgamesgoa.in/sports/archery/leaderboard?sport=archery&eventId=530&sportId=45&stages=leaderboard,elimination&eventType=individual"
        await page.goto(url, wait_until="networkidle")
        
        try:
            await page.wait_for_selector("div.row", timeout=10000)
            await page.wait_for_timeout(2000)
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")
            print("First few rows:")
            for row in soup.find_all("div", class_="row")[:5]:
                print("Row:", row.text.strip())
                for i, col in enumerate(row.find_all("div", class_=lambda c: c and "col" in c)):
                    print(f"  Col {i}:", col.text.strip())
        except Exception as e:
            print("Error:", e)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
