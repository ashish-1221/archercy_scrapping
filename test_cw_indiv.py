import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Navigate to Compound Women individual leaderboard
        url = "https://37nationalgamesgoa.in/sports/archery/leaderboard?sport=archery&eventId=530&sportId=45&stages=leaderboard,elimination&eventType=individual"
        await page.goto(url, wait_until="networkidle")
        
        try:
            await page.wait_for_selector("div.row", timeout=5000)
            await page.wait_for_timeout(1000)
        except: pass
        
        state_to_players = await page.evaluate("""() => {
            const map = {};
            document.querySelectorAll("div.row").forEach(row => {
                const cols = row.querySelectorAll("div[class*='col-sm']");
                if (cols.length >= 5) {
                    const player = cols[3].innerText.trim();
                    const state = cols[4].innerText.trim();
                    if (player && state) {
                        if (!map[state]) map[state] = [];
                        map[state].push(player);
                    }
                }
            });
            return map;
        }""")
        print("Players:", state_to_players)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
