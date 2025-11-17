import os
from dotenv import load_dotenv
import requests
import yfinance as yf
from datetime import datetime
import re

load_dotenv()

NEWS_API_KEY = os.environ.get('NEWS_API_KEY')
HACKCLUB_API_KEY = os.environ.get('HACKCLUB_API_KEY')

LOG_FILE = 'sp500bot.log'

def log_event(event):
    with open(LOG_FILE, 'a') as f:
        f.write(f"{datetime.now().isoformat()} - {event}\n")

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
    body += ("\nHeadlines:\n" + '\n'.join(headlines) +
             "\n\nWARNING: You are trading with 20x leverage on Revolut. This is extremely risky. Always use a stop loss and never risk more than you can afford to lose.")
    print(f"\n=== EMAIL ALERT (MANUAL SEND) ===\nSubject: {subject}\n\n{body}\n")
    print("\n--- Implement your own send_email() logic if you want automated emails ---")

if __name__ == "__main__":
    main()
