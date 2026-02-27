name: ASIC Solar/Renewables Distress Monitor

on:
  schedule:
    # Runs at 8:00 AM AEST (10:00 PM UTC previous day)
    - cron: '0 22 * * *'
  workflow_dispatch: # Allow manual trigger for testing

jobs:
  check-notices:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install requests beautifulsoup4

      - name: Verify secrets are set
        env:
          GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          NOTIFY_EMAIL: ${{ secrets.NOTIFY_EMAIL }}
        run: |
          echo "Checking secrets..."
          if [ -z "$GMAIL_ADDRESS" ]; then
            echo "❌ GMAIL_ADDRESS secret is NOT set"
            exit 1
          else
            echo "✅ GMAIL_ADDRESS is set (${#GMAIL_ADDRESS} chars)"
          fi
          if [ -z "$GMAIL_APP_PASSWORD" ]; then
            echo "❌ GMAIL_APP_PASSWORD secret is NOT set"
            exit 1
          else
            echo "✅ GMAIL_APP_PASSWORD is set (${#GMAIL_APP_PASSWORD} chars)"
          fi
          if [ -z "$NOTIFY_EMAIL" ]; then
            echo "⚠️  NOTIFY_EMAIL not set — will default to GMAIL_ADDRESS"
          else
            echo "✅ NOTIFY_EMAIL is set (${#NOTIFY_EMAIL} chars)"
          fi

      - name: Scrape ASIC and send email
        env:
          GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }}
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          NOTIFY_EMAIL: ${{ secrets.NOTIFY_EMAIL }}
          PYTHONUNBUFFERED: "1"
        run: python scrape_asic.py
