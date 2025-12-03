import os
import time
from datetime import datetime, timedelta, time as dt_time
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
import requests
import re
import mailtrap as mt
import yfinance as yf
from flask import Flask, jsonify


load_dotenv()

MAIL_TRAP_API_TOKEN = os.environ.get('MAIL_TRAP_API_TOKEN')
MAIL_TRAP_SENDER_EMAIL = os.environ.get('MAIL_TRAP_SENDER_EMAIL', 'hello@demomailtrap.co')
MAIL_TRAP_SENDER_NAME = os.environ.get('MAIL_TRAP_SENDER_NAME', 'SP500 Bot')
MAIL_TRAP_RECIPIENTS = os.environ.get('MAIL_TRAP_RECIPIENTS', 'simone.marton89@gmail.com')
NEWS_API_KEY = os.environ.get('NEWS_API_KEY')
HACKCLUB_API_KEY = os.environ.get('HACKCLUB_API_KEY')
LOG_FILE = 'sp500bot.log'
MARKET_TIMEZONE = os.environ.get('MARKET_TIMEZONE', 'America/New_York')
MARKET_ALERT_TIMES_STR = os.environ.get('MARKET_ALERT_TIMES', '09:30,15:30')
SCHEDULE_AT_MARKET_OPEN = os.environ.get('SCHEDULE_AT_MARKET_OPEN', 'false').lower() in {'1', 'true', 'yes', 'on'}
MARKET_ZONE = None
MARKET_ALERT_TIMES = None

def log_event(event):
    with open(LOG_FILE, 'a') as f:
        f.write(f"{datetime.now().isoformat()} - {event}\n")

def _init_market_zone():
    try:
        return ZoneInfo(MARKET_TIMEZONE)
    except Exception:
        message = f"Invalid MARKET_TIMEZONE '{MARKET_TIMEZONE}'. Falling back to UTC."
        log_event(message)
        print(message)
        return ZoneInfo("UTC")

MARKET_ZONE = _init_market_zone()

def _parse_alert_times(value):
    parsed_times = []
    for part in value.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            hour, minute = [int(token) for token in part.split(':', 1)]
            parsed_times.append(dt_time(hour=hour, minute=minute))
        except Exception:
            message = f"Invalid alert time '{part}'. Skipping."
            log_event(message)
            print(message)
    if not parsed_times:
        message = "No valid MARKET_ALERT_TIMES provided. Using defaults 09:30 and 15:30."
        log_event(message)
        print(message)
        parsed_times = [dt_time(hour=9, minute=30), dt_time(hour=15, minute=30)]
    return sorted(parsed_times)

MARKET_ALERT_TIMES = _parse_alert_times(MARKET_ALERT_TIMES_STR)

def send_email(subject, body):
    if not MAIL_TRAP_API_TOKEN:
        message = 'Missing MAIL_TRAP_API_TOKEN environment variable. Create a .env file or export it in the shell.'
        log_event(message)
        print(message)
        return False

    recipients = [addr.strip() for addr in MAIL_TRAP_RECIPIENTS.split(',') if addr.strip()]
    if not recipients:
        message = 'MAIL_TRAP_RECIPIENTS is empty. Configure at least one recipient email.'
        log_event(message)
        print(message)
        return False

    try:
        mail = mt.Mail(
            sender=mt.Address(email=MAIL_TRAP_SENDER_EMAIL, name=MAIL_TRAP_SENDER_NAME),
            to=[mt.Address(email=email) for email in recipients],
            subject=subject,
            text=body,
            category="SP500 Bot Alert",
        )
        client = mt.MailtrapClient(token=MAIL_TRAP_API_TOKEN)
        response = client.send(mail)
        log_event(f"Email sent successfully via Mailtrap: {response}")
        print("Email sent successfully!")
        return True
    except Exception as e:
        log_event(f"Error sending email: {e}")
        print(f"Error sending email: {e}")
        return False

def fetch_sp500_price():
    try:
        ticker = yf.Ticker("^GSPC")
        price = ticker.history(period="1d")["Close"].iloc[0]
        return float(price)
    except Exception as e:
        log_event(f"Error fetching S&P 500 price from Yahoo: {e}")
        print(f"Error fetching S&P 500 price from Yahoo: {e}")
        return None

def fetch_sp500_news():
    if not NEWS_API_KEY:
        log_event('Missing NEWS_API_KEY environment variable. Create a .env file or export it in the shell.')
        print('Missing NEWS_API_KEY. Set it in a .env file or export it in your shell.')
        return []
    url = 'https://newsapi.org/v2/everything'
    params = {
        'q': 'S&P 500 OR SP500 OR "S&P 500"',
        'language': 'en',
        'sortBy': 'publishedAt',
        'pageSize': 5,
    }
    try:
        headers = {"X-Api-Key": NEWS_API_KEY}
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        headlines = [a['title'] for a in data.get('articles', [])]
        return headlines
    except Exception as e:
        try:
            error_body = resp.text if 'resp' in locals() else ''
        except Exception:
            error_body = ''
        log_event(f"Error fetching news: {e} {error_body}")
        print(f"Error fetching news: {e}")
        return []

def interpret_news_with_ai(headlines, price=None):
    if not HACKCLUB_API_KEY:
        log_event('Missing HACKCLUB_API_KEY environment variable.')
        print('Missing HACKCLUB_API_KEY. Set it in your .env or export it.')
        return "Error: Missing HACKCLUB_API_KEY."
    prompt = (
        "You are advising a trader who always uses 20x leverage and trades S&P 500 on Revolut. "
        "Your recommendations must be conservative and always include a stop loss and take profit, based on the strength of the news and current market conditions. "
        "Given these news headlines about the S&P 500, should the trader buy, sell, or hold? "
        "Reply with one of: BUY, SELL, HOLD. Then give a one-sentence reason. "
        "Then suggest a stop loss and take profit (as price levels or percentages). "
        f"Current S&P 500 price: {price}. "
        f"Headlines: {headlines}"
    )
    url = "https://ai.hackclub.com/proxy/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {HACKCLUB_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "qwen/qwen3-32b",
        "messages": [{"role": "user", "content": prompt}]
    }
    try:
        resp = requests.post(url, headers=headers, json=data)
        resp.raise_for_status()
        response_json = resp.json()
        return response_json["choices"][0]["message"]["content"]
    except Exception as e:
        log_event(f"Error with HackClub AI: {e}")
        print(f"Error with HackClub AI: {e}")
        return "Error: Could not get AI interpretation."

def parse_ai_response(ai_response):
    action = 'HOLD'
    reason = ''
    stop_loss = None
    take_profit = None
    for word in ['BUY', 'SELL', 'HOLD']:
        if word in ai_response.upper():
            action = word
            break
    stop_loss_match = re.search(r'(Stop\s*Loss|stop\s*loss)[^\d\.%]*([\d\.,]+%?)', ai_response, re.IGNORECASE)
    take_profit_match = re.search(r'(Take\s*Profit|take\s*profit)[^\d\.%]*([\d\.,]+%?)', ai_response, re.IGNORECASE)
    if stop_loss_match:
        stop_loss = stop_loss_match.group(2).replace(',', '')
    if take_profit_match:
        take_profit = take_profit_match.group(2).replace(',', '')
    lines = ai_response.split('\n')
    for line in lines:
        if 'reason' in line.lower():
            reason = line.split(':', 1)[-1].strip()
            break
    if not reason and len(lines) > 1:
        reason = lines[1].strip()
    return action, reason, stop_loss, take_profit

def suggest_stoploss_takeprofit(price, action):
    if price is None:
        return (None, None)
    if action == 'BUY':
        stop_loss = round(price * 0.99, 2)
        take_profit = round(price * 1.02, 2)
    elif action == 'SELL':
        stop_loss = round(price * 1.01, 2)
        take_profit = round(price * 0.98, 2)
    else:
        stop_loss = None
        take_profit = None
    return (stop_loss, take_profit)

def next_alert_datetime(reference=None):
    if reference is None:
        reference = datetime.now(MARKET_ZONE)
    else:
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=MARKET_ZONE)
        else:
            reference = reference.astimezone(MARKET_ZONE)

    if reference.weekday() >= 5:
        next_date = _next_weekday_date(reference.date())
        return datetime.combine(next_date, MARKET_ALERT_TIMES[0], tzinfo=MARKET_ZONE)

    for alert_time in MARKET_ALERT_TIMES:
        candidate = datetime.combine(reference.date(), alert_time, tzinfo=MARKET_ZONE)
        if reference < candidate:
            return candidate

    next_date = _next_weekday_date(reference.date() + timedelta(days=1))
    return datetime.combine(next_date, MARKET_ALERT_TIMES[0], tzinfo=MARKET_ZONE)

def _next_weekday_date(date_value):
    next_date = date_value
    while next_date.weekday() >= 5:
        next_date += timedelta(days=1)
    return next_date

def get_trading_results():
    """Get trading results without sending email. Returns a dictionary with all results."""
    headlines = fetch_sp500_news()
    if not headlines:
        log_event('No news found.')
        return {
            'error': 'No news found.',
            'action': 'HOLD',
            'reason': 'No news available to analyze',
            'price': None,
            'stop_loss': None,
            'take_profit': None,
            'headlines': []
        }
    price = fetch_sp500_price()
    ai_result = interpret_news_with_ai(headlines, price)
    action, reason, stop_loss, take_profit = parse_ai_response(ai_result)
    
    return {
        'action': action,
        'reason': reason,
        'price': price,
        'stop_loss': stop_loss,
        'take_profit': take_profit,
        'headlines': headlines
    }

def main():
    headlines = fetch_sp500_news()
    if not headlines:
        print('No news found.')
        log_event('No news found.')
        return
    price = fetch_sp500_price()
    ai_result = interpret_news_with_ai(headlines, price)
    action, reason, stop_loss, take_profit = parse_ai_response(ai_result)
    subject = f'S&P 500 Trading Alert: {action}'
    body = (
        f"AI Trading Signal: {action}\n\n"
        f"Reason: {reason}\n\n"
        f"Current S&P 500 Price: {price}\n"
    )
    if stop_loss:
        body += f"Suggested Stop Loss: {stop_loss}\n"
    if take_profit:
        body += f"Suggested Take Profit: {take_profit}\n"
    body += ("\nHeadlines:\n" + '\n'.join(headlines))

    email_sent = send_email(subject, body)
    if email_sent:
        log_event('Email delivered successfully.')
    else:
        log_event('Email failed to send!')

def run_alert_scheduler():
    times_display = ', '.join(t.strftime('%H:%M') for t in MARKET_ALERT_TIMES)
    message = (
        f"Scheduler enabled. Alerts will run at {times_display} {MARKET_TIMEZONE} on weekdays."
    )
    log_event(message)
    print(message)
    while True:
        now = datetime.now(MARKET_ZONE)
        next_run = next_alert_datetime(now)
        wait_seconds = max(0, (next_run - now).total_seconds())
        minutes = wait_seconds / 60 if wait_seconds else 0
        print(f"Next alert scheduled for {next_run.isoformat()} ({minutes:.1f} minutes).")
        time.sleep(wait_seconds)
        try:
            main()
        except Exception as exc:
            log_event(f"Scheduled run failed: {exc}")
            print(f"Scheduled run failed: {exc}")
        # small delay to avoid tight loops immediately after execution
        time.sleep(1)


HTML_PAGE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>S&P 500 Trading Bot</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }

        .container {
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            max-width: 900px;
            width: 100%;
            padding: 40px;
        }


        h1 {
            color: #333;
            text-align: center;
            margin-bottom: 30px;
            font-size: 2em;
        }

        .button-container {
            text-align: center;
            margin-bottom: 30px;
        }

        #fetchButton {
            background: #333;
            color: white;
            border: none;
            padding: 12px 30px;
            font-size: 1em;
            border-radius: 4px;
            cursor: pointer;
            transition: background 0.2s ease;
            font-weight: 500;
        }

        #fetchButton:hover {
            background: #555;
        }

        #fetchButton:active {
            background: #222;
        }

        #fetchButton:disabled {
            background: #ccc;
            cursor: not-allowed;
        }

        .loading {
            text-align: center;
            color: #666;
            font-size: 1em;
            margin: 20px 0;
            display: none;
        }

        .spinner {
            border: 3px solid #f3f3f3;
            border-top: 3px solid #333;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .results {
            display: none;
            margin-top: 30px;
        }

        .results.show {
            display: block;
        }

        .result-card {
            background: #fafafa;
            border-radius: 4px;
            padding: 25px;
            margin-bottom: 20px;
            border: 1px solid #e0e0e0;
        }

        .result-card h2 {
            color: #333;
            margin-bottom: 15px;
            font-size: 1.5em;
        }

        .action {
            display: inline-block;
            padding: 8px 20px;
            border-radius: 20px;
            font-weight: bold;
            margin-bottom: 15px;
            font-size: 1.1em;
        }

        .action.BUY {
            background: #4a4a4a;
            color: white;
        }

        .action.SELL {
            background: #4a4a4a;
            color: white;
        }

        .action.HOLD {
            background: #4a4a4a;
            color: white;
        }

        .info-row {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #e0e0e0;
        }

        .info-row:last-child {
            border-bottom: none;
        }

        .info-label {
            font-weight: 600;
            color: #666;
        }

        .info-value {
            color: #333;
            font-size: 1.1em;
        }

        .price {
            font-size: 1.3em;
            font-weight: bold;
            color: #333;
        }

        .headlines-section {
            margin-top: 20px;
        }

        .headlines-section h3 {
            color: #333;
            margin-bottom: 15px;
            font-size: 1.3em;
        }

        .headline-item {
            background: white;
            padding: 12px 15px;
            margin-bottom: 10px;
            border-radius: 4px;
            border: 1px solid #e0e0e0;
            color: #000;
        }

        .headline-item:hover {
            background: #f5f5f5;
        }

        .error {
            background: #f5f5f5;
            color: #333;
            padding: 15px;
            border-radius: 4px;
            margin-top: 20px;
            border: 1px solid #e0e0e0;
        }

        .timestamp {
            text-align: center;
            color: #999;
            font-size: 0.9em;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📈 S&P 500 Trading Bot</h1>
        
        <div class="button-container">
            <button id="fetchButton" onclick="fetchResults()">Press to See the Result</button>
        </div>

        <div class="loading" id="loading">
            <div class="spinner"></div>
            <p>Fetching S&P 500 data and analyzing news...</p>
        </div>

        <div class="results" id="results">
            <div class="result-card">
                <h2>Trading Signal</h2>
                <div>
                    <span class="action" id="action">-</span>
                </div>
                
                <div class="info-row">
                    <span class="info-label">Reason:</span>
                    <span class="info-value" id="reason">-</span>
                </div>
                
                <div class="info-row">
                    <span class="info-label">Current S&P 500 Price:</span>
                    <span class="info-value price" id="price">-</span>
                </div>
                
                <div class="info-row">
                    <span class="info-label">Suggested Stop Loss:</span>
                    <span class="info-value" id="stopLoss">-</span>
                </div>
                
                <div class="info-row">
                    <span class="info-label">Suggested Take Profit:</span>
                    <span class="info-value" id="takeProfit">-</span>
                </div>
            </div>

            <div class="result-card headlines-section">
                <h3>📰 Recent News Headlines</h3>
                <div id="headlines"></div>
            </div>

            <div class="timestamp" id="timestamp"></div>
        </div>

        <div class="error" id="error" style="display: none;"></div>
    </div>

    <script>
        async function fetchResults() {
            const button = document.getElementById('fetchButton');
            const loading = document.getElementById('loading');
            const results = document.getElementById('results');
            const error = document.getElementById('error');
            
            // Reset UI
            button.disabled = true;
            loading.style.display = 'block';
            results.classList.remove('show');
            error.style.display = 'none';
            
            try {
                const apiUrl = window.location.origin + '/api/get-results';
                const response = await fetch(apiUrl);
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                const data = await response.json();
                
                // Display results
                document.getElementById('action').textContent = data.action || 'HOLD';
                document.getElementById('action').className = 'action ' + (data.action || 'HOLD');
                document.getElementById('reason').textContent = data.reason || 'No reason provided';
                document.getElementById('price').textContent = data.price ? `$${data.price.toFixed(2)}` : 'N/A';
                document.getElementById('stopLoss').textContent = data.stop_loss || 'N/A';
                document.getElementById('takeProfit').textContent = data.take_profit || 'N/A';
                
                // Display headlines
                const headlinesDiv = document.getElementById('headlines');
                if (data.headlines && data.headlines.length > 0) {
                    headlinesDiv.innerHTML = data.headlines.map(headline => 
                        `<div class="headline-item">${headline}</div>`
                    ).join('');
                } else {
                    headlinesDiv.innerHTML = '<div class="headline-item">No headlines available</div>';
                }
                
                // Display timestamp
                document.getElementById('timestamp').textContent = 
                    `Last updated: ${new Date().toLocaleString()}`;
                
                results.classList.add('show');
                
            } catch (err) {
                error.textContent = `Error: ${err.message}`;
                error.style.display = 'block';
            } finally {
                button.disabled = false;
                loading.style.display = 'none';
            }
        }
    </script>
</body>
</html>'''

# Flask app setup
app = Flask(__name__)

@app.route('/')
def index():
    return HTML_PAGE

@app.route('/api/get-results')
def api_get_results():
    try:
        results = get_trading_results()
        return jsonify(results)
    except Exception as e:
        log_event(f"Error in API endpoint: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    import sys
    

    if len(sys.argv) > 1 and sys.argv[1] == '--web':
        port = int(os.environ.get('PORT', 5001))
        print(f"Starting web server on http://0.0.0.0:{port}")
        app.run(host='0.0.0.0', port=port, debug=False)
    elif SCHEDULE_AT_MARKET_OPEN:
        run_alert_scheduler()
    else:
        main()
