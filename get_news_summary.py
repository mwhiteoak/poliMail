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

Prioritise actionable implications for interest rates, consumer spending, office/retail demand, construction activity, migration, foreign investment, valuations, and fund flows.

Structure exactly as follows:

1. **Key Takeaways** (4–6 bullets only)
   • Start each bullet with the direct implication for property markets/funds
   • Then briefly state the triggering political or economic event

2. **Australian Political News & Updates**
   • 4–6 bullet points on the top domestic developments in last 24 hours
   • Include leadership statements, policy moves, parliamentary activity, scandals, state-federal tensions
   • If any major poll shifted or was released, add one line: "Polling Snapshot: [e.g., Newspoll: Labor 52–48 TPP (+1 since last)]"
   • First mention of key people: brief background in brackets (party; role; key economic/housing stance; current perception)

3. **International Matters Impacting Australia**
   • 2–4 bullets on relevant global developments (trade, energy prices, security, migration flows, US/China relations)

4. **Property Sector Impacts**
   • Concise bullets covering:
     • Retail centres (foot traffic, vacancies, anchor health)
     • Commercial offices (leasing, hybrid work trends, yields)
     • Industrial/logistics demand
     • Valuations, cap rates, debt costs, investor/reit sentiment

5. **Outlook**
   • Next 24–48 hours: key speeches, data releases, votes
   • Key Dates This Week: list any RBA announcements, CPI/jobs data, parliamentary sittings, budget updates, major state infrastructure decisions

Keep total briefing under 650 words. Be concise and implication-focused. Use reliable sources: ABC, AFR, The Australian, Guardian Australia, Sky News, Reuters.

Professional, neutral tone.

Example backgrounds:
- Anthony Albanese (Prime Minister, Labor Party; priorities housing supply and cost-of-living relief; under pressure on inflation delivery and security issues)
- Peter Dutton (Opposition Leader, Liberal Party; pushes nuclear energy, tax cuts, strong borders; leading in most 2026 polls)
- Jim Chalmers (Treasurer, Labor Party; focused on budget repair and responsible spending; widely respected for economic stewardship)
- Sussan Ley (Deputy Opposition Leader, Liberal Party; advocates pro-business reform and fiscal discipline; seen as pragmatic)
"""
        }
    ],
    "temperature": 0.4,
    "max_tokens": 2400
}

# === EXECUTE REQUEST ===
response = requests.post(url, headers=headers, json=data)

# === HEADER ===
print(f"══════════════════════════════════════════════════════════")
print(f"     DAILY POLITICAL BRIEFING – PROPERTY FUND INSIGHTS")
print(f"                   {date_str}")
print(f"══════════════════════════════════════════════════════════\n")

if response.status_code == 200:
    summary = response.json()['choices'][0]['message']['content'].strip()
    print(summary)
    
    # === PERSISTENT WATCH LIST FOOTER ===
    print("\n" + "─" * 50)
    print("PERSISTENT WATCH LIST (Ongoing Structural Issues)")
    print("• RBA cash rate path & peak rate expectations")
    print("• Negative gearing / capital gains tax reform risk")
    print("• Net overseas migration levels vs housing supply response")
    print("• Office-to-residential conversion policy progress")
    print("• Foreign investment (FIRB) rules for commercial property")
    print("• Major retail anchor health (Coles, Woolworths, Wesfarmers impact)")
    print("• Infrastructure pipeline delays or accelerations (federal/state)")
    print("─" * 50)

else:
    print("⚠️  ERROR: Unable to generate briefing")
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")
