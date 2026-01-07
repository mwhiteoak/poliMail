import requests
import os
import datetime

# === CONFIGURATION ===
api_key = os.environ['XAI_API_KEY']
url = "https://api.x.ai/v1/chat/completions"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

# === DATE HANDLING ===
today = datetime.date.today()
date_str = today.strftime('%A, %B %d, %Y')  # e.g., Tuesday, January 07, 2026

yesterday = today - datetime.timedelta(days=1)
date_context = f"covering {yesterday.strftime('%B %d, %Y')} to {today.strftime('%B %d, %Y')}"

# === API REQUEST ===
data = {
    "model": "grok-4-0709",
    "messages": [
        {
            "role": "user",
            "content": f"""Provide a concise, professional daily briefing on Australian political and economic developments {date_context}.

Target audience: Property fund executives and board members managing retail and commercial portfolios.

Prioritise actionable implications for interest rates, consumer spending, office/retail demand, construction, migration, foreign investment, valuations, and fund flows.

Structure exactly as follows and output in clean HTML (no markdown):

<h2>1. Key Takeaways</h2>
<ul>
  <li>Start each with the direct property market implication → then the triggering event. Include 1 relevant source link if major.</li>
  <!-- 4–6 items total -->
</ul>

<h2>2. Australian Political News & Updates</h2>
<ul>
  <li>4–6 bullets on top domestic developments</li>
  <li>If a major poll shifted/released: add <strong>Polling Snapshot:</strong> [details]</li>
  <li>First mention of key people: (party; role; key stance; perception) in plain text</li>
  <li>Include 1–2 source links per significant item: <a href="URL">Source</a></li>
</ul>

<h2>3. International Matters Impacting Australia</h2>
<ul>
  <li>2–4 relevant global items with property/trade implications and links where possible</li>
</ul>

<h2>4. Property Sector Impacts</h2>
<ul>
  <li>Concise bullets on retail, office, industrial, valuations, cap rates, debt, REIT sentiment</li>
</ul>

<h2>5. Outlook</h2>
<ul>
  <li>Next 24–48 hours</li>
  <li><strong>Key Dates This Week:</strong> RBA speeches, CPI/jobs data, parliament, budget/infrastructure announcements</li>
</ul>

Keep total under 650 words. Use reliable sources and include clickable links (e.g., <a href="https://www.afr.com/...">AFR</a>, <a href="https://www.abc.net.au/...">ABC</a>).

Professional, neutral tone.

Example link usage:
<li>Housing supply boost expected → Federal government commits $2.5bn to states <a href="https://www.afr.com/politics/federal/new-housing-fund-20260107">AFR</a></li>

Example backgrounds:
- Anthony Albanese (Prime Minister, Labor Party; priorities housing supply and cost-of-living relief; under pressure on inflation delivery and security issues)
- Peter Dutton (Opposition Leader, Liberal Party; pushes nuclear energy, tax cuts, strong borders; leading in most 2026 polls)
- Jim Chalmers (Treasurer, Labor Party; focused on budget repair and responsible spending; widely respected for economic stewardship)
"""
        }
    ],
    "temperature": 0.4,
    "max_tokens": 2400
}

# === EXECUTE REQUEST ===
response = requests.post(url, headers=headers, json=data)

# === FULL HTML EMAIL OUTPUT (NO FOOTER) ===
html_header = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 20px auto; }}
    h1 {{ text-align: center; color: #1a3d7c; margin-bottom: 5px; }}
    h2 {{ color: #2c5282; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; }}
    ul {{ padding-left: 20px; }}
    li {{ margin-bottom: 10px; }}
    a {{ color: #0066cc; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <h1>DAILY POLITICAL BRIEFING – PROPERTY FUND INSIGHTS</h1>
  <h1>{date_str}</h1>
  <hr style="border: 1px solid #e2e8f0; margin: 30px 0;">
"""

print(html_header)

if response.status_code == 200:
    summary_html = response.json()['choices'][0]['message']['content'].strip()
    print(summary_html)
else:
    print("<p><strong>⚠️ ERROR: Unable to generate briefing today.</strong></p>")
    print(f"<p>API Status: {response.status_code}</p>")
    print(f"<p>{response.text}</p>")

print("</body></html>")
