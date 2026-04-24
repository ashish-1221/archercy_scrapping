import asyncio
from playwright.async_api import async_playwright

BASE_URL = "https://37nationalgamesgoa.in/sports/archery"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.goto(BASE_URL, wait_until="networkidle")
        await page.wait_for_selector(".styles_cardMainContainer__rQzdE")
        cards = await page.query_selector_all(".styles_cardMainContainer__rQzdE")
        
        for i, card in enumerate(cards):
            event_el = await card.query_selector("p.defaultHeading")
            event = (await event_el.inner_text()).strip() if event_el else ""
            if "team" in event.lower() or "mixed" in event.lower():
                print(f"[{i}] Event: {event}")
                buttons = await card.query_selector_all("button")
                for btn in buttons:
                    btn_text = (await btn.inner_text()).strip()
                    if "fixture" in btn_text.lower():
                        await btn.scroll_into_view_if_needed()
                        await btn.click()
                        await page.wait_for_load_state("networkidle")
                        
                        # Just dump the page content after networkidle
                        # Wait an extra 2 seconds just in case
                        await page.wait_for_timeout(2000)
                        html = await page.content()
                        with open("team_leaderboard.html", "w", encoding="utf-8") as f:
                            f.write(html)
                        print("Saved team_leaderboard.html")
                        await browser.close()
                        return

if __name__ == "__main__":
    asyncio.run(main())
