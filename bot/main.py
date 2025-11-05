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

# === TIEMPO ACTUAL UTC ===
def now_utc():
    return datetime.now(timezone.utc)

# === SCRAPER: SOLO PARTIDOS FUTUROS ===
def get_picks():
    if not ODDS_API_KEY:
        print("ODDS_API_KEY no configurada → usando mock")
        return get_mock_picks()

    sports = [
        "soccer_spain_la_liga",
        "soccer_epl",
        "soccer_germany_bundesliga",
        "soccer_france_ligue_one"
    ]
    all_picks = []
    now = now_utc()

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
                commence = game.get('commence_time')
                if not commence:
                    continue
                game_time = datetime.fromisoformat(commence.replace("Z", "+00:00"))
                if game_time <= now:
                    continue  # SOLO PARTIDOS FUTUROS

                home, away = game['home_team'], game['away_team']
                match_name = f"{home} vs {away}"

                for site in game.get('bookmakers', []):
                    if site['key'] not in ['bet365', 'bwin', 'unibet']:
                        continue
                    book_title = site['title']

                    for market in site.get('markets', []):
                        outcomes = market.get('outcomes', [])
                        if market['key'] == 'h2h':
                            for o in outcomes:
                                if o['name'] == home and o['price'] >= 1.70:
                                    all_picks.append({
                                        "match": match_name,
                                        "bet": "ML",
                                        "odds": o['price'],
                                        "book": book_title,
                                        "time": game_time.strftime("%H:%M")
                                    })
                        elif market['key'] == 'totals':
                            for o in outcomes:
                                if o['name'] == 'Over 2.5' and o['price'] >= 1.70:
                                    all_picks.append({
                                        "match": match_name,
                                        "bet": "Over 2.5",
                                        "odds": o['price'],
                                        "book": book_title,
                                        "time": game_time.strftime("%H:%M")
                                    })
                        elif market['key'] == 'asian_handicap':
                            for o in outcomes:
                                if '-1.5' in o['name'] and o['price'] >= 1.70:
                                    all_picks.append({
                                        "match": match_name,
                                        "bet": "-1.5",
                                        "odds": o['price'],
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

    return unique[:5] if len(unique) >= 3 else get_mock_picks()

# === MOCK SEGURO ===
def get_mock_picks():
    return [
        {"match": "Real Madrid vs Barcelona", "bet": "Over 2.5", "odds": 1.85, "book": "Bet365", "time": "21:00"},
        {"match": "Atlético vs Sevilla", "bet": "-0.5", "odds": 1.78, "book": "Bwin", "time": "20:30"},
        {"match": "Valencia vs Villarreal", "bet": "BTTS", "odds": 1.92, "book": "Bet365", "time": "19:15"}
    ]

# === GPT SEGURO (sin Markdown roto) ===
def gpt_reason(pick):
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Explica en 1 frase clara por qué apostar {pick['bet']} en {pick['match']}. Solo texto plano, sin * ni _."
            }],
            max_tokens=70
        )
        reason = resp.choices[0].message.content.strip()
        # LIMPIAR CARACTERES PELIGROSOS
        return reason.replace("*", "").replace("_", "").replace("[", "").replace("]", "")
    except Exception as e:
        print(f"GPT Error: {e}")
        return "Ventaja estadística clara."

# === ENVÍO SEGURO ===
async def send_picks():
    picks = get_picks()
    free = picks[:3]
    premium = picks[:5]

    now = now_utc().strftime("%H:%M UTC")

    # === FREE ===
    msg_free = f"**PRONÓSTICOS GRATIS** {now}\n\n"
    for p in free:
        msg_free += f"• **{p['match']}** → {p['bet']} @ {p['odds']} ({p['book']}) | {p['time']} UTC\n"
        msg_free += f"_{gpt_reason(p)}_\n\n"
    msg_free += "*18+ | Solo entretenimiento | Apuesta con responsabilidad*"

    # === PREMIUM ===
    msg_prem = f"**PRONÓSTICOS PREMIUM** (Acceso anticipado)\n\n"
    for p in premium:
        msg_prem += f"• **{p['match']}** → {p['bet']} @ {p['odds']} ({p['book']}) | {p['time']} UTC\n"
        msg_prem += f"_{gpt_reason(p)}_\n\n"
    msg_prem += "Suscríbete: 1€ por 7 días → @EliteApuestas_1aBot"

    # === ENVÍO CON TRY/EXCEPT SEGURO ===
    try:
        await bot.send_message(
            chat_id=os.getenv("FREE_CHANNEL"),
            text=msg_free,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        print("Enviado a GRATIS")
    except Exception as e:
        print(f"Error GRATIS: {e}")
        # ENVÍO SIN MARKDOWN SI FALLA
        await bot.send_message(chat_id=os.getenv("FREE_CHANNEL"), text=msg_free.replace("*", "").replace("_", ""))

    try:
        await bot.send_message(
            chat_id=os.getenv("PREMIUM_CHANNEL"),
            text=msg_prem,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        print("Enviado a PREMIUM")
    except Exception as e:
        print(f"Error PREMIUM: {e}")
        await bot.send_message(chat_id=os.getenv("PREMIUM_CHANNEL"), text=msg_prem.replace("*", "").replace("_", ""))

# === RUN ===
if __name__ == "__main__":
    asyncio.run(send_picks())
