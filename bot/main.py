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

# === HORA ESPAÑA + FECHA ===
def spain_datetime(utc_dt):
    spain_offset = timedelta(hours=1)  # CET noviembre
    spain_dt = utc_dt + spain_offset
    return spain_dt.strftime("%H:%M"), spain_dt.strftime("%d/%m")

# === FILTRO: HOY/72h ===
def now_utc():
    return datetime.now(timezone.utc)

def is_within_72h(game_time):
    now = now_utc()
    next_72h = now + timedelta(hours=72)
    return now < game_time <= next_72h.replace(hour=23, minute=59, second=59)

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
    return picks[:total], []

# === SCRAPER: 1X2 + 1 POR PARTIDO ===
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
        "soccer_champions_league",  # FIX: Key correcto para Champions
        "soccer_europa_league"      # FIX: Key correcto para Europa
    ]
    seen_matches = set()
    all_matches = []

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
                if not is_within_72h(game_time):
                    continue

                home, away = game['home_team'], game['away_team']
                match_key = f"{home} vs {away}"
                if match_key in seen_matches:
                    continue
                seen_matches.add(match_key)

                for site in game.get('bookmakers', []):
                    if site['key'] not in ['bet365', 'bwin', 'unibet', 'pinnacle']:
                        continue
                    outcomes = site.get('markets', [{}])[0].get('outcomes', [])
                    if len(outcomes) < 3:
                        continue

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

                    all_matches.append({
                        "match": match_key,
                        "odds_1": odds['home'],
                        "odds_x": odds['draw'],
                        "odds_2": odds['away'],
                        "book": site['title'],
                        "utc_time": game_time
                    })
                    break

        except Exception as e:
            print(f"Error API {sport}: {e}")

    all_matches.sort(key=lambda x: x['utc_time'])
    return all_matches[:10]

# === GPT: ORDENAR POR IMPORTANCIA ===
def order_by_importance(matches):
    if not matches:
        return []
    prompt = (
        "Ordena estos partidos de fútbol por importancia (1 = más importante, 10 = menos). "
        "Prioriza: Champions League > Europa League > Liga nacional. "
        "Equipos TOP PRIORIDAD ALTA: Barcelona, Real Madrid, Man City, Newcastle, Liverpool, Arsenal, Bayern, Inter, Juventus, PSG, AC Milan. "
        "Rivalidad y tamaño. Lista numerada con nombre del partido:\n\n"
    )
    for m in matches:
        prompt += f"- {m['match']} (1: {m['odds_1']}, X: {m['odds_x']}, 2: {m['odds_2']})\n"
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200
        )
        ordered_names = []
        for line in resp.choices[0].message.content.strip().split('\n'):
            if line.strip().startswith(tuple(str(i) for i in range(1, 11))):
                ordered_names.append(line.split('.', 1)[1].strip().split(' (')[0].strip())
        ordered_matches = []
        for name in ordered_names:
            for match in matches:
                if match['match'] in name:
                    ordered_matches.append(match)
                    break
        return ordered_matches[:10]
    except Exception as e:
        print(f"Error GPT orden: {e}")
        return matches

# === GPT RAZÓN ===
def gpt_reason(pick):
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Explica en 1 frase corta por qué {pick['match']} terminará con victoria local, empate o visitante. Incluye quién es favorito. Español, profesional, texto plano."
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
    raw_picks = get_picks()
    if len(raw_picks) == 0:
        print("NO HAY PARTIDOS HOY → NO ENVÍO")
        return

    # Ordenar por importancia con GPT
    ordered_picks = order_by_importance(raw_picks)
    free, premium_ex = distribute_picks(ordered_picks)
    now_time, now_date = spain_datetime(now_utc())

    # FREE
    msg_free = f"🔥 **PRONÓSTICOS GRATIS** {now_time} UTC | {now_date} | {len(free)} picks 🔥\n\n"
    for p in free:
        time_s, date_s = spain_datetime(p['utc_time'])
        msg_free += f"⚽ **{p['match']}** ({date_s})\n"
        msg_free += f"→ 1️⃣ **{p['odds_1']}** | X️⃣ **{p['odds_x']}** | 2️⃣ **{p['odds_2']}** ({p['book']})\n"
        msg_free += f"⏰ **{time_s} ESP**\n"
        msg_free += f"_{gpt_reason(p)}_\n\n"
    msg_free += "💎 *18+ | Solo entretenimiento | Apuesta con responsabilidad* 💎"

    # PREMIUM
    msg_prem = f"💎 **PRONÓSTICOS PREMIUM** (Acceso anticipado) | {now_date} | {len(premium_ex)} exclusivos 💎\n\n"
    for i, p in enumerate(ordered_picks, 1):
        time_s, date_s = spain_datetime(p['utc_time'])
        if i > len(free):
            msg_prem += f"🔒 **EXCLUSIVO PREMIUM:**\n"
        msg_prem += f"⚽ **{p['match']}** ({date_s})\n"
        msg_prem += f"→ 1️⃣ **{p['odds_1']}** | X️⃣ **{p['odds_x']}** | 2️⃣ **{p['odds_2']}** ({p['book']})\n"
        msg_prem += f"⏰ **{time_s} ESP**\n"
        msg_prem += f"_{gpt_reason(p)}_\n\n"
    msg_prem += "🚀 **Suscríbete YA:** 1€ por 7 días → @EliteApuestas_1aBot 🚀"

    # ENVÍO FREE
    try:
        await bot.send_message(chat_id=os.getenv("FREE_CHANNEL"), text=msg_free, parse_mode="Markdown")
        print(f"GRATIS: {len(free)} picks")
    except Exception as e:
        print(f"Error GRATIS: {e}")
        await bot.send_message(chat_id=os.getenv("FREE_CHANNEL"), text=msg_free.replace("**", "").replace("_", ""))

    # ENVÍO PREMIUM
    try:
        await bot.send_message(chat_id=os.getenv("PREMIUM_CHANNEL"), text=msg_prem, parse_mode="Markdown")
        print(f"PREMIUM: {len(premium_ex)} exclusivos")
    except Exception as e:
        print(f"Error PREMIUM: {e}")
        await bot.send_message(chat_id=os.getenv("PREMIUM_CHANNEL"), text=msg_prem.replace("**", "").replace("_", ""))

if __name__ == "__main__":
    asyncio.run(send_picks())
