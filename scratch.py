import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        # Navigate to the main page to get an event card, then click view fixture
        await page.goto("https://37nationalgamesgoa.in/sports/archery", wait_until="networkidle")
        cards = await page.query_selector_all(".styles_cardMainContainer__rQzdE")
        for i, card in enumerate(cards):
            event = await card.query_selector("p.defaultHeading")
            event_text = await event.inner_text()
            if "team" in event_text.lower() or "mixed" in event_text.lower():
                print(f"Found event: {event_text}")
                buttons = await card.query_selector_all("button")
                for btn in buttons:
                    if "fixture" in (await btn.inner_text()).lower():
                        await btn.scroll_into_view_if_needed()
                        await btn.click()
                        await page.wait_for_load_state("networkidle")
                        print("Leaderboard URL:", page.url)
                        html = await page.content()
                        with open("leaderboard.html", "w", encoding="utf-8") as f:
                            f.write(html)
                        await browser.close()
                        return

if __name__ == "__main__":
    asyncio.run(main())
