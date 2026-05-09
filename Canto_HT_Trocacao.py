import requests
import sqlite3
import time
from datetime import datetime

API_KEY = "a36c5f2f632e860640988e5e0fb8f7bb"
BASE_URL = "https://v3.football.api-sports.io"

HEADERS = {
    'x-rapidapi-key': API_KEY,
    'x-rapidapi-host': 'v3.football.api-sports.io'
}

DB_PATH = r"C:\Users\Jair1\FutebolStatsJnr.db"

jogos_sinalizados = set()

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

def enviar_telegram(msg):
    TOKEN = "8698884604:AAFsY7eT0YKCoYpxVlETExA-aPHvelBnEKY"
    CHAT_ID = "2083277600"

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    }

    try:
        requests.post(url, data=payload)
    except:
        print("Erro ao enviar Telegram")

def get_jogos_live():
    url = f"{BASE_URL}/fixtures?live=all"
    return requests.get(url, headers=HEADERS).json()


def get_estatisticas(fixture_id):
    url = f"{BASE_URL}/fixtures/statistics?fixture={fixture_id}"
    return requests.get(url, headers=HEADERS).json()


def get_dados_jogo(fixture_id):
    cursor.execute("""
        SELECT Odd_Home, Odd_Away, Pos_Home, Pos_Away, Liga_Nome
        FROM JOGOS_HOJE 
        WHERE ID_Fixture = ?
    """, (fixture_id,))
    
    return cursor.fetchone()


def extrair_valor(stats, nome):
    for item in stats:
        if item["type"] == nome:
            val = item["value"]
            if val is None:
                return 0
            if isinstance(val, str) and "%" in val:
                return float(val.replace("%", ""))
            return float(val)
    return 0


def analisar_jogo(fixture):
    fixture_id = fixture["fixture"]["id"]
    minuto = fixture["fixture"]["status"]["elapsed"]

    if minuto is None or minuto < 31 or minuto > 33:
        return

    if fixture_id in jogos_sinalizados:
        return

    dados = get_dados_jogo(fixture_id)
    if dados is None:
        return

    odd_home, odd_away, pos_home, pos_away, liga_nome = dados

    gols_home = fixture["goals"]["home"]
    gols_away = fixture["goals"]["away"]

    # ⚽ Placar válido (empate ou diferença de 1 gol)
    if abs(gols_home - gols_away) > 1:
        return

    stats_json = get_estatisticas(fixture_id)

    if len(stats_json["response"]) < 2:
        return

    stats_home = stats_json["response"][0]["statistics"]
    stats_away = stats_json["response"][1]["statistics"]

    # 📊 Estatísticas principais
    shots_home = extrair_valor(stats_home, "Total Shots")
    shots_away = extrair_valor(stats_away, "Total Shots")

    shots_on_home = extrair_valor(stats_home, "Shots on Goal")
    shots_on_away = extrair_valor(stats_away, "Shots on Goal")

    shots_in_home = extrair_valor(stats_home, "Shots insidebox")
    shots_in_away = extrair_valor(stats_away, "Shots insidebox")

    corners_home = extrair_valor(stats_home, "Corner Kicks")
    corners_away = extrair_valor(stats_away, "Corner Kicks")
    corners_total = corners_home + corners_away

    posse_home = extrair_valor(stats_home, "Ball Possession")
    posse_away = extrair_valor(stats_away, "Ball Possession")

    saves_home = extrair_valor(stats_home, "Goalkeeper Saves")
    saves_away = extrair_valor(stats_away, "Goalkeeper Saves")

    total_shots = shots_home + shots_away

    # 🔥 FILTROS TROCAÇÃO

    # Volume dos dois lados
    if shots_home < 4 or shots_away < 4:
        return

    if total_shots < 9:
        return

    # No alvo
    if shots_on_home < 1 or shots_on_away < 1:
        return

    # Inside box
    if not ((shots_in_home >= 2 and shots_in_away >= 2) or
            shots_in_home >= 4 or shots_in_away >= 4):
        return

    # Equilíbrio
    if abs(shots_home - shots_away) > 3:
        return

    # Escanteios
    if corners_total < 2 or corners_total > 5:
        return

    # Posse equilibrada (43–57)
    if not (43 <= posse_home <= 57 and 43 <= posse_away <= 57):
        return

    # 📛 Infos
    home_name = fixture["teams"]["home"]["name"]
    away_name = fixture["teams"]["away"]["name"]

    # 🕒 Tempo atual
    agora = datetime.now().strftime("%H:%M:%S")

    # 🚀 PRINT
    msg = f"""
    🥊 Trocação 🥊

    ⚽️ Partida: ({pos_home}°) {home_name} x {away_name} ({pos_away}°)
    🏆 Liga: {liga_nome}
    💰 Odds: {odd_home}  X  {odd_away}
    ⏰ Tempo: {minuto}' | Placar: {gols_home}-{gols_away}

    --------------------------------
    📊 Estatísticas ao vivo

    🏹 Finalizações: {shots_home} x {shots_away} = {shots_home + shots_away}
    🎯 No Alvo: {shots_on_home} x {shots_on_away}
    🧤 Defesas Goleiro: {saves_home} x {saves_away}
    🚩 Escanteios: {corners_home} x {corners_away}
    ⚖️ Posse: {posse_home}% x {posse_away}%
    """

    enviar_telegram(msg)
    jogos_sinalizados.add(fixture_id)


def main():
    while True:
        try:
            jogos = get_jogos_live()["response"]

            total_31_33 = 0
            total_no_db = 0

            for jogo in jogos:
                minuto = jogo["fixture"]["status"]["elapsed"]
                fixture_id = jogo["fixture"]["id"]

                if minuto and 31 <= minuto <= 33:
                    total_31_33 += 1

                    if get_dados_jogo(fixture_id):
                        total_no_db += 1

                analisar_jogo(jogo)

            agora = datetime.now().strftime("%H:%M:%S")

            print(f"\n🕒 Ciclo executado às: {agora}")
            print(f"📡 Jogos 31–33 min: {total_31_33} | No DB: {total_no_db}")
            print("--------------------------------------------------")

            time.sleep(160)

        except Exception as e:
            print("Erro:", e)
            time.sleep(30)


if __name__ == "__main__":
    main()