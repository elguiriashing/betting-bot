import os
import openai
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from telegram import Bot

# Config
openai.api_key = os.getenv("OPENAI_API_KEY")
bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# === FILTRO: SOLO HOY/MAÑANA ===
def now_utc():
    return datetime.now(timezone.utc)

def is_today_or_tomorrow(game_time):
    now = now_utc()
    tomorrow = now + timedelta(days=1)
    return now < game_time <= tomorrow.replace(hour=23, minute=59, second=59)

# === SCRAPER: SOLO API REAL (SIN MOCK) ===
def get_picks():
    if not ODDS_API_KEY:
        print("ODDS_API_KEY no configurada → NO HAY PARTIDOS")
        return []

    sports = [
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_germany_bundesliga",
        "soccer_italy_serie_a",
        "soccer_france_ligue_one",
        "soccer_uefa_champions_league",
        "soccer_uefa_europa_league"
    ]
    all_picks = []

    for sport in sports:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            'apiKey': ODDS_API_KEY,
            'regions': 'eu',
            'markets': 'h2h,totals,asian_handicap',
            'oddsFormat': 'decimal',
            'bookmakers': 'bet365,bwin,unibet,pinnacle'
        }
        try:
            r = requests.get(url, params=params, timeout=15)
            if r.status_code != 200:
                print(f"API {sport}: {r.status_code}")
                continue
            data = r.json()

            for game in data:
                commence = game.get('commence_time')
                if not commence:
                    continue
                game_time = datetime.fromisoformat(commence.replace('Z', '+00:00'))
                if not is_today_or_tomorrow(game_time):
                    continue  # SOLO HOY/MAÑANA

                home, away = game['home_team'], game['away_team']
                match_name = f"{home} vs {away}"

                for site in game.get('bookmakers', []):
                    if site['key'] not in ['bet365', 'bwin', 'unibet', 'pinnacle']:
                        continue
                    book_title = site['title']

                    for market in site.get('markets', []):
                        outcomes = market.get('outcomes', [])
                        if market['key'] == 'h2h':
                            for o in outcomes:
                                if o['price'] >= 1.70:
                                    all_picks.append({
                                        "match": match_name,
                                        "bet": "ML",
                                        "odds": round(o['price'], 2),
                                        "book": book_title,
                                        "time": game_time.strftime("%H:%M")
                                    })
                        elif market['key'] == 'totals':
                            for o in outcomes:
                                if 'Over 2.5' in o['name'] and o['price'] >= 1.70:
                                    all_picks.append({
                                        "match": match_name,
                                        "bet": "Over 2.5",
                                        "odds": round(o['price'], 2),
                                        "book": book_title,
                                        "time": game_time.strftime("%H:%M")
                                    })
                        elif market['key'] == 'asian_handicap':
                            for o in outcomes:
                                if '-1.5' in o['name'] and o['price'] >= 1.70:
                                    all_picks.append({
                                        "match": match_name,
                                        "bet": "-1.5",
                                        "odds": round(o['price'], 2),
                                        "book": book_title,
                                        "time": game_time.strftime("%H:%M")
                                    })
        except Exception as e:
            print(f"Error API {sport}: {e}")

    # Eliminar duplicados
    seen = set()
    unique = []
    for p in all_picks:
        key = (p['match'], p['bet'], p['book'])
        if key not in seen:
            seen.add(key)
            unique.append(p)

    # Ordenar por hora
    unique.sort(key=lambda x: x['time'])

    # MÁXIMO 5 PARTIDOS
    return unique[:5]

# === GPT SEGURO (TEXTO PLANO) ===
def gpt_reason(pick):
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Explica en 1 frase por qué apostar {pick['bet']} en {pick['match']} a las {pick['time']} UTC. Español, profesional, texto plano."
            }],
            max_tokens=70
        )
        reason = resp.choices[0].message.content.strip()
        return ''.join(c for c in reason if c.isalnum() or c in " .,?!'-")
    except Exception as e:
        print(f"GPT Error: {e}")
        return "Ventaja clara por forma y estadísticas."

# === ENVÍO CONDICIONAL ===
async def send_picks():
    picks = get_picks()

    if len(picks) < 3:
        print(f"Solo {len(picks)} partidos hoy → NO ENVÍO (mínimo 3)")
        return

    free = picks[:3]
    premium = picks  # 5 totales

    now = now_utc().strftime("%H:%M UTC")

    # FREE
    msg_free = f"**PRONÓSTICOS GRATIS** {now}\n\n"
    for p in free:
        msg_free += f"• **{p['match']}** → {p['bet']} @ {p['odds']} ({p['book']}) | {p['time']} UTC\n"
        msg_free += f"_{gpt_reason(p)}_\n\n"
    msg_free += "*18+ | Solo entretenimiento | Apuesta con responsabilidad*"

    # PREMIUM
    msg_prem = f"**PRONÓSTICOS PREMIUM** (Acceso anticipado)\n\n"
    for i, p in enumerate(premium, 1):
        if i > 3:
            msg_prem += f"EXCLUSIVO PREMIUM: **{p['match']}** → {p['bet']} @ {p['odds']} ({p['book']}) | {p['time']} UTC\n"
        else:
            msg_prem += f"• **{p['match']}** → {p['bet']} @ {p['odds']} ({p['book']}) | {p['time']} UTC\n"
        msg_prem += f"_{gpt_reason(p)}_\n\n"
    msg_prem += "Suscríbete: 1€ por 7 días → @EliteApuestas_1aBot"

    # ENVÍO SEGURO
    try:
        await bot.send_message(chat_id=os.getenv("FREE_CHANNEL"), text=msg_free, parse_mode="Markdown")
        print("Enviado a GRATIS")
    except Exception as e:
        print(f"Error GRATIS: {e}")
        await bot.send_message(chat_id=os.getenv("FREE_CHANNEL"), text=msg_free.replace("**", "").replace("_", ""))

    try:
        await bot.send_message(chat_id=os.getenv("PREMIUM_CHANNEL"), text=msg_prem, parse_mode="Markdown")
        print("Enviado a PREMIUM")
    except Exception as e:
        print(f"Error PREMIUM: {e}")
        await bot.send_message(chat_id=os.getenv("PREMIUM_CHANNEL"), text=msg_prem.replace("**", "").replace("_", ""))

if __name__ == "__main__":
    asyncio.run(send_picks())
