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

# === HORA ESPAÑA (CET/CEST) ===
def spain_time(utc_dt):
    # España: UTC+1 (invierno), UTC+2 (verano) — simplificado a +1 (noviembre)
    spain_offset = timedelta(hours=1)  # CET en noviembre
    return (utc_dt + spain_offset).strftime("%H:%M")

# === FILTRO: HOY/MAÑANA (48h) ===
def now_utc():
    return datetime.now(timezone.utc)

def is_today_or_next(game_time):
    now = now_utc()
    next_48h = now + timedelta(hours=48)
    return now < game_time <= next_48h.replace(hour=23, minute=59, second=59)

# === DISTRIBUCIÓN ESCALADA ===
def distribute_picks(picks):
    total = len(picks)
    if total == 1: return picks[:1], []
    elif total == 2: return picks[:1], picks[1:2]
    elif total == 3: return picks[:2], picks[2:3]
    elif total == 4: return picks[:2], picks[2:4]
    elif total == 5: return picks[:3], picks[3:5]
    elif total == 6: return picks[:4], picks[4:6]
    elif total == 7: return picks[:4], picks[4:7]
    elif total == 8: return picks[:5], picks[5:8]
    elif total == 9: return picks[:6], picks[6:9]
    elif total >= 10: return picks[:6], picks[6:10]
    return picks[:6], picks[6:10]

# === SCRAPER: 1X2 + 1 POR PARTIDO + SIN DUPLICADOS ===
def get_picks():
    if not ODDS_API_KEY:
        print("ODDS_API_KEY no configurada")
        return []

    sports = [
        "soccer_epl",
        "soccer_spain_la_liga",
        "soccer_germany_bundesliga",
        "soccer_italy_serie_a",
        "soccer_france_ligue_one",
        "soccer_champions_league",
        "soccer_europa_league"
    ]
    seen_matches = set()
    all_picks = []

    for sport in sports:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            'apiKey': ODDS_API_KEY,
            'regions': 'eu',
            'markets': 'h2h',
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
                match_key = f"{home} vs {away}"
                if match_key in seen_matches:
                    continue  # 1 por partido
                seen_matches.add(match_key)

                # Buscar 1X2 en cualquier bookie
                for site in game.get('bookmakers', []):
                    if site['key'] not in ['bet365', 'bwin', 'unibet', 'pinnacle']:
                        continue
                    outcomes = site.get('markets', [{}])[0].get('outcomes', [])
                    if len(outcomes) < 3:
                        continue

                    # Orden: Home, Draw, Away
                    odds = {'home': None, 'draw': None, 'away': None}
                    for o in outcomes:
                        if o['name'] == home:
                            odds['home'] = round(o['price'], 2)
                        elif o['name'] == 'Draw':
                            odds['draw'] = round(o['price'], 2)
                        elif o['name'] == away:
                            odds['away'] = round(o['price'], 2)

                    if None in odds.values():
                        continue

                    all_picks.append({
                        "match": match_key,
                        "odds_1": odds['home'],
                        "odds_x": odds['draw'],
                        "odds_2": odds['away'],
                        "book": site['title'],
                        "time_spain": spain_time(game_time),
                        "utc_time": game_time
                    })
                    break  # Solo 1 bookie por partido

        except Exception as e:
            print(f"Error API {sport}: {e}")

    all_picks.sort(key=lambda x: x['utc_time'])
    return all_picks[:10]

# === GPT: QUIÉN GANA + RAZÓN ===
def gpt_reason(pick):
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Explica en 1 frase corta por qué {pick['match']} terminará con victoria local, empate o visitante. Incluye quién es favorito. Solo texto plano, español."
            }],
            max_tokens=60
        )
        reason = resp.choices[0].message.content.strip()
        return ''.join(c for c in reason if c.isalnum() or c in " .,?!'-")
    except Exception as e:
        print(f"GPT Error: {e}")
        return "Equipo local favorito por forma reciente."

# === ENVÍO ===
async def send_picks():
    picks = get_picks()
    if len(picks) == 0:
        print("NO HAY PARTIDOS HOY → NO ENVÍO")
        return

    free, premium_ex = distribute_picks(picks)
    now = now_utc().strftime("%H:%M UTC")

    # FREE
    msg_free = f"**PRONÓSTICOS GRATIS** {now} ({len(free)} picks)\n\n"
    for p in free:
        msg_free += f"• **{p['match']}** → 1 ({p['odds_1']}) X ({p['odds_x']}) 2 ({p['odds_2']}) ({p['book']}) | {p['time_spain']} ESP\n"
        msg_free += f"_{gpt_reason(p)}_\n\n"
    msg_free += "*18+ | Solo entretenimiento | Apuesta con responsabilidad*"

    # PREMIUM
    msg_prem = f"**PRONÓSTICOS PREMIUM** (Acceso anticipado) ({len(premium_ex)} exclusivos)\n\n"
    for i, p in enumerate(picks, 1):
        if i > len(free):
            msg_prem += f"EXCLUSIVO PREMIUM: **{p['match']}** → 1 ({p['odds_1']}) X ({p['odds_x']}) 2 ({p['odds_2']}) ({p['book']}) | {p['time_spain']} ESP\n"
        else:
            msg_prem += f"• **{p['match']}** → 1 ({p['odds_1']}) X ({p['odds_x']}) 2 ({p['odds_2']}) ({p['book']}) | {p['time_spain']} ESP\n"
        msg_prem += f"_{gpt_reason(p)}_\n\n"
    msg_prem += "Suscríbete: 1€ por 7 días → @EliteApuestas_1aBot"

    # ENVÍO SEGURO
    try:
        await bot.send_message(chat_id=os.getenv("FREE_CHANNEL"), text=msg_free, parse_mode="Markdown")
        print(f"GRATIS: {len(free)} picks")
    except Exception as e:
        print(f"Error GRATIS: {e}")
        await bot.send_message(chat_id=os.getenv("FREE_CHANNEL"), text=msg_free.replace("**", "").replace("_", ""))

    try:
        await bot.send_message(chat_id=os.getenv("PREMIUM_CHANNEL"), text=msg_prem, parse_mode="Markdown")
        print(f"PREMIUM: {len(premium_ex)} exclusivos")
    except Exception as e:
        print(f"Error PREMIUM: {e}")
        await bot.send_message(chat_id=os.getenv("PREMIUM_CHANNEL"), text=msg_prem.replace("**", "").replace("_", ""))

if __name__ == "__main__":
    asyncio.run(send_picks())
