import requests
import sqlite3
import csv
import time
from datetime import datetime, timedelta
from tkinter import filedialog, Tk

# --- CONFIGURAÇÕES ---
API_KEY = "a36c5f2f632e860640988e5e0fb8f7bb"
HEADERS = {'x-apisports-key': API_KEY}
BANCO = 'FutebolStatsJnr.db'


def conectar():
    conn = sqlite3.connect(BANCO)
    cursor = conn.cursor()
    # Garante a tabela de LOG
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS LOG_ATUALIZACAO (
            ID_Liga INTEGER PRIMARY KEY,
            Ultima_Atualizacao TEXT NOT NULL
        )
    ''')
    conn.commit()
    return conn

def selecionar_arquivo():
    root = Tk(); root.withdraw()
    caminho = filedialog.askopenfilename(title="Selecione o CSV das Ligas", filetypes=[("CSV", "*.csv")])
    root.destroy(); return caminho

def pode_atualizar_liga(id_liga, cursor):
    cursor.execute("SELECT Ultima_Atualizacao FROM LOG_ATUALIZACAO WHERE ID_Liga = ?", (id_liga,))
    resultado = cursor.fetchone()
    if not resultado: return True 
    data_log = datetime.strptime(resultado[0], '%Y-%m-%d')
    return (datetime.now() - data_log).days >= 3

def registrar_log(id_liga, cursor):
    hoje_str = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("INSERT OR REPLACE INTO LOG_ATUALIZACAO (ID_Liga, Ultima_Atualizacao) VALUES (?, ?)", (id_liga, hoje_str))

def buscar_posicoes_liga(id_liga, temporada):
    url = f"https://v3.football.api-sports.io/standings?league={id_liga}&season={temporada}"
    try:
        res = requests.get(url, headers=HEADERS).json()
        standings = res['response'][0]['league']['standings'][0]
        return {team['team']['name']: team['rank'] for team in standings}
    except: return {}

def buscar_odds_vitoria(id_fixture):
    url = f"https://v3.football.api-sports.io/odds?fixture={id_fixture}&bookmaker=8&bet=1"
    odds = {'home': 0.0, 'draw': 0.0, 'away': 0.0}
    try:
        res = requests.get(url, headers=HEADERS).json()
        values = res['response'][0]['bookmakers'][0]['bets'][0]['values']
        for val in values:
            if val['value'] == 'Home': odds['home'] = float(val['odd'])
            elif val['value'] == 'Draw': odds['draw'] = float(val['odd'])
            elif val['value'] == 'Away': odds['away'] = float(val['odd'])
    except: pass
    return odds

# =========================================================
# LÓGICA DE MIGRAÇÃO (ECONOMIA DE API)
# =========================================================
def migrar_jogos_amanha_para_hoje(cursor):
    # Verifica se a tabela AMANHA tem dados
    cursor.execute("SELECT COUNT(*) FROM JOGOS_AMANHA")
    total_amanha = cursor.fetchone()[0]

    if total_amanha > 0:
        print(f"🔄 Movendo {total_amanha} jogos de 'Amanhã' para 'Hoje' via DB...")
        cursor.execute("DELETE FROM JOGOS_HOJE")
        cursor.execute("INSERT INTO JOGOS_HOJE SELECT * FROM JOGOS_AMANHA")
        cursor.execute("DELETE FROM JOGOS_AMANHA")
        return True # Indica que houve migração
    else:
        print("⚠️ Tabela 'Amanhã' vazia. O script buscará os dados de 'Hoje' na API.")
        return False # Indica que precisamos buscar 'Hoje' na API também

# =========================================================
# PROCESSAMENTO DE ESTATÍSTICAS (MALEÁVEL)
# =========================================================
def processar_e_salvar_stats(id_liga, nome_liga, pais, temporada, cursor, ignorar_log=False):
    if not ignorar_log and not pode_atualizar_liga(id_liga, cursor):
        print(f"⏩ Pulando: {nome_liga} (Atualizada há menos de 3 dias).")
        return
    
    # --- NOVO: LIMPEZA PREVENTIVA DA LIGA ---
    # Isso garante que não sobrem times que mudaram de nome ou IDs duplicados
    tabelas_para_limpar = [
        "STATS_GOLS", "STATS_GOLS_CASA", "STATS_GOLS_FORA",
        "STATS_GOLS_HT", "STATS_GOLS_HT_CASA", "STATS_GOLS_HT_FORA",
        "STATS_BTTS", "STATS_BTTS_CASA", "STATS_BTTS_FORA",
        "STATS_CLEAN_SHEETS", "STATS_CLEAN_SHEETS_CASA", "STATS_CLEAN_SHEETS_FORA"
    ]
    for tabela in tabelas_para_limpar:
        cursor.execute(f"DELETE FROM {tabela} WHERE ID_Liga = ?", (id_liga,))

    cursor.connection.commit()
    # ---------------------------------------

    print(f"📡 Processando: {pais} > {nome_liga}...")
    
    cursor.execute('''
        INSERT OR REPLACE INTO LIGAS (ID_Liga, Liga, Pais, Temporada) VALUES (?, ?, ?, ?)
    ''', (id_liga, nome_liga, pais, temporada))
    
    url = f"https://v3.football.api-sports.io/fixtures?league={id_liga}&season={temporada}"
    fixtures = requests.get(url, headers=HEADERS).json().get('response', [])
    if not fixtures: return

    dados_times = {}
    for fxt in fixtures:
        if fxt['fixture']['status']['short'] == 'FT':
            h_name, a_name = fxt['teams']['home']['name'], fxt['teams']['away']['name']
            h_id, a_id = fxt['teams']['home']['id'], fxt['teams']['away']['id']
            gh, ga = fxt['goals']['home'], fxt['goals']['away']
            hth, hta = fxt['score']['halftime']['home'], fxt['score']['halftime']['away']

            # Adicionamos o campo 'mando' para saber se foi casa ou fora
            if h_name not in dados_times: dados_times[h_name] = {'id': h_id, 'jogos': []}
            dados_times[h_name]['jogos'].append({'gp': gh, 'gc': ga, 'gph': hth, 'gch': hta, 'mando': 'CASA'})

            if a_name not in dados_times: dados_times[a_name] = {'id': a_id, 'jogos': []}
            dados_times[a_name]['jogos'].append({'gp': ga, 'gc': gh, 'gph': hta, 'gch': hth, 'mando': 'FORA'})

    for equipe, info in dados_times.items():
        id_equipe = info['id']
        
        # --- DEFINIÇÃO DOS 3 GRUPOS DE JOGOS ---
        jogos_geral = info['jogos']
        jogos_casa = [j for j in jogos_geral if j['mando'] == 'CASA']
        jogos_fora = [j for j in jogos_geral if j['mando'] == 'FORA']

        # Lista de configurações para rodar o mesmo cálculo nas 3 variações
        config_tabelas = [
            (jogos_geral, "STATS_GOLS", "STATS_GOLS_HT", "STATS_BTTS", "STATS_CLEAN_SHEETS"),
            (jogos_casa, "STATS_GOLS_CASA", "STATS_GOLS_HT_CASA", "STATS_BTTS_CASA", "STATS_CLEAN_SHEETS_CASA"),
            (jogos_fora, "STATS_GOLS_FORA", "STATS_GOLS_HT_FORA", "STATS_BTTS_FORA", "STATS_CLEAN_SHEETS_FORA")
        ]

        for lista_j, tab_ft, tab_ht, tab_btts, tab_cs in config_tabelas:
            if not lista_j: continue # Pula se não houver jogos (ex: time que ainda não jogou fora)
            
            total = len(lista_j)
            g_feitos = sum(j['gp'] for j in lista_j); g_sofridos = sum(j['gc'] for j in lista_j)
            tot_ft = [j['gp'] + j['gc'] for j in lista_j]
            
            jogos_ht = [j for j in lista_j if j['gph'] is not None]
            total_ht = len(jogos_ht) if jogos_ht else 1
            gh_feitos = sum(j['gph'] for j in jogos_ht); gh_sofridos = sum(j['gch'] for j in jogos_ht)
            tot_ht = [j['gph'] + j['gch'] for j in jogos_ht]

            # 1. FT
            cursor.execute(f'''
                INSERT OR REPLACE INTO {tab_ft} (ID_Liga, ID_Equipe, Equipe, Jogos, MDM, MDS, MD, "0.5+", "1.5+", "2.5+", "3.5+", "4.5+", BTS, CS)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (id_liga, id_equipe, equipe, total, round(g_feitos/total, 2), round(g_sofridos/total, 2), round(sum(tot_ft)/total, 2),
                  round((len([g for g in tot_ft if g > 0.5])/total)*100, 1), round((len([g for g in tot_ft if g > 1.5])/total)*100, 1),
                  round((len([g for g in tot_ft if g > 2.5])/total)*100, 1), round((len([g for g in tot_ft if g > 3.5])/total)*100, 1),
                  round((len([g for g in tot_ft if g > 4.5])/total)*100, 1), round((len([j for j in lista_j if j['gp']>0 and j['gc']>0])/total)*100, 1),
                  round((len([j for j in lista_j if j['gc']==0])/total)*100, 1)))

            # 2. HT
            cursor.execute(f'''
                INSERT OR REPLACE INTO {tab_ht} (ID_Liga, ID_Equipe, Equipe, Jogos, MDM_HT, MDS_HT, MD_HT, "0.5+", "1.5+", BTS_HT, CS_HT)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (id_liga, id_equipe, equipe, total_ht, round(gh_feitos/total_ht, 2), round(gh_sofridos/total_ht, 2), round(sum(tot_ht)/total_ht, 2),
                  round((len([g for g in tot_ht if g > 0.5])/total_ht)*100, 1), round((len([g for g in tot_ht if g > 1.5])/total_ht)*100, 1),
                  round((len([j for j in jogos_ht if j['gph']>0 and j['gch']>0])/total_ht)*100, 1), round((len([j for j in jogos_ht if j['gch']==0])/total_ht)*100, 1)))

            # 3. BTTS
            cursor.execute(f'INSERT OR REPLACE INTO {tab_btts} (ID_Liga, ID_Equipe, Equipe, BTS, Total_de_jogos, Percentual) VALUES (?, ?, ?, ?, ?, ?)',
                           (id_liga, id_equipe, equipe, len([j for j in lista_j if j['gp']>0 and j['gc']>0]), total, round((len([j for j in lista_j if j['gp']>0 and j['gc']>0])/total)*100, 1)))
            
            # 4. CLEAN SHEETS
            cursor.execute(f'INSERT OR REPLACE INTO {tab_cs} (ID_Liga, ID_Equipe, Equipe, CS, Total_de_Jogos, Percentual) VALUES (?, ?, ?, ?, ?, ?)',
                           (id_liga, id_equipe, equipe, len([j for j in lista_j if j['gc']==0]), total, round((len([j for j in lista_j if j['gc']==0])/total)*100, 1)))

    registrar_log(id_liga, cursor)
# =========================================================
# ATUALIZA ENCERRADOS
# =========================================================
def arquivar_resultados_hoje(cursor):
    import pytz
    import requests
    from datetime import datetime

    fuso_br = pytz.timezone('America/Sao_Paulo')
    
    # 1. Buscamos TODOS os campos da JOGOS_HOJE para transferir
    cursor.execute("""
        SELECT ID_Fixture, Hora, Liga_Nome, ID_Liga, Home_Team, ID_Home, Away_Team, ID_Away, Odd_Home, Odd_Away
        FROM JOGOS_HOJE
    """)
    jogos_hoje = cursor.fetchall()
    
    if not jogos_hoje:
        print("⚠️ Sem jogos em 'Hoje' para arquivar.")
        return

    for jogo in jogos_hoje:
        # Desempacotando o que já temos no banco (Link de colunas)
        # Link de colunas do banco local
        f_id, hora_db, liga_nome_db, id_liga_db, home_db, id_home_db, away_db, id_away_db, o_home_db, o_away_db = jogo
        
        print(f"🔄 Processando: {home_db} x {away_db}...")

        # 2. Buscamos na API apenas os dados de desfecho (Gols, Eventos e Odds)
        url = f"https://v3.football.api-sports.io/fixtures?id={f_id}"
        
        try:
            res = requests.get(url, headers=HEADERS).json()
            if not res.get('response'): continue
            
            item = res['response'][0]
            status = item['fixture']['status']['short']

            # Só move para Encerrados se o jogo acabou
            if status in ['FT', 'AET', 'PEN']:
                
                # Dados que SÓ a API tem agora (Gols e Minutagem)
                gh_ht, ga_ht = item['score']['halftime']['home'], item['score']['halftime']['away']
                gh_ft, ga_ft = item['goals']['home'], item['goals']['away']
                
                vencedor = 'Draw'
                if gh_ft > ga_ft: vencedor = 'Home'
                elif ga_ft > gh_ft: vencedor = 'Away'

                # Minutagem extraída dos eventos da API
                events = item.get('events', [])
                gols_h = [f"{e['time']['elapsed']}'" for e in events if e.get('type') == 'Goal' and e.get('team', {}).get('id') == id_home_db]
                gols_a = [f"{e['time']['elapsed']}'" for e in events if e.get('type') == 'Goal' and e.get('team', {}).get('id') == id_away_db]
                minutagem = f"{', '.join(gols_h)} | {', '.join(gols_a)}"

                # Data corrigida para o fuso Brasil
                dt_utc = datetime.fromisoformat(item['fixture']['date'].replace('Z', '+00:00'))
                data_br = dt_utc.astimezone(fuso_br).strftime('%Y-%m-%d')

                # 3. INSERT OR REPLACE Unificado
                # Aqui o link é total: Dados fixos e Odds do DB + Gols e Data da API
                cursor.execute("""
                    INSERT OR REPLACE INTO JOGOS_ENCERRADOS 
                    (ID_Fixture, Data, Hora, Liga, ID_Liga, Home_Team, ID_Home, Away_Team, ID_Away, 
                     Gols_Home_HT, Gols_Away_HT, Gols_Home_FT, Gols_Away_FT, Minutagem_Gols, Vencedor, Odd_Home, Odd_Away)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f_id,           # ID
                    data_br,        # Data (API corrigida)
                    hora_db,        # Hora (Link DB)
                    liga_nome_db,   # Liga (Link DB)
                    id_liga_db,     # ID_Liga (Link DB)
                    home_db,        # Home (Link DB)
                    id_home_db,     # ID_Home (Link DB)
                    away_db,        # Away (Link DB)
                    id_away_db,     # ID_Away (Link DB)
                    gh_ht, ga_ht,   # HT (API)
                    gh_ft, ga_ft,   # FT (API)
                    minutagem,      # Gols (API)
                    vencedor,       # Cálculo
                    o_home_db,      # Odd_Home (Link DB direto!)
                    o_away_db       # Odd_Away (Link DB direto!)
                ))
                
                # 4. Remove do Hoje para manter o fluxo limpo
                cursor.execute("DELETE FROM JOGOS_HOJE WHERE ID_Fixture = ?", (f_id,))
                print(f"✅ {home_db} x {away_db} movido para Encerrados.")

        except Exception as e:
            print(f"❌ Erro ao processar o link do jogo {f_id}: {e}")

# =========================================================
# SINCRONIZAÇÃO V5 (HOJE E AMANHÃ)
# =========================================================
def inserir_jogo_tabela(dados, tabela, cursor):
    """
    Insere ou atualiza um jogo em uma tabela específica (JOGOS_HOJE ou JOGOS_AMANHA)
    """
    sql = f'''
        INSERT OR REPLACE INTO {tabela} (ID_Fixture, Hora, ID_Liga, Liga_Nome, ID_Home, Home_Team, ID_Away, Away_Team, Pos_Home, Pos_Away, Odd_Home, Odd_Away, Odd_Draw) 
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    '''
    cursor.execute(sql, dados)


def rodar_automatico_dia():
    conn = conectar(); cursor = conn.cursor()
    
    # 1. Busca as ligas configuradas
    cursor.execute("SELECT ID_Liga, Liga, Pais, Temporada FROM LIGAS")
    ligas_db = {l[0]: {'nome': l[1], 'pais': l[2], 'temporada': l[3]} for l in cursor.fetchall()}
    
    import pytz
    from datetime import datetime, timedelta
    fuso_br = pytz.timezone('America/Sao_Paulo')
    agora_br = datetime.now(fuso_br)
    
    # PASSO A: Arquiva o 'Hoje' (Busca resultados na API e salva em ENCERRADOS)
    arquivar_resultados_hoje(cursor)
    conn.commit()

    # PASSO B: Amanhã -> Hoje (Migração interna do DB)
    # Note que a função migrar_jogos_amanha_para_hoje já faz o DELETE em JOGOS_HOJE
    houve_migracao = migrar_jogos_amanha_para_hoje(cursor)
    conn.commit()

    # PASSO C: Preparação para buscar novos dados (Amanhã)
    cursor.execute("SELECT COUNT(*) FROM JOGOS_HOJE")
    total_hoje = cursor.fetchone()[0]

    janelas_busca = []
    
    # Se a tabela de HOJE ainda está vazia após a migração, buscamos na API
    if total_hoje == 0:
        print("⚠️ Tabela de HOJE vazia. Adicionando dia atual na busca...")
        hoje_br_inicio = agora_br.replace(hour=0, minute=0, second=0, microsecond=0)
        janelas_busca.append(hoje_br_inicio)
    
    # Sempre buscamos o AMANHÃ para manter o fluxo
    amanha_br_inicio = (agora_br + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    janelas_busca.append(amanha_br_inicio)

    jogos_novos = []
    ids_atualizar_stats = set()
    cache_pos = {}

    # 3. LOOP DE CAPTURA POR JANELA (Hoje e/ou Amanhã)
    for data_referencia in janelas_busca:
        janela_inicio = data_referencia
        janela_fim = janela_inicio + timedelta(hours=23, minutes=59, seconds=59)
        
        # Define em qual tabela salvar com base na data da janela
        tabela_destino = "JOGOS_HOJE" if janela_inicio.date() == agora_br.date() else "JOGOS_AMANHA"
        
        print(f"\n--- SINCRONIZANDO {tabela_destino} (BR: {janela_inicio.strftime('%d/%m')}) ---")

        # Para cobrir as 24h BR, pedimos o dia da janela e o próximo para a API
        dias_api = [
            janela_inicio.strftime('%Y-%m-%d'),
            (janela_inicio + timedelta(days=1)).strftime('%Y-%m-%d')
        ]

        for d_api in dias_api:
            print(f"📡 Consultando API para data: {d_api}...")
            url = f"https://v3.football.api-sports.io/fixtures?date={d_api}"
            try:
                res = requests.get(url, headers=HEADERS).json()
                fixtures = res.get('response', [])
            except Exception as e:
                print(f"❌ Erro na API: {e}")
                continue

            for item in fixtures:
                dt_utc = datetime.fromisoformat(item['fixture']['date'].replace('Z', '+00:00'))
                dt_br = dt_utc.astimezone(fuso_br)
                
                # FILTRO DE FUSO: O jogo pertence a ESTA janela de 24h?
                if janela_inicio <= dt_br <= janela_fim:
                    id_api_liga = item['league']['id']
                    
                    if id_api_liga in ligas_db:
                        id_fix = item['fixture']['id']
                        th, ta = item['teams']['home']['name'], item['teams']['away']['name']
                        idh, ida = item['teams']['home']['id'], item['teams']['away']['id']
                        
                        if id_api_liga not in cache_pos:
                            cache_pos[id_api_liga] = buscar_posicoes_liga(id_api_liga, ligas_db[id_api_liga]['temporada'])
                        
                        odds = buscar_odds_vitoria(id_fix); time.sleep(0.4)
                        hora_formatada = dt_br.strftime('%H:%M')
                        
                        dados_jogo = (
                            id_fix, hora_formatada, id_api_liga, item['league']['name'], 
                            idh, th, ida, ta, 
                            cache_pos[id_api_liga].get(th, 0), cache_pos[id_api_liga].get(ta, 0), 
                            odds['home'], odds['away'], odds['draw']
                        )
                        
                        # Salva na tabela correta (Hoje ou Amanhã)
                        inserir_jogo_tabela(dados_jogo, tabela_destino, cursor)
                        ids_atualizar_stats.add(id_api_liga)
                        print(f"✅ [{tabela_destino}] {hora_formatada} - {th} x {ta}")
        conn.commit()

    # 4. ATUALIZAÇÃO DE STATS (MANTÉM TRAVA DE 3 DIAS)
    print("\n📊 Verificando necessidade de atualização de médias...")
    for id_l in ids_atualizar_stats:
        processar_e_salvar_stats(
            id_l, ligas_db[id_l]['nome'], ligas_db[id_l]['pais'], 
            ligas_db[id_l]['temporada'], cursor, ignorar_log=False
        )
        conn.commit()
            
    conn.close()
    print("✨ Processo concluído com sucesso!")

def rodar_via_csv():
    path = selecionar_arquivo()
    if not path: return
    conn = conectar(); cursor = conn.cursor()
    with open(path, 'r', encoding='utf-8') as f:
        for linha in csv.DictReader(f):
            processar_e_salvar_stats(linha['ID_LIGA'], linha['NOME_LIGA'], linha['PAIS'], linha['TEMPORADA'], cursor, ignorar_log=True)
            conn.commit(); time.sleep(1.8)
    conn.close(); print("🚀 CSV Concluído!")

import sys

if __name__ == "__main__":
    # Quando rodar no GitHub, ele vai direto para a atualização automática
    rodar_automatico_dia()
