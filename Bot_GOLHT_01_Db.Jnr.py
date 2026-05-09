import sqlite3
import requests
import time
import datetime
import urllib3
import os

# Silenciar avisos de SSL se necessário
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- CONFIGURAÇÕES ---
API_KEY = "a36c5f2f632e860640988e5e0fb8f7bb"
DB_NAME = r'C:\Users\Jair1\FutebolStatsJnr.db'
HEADERS = {'x-rapidapi-key': API_KEY, 'x-rapidapi-host': 'v3.football.api-sports.io'}
TELEGRAM_TOKEN = "8620904348:AAEAolwJk6dP7I_RVvOpNhDPRNBCR0tG-I4"
TELEGRAM_CHAT_ID = "2083277600"
# Captura apenas o nome do arquivo (ex: Bot_Volume_HT.py)
NOME_DO_BOT = os.path.basename(__file__)

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, data=payload, timeout=10).json()
        if r.get('ok'):
            return r['result']['message_id'] # Retorna o ID da mensagem para edição futura
    except Exception as e:
        print(f"Erro ao enviar Telegram: {e}")
    return None

def atualizar_telegram(message_id, novo_texto):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "message_id": message_id,
        "text": novo_texto,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Erro ao editar mensagem: {e}")

# --- MOTOR DE RESULTADOS (GREEN/RED) ---

def verificar_resultados_no_db():
    # Usar 'with' garante que a conexão feche mesmo se houver erro
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        
        # Busca apenas o que este bot disparou e ainda não processou
        cursor.execute("""
            SELECT ID_Fixture, ID_Mensagem_Telegram, Corpo_Mensagem 
            FROM ALERTAS_DISPARADOS 
            WHERE Status = 'PENDENTE' AND Name_Bot = ?
        """, (NOME_DO_BOT,))
        
        pendentes = cursor.fetchall()

        if not pendentes:
            return

        print(f"\n[AUDITORIA] {NOME_DO_BOT}: Verificando {len(pendentes)} jogos...")

        for jogo in pendentes:
            fid, m_id, corpo_orig = jogo
            url_audit = f"https://v3.football.api-sports.io/fixtures?id={fid}"
            
            try:
                # Timeout menor para não travar o bot principal
                r_audit = requests.get(url_audit, headers=HEADERS, timeout=10, verify=False).json()
                
                if r_audit.get('response'):
                    detalhes = r_audit['response'][0]
                    g_h = detalhes.get('goals', {}).get('home') or 0
                    g_a = detalhes.get('goals', {}).get('away') or 0
                    status_j = detalhes['fixture']['status']['short']
                    placar = f"{g_h}x{g_a}"

                    # 1. GREEN
                    if (g_h + g_a) > 0:
                        msg_g = f"✅ **GREEN: GOL CONFIRMADO!** 🎯\n\n{corpo_orig}\n\n🔢 **Placar: {placar}**"
                        atualizar_telegram(m_id, msg_g)
                        # FILTRO DUPLO NO UPDATE É A CHAVE DO SUCESSO
                        cursor.execute("UPDATE ALERTAS_DISPARADOS SET Status = 'GREEN' WHERE ID_Fixture = ? AND Name_Bot = ?", (fid, NOME_DO_BOT))
                        print(f"✅ {NOME_DO_BOT} | Jogo {fid} -> GREEN.")
                    
                    # 2. RED
                    elif status_j in ['HT', '2H', 'FT']:
                        msg_r = f"❌ **RED: SEM GOL NO HT**\n\n{corpo_orig}\n\n🔢 **Placar HT: 0x0**"
                        atualizar_telegram(m_id, msg_r)
                        cursor.execute("UPDATE ALERTAS_DISPARADOS SET Status = 'RED' WHERE ID_Fixture = ? AND Name_Bot = ?", (fid, NOME_DO_BOT))
                        print(f"❌ {NOME_DO_BOT} | Jogo {fid} -> RED.")
                    
                    conn.commit() # Salva cada jogo individualmente
                    
            except Exception as e:
                print(f"⚠️ Erro no jogo {fid} ({NOME_DO_BOT}): {e}")
                continue

def salvar_alerta_db(f, s_db, m_id, corpo):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Prepara os dados para o INSERT
    dados = (
        f['fixture']['id'],       # ID_Fixture
        NOME_DO_BOT,              # Nome do arquivo que disparou
        f['teams']['home']['id'], # ID_Home
        s_db[0],                  # Home_Team (Vem do seu SELECT)
        f['teams']['away']['id'], # ID_Away
        s_db[1],                  # Away_Team (Vem do seu SELECT)
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
    print(f"💾 Alerta salvo no DB pelo bot: {NOME_DO_BOT}")

def get_db_stats(fixture_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    query = """
    SELECT 
        j.Home_Team, j.Away_Team,
        IFNULL(g1.MD_HT, 0), IFNULL(g1.[0.5+], 0), 
        IFNULL(g2.MD_HT, 0), IFNULL(g2.[0.5+], 0),
        IFNULL(s1.MD_HT, 0), IFNULL(s1.[0.5+], 0), 
        IFNULL(s2.MD_HT, 0), IFNULL(s2.[0.5+], 0),
        -- CAMPOS EXTRAS PARA O FILTRO DE GOLS MARCADOS (MDM_HT)
        IFNULL(g1.MDM_HT, 0), IFNULL(g2.MDM_HT, 0), -- Geral
        IFNULL(s1.MDM_HT, 0), IFNULL(s2.MDM_HT, 0)  -- Casa/Fora
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

def processar_estatisticas(fixture_id, tempo):
    url = f"https://v3.football.api-sports.io/fixtures/statistics?fixture={fixture_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10).json()
        if not res.get('response') or len(res['response']) < 2: 
            return None
        
        stats_data = {team['team']['name']: {st['type']: st['value'] for st in team['statistics']} for team in res['response']}
        
        total_eventos = 0
        total_chutes_alvo = 0
        total_escanteios = 0
        total_bloqueados = 0
        total_para_fora = 0

        for team in stats_data:
            st = stats_data[team]
            
            # 1. Dados para o Ritmo
            ch_totais = (st.get('Total Shots') or 0)
            escanteios = (st.get('Corner Kicks') or 0)
            total_eventos += (ch_totais + escanteios)
            
            # 2. Dados para Critérios Obrigatórios
            total_chutes_alvo += (st.get('Shots on Goal') or 0)
            total_escanteios += escanteios
            
            # 3. Dados para o Novo Filtro (Bloqueados vs Fora)
            total_bloqueados += (st.get('Blocked Shots') or 0)
            total_para_fora += (st.get('Shots off Goal') or 0)

        # --- VALIDAÇÃO DOS CRITÉRIOS ---
        # A: Pelo menos 1 no alvo e 1 escanteio
        if total_chutes_alvo < 1 or total_escanteios < 1:
            return None

        # B: NOVO CRITÉRIO - Bloqueados NÃO pode ser maior que Chutes para Fora
        # Se Bloqueados > Para Fora, o jogo é descartado
        if total_bloqueados > total_para_fora:
            # print(f"DEBUG: Jogo com defesa muito fechada. Bloqueios({total_bloqueados}) > Fora({total_para_fora})")
            return None

        if total_eventos == 0: 
            return None
        
        ritmo = tempo / total_eventos
        
        if ritmo <= 2.0: 
            label = "🔥 MUITO QUENTE (Power Pressure)"
        elif ritmo <= 3.0: 
            label = "⚡ JOGO MOVIMENTADO"
        elif ritmo <= 3.6: 
            label = "👍🏻 RITMO OK"
        else: 
            label = "⚪ MORNO (MEDIAS PRE, BOA, MAS PARTIDA COM POUCA INTENSIDADE)"
            
        return stats_data, ritmo, label
    except Exception as e:
        return None

def emitir_alerta(f, s_live, s_db, ritmo, label):
    # BIP de atenção no PC
    if ritmo <= 2.0: print("\a\a\a") 
    else: print("\a")
        
    t1, t2 = s_db[0], s_db[1]
    st1 = s_live.get(t1, {})
    st2 = s_live.get(t2, {})
    
    def get_val(stats, key, default=0):
        val = stats.get(key)
        return val if val is not None else default

    # 1. Coleta de dados Live
    f1, f2 = get_val(st1, 'Total Shots'), get_val(st2, 'Total Shots')
    target1, target2 = get_val(st1, 'Shots on Goal'), get_val(st2, 'Shots on Goal')
    off1, off2 = get_val(st1, 'Shots off Goal'), get_val(st2, 'Shots off Goal')
    block1, block2 = get_val(st1, 'Blocked Shots'), get_val(st2, 'Blocked Shots')
    save1, save2 = get_val(st1, 'Goalkeeper Saves'), get_val(st2, 'Goalkeeper Saves')
    esc1, esc2 = get_val(st1, 'Corner Kicks'), get_val(st2, 'Corner Kicks')
    posse1, posse2 = get_val(st1, 'Ball Possession', "N/E"), get_val(st2, 'Ball Possession', "N/E")
    xg1, xg2 = get_val(st1, 'expected_goals', "N/E"), get_val(st2, 'expected_goals', "N/E")

    # 2. Cálculos das Médias Pré-Jogo (DB)
    md_g = (s_db[2] + s_db[4]) / 2
    pr_g = (s_db[3] + s_db[5]) / 2
    md_l = (s_db[6] + s_db[8]) / 2
    pr_l = (s_db[7] + s_db[9]) / 2

    # PEGANDO DIRETO DA API (Objeto f)
    nome_liga = f['league']['name']
    nome_pais = f['league']['country']

    # --- MONTAGEM DO CORPO ÚNICO DO ALERTA ---
    corpo_alerta = (
        f"🏟  Jogo: {t1} vs {t2}\n"
        f"🌍 {nome_pais} - {nome_liga}\n"
        f" ⏰ Minuto: {f['fixture']['status']['elapsed']}\n"
        f" 🔢 Placar: 0x0\n"
        f" {'='*28}\n"
        f" 📊 Estatísticas ao vivo:\n"

        f" 🏹 Finalizações: {f1} x {f2} = {f1+f2 if isinstance(f1, int) else 'N/E'}\n"
        f" 🎯 No Alvo: {target1} x {target2}\n"
        f" 📉 Para Fora: {off1} x {off2}\n"
        f" 🛡️ Bloqueados: {block1} x {block2}\n"
        f" 🧤 Defesas Goleiro: {save1} x {save2}\n"
        f" 🚩 Escanteios: {esc1} x {esc2}\n"
        f" ⚖️ Posse: {posse1} x {posse2}\n"
        f" 📈 xG Live: {xg1} x {xg2}\n"
        f" 📌 Ritmo: {ritmo:.2f} min/evento\n"
        f" 🌡️ Termometro: {label}\n"
        f" {'='*28}\n"

        f" 📊 Estatísticas pré-jogo:\n"

        f" 🌍 Geral: MD {md_g:.2f} | Prob {pr_g:.1f}%\n"
        f" 🏠 Local: MD {md_l:.2f} | Prob {pr_l:.1f}%"
    )

    # --- EXECUÇÃO ---
    
    # Print no Terminal
    print("\n" + "🚀" * 15)
    print(corpo_alerta)
    print("🚀" * 15 + "\n")

    # Envio para o Telegram (Markdown)
    # Envia e guarda o ID para o verificador de resultados
    m_id = enviar_telegram(f"🚀 *ALERTA PARA    GOL HT*\n\n{corpo_alerta}")
    if m_id:
    # Salva no Banco de Dados para que o verificador encontre o jogo
        salvar_alerta_db(f, s_db, m_id, corpo_alerta)

# --- LOOP PRINCIPAL ---
if __name__ == "__main__":
    cache_alertas = set()

    # Configurações de tempo (em segundos)
    SEC_BUSCA = 180  # 3 Minutos para novos jogos
    SEC_CHECK = 300  # 5 Minutos para conferir Green/Red
    contador_geral = 0

    print(f"🚀 {NOME_DO_BOT} INICIADO...")

    while True:
        horario = datetime.datetime.now().strftime("%H:%M:%S")
        
        try:
            # 1. BUSCA DE JOGOS E ALERTAS
            url = "https://v3.football.api-sports.io/fixtures?live=all"
            res = requests.get(url, headers=HEADERS, timeout=10).json()
            jogos_live = res.get('response', [])
            total_mundo = len(jogos_live)
            
            monitorados_agora = 0
            
            for f in jogos_live:
                fid = f['fixture']['id']
                tempo = f['fixture']['status'].get('elapsed')
                gols_h = f['goals'].get('home')
                gols_a = f['goals'].get('away')
                
                if fid in cache_alertas: continue
                # --- INICIALIZA AS VARIÁVEIS DE CONTROLE COMO FALSE ---
                volume_ok = False
                eficiencia_minima_ok = False

                # Janela de entrada 13-18
                if tempo and 13 <= tempo <= 17 and (gols_h == 0 and gols_a == 0):
                    if fid not in cache_alertas:
                        s_db = get_db_stats(fid)
                    
                        if s_db:
                            md_g, pr_g = (s_db[2] + s_db[4]) / 2, (s_db[3] + s_db[5]) / 2
                            md_l, pr_l = (s_db[6] + s_db[8]) / 2, (s_db[7] + s_db[9]) / 2
                            
                            # --- NOVO FILTRO DE SEGURANÇA (EFICIÊNCIA INDIVIDUAL) ---
                            # Pegamos os 4 valores individuais de gols marcados
                            # s_db[10]=Geral Mandante, s_db[11]=Geral Visitante, s_db[12]=Casa Mandante, s_db[13]=Fora Visitante
                            indices_marcados = [s_db[10], s_db[11], s_db[12], s_db[13]]

                            # O "any" garante que se AO MENOS UM desses 4 valores for >= 0.65, ele retorna True
                            eficiencia_minima_ok = any(valor >= 0.65 for valor in indices_marcados)

                            # Critério de Volume (que você já usava no Bot 01)
                            volume_ok = (md_g >= 1.00 and pr_g >= 66) and (md_l >= 1.00 and pr_l >= 66)

                            # SÓ PASSA SE TIVER VOLUME + TODO MUNDO MARCAR GOL (>= 0.65)
                            if volume_ok and eficiencia_minima_ok:
                                monitorados_agora += 1
                                resultado = processar_estatisticas(fid, tempo)

                                if resultado:
                                    s_live, ritmo, label = resultado
                                    if ritmo <= 4.5:
                                        # A função emitir_alerta agora deve alimentar a lista jogos_em_alerta
                                        emitir_alerta(f, s_live, s_db, ritmo, label)
                                        cache_alertas.add(fid)

            print(f"[{horario}] 📡 Mundo: {total_mundo} live | 🎯 Na Mira: {monitorados_agora} jogos...", end='\r')

            time.sleep(SEC_BUSCA)
            contador_geral += SEC_BUSCA
            
            # Se o tempo acumulado passou de 5 minutos (300s), rodamos a auditoria
            if contador_geral >= SEC_CHECK:
                verificar_resultados_no_db()
                contador_geral = 0 # Reinicia apenas o contador da auditoria

        except Exception as e:
            print(f"💥 ERRO NO LOOP: {e}")
            time.sleep(30)