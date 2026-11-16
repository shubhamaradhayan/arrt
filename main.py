import re
import csv
import json
import time
import os
import hashlib

from bs4 import BeautifulSoup
from DrissionPage import ChromiumPage, ChromiumOptions
from RecaptchaSolver import RecaptchaSolver
from random import randint, choice
# ---------------------------------------------------------------- config
LAST_NAME = "%%"
FIRST_NAME = ["z", "y"]
OUT_JSON = "details.json"
OUT_CSV = "details.csv"
FAILED_JSON = "failed.json"
DELAY_BETWEEN_DETAILS = 0.5
# DELAY_BETWEEN_DETAILS = 3
DELAY_BETWEEN_SEARCHES = 5
MAX_RETRIES = 5
URL = "https://www.arrt.org/pages/verify-credentials"

CHROME_ARGUMENTS = [
    "-no-first-run",
    "-force-color-profile=srgb",
    "-metrics-recording-only",
    "-password-store=basic",
    "-use-mock-keychain",
    "-export-tagged-pdf",
    "-no-default-browser-check",
    "-disable-background-mode",
    "-enable-features=NetworkService,NetworkServiceInProcess",
    "-disable-features=FlashDeprecationWarning",
    "-deny-permission-prompts",
    "-disable-gpu",
    "-accept-lang=en-US",
    "--disable-usage-stats",
    "--disable-crash-reporter",
    "--no-sandbox",
]

DETAILS_JS = """
const key = arguments[0];
return new Promise((resolve, reject) => {
  $.ajax({
    url: VerifyCredentialsGetDisplayDetailsUrl,
    type: 'POST',
    headers: {"RequestVerificationToken": $(':input[name="__RequestVerificationToken"]').val()},
    data: {key: key},
    success: r => resolve(r),
    error: (x, s, e) => reject(String(e || s))
  });
});
"""

DETAILS_JS_SYNC = """
const key = arguments[0];
let out = null;
$.ajax({
  url: VerifyCredentialsGetDisplayDetailsUrl,
  type: 'POST',
  async: false,
  headers: {"RequestVerificationToken": $(':input[name="__RequestVerificationToken"]').val()},
  data: {key: key},
  success: r => { out = r; }
});
return out;
"""

NON_CSV_KEYS = {"token", "details", "fingerprint"}


# ---------------------------------------------------------------- helpers

def parse_details(html):
    soup = BeautifulSoup(html, "html.parser")

    data = {}

    for row in soup.select("table.table-condensed tr"):
        cols = row.find_all("td", recursive=False)
        heading = row.find("th")

        if heading and cols:
            key = heading.get_text(" ", strip=True)
            value = cols[0].get_text(" ", strip=True)

            if key == "CQR Compliance Period(s)":
                value = value.replace("(Credential not subject to CQR)", "").strip()
                value += "(Credential not subject to CQR)"

            data[key] = value

    # Credential Description
    description_table = soup.find("b", string="Credential Description")

    if description_table:
        table = description_table.find_next("table")
        data["Credential Description"] = " ".join(
            td.get_text(" ", strip=True)
            for td in table.find_all("td")
        )


    return data



def make_fingerprint(row, details):
    """Stable ID for a person: visible fields + normalized details text."""
    text = re.sub(r"\s+", " ", details.get("_text", "")).strip().lower()
    base = "|".join([
        row["name"].lower(), row["city"].lower(),
        row["state"].lower(), row["credential"].lower(), text,
    ])
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def dedupe(results):
    """Remove duplicates by fingerprint, keeping the first occurrence."""
    seen, unique = set(), []
    for r in results:
        fp = r.get("fingerprint")
        if fp and fp in seen:
            continue
        if fp:
            seen.add(fp)
        unique.append(r)
    return unique


def save(results):
    unique = dedupe(results)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(unique, f, ensure_ascii=False, indent=2)

    if not unique:
        return
    keys = []
    for r in unique:
        for k in r:
            if k not in keys and k not in NON_CSV_KEYS:
                keys.append(k)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(unique)


def load_existing():
    if os.path.exists(OUT_JSON):
        try:
            with open(OUT_JSON, "r", encoding="utf-8") as f:
                return dedupe(json.load(f))
        except Exception as e:
            print("Could not read existing JSON, starting fresh:", e)
    return []


def get_details(driver, token):
    for js in (DETAILS_JS, DETAILS_JS_SYNC):
        try:
            result = driver.run_js(js, token)
            if result:
                return result
        except Exception as e:
            print("   run_js error:", str(e)[:120])
    return None

def get_details_with_retry(driver, token, retries=MAX_RETRIES):
    for attempt in range(1, retries + 1):
        try:
            html = get_details(driver, token)

            if html and len(html.strip()) > 1000:
                return html

            print(f"   Retry {attempt}/{retries}: Empty response")

        except Exception as e:
            print(f"   Retry {attempt}: {e}")

        time.sleep(2*attempt)

    return None

def read_rows_on_page(driver):
    rows = []
    for tr in driver.eles("css:#grid tbody tr"):
        tds = tr.eles("tag:td")
        if len(tds) < 5:
            continue
        link = tr.ele("css:a.btn-list", timeout=0.5)
        onclick = (link.attr("onclick") or "") if link else ""
        m = re.search(r"showDetails\(this,\s*'([^']+)'", onclick)
        rows.append({
            "name": tds[0].text.strip(),
            "city": tds[1].text.strip(),
            "state": tds[2].text.strip(),
            "credential": tds[3].text.strip(),
            "token": m.group(1) if m else None,
        })
    return rows


def set_max_page_length(driver):
    try:
        select = driver.ele("css:select[name='grid_length']", timeout=2)
        if select:
            values = [o.attr("value") for o in select.eles("tag:option")]
            if "-1" in values:
                select.select.by_value("-1")
            else:
                select.select.by_value(max(values, key=lambda v: int(v)))
            time.sleep(2)
    except Exception as e:
        print("Could not change page length:", e)


def has_next_page(driver):
    nxt = driver.ele("#grid_next", timeout=1)
    if not nxt:
        return False
    return "disabled" not in (nxt.attr("class") or "")


def run_search(driver, solver, last_name, first_name):
    driver.listen.start("VerifyCredentials/SearchByName", method="POST")
    driver.get(URL)
    time.sleep(5)

    driver.ele("#lastname").clear()
    driver.ele("#lastname").input(last_name)
    driver.ele("#firstname").clear()
    driver.ele("#firstname").input(first_name)

    try:
        solver.solveCaptcha()
    except Exception as e:
        print(f"Error solving captcha: {e}")

    time.sleep(5)
    driver.ele("#submitButton").click()

    packet = driver.listen.wait(timeout=60)
    driver.listen.stop()
    if not packet or not packet.response:
        print("No search response received (captcha failed?)")
        return False
    print("Search response status:", packet.response.status)

    try:
        driver.wait.ele_displayed("#grid", timeout=30)
    except Exception:
        print("Results table did not appear (maybe no matches).")
        return False
    time.sleep(2)
    return True


def scrape_current_search(driver, first_name, results, seen_fp, failed):
    set_max_page_length(driver)
    seen_tokens = set()          # avoid refetching the same row within this search
    page_no = 1

    while True:
        rows = read_rows_on_page(driver)
        print(f"\n[{first_name}] Page {page_no}: {len(rows)} rows")

        for i, row in enumerate(rows, 1):
            token = row["token"]
            if not token or token in seen_tokens:
                continue
            seen_tokens.add(token)

            # html = get_details(driver, token)
            html = get_details_with_retry(driver, token)
            print("html length:", len(html) if html else "None")
            if html is None:
                print(f"  [{i}] {row['name']}: no details (saved to failed list)")
                failed.append({k: v for k, v in row.items() if k != "token"}
                              | {"search_first_name": first_name})
                with open(FAILED_JSON, "w", encoding="utf-8") as f:
                    json.dump(failed, f, ensure_ascii=False, indent=2)
                continue

            details = parse_details(html)
            fp = make_fingerprint(row, details)
            if fp in seen_fp:
                print(f"  [{i}] {row['name']}: duplicate, skipped")
                time.sleep(DELAY_BETWEEN_DETAILS)
                continue
            seen_fp.add(fp)

            row["fingerprint"] = fp
            row["search_first_name"] = first_name
            row["details"] = details
            res={"fingerprint": fp, **details}
            for k, v in details.items():
                if k != "_text":
                    row.setdefault(k, v)

            results.append(res)
            save(results)
            # results.append(row)
            # save(results)
            print(f"  [{i}] {row['name']}: ok")
            time.sleep(DELAY_BETWEEN_DETAILS)

        if not has_next_page(driver):
            break
        driver.ele("#grid_next").click()
        page_no += 1
        time.sleep(2)


# ---------------------------------------------------------------- main
options = ChromiumOptions()
for argument in CHROME_ARGUMENTS:
    options.set_argument(argument)

# options.set_argument('--headless=new')

driver = ChromiumPage(addr_or_opts=options)
recaptchaSolver = RecaptchaSolver(driver)

results = load_existing()
seen_fp = {r["fingerprint"] for r in results if r.get("fingerprint")}
failed = []
print(f"Loaded {len(results)} existing records")

try:
    for first_name in FIRST_NAME:
        print(f"\n===== Searching first name: {first_name!r} =====")
        try:
            if run_search(driver, recaptchaSolver, LAST_NAME, first_name):
                scrape_current_search(driver, first_name, results, seen_fp, failed)
        except Exception as e:
            print(f"Search for {first_name!r} failed: {e}")
        time.sleep(DELAY_BETWEEN_SEARCHES)

    results = dedupe(results)
    save(results)
    print(f"\nDone. {len(results)} unique records in {OUT_JSON} and {OUT_CSV}")
    if failed:
        print(f"{len(failed)} rows had no details, see {FAILED_JSON}")

finally:
    try:
        driver.listen.stop()
    except Exception:
        pass
    input("Press Enter to close browser...")
    driver.quit()