import requests
import os
import datetime
import urllib.parse  # For URL encoding the prompt

# === CONFIGURATION ===
api_key = os.environ['XAI_API_KEY']
url = "https://api.x.ai/v1/chat/completions"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

# === DATE HANDLING ===
today = datetime.date.today()
date_str = today.strftime('%A, %B %d, %Y')

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

Structure exactly as follows and output in clean HTML (no markdown, NO <a href> links except as specified below):

<h2>1. Key Takeaways</h2>
<ul>
  <li>4–6 bullets: Start each with the direct property market implication → then the event</li>
</ul>

<h2>2. Australian Political News & Updates</h2>
<ul>
  <li>4–6 bullets on top domestic developments</li>
  <li>If major poll shifted/released: <strong>Polling Snapshot:</strong> [details]</li>
  <li>First mention of key people: (party; role; key stance; perception)</li>
</ul>

<h2>3. International Matters Impacting Australia</h2>
<ul>
  <li>2–4 relevant global items with property/trade implications</li>
</ul>

<h2>4. Property Sector Impacts</h2>
<ul>
  <li>Concise bullets: retail centres, commercial offices, industrial, valuations/cap rates/debt/REIT sentiment</li>
</ul>

<h2>5. Outlook</h2>
<ul>
  <li>Next 24–48 hours</li>
  <li><strong>Key Dates This Week:</strong> RBA speeches, CPI/jobs data, parliament, budget/infrastructure</li>
</ul>

<h2>For Latest Articles & Sources</h2>
<p><strong>Click here to open Grok and get today's top news articles with links:</strong></p>
<p><a href="https://grok.com/?query=PUT_ENCODED_PROMPT_HERE">→ Launch Grok: Search articles on today's key topics</a></p>
<p>(The prompt is prefilled – just hit Enter in Grok to run it)</p>

At the end, list the 3–5 most important topics from today's briefing in this exact format for the link:
TOPICS: topic one, topic two, topic three, topic four

Keep total under 650 words. Professional, neutral tone.

Example backgrounds:
- Anthony Albanese (Prime Minister, Labor Party; priorities housing supply and cost-of-living relief; under pressure on inflation and security)
- Peter Dutton (Opposition Leader, Liberal Party; pushes nuclear energy, tax cuts, strong borders; leading in most 2026 polls)
- Jim Chalmers (Treasurer, Labor Party; focused on budget repair; widely respected for economic stewardship)
"""
        }
    ],
    "temperature": 0.4,
    "max_tokens": 2400
}

# === EXECUTE REQUEST ===
response = requests.post(url, headers=headers, json=data)

# === HTML OUTPUT ===
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
    a {{ color: #0066cc; font-weight: bold; text-decoration: underline; }}
    p a {{ font-size: 1.1em; }}
  </style>
</head>
<body>
  <h1>DAILY NEWS UPDATE</h1>
  <h1>{date_str}</h1>
  <hr style="border: 1px solid #e2e8f0; margin: 30px 0;">
"""

print(html_header)

if response.status_code == 200:
    summary_html = response.json()['choices'][0]['message']['content'].strip()

    # Extract the topics line for the clickable link
    topics_line = None
    for line in summary_html.split('\n'):
        if line.strip().startswith('TOPICS:'):
            topics_line = line.strip()[8:].strip()  # Remove "TOPICS: "
            break

    if topics_line:
        prompt = f"What are the top news articles from the last 24 hours on: {topics_line}?"
        encoded_prompt = urllib.parse.quote(prompt)
        grok_link = f"https://grok.com/?query={encoded_prompt}"

        # Replace the placeholder in the HTML
        summary_html = summary_html.replace("PUT_ENCODED_PROMPT_HERE", encoded_prompt)
        summary_html = summary_html.replace("https://grok.com/?query=PUT_ENCODED_PROMPT_HERE", grok_link)

    print(summary_html)
else:
    print("<p><strong>⚠️ ERROR: Unable to generate briefing today.</strong></p>")
    print(f"<p>API Status: {response.status_code}</p>")

print("</body></html>")
