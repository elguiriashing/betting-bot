import os
import openai
import asyncio
import requests
from datetime import datetime, timezone, timedelta
from telegram import Bot

# Config
openai.api_key = os.getenv("OPENAI_API_KEY")
bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
ODDS_API_KEY = os.getenv("ODDS_API_KEY")  # CORREGIDO: Usa ODDS_API_KEY

# === FILTRO: HOY/MAÑANA (48h) ===
def now_utc():
    return datetime.now(timezone.utc)

def is_today_or_next(game_time):
    now = now_utc()
    next_48h = now + timedelta(hours=48)
    return now < game_time <= next_48h.replace(hour=23, minute=59, second=59)

# === SCRAPER: API REAL + VERIFICACIÓN ===
def get_picks():
    if not ODDS_API_KEY:
        print("ODDS_API_KEY no configurada → NO HAY PARTIDOS")
        return []

    # Verificar key
    test_url = "https://api.the-odds-api.com/v4/sports/upcoming/odds/"
    test_params = {'apiKey': ODDS_API_KEY, 'regions': 'eu'}
    try:
        test_r = requests.get(test_url, params=test_params, timeout=5)
        if test_r.status_code != 200:
            print(f"API KEY inválida: {test_r.status_code} - Regenera en the-odds-api.com")
            return []
    except Exception as e:
        print(f"Error verificando KEY: {e} → NO HAY PARTIDOS")
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
            'markets': 'h2h,totals',
            'oddsFormat': 'decimal',
            'bookmakers': 'bet365,bwin,unibet,pinnacle'
        }
        try:
            r = requests.get(url, params=params, timeout=15)
            print(f"API {sport}: {r.status_code}")
            if r.status_code != 200:
                continue
            data = r.json()

            for game in data:
                commence = game.get('commence_time')
                if not commence:
                    continue
                game_time = datetime.fromisoformat(commence.replace('Z', '+00:00'))
                if not is_today_or_next(game_time):
                    continue

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

    unique.sort(key=lambda x: x['time'])
    return unique[:10]  # Máximo 10 para escala

# === DISTRIBUCIÓN ESCALADA ===
def distribute_picks(picks):
    total = len(picks)
    if total == 0:
        return [], []
    elif total == 1:
        return picks[:1], []
    elif total == 2:
        return picks[:1], picks[1:2]
    elif total == 3:
        return picks[:2], picks[2:3]
    elif total == 4:
        return picks[:2], picks[2:4]
    elif total == 5:
        return picks[:3], picks[3:5]
    elif total == 6:
        return picks[:4], picks[4:6]
    elif total == 7:
        return picks[:4], picks[4:7]
    elif total == 8:
        return picks[:5], picks[5:8]
    elif total == 9:
        return picks[:6], picks[6:9]
    elif total >= 10:
        return picks[:6], picks[6:10]
    return picks[:total], []

# === GPT SEGURO ===
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

# === ENVÍO ===
async def send_picks():
    picks = get_picks()
    if len(picks) == 0:
        print("NO HAY PARTIDOS HOY → NO ENVÍO")
        return

    free, premium = distribute_picks(picks)
    now = now_utc().strftime("%H:%M UTC")

    # FREE
    msg_free = f"**PRONÓSTICOS GRATIS** {now} ({len(free)} picks)\n\n"
    for p in free:
        msg_free += f"• **{p['match']}** → {p['bet']} @ {p['odds']} ({p['book']}) | {p['time']} UTC\n"
        msg_free += f"_{gpt_reason(p)}_\n\n"
    msg_free += "*18+ | Solo entretenimiento | Apuesta con responsabilidad*"

    # PREMIUM
    msg_prem = f"**PRONÓSTICOS PREMIUM** (Acceso anticipado) ({len(premium)} exclusivos)\n\n"
    for i, p in enumerate(picks, 1):
        if i <= len(free):
            msg_prem += f"• **{p['match']}** → {p['bet']} @ {p['odds']} ({p['book']}) | {p['time']} UTC\n"
        else:
            msg_prem += f"🔒 **EXCLUSIVO:** {p['match']} → {p['bet']} @ {p['odds']} ({p['book']}) | {p['time']} UTC\n"
        msg_prem += f"_{gpt_reason(p)}_\n\n"
    msg_prem += "Suscríbete: 1€ por 7 días → @EliteApuestas_1aBot"

    # ENVÍO FREE
    try:
        await bot.send_message(chat_id=os.getenv("FREE_CHANNEL"), text=msg_free, parse_mode="Markdown")
        print(f"Enviado a GRATIS ({len(free)} picks)")
    except Exception as e:
        print(f"Error GRATIS: {e}")
        await bot.send_message(chat_id=os.getenv("FREE_CHANNEL"), text=msg_free.replace("**", "").replace("_", ""))

    # ENVÍO PREMIUM
    if len(premium) > 0:
        try:
            await bot.send_message(chat_id=os.getenv("PREMIUM_CHANNEL"), text=msg_prem, parse_mode="Markdown")
            print(f"Enviado a PREMIUM ({len(premium)} exclusivos)")
        except Exception as e:
            print(f"Error PREMIUM: {e}")
            await bot.send_message(chat_id=os.getenv("PREMIUM_CHANNEL"), text=msg_prem.replace("**", "").replace("_", ""))

if __name__ == "__main__":
    asyncio.run(send_picks())
