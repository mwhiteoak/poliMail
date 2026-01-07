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
    "model": "grok-4-0709",  # Use latest Grok 4 model
    "messages": [
        {
            "role": "user",
            "content": f"""Provide a professional daily briefing on key developments in Australian domestic politics and international matters impacting Australia {date_context}.

Target audience: Executives and board members at a property fund managing retail and commercial real estate portfolios.

Focus on actionable insights linking politics and economy to the property sector, including:
- Interest rates and RBA signals
- Consumer confidence and retail spending
- Office and retail vacancy/leasing trends
- Construction costs, infrastructure policy, housing supply
- Migration levels, foreign investment rules
- Investor sentiment, cap rates, fund flows

Structure exactly as follows:

1. **Key Takeaways** (4–7 bullets: most critical event + direct property sector implication)

2. **Australian Domestic Politics**
   - Bullet-point major developments
   - On first mention of a significant person, add brief background in brackets:
     (party; current/recent role; key stances relevant to economy/property; executive/public perception)

3. **International Matters Impacting Australia**
   - Bullet-point developments relevant to trade, energy, security, or global markets

4. **Property Sector Impacts**
   - Expanded bullets on specific risks/opportunities for:
     • Retail centres (foot traffic, anchor tenants, vacancies)
     • Commercial offices (hybrid work, demand, yields)
     • Industrial/logistics assets
     • Valuations, cap rates, debt costs, investor flows

5. **Outlook**
   - What to watch in next 24–48 hours
   - Longer-term risks/opportunities for property funds

Keep total under 700 words. Use balanced, reliable sources (ABC, AFR, The Guardian, The Australian, Reuters, Sky News Australia). Maintain factual, neutral, professional tone.

Example backgrounds:
- Anthony Albanese (Prime Minister, Labor Party; focuses on housing supply, cost-of-living relief, renewable energy; approval under pressure due to inflation and security concerns)
- Sussan Ley (Deputy Opposition Leader, Liberal Party; advocates lower taxes, fiscal discipline, pro-business reform; seen as experienced and steady)
"""
        }
    ],
    "temperature": 0.4,
    "max_tokens": 2000
}

# === EXECUTE REQUEST ===
response = requests.post(url, headers=headers, json=data)

# === OUTPUT WITH PROMINENT DATESTAMP ===
print(f"══════════════════════════════════════════════════════════")
print(f"     DAILY POLITICAL BRIEFING – PROPERTY FUND INSIGHTS")
print(f"                   {date_str}")
print(f"══════════════════════════════════════════════════════════\n")

if response.status_code == 200:
    summary = response.json()['choices'][0]['message']['content'].strip()
    print(summary)
else:
    print("⚠️  ERROR: Unable to generate briefing")
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
