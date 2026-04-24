import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Navigate to Compound Women individual leaderboard
        url = "https://37nationalgamesgoa.in/sports/archery/leaderboard?sport=archery&eventId=530&sportId=45&stages=leaderboard,elimination&eventType=individual"
        await page.goto(url, wait_until="networkidle")
        
        await page.wait_for_timeout(3000)
        
        state_to_players = await page.evaluate("""() => {
            const map = {};
            document.querySelectorAll("div.row").forEach(row => {
                const cols = row.querySelectorAll("div[class*='col-sm']");
                let player = "";
                let state = "";
                if (cols.length === 4) {
                    player = cols[1].innerText.trim();
                    state = cols[2].innerText.trim();
                } else if (cols.length >= 5) {
                    player = cols[3].innerText.trim();
                    state = cols[4].innerText.trim();
                }
                
                if (player && state && player.toLowerCase() !== "player name") {
                    if (!map[state]) map[state] = [];
                    map[state].push(player);
                }
            });
            return map;
        }""")
        print("Players:", state_to_players)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
