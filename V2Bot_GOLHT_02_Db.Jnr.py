import sqlite3
import requests
import time
import datetime
import urllib3
import os


# Silenciar avisos de SSL se necessário
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

NOME_DO_BOT = os.path.basename(__file__)
# --- CONFIGURAÇÕES ---
API_KEY = "a36c5f2f632e860640988e5e0fb8f7bb"
DB_NAME = r'C:\Users\Jair1\FutebolStatsJnr.db'
HEADERS = {'x-rapidapi-key': API_KEY, 'x-rapidapi-host': 'v3.football.api-sports.io'}
TELEGRAM_TOKEN = "8749904937:AAGLUE6dkTl4WxnqijFipBOYaJbVmqfM-Ec"
TELEGRAM_CHAT_ID = "2083277600"

jogos_em_alerta_beta = [] # Lista para controle de Green/Red

# --- FUNÇÕES TELEGRAM ---

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, data=payload, timeout=10, verify=False).json()
        if r.get('ok'): return r['result']['message_id']
    except: return None

def atualizar_telegram(message_id, novo_texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "message_id": message_id, "text": novo_texto, "parse_mode": "Markdown"}
    try: requests.post(url, data=payload, timeout=10, verify=False)
    except: pass

def salvar_alerta_db(f, s_db, m_id, corpo):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    dados = (
        f['fixture']['id'],       # ID_Fixture
        NOME_DO_BOT,              # Nome do arquivo (Bot_Beta.py)
        f['teams']['home']['id'], # ID_Home
        s_db[0],                  # Home_Team
        f['teams']['away']['id'], # ID_Away
        s_db[1],                  # Away_Team
        m_id,                     # ID da mensagem no Telegram
        corpo                     # Texto completo do alerta
    )
    cursor.execute("""
        INSERT OR IGNORE INTO ALERTAS_DISPARADOS 
        (ID_Fixture, Name_Bot, ID_Home, Home_Team, ID_Away, Away_Team, ID_Mensagem_Telegram, Corpo_Mensagem)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, dados)
    conn.commit()
    conn.close()



# --- FUNÇÕES DE DADOS ---
def get_db_stats_full(fixture_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    query = """
    SELECT 
        j.Home_Team, j.Away_Team,
        IFNULL(g1.MD_HT, 0), IFNULL(g1.[0.5+], 0), 
        IFNULL(g2.MD_HT, 0), IFNULL(g2.[0.5+], 0),
        IFNULL(s1.MD_HT, 0), IFNULL(s1.[0.5+], 0), 
        IFNULL(s2.MD_HT, 0), IFNULL(s2.[0.5+], 0),
        -- NOVOS CAMPOS (MDM_HT)
        IFNULL(g1.MDM_HT, 0), IFNULL(g2.MDM_HT, 0), -- Médias Gerais
        IFNULL(s1.MDM_HT, 0), IFNULL(s2.MDM_HT, 0)  -- Médias Local (Casa/Fora)
    FROM JOGOS_HOJE j
    LEFT JOIN STATS_GOLS_HT g1 ON j.ID_Home = g1.ID_Equipe AND j.ID_Liga = g1.ID_Liga
    LEFT JOIN STATS_GOLS_HT g2 ON j.ID_Away = g2.ID_Equipe AND j.ID_Liga = g2.ID_Liga
    LEFT JOIN STATS_GOLS_HT_CASA s1 ON j.ID_Home = s1.ID_Equipe AND j.ID_Liga = s1.ID_Liga
    LEFT JOIN STATS_GOLS_HT_FORA s2 ON j.ID_Away = s2.ID_Equipe AND j.ID_Liga = s2.ID_Liga
    WHERE j.ID_Fixture = ?
    """
    cursor.execute(query, (fixture_id,))
    row = cursor.fetchone()
    conn.close()
    return row

def get_live_stats_msg(fixture_id):
    url = f"https://v3.football.api-sports.io/fixtures/statistics?fixture={fixture_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10, verify=False).json()
        if not res.get('response'): return "⚠️ Sem dados live (_jogo com alta expectativa pré-game, Verificar estatistica da partida para entrada_)"
        msg = ""
        for team in res['response']:
            t_name = team['team']['name']
            s = {st['type']: st['value'] for st in team['statistics']}
            chutes = s.get('Total Shots') or 0
            alvo = s.get('Shots on Goal') or 0
            cantos = s.get('Corner Kicks') or 0
            msg += f" {t_name}: 🏹{chutes} (🎯{alvo}) | 🚩{cantos}\n"
        return msg
    except: return "⚠️ Erro ao buscar stats live"

# --- VERIFICADOR DE RESULTADOS ---

def verificar_resultados_no_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Busca apenas alertas PENDENTES deste bot específico
    cursor.execute("""
        SELECT ID_Fixture, ID_Mensagem_Telegram, Corpo_Mensagem 
        FROM ALERTAS_DISPARADOS 
        WHERE Status = 'PENDENTE' AND Name_Bot = ?
    """, (NOME_DO_BOT,))
    
    pendentes = cursor.fetchall()
    if not pendentes:
        conn.close()
        return

    for jogo in pendentes:
        fid, m_id, corpo_original = jogo
        url = f"https://v3.football.api-sports.io/fixtures?id={fid}"
        try:
            res = requests.get(url, headers=HEADERS, timeout=10, verify=False).json()
            if res.get('response'):
                dados = res['response'][0]
                g_h = dados['goals']['home'] or 0
                g_a = dados['goals']['away'] or 0
                status_jogo = dados['fixture']['status']['short']

                if (g_h + g_a) > 0:
                    atualizar_telegram(m_id, f"✅ **GREEN VOLUME HT!** 🎯\n\n{corpo_original}\n\n🔢 **Placar: {g_h}x{g_a}**")
                    cursor.execute("UPDATE ALERTAS_DISPARADOS SET Status = 'GREEN' WHERE ID_Fixture = ? AND Name_Bot = ?", (fid, NOME_DO_BOT))
                elif status_jogo in ['HT', '2H', 'FT']:
                    atualizar_telegram(m_id, f"❌ **RED VOLUME HT**\n\n{corpo_original}\n\n🔢 **Placar HT: 0x0**")
                    cursor.execute("UPDATE ALERTAS_DISPARADOS SET Status = 'RED' WHERE ID_Fixture = ? AND Name_Bot = ?", (fid, NOME_DO_BOT))
                conn.commit()
        except: continue
    conn.close()

# --- EMISSÃO DE ALERTA ---

def emitir_alerta_beta_full(f, s):
    # s[2] = Média Total HT Geral do Time Casa (ex: 1.47)
    # s[4] = Média Total HT Geral do Time Fora (ex: 1.19)
    # s[6] = Média Total HT Casa do Time Casa (ex: 1.62)
    # s[8] = Média Total HT Fora do Time Fora (ex: 1.00)
    
    # Cálculo Geral: Média das médias totais das duas equipes
    md_geral = (s[2] + s[4]) / 2
    # Cálculo Local: Média das médias específicas (Casa do mandante e Fora do visitante)
    md_local = (s[6] + s[8]) / 2
    
    # Para a Probabilidade (Frequência % +0.5 HT), a lógica é a mesma:
    # (Frequência Time A + Frequência Time B) / 2
    prob_geral = (s[3] + s[5]) / 2
    prob_local = (s[7] + s[9]) / 2

    live_info = get_live_stats_msg(f['fixture']['id'])

    # PEGANDO DIRETO DA API (Objeto f)
    nome_liga = f['league']['name']
    nome_pais = f['league']['country']

    corpo = (
        f"🏟  Jogo: {s[0]} x {s[1]}\n"
        f"🌍 {nome_pais} - {nome_liga}\n"
        f"⏰ Minuto: {f['fixture']['status']['elapsed']}' | 🔢 0x0\n"
        f"{'='*25}\n"
        f"📊 *Live Stats:*\n{live_info}"
        f"{'='*25}\n"
        f"📈 *Pré-Jogo (Volume):*\n"
        f"🌍 Geral: {md_geral:.2f} / {prob_geral:.1f}%\n"
        f"🏠 Local: {md_local:.2f} / {prob_local:.1f}%"
    )

    print("\n🚀 ALERTA BETA GERADO \n" + corpo)
    m_id = enviar_telegram(f"🔥 *BETA: ALERTA PRÉ DE VOLUME GOL HT*\n\n{corpo}")
    if m_id:
        salvar_alerta_db(f, s, m_id, corpo) # Substituiu a lista pelo DB

# --- LOOP PRINCIPAL ---
if __name__ == "__main__":
    cache_beta = set()
    SEC_BUSCA = 450  
    SEC_CHECK = 300  
    contador_check = 0
    print(f"🚀 {NOME_DO_BOT} INICIADO (Volume HT)...")

    while True:
        horario = datetime.datetime.now().strftime("%H:%M:%S")
        try:
            # 1. BUSCA DE JOGOS
            url = "https://v3.football.api-sports.io/fixtures?live=all"
            res = requests.get(url, headers=HEADERS, timeout=10, verify=False).json()
            jogos = res.get('response', [])
            
            monitorados = 0
            for f in jogos:
                tempo = f['fixture']['status'].get('elapsed')
                gols_h, gols_a = f['goals'].get('home'), f['goals'].get('away')
                fid = f['fixture']['id']

                if tempo and 12 <= tempo <= 15 and gols_h == 0 and gols_a == 0:
                    if fid not in cache_beta:
                        s = get_db_stats_full(fid)
                        if s:
                            # --- MEDIA GOLS HT ---
                            md_g, pr_g = (s[2]+s[4])/2, (s[3]+s[5])/2
                            md_l, pr_l = (s[6]+s[8])/2, (s[7]+s[9])/2
                            # --- GOLS MARCADOS (MDM_HT) ---
                            mdm_geral = (s[10] + s[11]) / 2
                            mdm_local = (s[12] + s[13]) / 2

                            # CRITÉRIO AND (As duas métricas juntas)
                            # CRITÉRIO AND (Volume + Probabilidade + Gols Marcados)
                            volume_ok = (md_g >= 1.25 and pr_g >= 73) and (md_l >= 1.25 and pr_l >= 73)
                            gols_marcados_ok = (mdm_geral >= 0.71 and mdm_local >= 0.71)

                            if volume_ok and gols_marcados_ok:
                                monitorados += 1
                                emitir_alerta_beta_full(f, s)
                                cache_beta.add(fid)

            print(f"[{horario}] 📡 Live: {len(jogos)} | 🎯 Alertas: {monitorados}")

            # 2. CONTROLE DE TEMPO E AUDITORIA
            time.sleep(SEC_BUSCA)
            contador_check += SEC_BUSCA

            if contador_check >= SEC_CHECK:
                print(f"\n[{horario}] 🏁 Verificando resultados no DB...")
                verificar_resultados_no_db()
                contador_check = 0

        except Exception as e:
            print(f"\nErro no loop: {e}")
            time.sleep(30)