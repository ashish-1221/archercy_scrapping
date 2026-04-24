import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Navigate from the main page to the fixture, because direct navigation might be failing
        await page.goto("https://37nationalgamesgoa.in/sports/archery", wait_until="networkidle")
        cards = await page.query_selector_all(".styles_cardMainContainer__rQzdE")
        
        for card in cards:
            event = await card.query_selector("p.defaultHeading")
            if event and "Compound Women Team" in await event.inner_text():
                buttons = await card.query_selector_all("button")
                for btn in buttons:
                    if "fixture" in (await btn.inner_text()).lower():
                        await btn.scroll_into_view_if_needed()
                        await btn.click()
                        await page.wait_for_load_state("networkidle")
                        await page.wait_for_timeout(3000)
                        
                        html = await page.content()
                        soup = BeautifulSoup(html, "html.parser")
                        print("Text from page:")
                        print(soup.text[:2000])
                        with open("compound_women_team.html", "w") as f:
                            f.write(html)
                        await browser.close()
                        return

if __name__ == "__main__":
    asyncio.run(main())
