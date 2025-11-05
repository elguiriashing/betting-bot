import os
import openai
import asyncio
import requests
from datetime import datetime, timezone
from telegram import Bot

# Config
openai.api_key = os.getenv("OPENAI_API_KEY")
bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# === SCRAPER REAL: TheOddsAPI (EPL + LaLiga + Bundesliga + Ligue 1) ===
def get_picks():
    if not ODDS_API_KEY:
        print("ODDS_API_KEY no configurada → usando mock")
        return get_mock_picks()

    sports = [
        "soccer_epl",           # Premier League
        "soccer_spain_la_liga", # La Liga
        "soccer_germany_bundesliga",
        "soccer_france_ligue_one"
    ]
    all_picks = []

    for sport in sports:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            'apiKey': ODDS_API_KEY,
            'regions': 'eu',
            'markets': 'h2h,totals,asian_handicap',
            'oddsFormat': 'decimal',
            'bookmakers': 'bet365,bwin,unibet'
        }
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            for game in data:
                if game.get('commence_time'):
                    home, away = game['home_team'], game['away_team']
                    match_name = f"{home} vs {away}"

                    for site in game.get('bookmakers', []):
                        if site['key'] not in ['bet365', 'bwin', 'unibet']:
                            continue
                        for market in site.get('markets', []):
                            if market['key'] == 'h2h':
                                for outcome in market['outcomes']:
                                    if outcome['name'] == home:
                                        all_picks.append({
                                            "match": match_name,
                                            "bet": "ML",
                                            "odds": outcome['price'],
                                            "book": site['title']
                                        })
                            elif market['key'] == 'totals' and 'Over 2.5' in [o['name'] for o in market['outcomes']]:
                                for outcome in market['outcomes']:
                                    if outcome['name'] == 'Over 2.5':
                                        all_picks.append({
                                            "match": match_name,
                                            "bet": "Over 2.5",
                                            "odds": outcome['price'],
                                            "book": site['title']
                                        })
                            elif market['key'] == 'asian_handicap':
                                for outcome in market['outcomes']:
                                    if '-1.5' in outcome['name']:
                                        all_picks.append({
                                            "match": match_name,
                                            "bet": "-1.5",
                                            "odds": outcome['price'],
                                            "book": site['title']
                                        })
        except Exception as e:
            print(f"Error en {sport}: {e}")

    # Filtrar duplicados y tomar los 5 mejores (odds > 1.7)
    unique = {}
    for p in all_picks:
        key = f"{p['match']}_{p['bet']}_{p['book']}"
        if key not in unique and p['odds'] >= 1.70:
            unique[key] = p
    filtered = list(unique.values())[:5]

    return filtered if len(filtered) >= 3 else get_mock_picks()

# === FALLBACK MOCK (si API falla o no hay datos) ===
def get_mock_picks():
    return [
        {"match": "Real Madrid vs Barcelona", "bet": "Over 2.5", "odds": 1.85, "book": "Bet365"},
        {"match": "Atlético vs Sevilla", "bet": "-0.5", "odds": 1.78, "book": "Bwin"},
        {"match": "Valencia vs Villarreal", "bet": "BTTS", "odds": 1.92, "book": "Bet365"},
        {"match": "Betis vs Granada", "bet": "ML", "odds": 1.70, "book": "Bwin"},
        {"match": "Celta vs Cádiz", "bet": "Under 3.5", "odds": 1.65, "book": "Bet365"}
    ]

# === GPT EN ESPAÑOL ===
def gpt_reason(pick):
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Explica en 1 frase clara y profesional por qué apostar {pick['bet']} en {pick['match']}. En español."
            }],
            max_tokens=70
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"GPT Error: {e}")
        return "Ventaja estadística clara."

# === ENVÍO DE PICKS ===
async def send_picks():
    picks = get_picks()
    free = picks[:3]
    premium = picks[:5]

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")

    # FREE
    msg_free = f"**PRONÓSTICOS GRATIS** {now}\n\n"
    for p in free:
        msg_free += f"• **{p['match']}** → {p['bet']} @ {p['odds']} ({p['book']})\n_{gpt_reason(p)}_\n\n"
    msg_free += "*18+ | Solo entretenimiento | Apuesta con responsabilidad*"

    # PREMIUM
    msg_prem = "**PRONÓSTICOS PREMIUM** (Acceso anticipado)\n\n"
    for p in premium:
        msg_prem += f"• **{p['match']}** → {p['bet']} @ {p['odds']} ({p['book']})\n_{gpt_reason(p)}_\n\n"
    msg_prem += "Suscríbete: 1€ por 7 días → @EliteApuestas_1aBot"

    # ENVÍO
    try:
        await bot.send_message(chat_id=os.getenv("FREE_CHANNEL"), text=msg_free, parse_mode="Markdown")
        print("Enviado a GRATIS")
    except Exception as e:
        print(f"Error GRATIS: {e}")

    try:
        await bot.send_message(chat_id=os.getenv("PREMIUM_CHANNEL"), text=msg_prem, parse_mode="Markdown")
        print("Enviado a PREMIUM")
    except Exception as e:
        print(f"Error PREMIUM: {e}")

# === EJECUCIÓN ===
if __name__ == "__main__":
    asyncio.run(send_picks())
