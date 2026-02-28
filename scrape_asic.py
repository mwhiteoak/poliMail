"""
ASIC Published Notices Scraper - Solar/Renewables Distress Monitor

Uses Playwright (headless Chromium) to bypass AWS WAF bot protection.
The WAF serves a JS challenge that gets a token, then reloads the page.
We must wait for that reload cycle to complete before scraping.
"""

import json
import os
import re
import smtplib
import sys
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
from bs4 import BeautifulSoup, Tag

# --- Configuration ---
SEARCH_TERMS = [
    "solar",
    "renewable",
    "photovoltaic",
    "battery",
    "wind+energy",
    "wind+farm",
    "energy+storage",
    "green+energy",
    "clean+energy",
    "hydrogen",
    "EV+charging",
    "electric+vehicle",
    "inverter",
    "geothermal",
]
BASE_URL = "https://publishednotices.asic.gov.au/browsesearch-notices"
NOTICE_BASE = "https://publishednotices.asic.gov.au"
DETAIL_DELAY = 2  # seconds between detail page loads
SEEN_FILE = Path(__file__).parent / "seen_notices.json"
SEEN_MAX_AGE_DAYS = 30  # purge entries older than this


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def load_seen() -> dict:
    """Load seen notices. Format: {"url_or_key": "2026-03-01T05:00:00Z", ...}"""
    if SEEN_FILE.exists():
        try:
            data = json.loads(SEEN_FILE.read_text())
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_seen(seen: dict):
    """Save seen notices, purging entries older than SEEN_MAX_AGE_DAYS."""
    cutoff = (now_utc() - timedelta(days=SEEN_MAX_AGE_DAYS)).isoformat()
    pruned = {k: v for k, v in seen.items() if v >= cutoff}
    SEEN_FILE.write_text(json.dumps(pruned, indent=2))
    print(f"  [seen] Saved {len(pruned)} entries ({len(seen) - len(pruned)} pruned)")


def notice_key(n: dict) -> str:
    """Unique key for a notice."""
    return n["view_link"] or f"{n['date_str']}|{n['notice_type']}|{'|'.join(c['acn'] for c in n['companies'])}"


def build_search_url(term: str) -> str:
    return (
        f"{BASE_URL}?appointment=All&noticestate=All"
        f"&companynameoracn={term}&court=&district=&dnotice="
    )


def parse_date(date_str: str) -> datetime | None:
    for fmt in ("%d/%m/%Y", "%d %B %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Browser page fetching — handles AWS WAF challenge
# ---------------------------------------------------------------------------

def fetch_with_waf(page, url: str, content_marker: str = "article-block") -> str:
    """
    Navigate to URL and handle the AWS WAF challenge.
    
    The WAF flow is:
    1. First response is a small page with AwsWafIntegration JS
    2. The JS gets a token and calls window.location.reload(true)
    3. The reloaded page has the actual content
    
    We use page.goto() which waits for load, but the WAF reload happens
    AFTER load. So we need to detect the WAF page and wait for navigation.
    """
    print(f"  [browser] Navigating: {url}")
    
    # First load — this will get the WAF challenge page
    page.goto(url, wait_until="load", timeout=30000)
    
    # Check if we got WAF challenge or real content
    content = page.content()
    
    if "AwsWafIntegration" in content or "challenge-container" in content:
        print(f"  [browser] WAF challenge detected — waiting for auto-reload...")
        
        # The WAF JS will reload the page. Wait for that navigation to complete.
        # We wait for the page to navigate away (the reload) and then for
        # our expected content to appear.
        try:
            # Wait for the page to reload — the WAF JS calls location.reload()
            # This will trigger a new navigation event
            page.wait_for_load_state("networkidle", timeout=15000)
        except PwTimeout:
            pass
        
        # Check again
        content = page.content()
        
        if "AwsWafIntegration" in content:
            # Still on WAF page — wait longer for the reload
            print(f"  [browser] Still on WAF page — waiting for reload...")
            try:
                page.wait_for_url(url + "**", timeout=15000)
            except PwTimeout:
                pass
            
            # Give it extra time and check repeatedly
            for attempt in range(6):
                page.wait_for_timeout(3000)
                content = page.content()
                if content_marker in content or "published-date" in content:
                    print(f"  [browser] Content loaded after {(attempt+1)*3}s wait")
                    break
                if "AwsWafIntegration" not in content and len(content) > 5000:
                    print(f"  [browser] Page changed ({len(content)} chars) after {(attempt+1)*3}s")
                    break
            else:
                print(f"  [browser] WARNING: Timed out waiting for WAF to resolve")
                print(f"  [browser] Page length: {len(content)} chars")
                # Print first 500 chars for debug
                body_match = re.search(r'<body[^>]*>(.*?)</body>', content, re.DOTALL)
                if body_match:
                    print(f"  [browser] Body: {body_match.group(1)[:500]}")
    
    final_html = page.content()
    has_content = content_marker in final_html or "published-date" in final_html
    print(f"  [browser] Final page: {len(final_html)} chars, has_content={has_content}")
    return final_html


# ---------------------------------------------------------------------------
# STEP 1: Scrape listing page
# ---------------------------------------------------------------------------

def scrape_listing(page, search_term: str) -> list[dict]:
    url = build_search_url(search_term)
    print(f"\n[listing] Term: '{search_term}'")

    html = fetch_with_waf(page, url, content_marker="article-block")

    if "article-block" not in html and "published-date" not in html:
        print(f"  [listing] No notice content found in response")
        return []

    soup = BeautifulSoup(html, "html.parser")

    blocks = soup.select("div.article-block")
    if not blocks:
        for date_div in soup.select("div.published-date"):
            parent = date_div
            for _ in range(5):
                parent = parent.parent
                if parent and parent.name in ("div", "td"):
                    blocks.append(parent)
                    break

    print(f"  [listing] Found {len(blocks)} notice blocks")

    notices = []
    for block in blocks:
        date_el = block.find("div", class_="published-date")
        if not date_el:
            date_el_text = block.find(string=re.compile(r"Published:"))
            if date_el_text:
                date_el = date_el_text.parent
        if not date_el:
            continue

        date_text = date_el.get_text(strip=True).replace("Published:", "").strip()
        pub_date = parse_date(date_text)
        if not pub_date:
            continue

        h3 = block.find("h3")
        notice_type = h3.get_text(" ", strip=True) if h3 else "Unknown"

        companies = []
        for dl in block.find_all("dl"):
            acn = status = ""
            for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd")):
                k = dt.get_text(strip=True).rstrip(":")
                v = dd.get_text(strip=True)
                if k == "ACN": acn = v
                elif k == "Status": status = v

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
                        name, trading_as = parts[0].strip(), parts[1].strip()

            if acn:
                companies.append({"name": name, "trading_as": trading_as, "acn": acn, "status": status})

        view_link = ""
        link_tag = block.find("a", href=re.compile(r"notice-details"))
        if not link_tag:
            link_tag = block.select_one("a.button")
        if link_tag and link_tag.get("href"):
            href = link_tag["href"].split("?")[0]
            view_link = (NOTICE_BASE + href) if href.startswith("/") else href

        notices.append({
            "date": pub_date, "date_str": date_text,
            "notice_type": notice_type, "companies": companies,
            "view_link": view_link, "search_term": search_term,
            "detail": None,
        })

    return notices


# ---------------------------------------------------------------------------
# STEP 2: Scrape detail pages
# ---------------------------------------------------------------------------

def extract_table_pairs(soup_section) -> dict:
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


def scrape_detail_page(page, url: str) -> dict:
    detail = {}
    try:
        html = fetch_with_waf(page, url, content_marker="Notice")
    except Exception as e:
        print(f"  [detail] ERROR: {e}")
        return detail

    soup = BeautifulSoup(html, "html.parser")
    notice_heading = soup.find("h2", string=re.compile(r"^Notice$", re.I))
    if not notice_heading:
        return detail

    content_els = []
    for sib in notice_heading.find_next_siblings():
        if isinstance(sib, Tag):
            if sib.name == "ul" and sib.find("a", href="/about-us"):
                break
            content_els.append(sib)

    content_html = "\n".join(str(el) for el in content_els)
    content_soup = BeautifulSoup(content_html, "html.parser")
    all_kv = extract_table_pairs(content_soup)
    detail["all_fields"] = all_kv

    detail["company"] = all_kv.get("Company", "")
    detail["acn"] = all_kv.get("ACN", "")
    detail["status"] = all_kv.get("Status", "")
    detail["appointment_date"] = all_kv.get("Appointment Date", all_kv.get("Appointed", ""))
    detail["appointor"] = all_kv.get("Appointor", "")
    detail["date_of_notice"] = all_kv.get("Date of Notice", "")
    detail["practitioner_name"] = all_kv.get("Administrator(s)", all_kv.get("Liquidator(s)", ""))
    detail["practitioner_address"] = all_kv.get("Address", "")
    detail["contact_person"] = all_kv.get("Contact person", "")
    detail["contact_number"] = all_kv.get("Contact number", "")
    detail["contact_email"] = all_kv.get("Email", "")
    detail["meeting_location"] = all_kv.get("Location", "")
    detail["meeting_date"] = all_kv.get("Meeting date", "")
    detail["meeting_time"] = all_kv.get("Meeting time", "")
    pod_time, pod_date = all_kv.get("Time", ""), all_kv.get("Date", "")
    if pod_time and pod_date:
        detail["proof_of_debt_deadline"] = f"{pod_time} on {pod_date}"
    detail["hearing_date"] = all_kv.get("Hearing date", "")
    detail["hearing_time"] = all_kv.get("Hearing time", "")
    detail["court"] = all_kv.get("Court", "")
    detail["dividend_date"] = all_kv.get("Dividend Payable Date", all_kv.get("Dividend payable date", ""))

    h2 = content_soup.find("h2")
    if h2:
        detail["notice_title"] = h2.get_text(" ", strip=True)

    detail["body_text"] = [p.get_text(strip=True) for p in content_soup.find_all("p")
                           if p.get_text(strip=True) and len(p.get_text(strip=True)) > 20]
    detail["agenda_items"] = [li.get_text(strip=True) for li in content_soup.find_all("li")
                              if li.get_text(strip=True)]

    special = []
    for el in content_soup.find_all(string=re.compile(r"[Ss]pecial")):
        parent = el.find_parent()
        if parent:
            nxt = parent.find_next_sibling()
            if nxt:
                txt = nxt.get_text(strip=True)
                if txt and len(txt) > 10:
                    special.append(txt)
    detail["special_instructions"] = " ".join(special) if special else ""

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
                        nm = prev_p.get_text(strip=True)
                        if nm and len(nm) < 100:
                            detail["practitioner_name"] = nm
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

def is_recent(notice):
    cutoff = (now_utc() - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    return notice["date"] >= cutoff

def deduplicate(notices):
    seen = set()
    return [n for n in notices if not ((k := n["view_link"] or f"{n['date_str']}|{n['notice_type']}") in seen or seen.add(k))]


# ---------------------------------------------------------------------------
# Email HTML
# ---------------------------------------------------------------------------

def fmt(label, value):
    if not value: return ""
    return f'<tr><td style="padding:2px 8px 2px 0;color:#888;font-size:12px;vertical-align:top;white-space:nowrap;">{label}</td><td style="padding:2px 0;font-size:12px;">{value}</td></tr>'

def build_notice_card(n):
    d = n.get("detail") or {}
    sr = d.get("status", "") or (n["companies"][0]["status"] if n["companies"] else "")
    sc, bg = ("#c0392b","🔴") if "Liquidation" in sr else ("#e67e22","🟠") if "Administrator" in sr else ("#2980b9","🔵") if "Restructuring" in sr else ("#7f8c8d","⚪")

    ch = ""
    for c in n["companies"]:
        ta = f' <span style="color:#888;font-size:12px;">(t/a {c["trading_as"]})</span>' if c.get("trading_as") else ""
        ch += f'<div style="margin-bottom:6px;"><strong style="font-size:14px;">{c["name"]}</strong>{ta}<br><span style="font-size:12px;color:#666;">ACN: {c["acn"]}</span> <span style="margin-left:8px;font-size:12px;color:{sc};font-weight:bold;">{c["status"]}</span></div>'

    f = fmt("Published", n["date_str"])
    f += fmt("Appointment Date", d.get("appointment_date",""))
    f += fmt("Appointor", d.get("appointor",""))
    mp = list(filter(None, [d.get("meeting_date"), d.get("meeting_time")]))
    if mp: f += fmt("Meeting", " at ".join(mp))
    f += fmt("Meeting Location", d.get("meeting_location",""))
    f += fmt("Proofs/Proxies Due", d.get("proof_of_debt_deadline",""))
    hp = list(filter(None, [d.get("hearing_date"), d.get("hearing_time")]))
    if hp: f += fmt("Hearing", " at ".join(hp))
    f += fmt("Court", d.get("court",""))
    f += fmt("Dividend Payable", d.get("dividend_date",""))
    pn = d.get("practitioner_name",""); pr = d.get("practitioner_role","")
    if pn: f += fmt(f"Practitioner ({pr})" if pr else "Practitioner", pn)
    f += fmt("Firm", d.get("practitioner_address",""))
    f += fmt("Contact", d.get("contact_person",""))
    f += fmt("Phone", d.get("contact_number",""))
    em = d.get("contact_email","")
    if em: f += fmt("Email", f'<a href="mailto:{em}" style="color:#2980b9;">{em}</a>')
    ft = f'<table style="margin-top:8px;border-collapse:collapse;">{f}</table>' if f else ""

    bh = ""
    for t in d.get("body_text",[])[:3]:
        bh += f'<p style="font-size:12px;color:#555;margin:4px 0;line-height:1.4;">{t}</p>'
    ag = d.get("agenda_items",[])
    if ag:
        bh += '<ul style="font-size:12px;color:#555;margin:4px 0;padding-left:18px;">'
        for i in ag[:6]: bh += f'<li style="margin-bottom:2px;">{i}</li>'
        bh += '</ul>'
    if d.get("special_instructions"):
        bh += f'<div style="font-size:11px;color:#8e44ad;margin:8px 0;padding:6px 10px;background:#f5eef8;border-radius:4px;"><strong>ℹ️ Special Instructions:</strong> {d["special_instructions"]}</div>'

    lh = f'<a href="{n["view_link"]}" style="font-size:12px;color:#2980b9;text-decoration:none;font-weight:bold;">View full notice on ASIC →</a>' if n["view_link"] else ""
    nt = d.get("notice_title", n["notice_type"])
    st = n.get("search_term", "").replace("+", " ")
    st_tag = f' <span style="font-size:10px;color:#fff;background:{sc};padding:1px 6px;border-radius:3px;text-transform:none;letter-spacing:0;font-weight:normal;">matched: {st}</span>' if st else ""

    return f'<div style="border:1px solid #e0e0e0;border-left:4px solid {sc};border-radius:6px;padding:16px;margin-bottom:16px;background:white;"><div style="font-size:11px;color:{sc};font-weight:bold;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">{bg} {nt}{st_tag}</div>{ch}{ft}{bh}<div style="margin-top:12px;padding-top:8px;border-top:1px solid #f0f0f0;">{lh}</div></div>'


def build_search_links_html(matched_terms: set = None) -> str:
    """Build clickable search term pills. Highlight the ones that returned results."""
    pills = []
    for t in SEARCH_TERMS:
        label = t.replace("+", " ")
        url = build_search_url(t)
        is_matched = matched_terms and t in matched_terms
        if is_matched:
            style = "display:inline-block;margin:2px 4px 2px 0;padding:3px 8px;border-radius:4px;font-size:11px;text-decoration:none;background:#2ecc71;color:#fff;font-weight:bold;"
        else:
            style = "display:inline-block;margin:2px 4px 2px 0;padding:3px 8px;border-radius:4px;font-size:11px;text-decoration:none;background:#ecf0f1;color:#666;"
        pills.append(f'<a href="{url}" style="{style}">{label}</a>')
    return " ".join(pills)


def build_email(notices):
    ts = now_utc().strftime("%A %d %B %Y")
    matched = set(n.get("search_term", "") for n in notices) if notices else set()
    search_section = (
        f'<div style="margin:16px 0;padding:12px 16px;background:#f8f9fa;border-radius:6px;">'
        f'<div style="font-size:12px;color:#555;margin-bottom:6px;font-weight:bold;">Search terms monitored ({len(SEARCH_TERMS)}):</div>'
        f'<div>{build_search_links_html(matched)}</div>'
        f'<div style="font-size:10px;color:#999;margin-top:6px;">🟢 = returned results today &nbsp;|&nbsp; Click any term to view on ASIC</div>'
        f'</div>'
    )

    if not notices:
        return (
            f'<html><body style="font-family:-apple-system,Arial,sans-serif;color:#333;max-width:700px;margin:0 auto;padding:20px;">'
            f'<h2 style="color:#2c3e50;">⚡ ASIC Distress Monitor</h2>'
            f'<p style="color:#666;">{ts}</p>'
            f'<div style="background:#f0f9f0;border:1px solid #c3e6cb;border-radius:6px;padding:16px;margin:20px 0;">'
            f'<p style="color:#155724;margin:0;">✅ No new solar/renewable insolvency notices found today.</p>'
            f'</div>'
            f'{search_section}'
            f'<hr style="border:none;border-top:1px solid #eee;margin:24px 0;">'
            f'<p style="font-size:11px;color:#999;">Source: <a href="{BASE_URL}" style="color:#999;">ASIC Published Notices</a><br>'
            f'Generated: {now_utc().strftime("%Y-%m-%d %H:%M UTC")}</p>'
            f'</body></html>'
        )

    lq = [n for n in notices if any("Liquidation" in c.get("status","") for c in n["companies"])]
    ad = [n for n in notices if any("Administrator" in c.get("status","") for c in n["companies"])]
    ot = [n for n in notices if n not in lq and n not in ad]
    cards = ""
    if lq: cards += '<h3 style="color:#c0392b;margin:24px 0 12px;">🔴 Liquidations</h3>' + "".join(build_notice_card(n) for n in lq)
    if ad: cards += '<h3 style="color:#e67e22;margin:24px 0 12px;">🟠 Administrations</h3>' + "".join(build_notice_card(n) for n in ad)
    if ot: cards += '<h3 style="color:#2980b9;margin:24px 0 12px;">🔵 Other Notices</h3>' + "".join(build_notice_card(n) for n in ot)
    uc = set(c["acn"] for n in notices for c in n["companies"] if c.get("acn"))

    return (
        f'<html><body style="font-family:-apple-system,Arial,sans-serif;color:#333;max-width:700px;margin:0 auto;padding:20px;">'
        f'<h2 style="color:#2c3e50;margin-bottom:4px;">⚡ ASIC Distress Monitor — Daily Report</h2>'
        f'<p style="color:#666;margin-top:0;">{ts}</p>'
        f'<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:6px;padding:12px 16px;margin-bottom:20px;">'
        f'<strong>{len(notices)}</strong> notice(s) across '
        f'<strong>{len(uc)}</strong> unique compan{"y" if len(uc)==1 else "ies"} | '
        f'🔴 {len(lq)} liquidation 🟠 {len(ad)} administration 🔵 {len(ot)} other</div>'
        f'{cards}'
        f'{search_section}'
        f'<hr style="border:none;border-top:1px solid #eee;margin:24px 0;">'
        f'<p style="font-size:11px;color:#999;">Source: <a href="{BASE_URL}" style="color:#999;">ASIC Published Notices</a><br>'
        f'Generated: {now_utc().strftime("%Y-%m-%d %H:%M UTC")}</p>'
        f'</body></html>'
    )


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(subject, html_body):
    ga = os.environ.get("GMAIL_ADDRESS","").strip()
    gp = os.environ.get("GMAIL_APP_PASSWORD","").strip()
    ne = os.environ.get("NOTIFY_EMAIL", ga).strip()
    if not ga or not gp:
        print("⚠️  Gmail credentials not set — skipping email"); return

    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, ga, ne
    msg.attach(MIMEText(html_body, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(ga, gp); s.sendmail(ga, [ne], msg.as_string())
        print(f"✉️  Email sent to {ne}")
    except smtplib.SMTPAuthenticationError as e:
        print(f"❌ Gmail auth failed: {e}\n   Use App Password from https://myaccount.google.com/apppasswords"); sys.exit(1)
    except Exception as e:
        print(f"❌ Email failed: {e}"); sys.exit(1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("ASIC Distress Monitor — Starting scrape (Playwright)")
    print(f"Time: {now_utc().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # Load previously seen notices
    seen = load_seen()
    print(f"[seen] {len(seen)} previously seen notices loaded")

    all_notices = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-AU",
        )
        page = context.new_page()

        # Warm up: hit homepage first to get WAF cookies established
        print("\n[init] Loading ASIC homepage to establish WAF session...")
        try:
            page.goto("https://publishednotices.asic.gov.au/", wait_until="load", timeout=30000)
            for i in range(8):
                page.wait_for_timeout(2000)
                content = page.content()
                if "AwsWafIntegration" not in content and len(content) > 3000:
                    print(f"[init] Homepage loaded after {(i+1)*2}s")
                    break
            else:
                print("[init] WARNING: Homepage may still be behind WAF")
        except Exception as e:
            print(f"[init] Homepage error (continuing): {e}")

        # Scrape listings
        for term in SEARCH_TERMS:
            try:
                notices = scrape_listing(page, term)
                print(f"  → {len(notices)} notices for '{term}'")
                all_notices.extend(notices)
            except Exception as e:
                print(f"  ✗ Error scraping '{term}': {e}")

        all_notices = deduplicate(all_notices)
        print(f"\n{len(all_notices)} unique notices total (all dates)")

        # Filter to recent (last 7 days to cast a wider net, then dedupe via seen)
        recent = [n for n in all_notices if is_recent(n)]
        print(f"{len(recent)} notices from last 7 days")

        # Filter out already-seen notices
        new_notices = [n for n in recent if notice_key(n) not in seen]
        print(f"{len(new_notices)} NEW notices (not previously sent)\n")

        # Fetch detail pages for new notices only
        if new_notices:
            print("Fetching detail pages...")
            for i, notice in enumerate(new_notices):
                if notice["view_link"]:
                    notice["detail"] = scrape_detail_page(page, notice["view_link"])
                    if i < len(new_notices) - 1:
                        time.sleep(DETAIL_DELAY)
                else:
                    notice["detail"] = {}
            print()

        browser.close()

    # Mark all recent notices as seen (even if already seen, refreshes timestamp)
    ts_now = now_utc().isoformat()
    for n in recent:
        seen[notice_key(n)] = ts_now
    save_seen(seen)

    # Send email
    ts = now_utc().strftime("%Y-%m-%d")
    subj = f"ASIC Solar/Renewables Monitor — {ts}"
    if new_notices:
        subj += f" — {len(new_notices)} NEW notice(s)"
    else:
        subj += " — no new notices"
    send_email(subj, build_email(new_notices))

    print("=" * 60)
    print("✅ Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
