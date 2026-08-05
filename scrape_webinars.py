"""
AEE Webinar Scraper — pulls live upcoming webinars from
https://www.aeecenter.org/membership/member-webinars/
and writes a clean webinars.json file for the Boeing Access page to read.

Design note: this keys off the real "More Info & Register" links
(education.aeecenter.org/products/...) rather than CSS class names,
since link URLs and link text are far more stable than a WordPress
theme's internal markup.
"""
import json
import re
import sys
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.aeecenter.org/membership/member-webinars/"
OUTPUT_FILE = "webinars.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (AEE Boeing Access Page updater)"}


def fetch_page(url):
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def parse_webinars(html):
    soup = BeautifulSoup(html, "html.parser")
    webinars = []

    # Anchor on real registration links — this is the stable signal.
    reg_links = soup.find_all(
        "a",
        href=re.compile(r"education\.aeecenter\.org/products/"),
    )

    for link in reg_links:
        href = link.get("href", "").strip()
        link_text = link.get_text(strip=True)
        if "register" not in link_text.lower() and "info" not in link_text.lower():
            continue  # skip incidental links that happen to match the domain

        # Walk up only until the container would start including
        # more than one registration link — that's the boundary of
        # "this webinar's own block," regardless of how many levels
        # of nesting the theme happens to use.
        container = link
        while container.parent:
            parent = container.parent
            links_in_parent = parent.find_all(
                "a", href=re.compile(r"education\.aeecenter\.org/products/")
            )
            if len(links_in_parent) > 1:
                break  # parent now spans multiple webinars, stop here
            container = parent

        block_text = container.get_text("\n", strip=True)

        date_match = re.search(
            r"([A-Z][a-z]{2}\s+\d{1,2},?\s+\d{4})", block_text
        )
        time_match = re.search(
            r"(\d{1,2}:\d{2}\s*[ap]m\s*[-–]\s*\d{1,2}:\d{2}\s*[ap]m)",
            block_text,
            re.IGNORECASE,
        )
        credit_match = re.search(
            r"(\d+(?:\.\d+)?)\s*AEE credits?", block_text, re.IGNORECASE
        )
        nonmember_match = re.search(
            r"Non-?Member\s*\|?\s*(?:USD\s*)?\$?(\d+)", block_text, re.IGNORECASE
        )
        members_only = bool(
            re.search(r"members?\s+only", block_text, re.IGNORECASE)
        )

        # Title heuristic: prefer h3 specifically (the real page uses
        # h3 for titles, h4 for dates, h5 for times) — fall back to
        # any heading that doesn't look like a date/time if h3 is absent.
        title = None
        h3 = container.find("h3")
        if h3:
            title = h3.get_text(strip=True)
        else:
            for tag in container.find_all(["h2", "h4"]):
                text = tag.get_text(strip=True)
                if not re.match(r"^[A-Z][a-z]{2}\s+\d{1,2}", text) and not re.match(
                    r"^\d{1,2}:\d{2}", text
                ):
                    title = text
                    break

        if not title or not date_match:
            continue  # incomplete match, skip rather than guess

        entry = {
            "title": title,
            "date_raw": date_match.group(1),
            "time_raw": time_match.group(1) if time_match else None,
            "ceu_credits": credit_match.group(1) if credit_match else None,
            "nonmember_price": nonmember_match.group(1) if nonmember_match else None,
            "members_only": members_only,
            "register_url": href,
        }

        # De-dupe (same webinar can appear near multiple nested containers)
        if not any(e["register_url"] == href for e in webinars):
            webinars.append(entry)

    return webinars


def main():
    try:
        html = fetch_page(SOURCE_URL)
    except Exception as e:
        print(f"FETCH FAILED: {e}", file=sys.stderr)
        sys.exit(1)

    webinars = parse_webinars(html)

    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_URL,
        "count": len(webinars),
        "webinars": webinars,
    }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(webinars)} webinars to {OUTPUT_FILE}")
    if len(webinars) == 0:
        print("WARNING: zero webinars parsed — page structure may have changed.", file=sys.stderr)
        sys.exit(1)  # fail the Action so it's visible, not silent


if __name__ == "__main__":
    main()
