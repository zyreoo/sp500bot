import os
from dotenv import load_dotenv
import requests
import smtplib
from email.mime.text import MIMEText
import openai
from datetime import datetime
import re

load_dotenv()

NEWS_API_KEY = os.environ.get('NEWS_API_KEY')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
EMAIL_FROM = os.environ.get('EMAIL_FROM')
EMAIL_TO = os.environ.get('EMAIL_TO')
EMAIL_PASSWORD = os.environ.get('EMAIL_PASSWORD')

LOG_FILE = 'sp500bot.log'

def log_event(event):
    with open(LOG_FILE, 'a') as f:
        f.write(f"{datetime.now().isoformat()} - {event}\n")

def fetch_sp500_price():
    import time
    try:
        url = 'https://query1.finance.yahoo.com/v7/finance/quote?symbols=^GSPC'
        resp = requests.get(url)
        if resp.status_code == 429:
            log_event('Yahoo Finance rate limit hit (429). Retrying after delay.')
            print('Yahoo Finance rate limit hit (429). Retrying after 5 seconds...')
            time.sleep(5)
            resp = requests.get(url)
        resp.raise_for_status()
        data = resp.json()
        price = data['quoteResponse']['result'][0]['regularMarketPrice']
        return price
    except Exception as e:
        log_event(f"Error fetching S&P 500 price: {e}")
        print(f"Error fetching S&P 500 price: {e}")
        return None

def fetch_sp500_news():
    url = (
        f'https://newsapi.org/v2/everything?'
        f'q=S%26P%20500 OR SP500 OR "S&P 500"&'
        f'language=en&sortBy=publishedAt&pageSize=5&apiKey={NEWS_API_KEY}'
    )
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        data = resp.json()
        headlines = [a['title'] for a in data.get('articles', [])]
        return headlines
    except Exception as e:
        log_event(f"Error fetching news: {e}")
        print(f"Error fetching news: {e}")
        return []

def interpret_news_with_ai(headlines, price=None):
    openai.api_key = OPENAI_API_KEY
    prompt = (
        "You are advising a trader who always uses 20x leverage and trades S&P 500 on Revolut. "
        "Your recommendations must be conservative and always include a stop loss and take profit, based on the strength of the news and current market conditions. "
        "Given these news headlines about the S&P 500, should the trader buy, sell, or hold? "
        "Reply with one of: BUY, SELL, HOLD. Then give a one-sentence reason. "
        "Then suggest a stop loss and take profit (as price levels or percentages). "
        f"Current S&P 500 price: {price}. "
        f"Headlines: {headlines}"
    )
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        return response['choices'][0]['message']['content']
    except openai.error.RateLimitError as e:
        log_event(f"OpenAI API rate limit (429): {e}")
        print(f"OpenAI API rate limit (429): {e}")
        return "Error: OpenAI API rate limit exceeded. Please try again later."
    except Exception as e:
        log_event(f"Error with OpenAI: {e}")
        print(f"Error with OpenAI: {e}")
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
    stop_loss_match = re.search(r'Stop Loss\s*[:\-]?\s*([\d\.]+)', ai_response, re.IGNORECASE)
    take_profit_match = re.search(r'Take Profit\s*[:\-]?\s*([\d\.]+)', ai_response, re.IGNORECASE)
    if stop_loss_match:
        stop_loss = stop_loss_match.group(1)
    if take_profit_match:
        take_profit = take_profit_match.group(1)
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

def send_email(subject, body):
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_FROM, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        log_event(f"Email sent: {subject}")
        print('Email sent!')
        return True
    except Exception as e:
        log_event(f"Error sending email: {e}")
        print(f"Error sending email: {e}")
        return False

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
    email_success = send_email(subject, body)
    if email_success:
        log_event('Email sent!')
    else:
        log_event('Email failed to send!')

if __name__ == '__main__':
    main()
