import os, openai, random
from telegram import Bot
from datetime import datetime

openai.api_key = os.getenv("OPENAI_API_KEY")
bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))

def get_picks():
    matches = ["Liverpool vs Madrid", "Man Utd vs Chelsea", "Arsenal vs City", "Bayern vs Dortmund", "PSG vs Monaco"]
    bets = ["-1.5", "Over 2.5", "BTTS", "Over 3.5", "ML"]
    odds = [2.10, 1.95, 1.80, 2.25, 1.70]
    books = ["Bet365", "Bwin", "Bet365", "Bwin", "Bet365"]
    return [{"match": m, "bet": b, "odds": o, "book": k} for m,b,o,k in zip(matches, bets, odds, books)]

def gpt_reason(pick):
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"Why bet {pick['bet']} on {pick['match']}? 1 sentence."}],
            max_tokens=50
        )
        return resp.choices[0].message.content.strip()
    except:
        return "Strong edge."

def send():
    picks = get_picks()
    free = picks[:3]
    premium = picks[:5]

    msg_free = "**FREE PICKS** " + datetime.utcnow().strftime("%H:%M UTC") + "\n\n"
    for p in free:
        msg_free += f"• **{p['match']}** → {p['bet']} @ {p['odds']} ({p['book']})\n_{gpt_reason(p)}_\n\n"
    msg_free += "*18+ | Entertainment only*"
    bot.send_message(chat_id=os.getenv("FREE_CHANNEL"), text=msg_free, parse_mode="Markdown")

    msg_prem = "**PREMIUM PICKS** (Early)\n\n"
    for p in premium:
        msg_prem += f"• **{p['match']}** → {p['bet']} @ {p['odds']} ({p['book']})\n_{gpt_reason(p)}_\n\n"
    bot.send_message(chat_id=os.getenv("PREMIUM_CHANNEL"), text=msg_prem, parse_mode="Markdown")

if __name__ == "__main__":
    send()
