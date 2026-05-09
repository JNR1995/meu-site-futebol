import requests
import sqlite3
import time
from datetime import datetime

# Configurações de Acesso
API_KEY = 'a36c5f2f632e860640988e5e0fb8f7bb'
BASE_URL = "https://v3.football.api-sports.io/fixtures"
DB_PATH = r"C:\Users\Jair1\FutebolStatsJnr.db"
TOKEN_TELEGRAM = "8678720195:AAHxiJjKnAItGPXFrnkXfnu-oOg8MPshp50"
CHAT_ID = "2083277600"

# Sistema de Cache: Armazena "ID_JOGO-NUMERO_JANELA"
# Exemplo: "1029384-1" (Alerta da 1ª janela enviado)
alertas_enviados_cache = set()

def obter_id_janela(tempo):
    # Se o tempo for None ou não for um número, ignora o jogo
    if tempo is None: 
        return None
        
    if 30 <= tempo <= 33: return 1
    if 55 <= tempo <= 60: return 2
    if 77 <= tempo <= 80: return 3
    return None

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TOKEN_TELEGRAM}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"   ❌ Erro ao enviar Telegram: {e}")

def buscar_dados_db(id_fixture):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT Pos_Home, Pos_Away, Liga_Nome, Odd_Home, Odd_Away 
        FROM JOGOS_HOJE WHERE ID_Fixture = ?
    """, (id_fixture,))
    result = cursor.fetchone()
    conn.close()
    return result

def processar_alertas():
    agora = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{agora}] 🔍 Iniciando busca por jogos Live...")
    
    headers = {'x-rapidapi-key': API_KEY, 'x-rapidapi-host': 'v3.football.api-sports.io'}
    params = {'live': 'all'}
    
    try:
        response = requests.get(BASE_URL, headers=headers, params=params)
        jogos = response.json().get('response', [])
    except Exception as e:
        print(f"❌ Erro na conexão com a API: {e}")
        return

    total_live = len(jogos)
    jogos_na_janela = 0
    novos_alertas = 0

    for jogo in jogos:
        tempo = jogo['fixture']['status']['elapsed']
        id_fix = jogo['fixture']['id']
        janela = obter_id_janela(tempo)
        
        # 1. Filtro de Janela
        if janela is None:
            continue

        # 2. Verifica se já alertamos ESTE JOGO nesta JANELA específica
        cache_key = f"{id_fix}-{janela}"
        if cache_key in alertas_enviados_cache:
            continue

        jogos_na_janela += 1
        dados_estaticos = buscar_dados_db(id_fix)
        if not dados_estaticos: continue
        
        pos_h, pos_a, liga, odd_h, odd_a = dados_estaticos
        gols_h = jogo['goals']['home']
        gols_a = jogo['goals']['away']

        # Ignora se as odds forem 0, None ou vazias
        if not odd_h or not odd_a or odd_h == 0 or odd_a == 0:
            continue
        
        # 3. Lógica Favorito Perdendo (Odd <= 1.72 e dif <= 2 gols)
        fav_perdendo = False
        time_fav = None
        if odd_h <= 1.72 and gols_a > gols_h and (gols_a - gols_h) <= 2:
            fav_perdendo, time_fav = True, "home"
        elif odd_a <= 1.72 and gols_h > gols_a and (gols_h - gols_a) <= 2:
            fav_perdendo, time_fav = True, "away"

        if fav_perdendo:
            # 4. Busca estatísticas para checar Red Card e montar o corpo
            stats_url = f"{BASE_URL}/statistics"
            res_stats = requests.get(stats_url, headers=headers, params={'fixture': id_fix}).json()
            s = {team['team']['id']: team['statistics'] for team in res_stats.get('response', [])}
            
            id_fav = jogo['teams'][time_fav]['id']
            red_cards = 0
            if id_fav in s:
                red_cards = next((item['value'] for item in s[id_fav] if item['type'] == 'Red Cards'), 0) or 0

            if red_cards > 0:
                print(f"   ⚠️ Ignorado: Favorito com vermelho em {jogo['teams']['home']['name']}")
                continue

            # 5. Montagem e Envio
            msg = f"🤖 *Favorito Perdendo*\n\n"
            msg += f"⚽️ *Partida:* ({pos_h}°) {jogo['teams']['home']['name']} x {jogo['teams']['away']['name']} ({pos_a}°)\n"
            msg += f"🏆 *Liga:* {liga}\n"
            msg += f"💰 *Odds:* {odd_h}  X  {odd_a}\n"
            msg += f"⏰ *Tempo:* {tempo}' | *Placar:* {gols_h}-{gols_a}\n"
            msg += "--------------------------------\n"

            if not s:
                msg += "⚠️ *Api Não Retornou estatísticas em LIVE*\nVerificar cenário para realização de entrada"
            else:
                def get_s(tid, tipo):
                    return next((item['value'] for item in s[tid] if item['type'] == tipo), 0) or 0
                id_h, id_a = jogo['teams']['home']['id'], jogo['teams']['away']['id']
                msg += "📊 *Estatísticas ao vivo (API)*\n\n"
                msg += f"🏹 Finalizações: {get_s(id_h, 'Total Shots')} x {get_s(id_a, 'Total Shots')}\n"
                msg += f"🎯 No Alvo: {get_s(id_h, 'Shots on Goal')} x {get_s(id_a, 'Shots on Goal')}\n"
                msg += f"🚩 Escanteios: {get_s(id_h, 'Corner Kicks')} x {get_s(id_a, 'Corner Kicks')}\n"
                msg += f"⚖️ Posse: {get_s(id_h, 'Ball Possession')} x {get_s(id_a, 'Ball Possession')}\n"
                msg += f"🟥 Red Card: {get_s(id_h, 'Red Cards')} x {get_s(id_a, 'Red Cards')}"

            enviar_telegram(msg)
            alertas_enviados_cache.add(cache_key) # Salva no cache
            novos_alertas += 1
            print(f"   ✅ Alerta enviado: {jogo['teams']['home']['name']} v {jogo['teams']['away']['name']} (Janela {janela})")

    print(f"📊 Resumo: {total_live} Live | {jogos_na_janela} Janelas Relevantes | {novos_alertas} Novos Alertas.")
    
    # Limpeza opcional: Se o cache ficar muito grande (ex: > 1000 itens), limpa os antigos
    if len(alertas_enviados_cache) > 1000:
        alertas_enviados_cache.clear()

if __name__ == "__main__":
    print("🚀 Bot de Alertas Favorito Perdendo Iniciado com Cache por Janela!")
    while True:
        processar_alertas()
        time.sleep(170)