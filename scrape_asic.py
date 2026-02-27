"""
ASIC Published Notices Scraper - Solar/Renewables Distress Monitor
Scrapes ASIC insolvency notices for solar/renewable companies,
follows through to each detail page for full data extraction,
and emails a daily HTML digest.
"""

import os
import re
import smtplib
import sys
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup, Tag

# --- Configuration ---
SEARCH_TERMS = ["solar", "renewable", "energy+storage", "battery+storage"]
BASE_URL = "https://publishednotices.asic.gov.au/browsesearch-notices"
NOTICE_BASE = "https://publishednotices.asic.gov.au"
REQUEST_DELAY = 1.5  # seconds between detail page fetches

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

# Reuse a session for cookies (ASP.NET needs this)
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def now_utc() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


def build_search_url(term: str) -> str:
    return (
        f"{BASE_URL}?appointment=All&noticestate=All"
        f"&companynameoracn={term}&court=&district=&dnotice="
    )


def parse_date(date_str: str) -> datetime | None:
    """Parse '26/02/2026' or '26 February 2026' style dates."""
    for fmt in ("%d/%m/%Y", "%d %B %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# STEP 1: Scrape the search results listing page
# ---------------------------------------------------------------------------

def scrape_listing(search_term: str) -> list[dict]:
    """Scrape page 1 of the ASIC search listing for a given term."""
    url = build_search_url(search_term)
    print(f"[listing] Fetching: {url}")

    resp = SESSION.get(url, timeout=30)
    resp.raise_for_status()

    html = resp.text
    print(f"  [debug] Response length: {len(html)} chars, status: {resp.status_code}")

    # Debug: dump first 500 chars and check for key markers
    if "article-block" not in html:
        print(f"  [debug] WARNING: 'article-block' not found in response!")
        print(f"  [debug] Checking for alternative markers...")
        for marker in ["NoticeTable", "published-date", "notice-buttons", "title-block", 
                        "search-results", "lvNoticeList", "<table", "<h3"]:
            if marker in html:
                print(f"  [debug]   Found: '{marker}'")

        # Dump a snippet for debugging
        # Find the <body> content
        body_start = html.find("<body")
        if body_start > -1:
            snippet = html[body_start:body_start + 2000]
            print(f"  [debug] Body snippet (first 2000 chars):")
            print(snippet[:2000])
        else:
            print(f"  [debug] First 2000 chars of response:")
            print(html[:2000])

    soup = BeautifulSoup(html, "html.parser")

    # Try multiple selectors in case class names differ
    blocks = soup.select("div.article-block")
    if not blocks:
        # Fallback: try finding by the published-date div
        blocks = []
        for date_div in soup.select("div.published-date"):
            # Walk up to find the containing block
            parent = date_div
            for _ in range(5):
                parent = parent.parent
                if parent and parent.name == "div":
                    blocks.append(parent)
                    break
                if parent and parent.name == "td":
                    # The block might be inside a <td>
                    inner_div = parent.find("div")
                    if inner_div:
                        blocks.append(inner_div)
                    break

    if not blocks:
        # Last resort: try to find notice content by h3 tags with known notice text
        print(f"  [debug] Trying h3-based fallback extraction...")
        for h3 in soup.find_all("h3"):
            text = h3.get_text(strip=True).upper()
            if any(kw in text for kw in ["NOTICE OF", "APPLICATION FOR", "MEETING OF"]):
                # Walk up to enclosing div or td
                parent = h3.parent
                for _ in range(5):
                    if parent and parent.name in ("div", "td"):
                        blocks.append(parent)
                        break
                    if parent:
                        parent = parent.parent

    print(f"  [debug] Found {len(blocks)} notice blocks")

    notices = []
    for block in blocks:
        # Published date
        date_el = block.find("div", class_="published-date")
        if not date_el:
            # Fallback: look for "Published:" text anywhere in block
            date_el = block.find(string=re.compile(r"Published:"))
            if date_el:
                date_el = date_el.parent

        if not date_el:
            continue

        date_text = date_el.get_text(strip=True).replace("Published:", "").strip()
        pub_date = parse_date(date_text)
        if not pub_date:
            continue

        # Notice type from h3
        h3 = block.find("h3")
        notice_type = h3.get_text(" ", strip=True) if h3 else "Unknown"

        # Company list from dl elements
        companies = []
        for dl in block.find_all("dl"):
            acn = status = ""
            for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd")):
                k = dt.get_text(strip=True).rstrip(":")
                v = dd.get_text(strip=True)
                if k == "ACN":
                    acn = v
                elif k == "Status":
                    status = v

            # Company name: the <p> immediately before the <dl>
            prev = dl.find_previous_sibling("p") if dl.parent else None
            if not prev:
                prev = dl.find_previous("p")
            name = prev.get_text(strip=True) if prev else ""
            trading_as = ""
            if prev:
                ta_span = prev.find("span")
                if ta_span and "trading as" in ta_span.get_text().lower():
                    parts = prev.get_text(strip=True).split("trading as")
                    if len(parts) == 2:
                        name = parts[0].strip()
                        trading_as = parts[1].strip()

            if acn:
                companies.append({
                    "name": name,
                    "trading_as": trading_as,
                    "acn": acn,
                    "status": status,
                })

        # Detail page link
        view_link = ""
        link_tag = block.find("a", href=re.compile(r"notice-details"))
        if not link_tag:
            link_tag = block.select_one("a.button")
        if link_tag and link_tag.get("href"):
            href = link_tag["href"]
            clean = href.split("?")[0]
            if clean.startswith("/"):
                view_link = NOTICE_BASE + clean
            elif clean.startswith("http"):
                view_link = clean

        notices.append({
            "date": pub_date,
            "date_str": date_text,
            "notice_type": notice_type,
            "companies": companies,
            "view_link": view_link,
            "search_term": search_term,
            "detail": None,
        })

    return notices


# ---------------------------------------------------------------------------
# STEP 2: Scrape the detail page for each notice
# ---------------------------------------------------------------------------

def extract_table_pairs(soup_section) -> dict:
    """Extract key-value pairs from table rows with 2 cells."""
    data = {}
    for table in soup_section.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) == 2:
                key = cells[0].get_text(strip=True).rstrip(":")
                val = cells[1].get_text(strip=True)
                if key and val:
                    data[key] = val
    return data


def scrape_detail_page(url: str) -> dict:
    """Fetch a notice detail page and extract all structured data."""
    print(f"  [detail] Fetching: {url}")
    detail = {}

    try:
        resp = SESSION.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [detail] ERROR: {e}")
        return detail

    soup = BeautifulSoup(resp.text, "html.parser")

    # The notice content sits after the "Notice" h2 heading
    notice_heading = soup.find("h2", string=re.compile(r"^Notice$", re.I))
    if not notice_heading:
        print(f"  [detail] WARNING: Could not find 'Notice' heading")
        return detail

    # Gather content elements until footer
    content_els = []
    for sib in notice_heading.find_next_siblings():
        if isinstance(sib, Tag):
            if sib.name == "ul" and sib.find("a", href="/about-us"):
                break
            content_els.append(sib)

    content_html = "\n".join(str(el) for el in content_els)
    content_soup = BeautifulSoup(content_html, "html.parser")

    # Extract all table key-value pairs
    all_kv = extract_table_pairs(content_soup)
    detail["all_fields"] = all_kv

    # Map known fields
    detail["company"] = all_kv.get("Company", "")
    detail["acn"] = all_kv.get("ACN", "")
    detail["status"] = all_kv.get("Status", "")
    detail["appointment_date"] = all_kv.get("Appointment Date", all_kv.get("Appointed", ""))
    detail["appointor"] = all_kv.get("Appointor", "")
    detail["date_of_notice"] = all_kv.get("Date of Notice", "")

    # Practitioner info
    detail["practitioner_name"] = all_kv.get("Administrator(s)",
                                    all_kv.get("Liquidator(s)", ""))
    detail["practitioner_address"] = all_kv.get("Address", "")
    detail["contact_person"] = all_kv.get("Contact person", "")
    detail["contact_number"] = all_kv.get("Contact number", "")
    detail["contact_email"] = all_kv.get("Email", "")

    # Meeting info
    detail["meeting_location"] = all_kv.get("Location", "")
    detail["meeting_date"] = all_kv.get("Meeting date", "")
    detail["meeting_time"] = all_kv.get("Meeting time", "")

    # Proof of debt deadline
    pod_time = all_kv.get("Time", "")
    pod_date = all_kv.get("Date", "")
    if pod_time and pod_date:
        detail["proof_of_debt_deadline"] = f"{pod_time} on {pod_date}"

    # Hearing info (winding up applications)
    detail["hearing_date"] = all_kv.get("Hearing date", "")
    detail["hearing_time"] = all_kv.get("Hearing time", "")
    detail["court"] = all_kv.get("Court", "")

    # Dividend info
    detail["dividend_date"] = all_kv.get("Dividend Payable Date",
                               all_kv.get("Dividend payable date", ""))

    # Notice title
    h2 = content_soup.find("h2")
    if h2:
        detail["notice_title"] = h2.get_text(" ", strip=True)

    # Resolution / body text
    paragraphs = []
    for p in content_soup.find_all("p"):
        text = p.get_text(strip=True)
        if text and len(text) > 20:
            paragraphs.append(text)
    detail["body_text"] = paragraphs

    # Agenda / list items
    list_items = []
    for li in content_soup.find_all("li"):
        text = li.get_text(strip=True)
        if text:
            list_items.append(text)
    detail["agenda_items"] = list_items

    # Special instructions
    special = []
    for el in content_soup.find_all(string=re.compile(r"[Ss]pecial")):
        parent = el.find_parent()
        if parent:
            next_el = parent.find_next_sibling()
            if next_el:
                txt = next_el.get_text(strip=True)
                if txt and len(txt) > 10:
                    special.append(txt)
    detail["special_instructions"] = " ".join(special) if special else ""

    # Practitioner name fallback (from bold role text near bottom)
    role_keywords = ("Liquidator", "Administrator", "Restructuring Practitioner",
                     "Provisional Liquidator", "Solicitor for the Applicant")

    if not detail["practitioner_name"]:
        for strong in content_soup.find_all("strong"):
            text = strong.get_text(strip=True)
            if text in role_keywords:
                detail["practitioner_role"] = text
                parent_p = strong.find_parent("p")
                if parent_p:
                    prev_p = parent_p.find_previous_sibling("p")
                    if prev_p:
                        name_text = prev_p.get_text(strip=True)
                        if name_text and len(name_text) < 100:
                            detail["practitioner_name"] = name_text
                break

    if not detail.get("practitioner_role"):
        for strong in content_soup.find_all("strong"):
            text = strong.get_text(strip=True)
            if text in role_keywords:
                detail["practitioner_role"] = text
                break

    return detail


# ---------------------------------------------------------------------------
# Filtering & deduplication
# ---------------------------------------------------------------------------

def is_recent(notice: dict) -> bool:
    """Keep only notices from today or yesterday (AEST-aware with UTC buffer)."""
    now = now_utc()
    cutoff = (now - timedelta(days=2)).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None
    )
    return notice["date"] >= cutoff


def deduplicate(notices: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for n in notices:
        key = n["view_link"] or f"{n['date_str']}|{n['notice_type']}"
        if key not in seen:
            seen.add(key)
            unique.append(n)
    return unique


# ---------------------------------------------------------------------------
# Email HTML formatting
# ---------------------------------------------------------------------------

def fmt_field(label: str, value: str) -> str:
    if not value:
        return ""
    return (
        f'<tr>'
        f'<td style="padding:2px 8px 2px 0;color:#888;font-size:12px;vertical-align:top;white-space:nowrap;">{label}</td>'
        f'<td style="padding:2px 0;font-size:12px;">{value}</td>'
        f'</tr>'
    )


def build_notice_card(n: dict) -> str:
    """Build a styled HTML card for a single notice."""
    d = n.get("detail") or {}

    status_raw = d.get("status", "") or (n["companies"][0]["status"] if n["companies"] else "")
    if "Liquidation" in status_raw:
        status_color, badge = "#c0392b", "🔴"
    elif "Administrator" in status_raw:
        status_color, badge = "#e67e22", "🟠"
    elif "Restructuring" in status_raw:
        status_color, badge = "#2980b9", "🔵"
    else:
        status_color, badge = "#7f8c8d", "⚪"

    # Company rows
    company_html = ""
    for c in n["companies"]:
        ta = f' <span style="color:#888;font-size:12px;">(t/a {c["trading_as"]})</span>' if c.get("trading_as") else ""
        company_html += f"""
        <div style="margin-bottom:6px;">
            <strong style="font-size:14px;">{c['name']}</strong>{ta}<br>
            <span style="font-size:12px;color:#666;">ACN: {c['acn']}</span>
            <span style="margin-left:8px;font-size:12px;color:{status_color};font-weight:bold;">{c['status']}</span>
        </div>"""

    # Detail fields
    fields = ""
    fields += fmt_field("Published", n["date_str"])
    fields += fmt_field("Appointment Date", d.get("appointment_date", ""))
    fields += fmt_field("Appointor", d.get("appointor", ""))

    meeting_parts = list(filter(None, [d.get("meeting_date"), d.get("meeting_time")]))
    if meeting_parts:
        fields += fmt_field("Meeting", " at ".join(meeting_parts))
    if d.get("meeting_location"):
        fields += fmt_field("Meeting Location", d["meeting_location"])
    if d.get("proof_of_debt_deadline"):
        fields += fmt_field("Proofs/Proxies Due", d["proof_of_debt_deadline"])

    hearing_parts = list(filter(None, [d.get("hearing_date"), d.get("hearing_time")]))
    if hearing_parts:
        fields += fmt_field("Hearing", " at ".join(hearing_parts))
    if d.get("court"):
        fields += fmt_field("Court", d["court"])
    if d.get("dividend_date"):
        fields += fmt_field("Dividend Payable", d["dividend_date"])

    prac = d.get("practitioner_name", "")
    prac_role = d.get("practitioner_role", "")
    if prac:
        label = f"Practitioner ({prac_role})" if prac_role else "Practitioner"
        fields += fmt_field(label, prac)
    if d.get("practitioner_address"):
        fields += fmt_field("Firm", d["practitioner_address"])
    if d.get("contact_person"):
        fields += fmt_field("Contact", d["contact_person"])
    if d.get("contact_number"):
        fields += fmt_field("Phone", d["contact_number"])
    if d.get("contact_email"):
        email_addr = d["contact_email"]
        fields += fmt_field("Email", f'<a href="mailto:{email_addr}" style="color:#2980b9;">{email_addr}</a>')

    fields_table = f'<table style="margin-top:8px;border-collapse:collapse;">{fields}</table>' if fields else ""

    # Body text
    body_html = ""
    body_texts = [t for t in d.get("body_text", []) if len(t) > 20]
    for t in body_texts[:3]:
        body_html += f'<p style="font-size:12px;color:#555;margin:4px 0;line-height:1.4;">{t}</p>'

    agenda = d.get("agenda_items", [])
    if agenda:
        body_html += '<ul style="font-size:12px;color:#555;margin:4px 0;padding-left:18px;">'
        for item in agenda[:6]:
            body_html += f'<li style="margin-bottom:2px;">{item}</li>'
        body_html += '</ul>'

    if d.get("special_instructions"):
        body_html += (
            f'<div style="font-size:11px;color:#8e44ad;margin:8px 0;padding:6px 10px;'
            f'background:#f5eef8;border-radius:4px;">'
            f'<strong>ℹ️ Special Instructions:</strong> {d["special_instructions"]}'
            f'</div>'
        )

    # Source link
    link_html = ""
    if n["view_link"]:
        link_html = (
            f'<a href="{n["view_link"]}" style="font-size:12px;color:#2980b9;'
            f'text-decoration:none;font-weight:bold;">View full notice on ASIC →</a>'
        )

    notice_title = d.get("notice_title", n["notice_type"])

    return f"""
    <div style="border:1px solid #e0e0e0;border-left:4px solid {status_color};border-radius:6px;
                padding:16px;margin-bottom:16px;background:white;">
        <div style="font-size:11px;color:{status_color};font-weight:bold;text-transform:uppercase;
                    letter-spacing:0.5px;margin-bottom:8px;">
            {badge} {notice_title}
        </div>
        {company_html}
        {fields_table}
        {body_html}
        <div style="margin-top:12px;padding-top:8px;border-top:1px solid #f0f0f0;">{link_html}</div>
    </div>
    """


def build_email(notices: list[dict]) -> str:
    today_str = now_utc().strftime("%A %d %B %Y")

    if not notices:
        return f"""
        <html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
                          color:#333;max-width:700px;margin:0 auto;padding:20px;">
        <h2 style="color:#2c3e50;">⚡ ASIC Distress Monitor</h2>
        <p style="color:#666;">{today_str}</p>
        <div style="background:#f0f9f0;border:1px solid #c3e6cb;border-radius:6px;padding:16px;margin:20px 0;">
            <p style="color:#155724;margin:0;">✅ No new solar/renewable insolvency notices found today.</p>
        </div>
        <p style="font-size:11px;color:#999;">
            Search terms: {', '.join(t.replace('+', ' ') for t in SEARCH_TERMS)}<br>
            Source: <a href="{BASE_URL}" style="color:#999;">ASIC Published Notices</a>
        </p>
        </body></html>"""

    # Group by severity
    liquidations = [n for n in notices
                    if any("Liquidation" in c.get("status", "") for c in n["companies"])]
    administrations = [n for n in notices
                       if any("Administrator" in c.get("status", "") for c in n["companies"])]
    other = [n for n in notices if n not in liquidations and n not in administrations]

    cards_html = ""
    if liquidations:
        cards_html += '<h3 style="color:#c0392b;margin:24px 0 12px;">🔴 Liquidations</h3>'
        for n in liquidations:
            cards_html += build_notice_card(n)
    if administrations:
        cards_html += '<h3 style="color:#e67e22;margin:24px 0 12px;">🟠 Administrations</h3>'
        for n in administrations:
            cards_html += build_notice_card(n)
    if other:
        cards_html += '<h3 style="color:#2980b9;margin:24px 0 12px;">🔵 Other Notices</h3>'
        for n in other:
            cards_html += build_notice_card(n)

    unique_companies = set()
    for n in notices:
        for c in n["companies"]:
            if c.get("acn"):
                unique_companies.add(c["acn"])

    return f"""
    <html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
                      color:#333;max-width:700px;margin:0 auto;padding:20px;">
        <h2 style="color:#2c3e50;margin-bottom:4px;">⚡ ASIC Distress Monitor — Daily Report</h2>
        <p style="color:#666;margin-top:0;">{today_str}</p>

        <div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:12px 16px;margin-bottom:20px;">
            <strong>{len(notices)}</strong> notice(s) across
            <strong>{len(unique_companies)}</strong> unique compan{'y' if len(unique_companies) == 1 else 'ies'}
            &nbsp;|&nbsp;
            🔴 {len(liquidations)} liquidation &nbsp;
            🟠 {len(administrations)} administration &nbsp;
            🔵 {len(other)} other
        </div>

        {cards_html}

        <hr style="border:none;border-top:1px solid #eee;margin:24px 0;">
        <p style="font-size:11px;color:#999;">
            Search terms: {', '.join(t.replace('+', ' ') for t in SEARCH_TERMS)}<br>
            Source: <a href="{BASE_URL}" style="color:#999;">ASIC Published Notices</a><br>
            Generated: {now_utc().strftime('%Y-%m-%d %H:%M UTC')}
        </p>
    </body></html>"""


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def send_email(subject: str, html_body: str):
    gmail_addr = os.environ.get("GMAIL_ADDRESS", "")
    gmail_pass = os.environ.get("GMAIL_APP_PASSWORD", "")
    notify_email = os.environ.get("NOTIFY_EMAIL", gmail_addr)

    if not gmail_addr or not gmail_pass:
        print("⚠️  GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set — skipping email")
        print("    Set these as GitHub Secrets to enable email delivery")
        return

    # Strip whitespace/newlines that can sneak into secrets
    gmail_addr = gmail_addr.strip()
    gmail_pass = gmail_pass.strip()
    notify_email = notify_email.strip()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_addr
    msg["To"] = notify_email
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_addr, gmail_pass)
            server.sendmail(gmail_addr, [notify_email], msg.as_string())
        print(f"✉️  Email sent to {notify_email}")
    except smtplib.SMTPAuthenticationError as e:
        print(f"\n❌ Gmail authentication failed!")
        print(f"   Error: {e}")
        print(f"\n   Common fixes:")
        print(f"   1. Make sure you're using an App Password, NOT your regular password")
        print(f"   2. Go to https://myaccount.google.com/apppasswords to create one")
        print(f"   3. You MUST have 2-Step Verification enabled first")
        print(f"   4. The App Password is 16 chars with no spaces (e.g. 'abcdefghijklmnop')")
        print(f"   5. Check your GMAIL_APP_PASSWORD secret has no leading/trailing spaces")
        print(f"   6. GMAIL_ADDRESS should be your full email (e.g. 'you@gmail.com')")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Failed to send email: {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    all_notices = []

    print("=" * 60)
    print("ASIC Distress Monitor — Starting scrape")
    print(f"Time: {now_utc().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    for term in SEARCH_TERMS:
        try:
            notices = scrape_listing(term)
            print(f"  → {len(notices)} notices for '{term}'")
            all_notices.extend(notices)
        except Exception as e:
            print(f"  ✗ Error scraping '{term}': {e}")

    # Deduplicate
    all_notices = deduplicate(all_notices)
    print(f"\n{len(all_notices)} unique notices total (all dates)")

    # Filter to recent
    recent = [n for n in all_notices if is_recent(n)]
    print(f"{len(recent)} notices from today/yesterday\n")

    # Fetch detail pages
    if recent:
        print("Fetching detail pages...")
        for i, notice in enumerate(recent):
            if notice["view_link"]:
                notice["detail"] = scrape_detail_page(notice["view_link"])
                if i < len(recent) - 1:
                    time.sleep(REQUEST_DELAY)
            else:
                notice["detail"] = {}
        print()

    # Build and send email
    today_str = now_utc().strftime("%Y-%m-%d")
    subject = f"ASIC Solar/Renewables Monitor — {today_str}"
    if recent:
        subject += f" — {len(recent)} notice(s)"
    else:
        subject += " — no new notices"

    html = build_email(recent)
    send_email(subject, html)

    print("=" * 60)
    print("✅ Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
