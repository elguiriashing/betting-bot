import os
import openai
import asyncio
from datetime import datetime, timezone
from telegram import Bot

# Config
openai.api_key = os.getenv("OPENAI_API_KEY")
bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))

# === SCRAPER REAL (Bet365/Bwin) - AÑADIMOS DESPUÉS ===
def get_picks():
    # Mock temporal (reemplazado por scraper real)
    matches = [
        "Liverpool vs Madrid", "Man Utd vs Chelsea", "Arsenal vs City",
        "Bayern vs Dortmund", "PSG vs Monaco"
    ]
    bets = ["-1.5", "Over 2.5", "BTTS", "Over 3.5", "ML"]
    odds = [2.10, 1.95, 1.80, 2.25, 1.70]
    books = ["Bet365", "Bwin", "Bet365", "Bwin", "Bet365"]
    return [{"match": m, "bet": b, "odds": o, "book": k} for m,b,o,k in zip(matches, bets, odds, books)]

def gpt_reason(pick):
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": f"Explica en 1 frase por qué apostar {pick['bet']} en {pick['match']}. En español, profesional, breve."
            }],
            max_tokens=60
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"GPT Error: {e}")
        return "Fuerte ventaja estadística."

async def send_picks():
    picks = get_picks()
    free = picks[:3]
    premium = picks[:5]

    now = datetime.now(timezone.utc).strftime("%H:%M UTC")

    # === FREE PICKS (ESPAÑOL) ===
    msg_free = f"**PRONÓSTICOS GRATIS** {now}\n\n"
    for p in free:
        msg_free += f"• **{p['match']}** → {p['bet']} @ {p['odds']} ({p['book']})\n_{gpt_reason(p)}_\n\n"
    msg_free += "*18+ | Solo entretenimiento | Apuesta con responsabilidad*"

    # === PREMIUM PICKS (ESPAÑOL) ===
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

if __name__ == "__main__":
    asyncio.run(send_picks())
