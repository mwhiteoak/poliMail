import requests
import os
import datetime
import urllib.parse

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
date_context = f"covering developments from {yesterday.strftime('%B %d, %Y')} through today ({today.strftime('%B %d, %Y')})"

tomorrow = today + datetime.timedelta(days=1)
day_after = today + datetime.timedelta(days=2)
next_48h_context = f"major scheduled events, announcements, meetings, data releases or developments that markets, policymakers and investors worldwide/Australia are closely monitoring between {today.strftime('%B %d')} and {day_after.strftime('%B %d, %Y')} inclusive"

# === API REQUEST ===
data = {
    "model": "grok-4-0709",
    "messages": [
        {
            "role": "user",
            "content": f"""Provide a concise, professional daily briefing on Australian political and economic developments {date_context}.

Target audience: Property fund executives and board members managing retail and commercial portfolios.

Prioritise actionable implications for interest rates, consumer spending, office/retail demand, construction, migration, foreign investment, valuations, and fund flows.

Structure exactly as follows and output in clean HTML (no markdown, NO <a href> links except as specified):

<h2>1. Key Takeaways</h2>
<ul>
  <li>4–6 bullets: Start each with the direct property market implication → then the event/news</li>
</ul>

<h2>2. Australian Political News & Updates</h2>
<ul>
  <li>4–6 bullets on the most important domestic developments</li>
  <li>If major poll shifted/released: <strong>Polling Snapshot:</strong> [brief details]</li>
</ul>

<h2>3. International Matters Impacting Australia</h2>
<ul>
  <li>2–4 most relevant global items with clear property, trade, investment or macro implications for Australia</li>
</ul>

<h2>4. Property Sector Impacts</h2>
<ul>
  <li>Concise bullets covering retail centres, commercial offices, industrial/logistics, valuations/cap rates/debt costs, REIT sentiment/fund flows</li>
</ul>

<h2>5. Outlook – Next 48 Hours</h2>
<ul>
  <li>Focus on major scheduled events, data releases, political meetings, RBA commentary, international developments or announcements that global/Australian markets are watching closely over the next 48 hours ({next_48h_context})</li>
  <li><strong>Key Dates This Week:</strong> list important upcoming RBA speeches, economic data (CPI, jobs, retail sales etc.), parliament sitting days, major infrastructure/budget decisions</li>
</ul>

<h2>For Latest Articles & Sources</h2>
<p><strong>Click here to open Grok and get today's top news articles with links:</strong></p>
<p><a href="https://grok.com/?query=PUT_ENCODED_PROMPT_HERE">→ Launch Grok: Search articles on today's key topics</a></p>
<p>(The prompt is prefilled – just hit Enter in Grok to run it)</p>

<h2>Key People – Quick Reference</h2>
<ul>
  <li>List 3–6 most important people mentioned above with brief neutral background: Name (Party; Role; Key current priorities/stances; General market/political perception)</li>
  <li>Example format: Anthony Albanese (Labor; Prime Minister; focused on housing supply, cost-of-living, energy transition; under ongoing pressure on inflation and cost metrics)</li>
</ul>

At the very end, output this exact line for the link (after all HTML):
TOPICS: topic one, topic two, topic three, topic four, topic five

Keep total briefing content (excluding HTML tags) comfortably under 1000 words, ideally 550–750 words. Professional, neutral, fact-focused tone.

Current date context for reference: today is {today.strftime('%Y-%m-%d')}.
"""
        }
    ],
    "temperature": 0.35,
    "max_tokens": 2800
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
    h2 {{ color: #2c5282; border-bottom: 2px solid #e2e8f0; padding-bottom: 8px; margin-top: 40px; }}
    ul {{ padding-left: 20px; }}
    li {{ margin-bottom: 10px; }}
    a {{ color: #0066cc; font-weight: bold; text-decoration: underline; }}
    p a {{ font-size: 1.1em; }}
    .people-section {{ margin-top: 40px; border-top: 1px solid #ccc; padding-top: 20px; }}
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

    # Extract TOPICS line
    topics_line = None
    lines = summary_html.split('\n')
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('TOPICS:'):
            topics_line = stripped[8:].strip()  # remove "TOPICS: "
            # Remove the TOPICS line from HTML output (it's metadata)
            summary_html = '\n'.join([l for l in lines if not l.strip().startswith('TOPICS:')])
            break

    if topics_line:
        prompt = f"What are the top news articles from the last 24–36 hours on: {topics_line}?"
        encoded_prompt = urllib.parse.quote(prompt)
        grok_link = f"https://grok.com/?query={encoded_prompt}"

        summary_html = summary_html.replace("PUT_ENCODED_PROMPT_HERE", encoded_prompt)
        summary_html = summary_html.replace("https://grok.com/?query=PUT_ENCODED_PROMPT_HERE", grok_link)

    print(summary_html)
else:
    print("<p><strong>⚠️ ERROR: Unable to generate briefing today.</strong></p>")
    print(f"<p>API Status: {response.status_code}</p>")

print("</body></html>")
