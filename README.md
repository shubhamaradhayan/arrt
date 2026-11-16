# ARRT Credential Search Exporter

This Python project automates searches on the public [ARRT credential verification page](https://www.arrt.org/pages/verify-credentials), collects the details shown for matching records, removes duplicate records, and writes the results to JSON and CSV files.

Use it only for searches you are authorized to perform, in line with ARRT's terms, privacy requirements, and applicable law. The project automates interaction with a site that presents reCAPTCHA; do not use it to evade access controls. Prefer an official API or obtain permission from ARRT for automated or bulk access.

## What it does

`main.py` opens the verification page in Chromium, submits the configured last name and each configured first name, reads the result table, requests the associated detail markup, and extracts the displayed fields. It retries missing detail responses, computes a SHA-256 fingerprint to identify duplicate records, and saves progress as records are collected.

`RecaptchaSolver.py` contains browser and audio-recognition handling for the site's reCAPTCHA challenge. This behavior can fail or change when the site changes its challenge. It is not an official ARRT integration and should not be used to bypass the site's controls.

## Requirements

- Python 3.10 or later is recommended.
- Chromium browser available to DrissionPage.
- Python packages listed in `requirements.txt`:
  - **DrissionPage** — controls Chromium and observes browser page/network activity.
  - **BeautifulSoup4** — parses returned HTML into credential fields.
  - **pydub** — converts downloaded audio to WAV for speech recognition.
  - **SpeechRecognition** — submits audio to Google's recognition service.

`main.py` also uses Python's standard library modules for CSV/JSON files, hashing, regular expressions, timing, and configuration.

## Setup

Create and activate a virtual environment, then install the dependencies:

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\\Scripts\\activate
python -m pip install -r requirements.txt
```

`pydub` may require FFmpeg installed and available on `PATH` for MP3 conversion. A working Chromium installation is also required.

## Configure and run

Edit the configuration near the top of `main.py` before running:

```python
LAST_NAME = "%%"
FIRST_NAME = ["z", "y"]
OUT_JSON = "details.json"
OUT_CSV = "details.csv"
FAILED_JSON = "failed.json"
```

Set search terms and output paths appropriate to your authorized search. The current values are examples from the script and may produce broad searches. Then run:

```bash
python main.py
```

The script launches a Chromium window. It observes the site response and page state, so unattended or headless runs may need additional setup. Site changes, network issues, browser compatibility, or challenge failures may cause searches to stop or return no records.

## Output files

- **`details.json`** — structured detail records, including a fingerprint used for deduplication.
- **`details.csv`** — a tabular export of the extracted credential fields; internal token/detail metadata is omitted.
- **`failed.json`** — result rows for which the detail request did not return usable markup.

The JSON results are loaded on later runs and deduplicated, so the script can retain prior results. The CSV is regenerated from the current JSON records. These files may contain personal or professional credential information; store and share them carefully, and delete them when no longer needed.

## Implementation notes and tool choices

| Tool or library | Role | Why it is used |
| --- | --- | --- |
| Python | Workflow and data handling | Provides the browser orchestration, parsing, retries, deduplication, and export logic in one script. |
| DrissionPage + Chromium | Browser automation | Loads the search page and interacts with its rendered form and results table. |
| BeautifulSoup4 | HTML parsing | Extracts labeled values from the returned credential detail HTML. |
| `csv` and `json` (standard library) | Export and persistence | Produce formats that are easy to inspect and use in other tools. |
| SHA-256 (`hashlib`, standard library) | Duplicate detection | Builds a stable fingerprint from visible search fields and normalized detail text. |
| pydub + SpeechRecognition | Audio processing in the included challenge handler | Converts challenge audio and performs speech recognition; this is dependent on external services and may not work reliably. |

## Time to complete

The development time was approx 4 hours(included testing). The script's runtime is separate and depends on how many searches and result rows are returned, network speed, configured delays, and retries (approx 30 mins for 1200 data).

## Known limitations

- The page selectors, request behavior, and HTML layout are specific to the current ARRT page and may break if it changes.
- The script makes assumptions about the site's client-side request setup and result-table structure.
- Search response and reCAPTCHA behavior are controlled by the site and are not guaranteed.
- The audio-recognition path relies on third-party services and should not be treated as a robust or supported verification method.
- The script has no formal test suite or command-line configuration layer; settings are edited in `main.py`.
