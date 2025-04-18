
import datetime
import time
import requests
import pytz
import json
import os
import csv
import matplotlib.pyplot as plt

API_KEY = 'sandbox-key'  # Use your sandbox API key if available
BASE_URL = 'https://demo.kalshi.com/trade-api/v2'
HEADERS = {'Authorization': f'Bearer {API_KEY}'}
MARKET_SUFFIX = "INX"
MIN_PROBABILITY = 0.94
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/your_webhook_url"
DRY_RUN = True

BANKROLL_FILE = "bankroll.json"
TRADE_LOG_FILE = "trade_log.json"
TRADE_CSV_FILE = "trades.csv"
BANKROLL_CSV_FILE = "bankroll_history.csv"

def load_bankroll():
    if os.path.exists(BANKROLL_FILE):
        with open(BANKROLL_FILE, 'r') as f:
            return json.load(f)['bankroll']
    return 125.0

def save_bankroll(bankroll):
    with open(BANKROLL_FILE, 'w') as f:
        json.dump({'bankroll': bankroll}, f)

def log_bankroll_history(bankroll):
    now = datetime.datetime.now().isoformat()
    write_csv_row(BANKROLL_CSV_FILE, [now, bankroll], ["timestamp", "bankroll"])

def write_csv_row(file_path, row, headers):
    write_header = not os.path.exists(file_path)
    with open(file_path, 'a', newline='') as csvfile:
        writer = csv.writer(csvfile)
        if write_header:
            writer.writerow(headers)
        writer.writerow(row)

def load_trade_log():
    if os.path.exists(TRADE_LOG_FILE):
        with open(TRADE_LOG_FILE, 'r') as f:
            return json.load(f)
    return []

def save_trade_log(trades):
    with open(TRADE_LOG_FILE, 'w') as f:
        json.dump(trades, f, indent=2)

def fetch_sp500_markets():
    response = requests.get(f'{BASE_URL}/markets?event_ticker_suffix={MARKET_SUFFIX}', headers=HEADERS)
    return response.json().get('markets', [])

def get_market_info(ticker):
    response = requests.get(f'{BASE_URL}/markets/{ticker}', headers=HEADERS)
    return response.json()

def place_trade(market, side, quantity):
    if DRY_RUN:
        return True
    order_data = {
        'ticker': market,
        'side': side,
        'type': 'market',
        'quantity': quantity
    }
    response = requests.post(f'{BASE_URL}/orders', headers=HEADERS, json=order_data)
    return response.status_code == 200

def notify_discord(message, image_path=None):
    if not DISCORD_WEBHOOK_URL:
        return
    if image_path:
        with open(image_path, 'rb') as f:
            files = {'file': (os.path.basename(image_path), f)}
            payload = {'content': message}
            requests.post(DISCORD_WEBHOOK_URL, data=payload, files=files)
    else:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message})

def generate_bankroll_graph():
    timestamps = []
    values = []
    if not os.path.exists(BANKROLL_CSV_FILE):
        return
    with open(BANKROLL_CSV_FILE, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            timestamps.append(datetime.datetime.fromisoformat(row['timestamp']))
            values.append(float(row['bankroll']))
    plt.figure(figsize=(10, 5))
    plt.plot(timestamps, values, marker='o')
    plt.title("Bankroll Over Time")
    plt.xlabel("Time")
    plt.ylabel("Bankroll ($)")
    plt.grid(True)
    plt.tight_layout()
    plt.savefig("bankroll_graph.png")
    plt.close()

def run_trading_bot():
    global bankroll
    pacific = pytz.timezone('US/Pacific')
    now = datetime.datetime.now(pacific)

    unresolved_trades = load_trade_log()
    new_log = []
    for trade in unresolved_trades:
        market_info = get_market_info(trade['market'])
        if market_info['status'] == 'resolved':
            winning_side = market_info['settled_side']
            payout = trade['quantity'] if trade['side'] == winning_side else 0
            bankroll += payout
            result = "WIN" if payout > 0 else "LOSS"
            notify_discord(f"Resolved: {trade['side'].upper()} on {trade['market']} - {result} - New bankroll: ${bankroll:.2f}")
            log_bankroll_history(bankroll)
            write_csv_row(TRADE_CSV_FILE, [
                datetime.datetime.now().isoformat(),
                trade['market'],
                trade['side'],
                trade['price'],
                trade['quantity'],
                result,
                bankroll
            ], ["timestamp", "market", "side", "price", "quantity", "result", "bankroll"])
        else:
            new_log.append(trade)

    save_trade_log(new_log)
    save_bankroll(bankroll)

    markets = fetch_sp500_markets()
    good_trades = []
    for market in markets:
        for side in ['yes', 'no']:
            price = market.get(f"{side}_price")
            if price and price / 100 >= MIN_PROBABILITY:
                good_trades.append({
                    'market': market['ticker'],
                    'side': side,
                    'price': price / 100
                })

    if not good_trades:
        notify_discord("No qualifying trades found today.")
        return

    trade = sorted(good_trades, key=lambda x: -x['price'])[0]
    cost_per_contract = 1 - trade['price'] if trade['side'] == 'yes' else trade['price']
    max_contracts = int(bankroll // cost_per_contract)

    if max_contracts == 0:
        notify_discord("Not enough bankroll for a trade.")
        return

    if place_trade(trade['market'], trade['side'], max_contracts):
        bankroll -= cost_per_contract * max_contracts
        save_bankroll(bankroll)
        log_bankroll_history(bankroll)
        dry_note = "(DRY RUN)" if DRY_RUN else ""
        notify_discord(f"{dry_note} Placed trade: {trade['side'].upper()} on {trade['market']} @ {trade['price']*100:.1f}% for {max_contracts} contracts.
New bankroll: ${bankroll:.2f}")

        trade_log = load_trade_log()
        trade_log.append({
            'market': trade['market'],
            'side': trade['side'],
            'price': trade['price'],
            'quantity': max_contracts
        })
        save_trade_log(trade_log)
        write_csv_row(TRADE_CSV_FILE, [
            now.isoformat(),
            trade['market'],
            trade['side'],
            trade['price'],
            max_contracts,
            "PENDING",
            bankroll
        ], ["timestamp", "market", "side", "price", "quantity", "result", "bankroll"])

    generate_bankroll_graph()
    notify_discord("📈 Current bankroll trend:", image_path="bankroll_graph.png")

if __name__ == '__main__':
    bankroll = load_bankroll()
    run_trading_bot()
