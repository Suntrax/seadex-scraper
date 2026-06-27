from playwright.async_api import async_playwright
import requests
import asyncio


def get_anilist_id(anime_name: str) -> str | None:
    query = """
    query ($search: String) {
      Media(search: $search, type: ANIME) {
        id
        idMal
        title {
          romaji
          english
          native
        }
      }
    }
    """

    variables = {
        "search": anime_name
    }

    response = requests.post(
        "https://graphql.anilist.co",
        json={
            "query": query,
            "variables": variables
        },
        timeout=10
    )

    response.raise_for_status()

    data = response.json()["data"]["Media"]

    return str(data["id"])


# -----------------------------
# STEP 1: get nyaa links
# -----------------------------
async def fetch_releases_links(page, url):
    await page.goto(url, wait_until="domcontentloaded", timeout=15000)

    await page.wait_for_function("""
    () => Array.from(document.querySelectorAll("a"))
        .some(a => (a.href || a.dataset.href || "").includes("nyaa.si/view"))
    """, timeout=10000)

    links = await page.eval_on_selector_all(
        "a",
        """els => els
            .map(e => e.getAttribute('data-href') || e.href || '')
            .filter(u => u.includes('nyaa.si/view'))
        """
    )

    # remove duplicates
    return list(set(links))


# -----------------------------
# STEP 2: extract magnets from nyaa page
# -----------------------------
async def fetch_magnets(context, url):
    page = await context.new_page()

    await page.goto(url, wait_until="domcontentloaded", timeout=15000)

    await page.wait_for_selector("a[href^='magnet:']", timeout=10000)

    magnets = await page.eval_on_selector_all(
        "a[href^='magnet:']",
        """els => els.map(e => e.href)"""
    )

    await page.close()
    return magnets


# -----------------------------
# MAIN PIPELINE
# -----------------------------
async def run(base_url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox"]
        )

        context = await browser.new_context()

        # speed boost: block heavy resources
        async def block(route):
            if route.request.resource_type in ["image", "font", "media"]:
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", block)

        page = await context.new_page()

        # STEP 1: get nyaa pages
        nyaa_links = await fetch_releases_links(page, base_url)

        await page.close()

        print(f"Found {len(nyaa_links)} Nyaa links")

        # STEP 2: fetch magnets in parallel (FAST)
        tasks = [
            fetch_magnets(context, url)
            for url in nyaa_links
        ]

        results = await asyncio.gather(*tasks)

        await browser.close()

        # flatten
        magnets = [m for sub in results for m in sub]

        return nyaa_links, magnets


# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    base_url = "https://releases.moe/" + get_anilist_id("blue lock")

    print("Fetching:", base_url)

    nyaa_links, magnets = asyncio.run(run(base_url))

    print("\n=== NYAA LINKS ===")
    for l in nyaa_links:
        print(l)

    print("\n=== MAGNET LINKS ===")
    for m in magnets:
        print(m)