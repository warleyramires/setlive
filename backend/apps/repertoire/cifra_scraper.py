import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

TIMEOUT_SECONDS = 15


def fetch_cifra_text(url):
    """Fetch chord/tab content from a CifraClub URL.

    Tries <pre> first (imprimir.html format), then falls back to
    common cifra container divs.
    """
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    pre = soup.find("pre")
    if pre:
        return pre.get_text()

    for selector in ("div.cifra_cnt", "div.cifra"):
        div = soup.select_one(selector)
        if div:
            return div.get_text("\n")

    return ""
