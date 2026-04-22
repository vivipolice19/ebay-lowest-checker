import asyncio
import random
from config import RANDOM_WAIT_MIN, RANDOM_WAIT_MAX, SOLD_KEYWORDS
from logger import log_info, log_error, log_debug

async def check_mercari_sold(mercari_url):
    from playwright.async_api import async_playwright
    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            wait_time = random.uniform(RANDOM_WAIT_MIN, RANDOM_WAIT_MAX)
            await asyncio.sleep(wait_time)

            await page.goto(mercari_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            page_content = await page.content()
            page_text = await page.inner_text("body")

            is_sold = False
            for keyword in SOLD_KEYWORDS:
                if keyword.lower() in page_text.lower() or keyword.lower() in page_content.lower():
                    is_sold = True
                    log_info(f"売り切れ検出: {mercari_url} (キーワード: {keyword})")
                    break

            await browser.close()

            if not is_sold:
                log_debug(f"在庫あり: {mercari_url}")

            return is_sold

    except Exception as e:
        log_error(f"Mercariチェックエラー: {mercari_url} - {e}")
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        return False

async def check_mercari_sold_batch(urls):
    results = {}
    for url in urls:
        try:
            result = await check_mercari_sold(url)
            results[url] = result
        except Exception as e:
            log_error(f"バッチチェックエラー: {url} - {e}")
            results[url] = False
    return results
