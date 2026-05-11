import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import requests
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- CONEXÃO COM GOOGLE SHEETS E SQLITE ---
conn = st.connection("gsheets", type=GSheetsConnection)

if 'favoritos' not in st.session_state:
    st.session_state.favoritos = set()

if 'username' not in st.session_state:
    st.session_state.username = None

try:
    df = conn.read()
    st.success("Conectado!")
    st.write(df)
except Exception as e:
    st.error(e)
    
# --- FUNÇÃO DE SEGURANÇA (HASH) ---
def gerar_hash(senha):
    return hashlib.sha256(str.encode(senha)).hexdigest()

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Futebol Stats Jnr", layout="wide")

def salvar_favorito(fix_id):
    # 1. Atualiza no Sheets (Tabela 'FAVORITOS')
    # Supomos que sua função de salvar no sheets aceite o email do usuário e o ID
    email_usuario = st.session_state.get('usuario_email', 'convidado')
    
    # Aqui você chama sua função de escrita no Google Sheets
    # Exemplo: adicionar_linha_sheets("FAVORITOS", [email_usuario, fix_id])
    
    # 2. Mantém o SQLite como cache temporário (opcional)
    conn = sqlite3.connect('FutebolStatsJnr.db')
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO FAVORITOS (ID_Fixture) VALUES (?)", (fix_id,))
    conn.commit()
    conn.close()

def remover_favorito(fix_id):
    # 1. Remove do Sheets
    email_usuario = st.session_state.get('usuario_email', 'convidado')
    # Exemplo: remover_linha_sheets("FAVORITOS", email_usuario, fix_id)

    # 2. Remove do SQLite
    conn = sqlite3.connect('FutebolStatsJnr.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM FAVORITOS WHERE ID_Fixture = ?", (fix_id,))
    conn.commit()
    conn.close()
    
def atualizar_favoritos_sheets(fix_id, acao):
    # 1. Lê a base atual de favoritos
    df_atual = conn.read(worksheet="FAVORITOS")
    username = st.session_state.username

    if acao == "adicionar":
        # Cria uma nova linha
        nova_linha = pd.DataFrame([{"Username": username, "ID_Fixture": fix_id}])
        df_atual = pd.concat([df_atual, nova_linha], ignore_index=True)
    
    elif acao == "remover":
        # Remove a linha que contém o usuário AND o ID do jogo
        df_atual = df_atual[~((df_atual['Username'] == username) & (df_atual['ID_Fixture'] == fix_id))]

    # 2. Envia de volta para o Google Sheets
    conn.update(worksheet="FAVORITOS", data=df_atual)

@st.cache_data(ttl=3600)
def carregar_stats_completas_liga(id_liga):
    # Unificamos as 6 tabelas em uma única linha por time
    query = f"""
    SELECT 
        g.Equipe,
        g.MD AS MD_FT_Geral,
        gc.MD AS MD_FT_Casa,
        gf.MD AS MD_FT_Fora,
        ht.MD_HT AS MD_HT_Geral,
        htc.MD_HT AS MD_HT_Casa,
        htf.MD_HT AS MD_HT_Fora
    FROM STATS_GOLS g
    LEFT JOIN STATS_GOLS_CASA gc ON g.Equipe = gc.Equipe AND g.ID_Liga = gc.ID_Liga
    LEFT JOIN STATS_GOLS_FORA gf ON g.Equipe = gf.Equipe AND g.ID_Liga = gf.ID_Liga
    LEFT JOIN STATS_GOLS_HT ht ON g.Equipe = ht.Equipe AND g.ID_Liga = ht.ID_Liga
    LEFT JOIN STATS_GOLS_HT_CASA htc ON g.Equipe = htc.Equipe AND g.ID_Liga = htc.ID_Liga
    LEFT JOIN STATS_GOLS_HT_FORA htf ON g.Equipe = htf.Equipe AND g.ID_Liga = htf.ID_Liga
    WHERE g.ID_Liga = {id_liga}
    """
    df = carregar_dados(query) # Sua função que executa o SQL no SQLite
    
    # Transformamos em dicionário: { 'Nome do Time': { 'MD_FT_Geral': 1.5, ... }, ... }
    return df.set_index('Equipe').to_dict('index')

# --- FUNÇÕES DE DADOS ---
@st.cache_data(show_spinner=False)
def carregar_dados(query, params=None):
    conn = sqlite3.connect('FutebolStatsJnr.db')
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df

def buscar_stats_duplas(id_liga, time, mando):
    conn = sqlite3.connect('FutebolStatsJnr.db')
    sufixo = "_CASA" if mando == 'CASA' else "_FORA"
    df_ft_g = pd.read_sql('SELECT MDM, MDS, MD, BTS, CS, "2.5+" AS OVER_25_FT FROM STATS_GOLS WHERE ID_Liga = ? AND Equipe = ?', conn, params=(id_liga, time))
    df_ht_g = pd.read_sql('SELECT MDM_HT, MDS_HT, MD_HT, BTS_HT, CS_HT, "0.5+" AS OVER_05_HT FROM STATS_GOLS_HT WHERE ID_Liga = ? AND Equipe = ?', conn, params=(id_liga, time))
    df_ft_m = pd.read_sql(f'SELECT MDM, MDS, MD, BTS, CS, "2.5+" AS OVER_25_FT FROM STATS_GOLS{sufixo} WHERE ID_Liga = ? AND Equipe = ?', conn, params=(id_liga, time))
    df_ht_m = pd.read_sql(f'SELECT MDM_HT, MDS_HT, MD_HT, BTS_HT, CS_HT, "0.5+" AS OVER_05_HT FROM STATS_GOLS_HT{sufixo} WHERE ID_Liga = ? AND Equipe = ?', conn, params=(id_liga, time))
    conn.close()
    res = {"geral": {}, "mando": {}}
    if not df_ft_g.empty: res["geral"].update(df_ft_g.iloc[0].to_dict())
    if not df_ht_g.empty: res["geral"].update(df_ht_g.iloc[0].to_dict())
    if not df_ft_m.empty: res["mando"].update(df_ft_m.iloc[0].to_dict())
    if not df_ht_m.empty: res["mando"].update(df_ht_m.iloc[0].to_dict())
    return res

def buscar_data_atualizacao(id_liga):
    try:
        conn = sqlite3.connect('FutebolStatsJnr.db')
        cursor = conn.cursor()
        cursor.execute("SELECT Ultima_Atualizacao FROM LOG_ATUALIZACAO WHERE ID_Liga = ?", (int(id_liga),))
        resultado = cursor.fetchone()
        conn.close()
        if resultado and resultado[0]:
            data_log = datetime.strptime(resultado[0], '%Y-%m-%d')
            hoje = datetime.now()
            dias_passados = (hoje - data_log).days
            data_formatada = data_log.strftime('%d/%m/%Y')
            if dias_passados <= 2: return data_formatada, "date-safe"
            elif dias_passados <= 5: return data_formatada, "date-warning"
            else: return data_formatada, "date-danger"
        return "Sem dados", "date-danger"
    except:
        return "Erro", "date-danger"

# --- INICIALIZAÇÃO DO ESTADO ---
if 'pagina' not in st.session_state: st.session_state.pagina = 'logon'
if 'logado' not in st.session_state: st.session_state.logado = False
if 'user_id' not in st.session_state: st.session_state.user_id = None
if 'username' not in st.session_state: st.session_state.username = None

# --- ESTILIZAÇÃO CSS COMPLETA (MANTIDA 100%) ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Montserrat:wght@300;400&display=swap');
    @import url('https://fonts.googleapis.com/css2?family=Saira+Stencil:ital,wght@0,100..900;1,100..900&display=swap');

    .main-title { font-family: 'Bebas Neue', cursive; font-size: 105px !important; text-align: center; margin-bottom: -15px; line-height: 1; }
    .parte-cinza { color: #888888; }
    .parte-verde { color: #00FF7F; text-shadow: 0px 0px 20px rgba(0, 255, 127, 0.3); }
    .sub-title { font-family: "Saira Stencil", sans-serif; font-size: 26px !important; font-weight: 300; color: #AAAAAA; text-align: center; letter-spacing: 3px; text-transform: uppercase; margin-top: 5px; }
    
    .liga-header { text-align: center; background-color: #1E1E1E; color: #FFFFFF; padding: 4px; font-weight: bold; font-size: 22px; border-radius: 8px; margin-top: 5px; border: 1px solid #333; margin-bottom: -12.5px !important; }
    .stExpander { margin-bottom: -11px !important; border-radius: 5px !important; }
    
    div.stButton > button { background-color: #1E1E1E; color: white; border-radius: 6px; border: 2px solid #333; height: 3.5em; width: 100%; font-family: 'Montserrat', sans-serif; font-weight: bold; transition: 0.3s; }
    div.stButton > button:hover { border: 1px solid #00FF7F; color: #00FF7F; background-color: #1E1E1E; box-shadow: 0px 10px 15px rgba(0, 255, 127, 0.2); }
    
    .card-vs { text-align: center; font-size: 20px !important; font-weight: bold; color: #ff4b4b; }
    .team-name { font-size: 20px !important; font-weight: bold; }
    .odd-box { background-color: #262730; padding: 1px; border-radius: 8px; text-align: center; border: 1px solid #444; width: 100%; font-size: 15px !important; }
    .update-text-gray { color: #888888; font-style: italic; font-size: 11px; margin-top: -25px; margin-bottom: 20px; }
    .date-safe { color: #2ecc71; font-weight: bold; }
    .date-warning { color: #f39c12; font-weight: bold; }
    .date-danger { color: #e74c3c; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# =========================================================
# LÓGICA DE NAVEGAÇÃO DE PÁGINAS
# =========================================================

# --- FUNÇÃO PARA LER PLANILHA SEM ERRO HTTP ---
def ler_planilha():
    try:
        # Tenta pegar pela chave 'spreadsheet' que você já usava antes
        if "connections" in st.secrets and "gsheets" in st.secrets["connections"]:
            url = st.secrets["connections"]["gsheets"]["spreadsheet"].strip()
        else:
            # Se não achar, tenta pegar direto se você colocou sem hierarquia
            url = st.secrets["spreadsheet"].strip()

        # Lê a planilha forçando o cabeçalho na primeira linha
        df = pd.read_csv(url)
        
        # LIMPEZA CRÍTICA: Remove espaços dos nomes das colunas
        # Isso resolve o erro de "Coluna Username não encontrada"
        df.columns = [str(c).strip() for c in df.columns]
        
        return df
    except Exception as e:
        st.error(f"Erro ao ler banco de dados: {e}")
        return pd.DataFrame() # Retorna um DF vazio em vez de None para não quebrar o login

# --- TELA DE LOGON ---
if st.session_state.pagina == 'logon':
    st.markdown('<div class="main-title"><span class="parte-cinza">📊FutebolStats</span><span class="parte-verde">Jnr</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">O Mundo do futebol em suas mãos</div>', unsafe_allow_html=True)
    
    col_l1, col_log, col_l2 = st.columns([1, 2, 1])
    with col_log:
        st.write("### 🔐 Acesso")
        u = st.text_input("Username").strip()
        p = st.text_input("Senha", type="password")
        
        if st.button("Entrar"):
            df = ler_planilha()
            
            # Verificamos se o DataFrame foi lido e se a coluna Username existe
            if df is not None and not df.empty and 'Username' in df.columns:
                # Localiza o usuário
                user_db = df[df['Username'].astype(str) == u]
                
                if not user_db.empty:
                    # Comparamos o hash da senha digitada com a salva (na coluna 'Senha')
                    senha_salva = str(user_db.iloc[0]['Senha'])
                    
                    if gerar_hash(p) == senha_salva:
                        # Verificamos se está ativo (converte para string para garantir)
                        status_ativo = str(user_db.iloc[0]['Ativo']).upper()
                        
                        if status_ativo == "TRUE":
                            st.session_state.logado = True
                            st.session_state.username = u
                            # REMOVIDO: id_usuario (pois não existe na sua planilha atual)
                            st.session_state.pagina = 'home'
                            st.rerun()
                        else: 
                            st.error("Usuário bloqueado.")
                    else: 
                        st.error("Senha incorreta.")
                else: 
                    st.error("Usuário não encontrado.")
            else:
                st.error("Erro técnico: Coluna 'Username' não encontrada na planilha ou base vazia.")
                
                if login_sucesso: # <--- AQUI COMEÇA O TRECHO
                    st.session_state.username = username_digitado 
                    st.success(f"Bem-vindo, {username_digitado}!")
            
                    # AGORA ENTRA A SINCRONIZAÇÃO:
                    try:
                        # Lemos a aba de favoritos uma única vez no login
                        df_favs_geral = conn.read(worksheet="FAVORITOS")
                        
                        # Filtramos o que é SEU
                        meus_favs = df_favs_geral[df_favs_geral['Username'] == st.session_state.username]
                        
                        # Guardamos na memória para a estrela brilhar nos jogos certos
                        st.session_state.favoritos = set(meus_favs['ID_Fixture'].tolist())
                    except Exception:
                        # Caso a aba esteja vazia (primeiro uso), garante que não dê erro
                        st.session_state.favoritos = set()
                        
                    st.rerun() # Recarrega para já mostrar os favoritos na tela
                    
        st.write("---")
        if st.button("🆕 Cadastrar novo usuário"):
            st.session_state.pagina = 'cadastro'
            st.rerun()

# --- TELA DE CADASTRO ---
elif st.session_state.pagina == 'cadastro':
    st.title("📝 Cadastro")
    with st.form("c"):
        n = st.text_input("Nome Completo")
        c = st.text_input("CPF")
        e = st.text_input("E-mail")
        un = st.text_input("Username").strip()
        ps = st.text_input("Senha", type="password")
        
        if st.form_submit_button("Finalizar"):
            df = ler_planilha()
            
            # 1. Verifica se o Username já existe
            username_existe = False
            if df is not None and not df.empty and 'Username' in df.columns:
                if un in df['Username'].astype(str).values:
                    username_existe = True

            if username_existe:
                st.error("Username já existe.")
            else:
                # 2. Dados para o Apps Script (Mantenha e_mail com underline)
                dados_para_envio = {
                    "Nome": n, 
                    "CPF": c, 
                    "e_mail": e, 
                    "Username": un, 
                    "Senha": gerar_hash(ps), 
                    "Ativo": "True"
                }
                
                try:
                    # URL do seu Script (Verifique se é exatamente esta)
                    url_script = "https://script.google.com/macros/s/AKfycbxi85QwCTq_sfoA7WppprMxDoOeis_ef3P83hTFAhWmxL5RuRJqBDFrJV6-uut_f4YHww/exec"
                    
                    # O segredo do redirecionamento
                    response = requests.post(url_script, json=dados_para_envio, timeout=10)
                    
                    # Se o Google responder 200, ele gravou!
                    if response.status_code == 200:
                        st.success("Cadastro realizado com sucesso!")
                        st.session_state.pagina = 'logon'
                        st.rerun()
                    else:
                        st.error(f"Erro no Google (Status {response.status_code}).")
                except Exception as erro:
                    st.error(f"Erro na conexão: {erro}")

    if st.button("Voltar"):
        st.session_state.pagina = 'logon'
        st.rerun()
        
# TELA HOME (SÓ SE LOGADO)
elif st.session_state.pagina == 'home' and st.session_state.logado:
    st.markdown(f"<p style='text-align:right'>Olá, <b>{st.session_state.username}</b></p>", unsafe_allow_html=True)
    st.markdown('<div class="main-title"><span class="parte-cinza">📊FutebolStats</span><span class="parte-verde">Jnr</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">O Mundo do futebol em suas mãos</div>', unsafe_allow_html=True)
    st.write("---")
    
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        if st.button("📅 Calendário"):
            st.session_state.pagina = 'jogos_dia'
            st.rerun()
        if st.button("📈 Estatísticas de Gols"):
            st.session_state.pagina = 'stats'
            st.rerun()
        if st.button("🎯 Prognósticos"):
            st.session_state.pagina = 'prognosticos'
            st.rerun()
        if st.button("🚪 Sair"):
            st.session_state.logado = False
            st.session_state.pagina = 'logon'
            st.rerun()

# =========================================================
# 2. PÁGINA STATS GOLS (MANTIDA)
# =========================================================
elif st.session_state.pagina == 'stats':
    st.sidebar.header("Menu de Navegação")
    if st.sidebar.button("⬅️ Voltar ao Início"):
        st.session_state.pagina = 'home'
        st.session_state.pais_nav, st.session_state.liga_nav, st.session_state.time_nav = None, None, None
        st.rerun()

    if st.sidebar.button("📅 Go to calendário"):
        st.session_state.pagina = 'jogos_dia'
        st.rerun()

    if st.sidebar.button("🔄 Atualizar Dados"):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.markdown("---")
    df_menu = carregar_dados("SELECT DISTINCT Pais, Liga, ID_Liga FROM LIGAS ORDER BY Pais, Liga")

    if not df_menu.empty:
        lista_paises = sorted(df_menu['Pais'].unique().tolist())
        idx_p = lista_paises.index(st.session_state.pais_nav) if st.session_state.pais_nav in lista_paises else 0
        pais_sel = st.sidebar.selectbox("1. Escolha o País:", lista_paises, index=idx_p)
        
        df_ligas_f = df_menu[df_menu['Pais'] == pais_sel]
        lista_ligas = df_ligas_f['Liga'].tolist()
        idx_l = lista_ligas.index(st.session_state.liga_nav) if st.session_state.liga_nav in lista_ligas else 0
        liga_sel = st.sidebar.selectbox("2. Escolha a Competição:", lista_ligas, index=idx_l)
        
        busca_time = st.sidebar.text_input("🔍 Localizar Time:", value=st.session_state.time_nav if st.session_state.time_nav else "")
        id_final = df_ligas_f[df_ligas_f['Liga'] == liga_sel]['ID_Liga'].values[0]

        st.title(f"📊 {pais_sel}: {liga_sel}")
        data_att, classe_data = buscar_data_atualizacao(id_final)
        st.markdown(f'<p class="update-text-gray">Última atualização de dados da liga em: <span class="{classe_data}">{data_att}</span></p>', unsafe_allow_html=True)

        tab1, tab2, tab3, tab4 = st.tabs(["📊 Geral (FT)", "⏱️ Intervalo (HT)", "🤝 Ambas Marcam", "🛡️ Clean Sheets"])

        # --- FUNÇÃO AUXILIAR PARA RENDERIZAR TABELAS REPETITIVAS ---
        # --- FUNÇÃO AUXILIAR CORRIGIDA ---
        def exibir_tabelas_mando(tabela_base, colunas_sql, colunas_perc, titulo_secao):
            # 1. Geral
            st.subheader(f"{titulo_secao}")
            df = carregar_dados(f"SELECT {colunas_sql} FROM {tabela_base} WHERE ID_Liga = {id_final}")
            if busca_time: df = df[df['Equipe'].str.contains(busca_time, case=False)]
            st.dataframe(df.style.format({c: "{:.1f}%" for c in colunas_perc}, precision=2), use_container_width=True, hide_index=True)
            
            # 2. Casa
            st.subheader(f"🏠 Home")
            df_c = carregar_dados(f"SELECT {colunas_sql} FROM {tabela_base}_CASA WHERE ID_Liga = {id_final}")
            if busca_time: df_c = df_c[df_c['Equipe'].str.contains(busca_time, case=False)]
            st.dataframe(df_c.style.format({c: "{:.1f}%" for c in colunas_perc}, precision=2), use_container_width=True, hide_index=True)

            # 3. Fora
            st.subheader(f"✈️ Away")
            df_f = carregar_dados(f"SELECT {colunas_sql} FROM {tabela_base}_FORA WHERE ID_Liga = {id_final}")
            if busca_time: df_f = df_f[df_f['Equipe'].str.contains(busca_time, case=False)]
            st.dataframe(df_f.style.format({c: "{:.1f}%" for c in colunas_perc}, precision=2), use_container_width=True, hide_index=True)

        # --- APLICAÇÃO NAS TABS ---
        with tab1:
            cols_ft = 'Equipe, Jogos, MDM, MDS, MD, "0.5+", "1.5+", "2.5+", "3.5+", "4.5+", BTS, CS'
            exibir_tabelas_mando("STATS_GOLS", cols_ft, ["0.5+", "1.5+", "2.5+", "3.5+", "4.5+", "BTS", "CS"], "Estatísticas de Gols")

        with tab2:
            cols_ht = 'Equipe, Jogos, MDM_HT, MDS_HT, MD_HT, "0.5+", "1.5+", BTS_HT, CS_HT'
            exibir_tabelas_mando("STATS_GOLS_HT", cols_ht, ["0.5+", "1.5+", "BTS_HT", "CS_HT"], "Estatísticas de Gols HT")

        with tab3:
            cols_btts = "Equipe, BTS, Total_de_jogos, Percentual"
            exibir_tabelas_mando("STATS_BTTS", cols_btts, ["Percentual"], "Ambas Marcam (BTTS)")

        with tab4:
            cols_cs = "Equipe, CS, Total_de_Jogos, Percentual"
            exibir_tabelas_mando("STATS_CLEAN_SHEETS", cols_cs, ["Percentual"], "Clean Sheets (Defesa)")

# =========================================================
# 3. PÁGINA JOGOS DO DIA (HOJE, AMANHÃ E FAVORITOS)
# =========================================================
elif st.session_state.pagina == 'jogos_dia':
    st.sidebar.header("Menu de Navegação")
    if st.sidebar.button("⬅️ Voltar ao Início"):
        st.session_state.pagina = 'home'
        st.rerun()

    if st.sidebar.button("🔄 Atualizar Dados"):
        st.cache_data.clear()
        st.rerun()

    st.title("📅 Calendário de Jogos")

    # --- FUNÇÃO DO CARD (ESTRELA REMOVIDA - FOCO NO EXPANDER) ---
    def exibir_card_jogo(row, mostrar_liga_no_label=False, suffix="", encerrado=False):
        fix_id = row['ID_Fixture']

        # 1. Definição do Label (Seu código original)
        if encerrado:
            label_jogo = f"🏁 {row['Hora']} | {row['Home_Team']} {row['Gols_Home_FT']} x {row['Gols_Away_FT']} {row['Away_Team']}"
        else:
            if mostrar_liga_no_label:
                label_jogo = f"⏰ {row['Hora']} | {row['Pais']} - {row['Liga_Nome']} | {row['Home_Team']} x {row['Away_Team']}"
            else:
                label_jogo = f"⏰ {row['Hora']} | {row['Home_Team']} x {row['Away_Team']}"

        # 2. ESTRUTURA DE COLUNAS (A Estrela à esquerda e o Card à direita)
        # O 'gap' pequeno ajuda a manter tudo próximo
        col_fav, col_expander = st.columns([0.6, 9.4], gap="small")

        with col_fav:
            # O Checkbox atua como o botão de favorito independente
            # value=True se o ID estiver nos favoritos, False se não estiver
            is_favo = st.checkbox(
                "⭐", 
                value=(fix_id in st.session_state.favoritos), 
                key=f"check_{fix_id}_{suffix}"
            )
            
            # Lógica de atualização (sem abrir o expander)
            if is_favo and fix_id not in st.session_state.favoritos:
                st.session_state.favoritos.add(fix_id)
                # LÓGICA GOOGLE SHEETS ENTRARÁ AQUI
            elif not is_favo and fix_id in st.session_state.favoritos:
                st.session_state.favoritos.remove(fix_id)
                # LÓGICA GOOGLE SHEETS ENTRARÁ AQUI

        with col_expander:
            # TODO O SEU CONTEÚDO ORIGINAL DENTRO DESTE EXPANDER
            with st.expander(label_jogo, expanded=False):
                # --- INÍCIO DO SEU CONTEÚDO DE ESTATÍSTICAS ---
                c1, c2, c3 = st.columns([2.5, 1, 2.5])
                with c1:
                    st.markdown(f"<div><span class='rank-text'>{row['Pos_Home']}º</span> <b class='team-name'>{row['Home_Team']}</b></div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='odd-box'>Casa: <b>{row['Odd_Home']:.2f}</b></div>", unsafe_allow_html=True)
                with c2:
                    st.markdown("<div class='card-vs'>VS</div>", unsafe_allow_html=True)
                    st.markdown(f"<p style='text-align:center; color:#888; font-size: 13px;'>Empate<br><b>{row['Odd_Draw']:.2f}</b></p>", unsafe_allow_html=True)
                with c3:
                    st.markdown(f"<div style='text-align:right;'><b class='team-name'>{row['Away_Team']}</b> <span class='rank-text'>{row['Pos_Away']}º</span></div>", unsafe_allow_html=True)
                    st.markdown(f"<div class='odd-box'>Fora: <b>{row['Odd_Away']:.2f}</b></div>", unsafe_allow_html=True)
    
                st.divider()
    
                data_h = buscar_stats_duplas(row['ID_Liga'], row['Home_Team'], 'CASA')
                data_a = buscar_stats_duplas(row['ID_Liga'], row['Away_Team'], 'FORA')
    
                if data_h and data_a:
                    s_h_g, s_h_m = data_h["geral"], data_h["mando"]
                    s_a_g, s_a_m = data_a["geral"], data_a["mando"]
    
                    st.markdown("<style>table { width: 100% !important; table-layout: fixed; margin-top: -24px !important; }</style>", unsafe_allow_html=True)
    
                    st.markdown("<h5 style='text-align: center; font-size: 18px; margin-top: -52px; margin-bottom: -10px;'>📊 Média de Gols Por Jogo</h5>", unsafe_allow_html=True)
                    c_esp1, c1, c_vazio, c2, c_esp2 = st.columns([1, 8, 0.5, 8, 1])
    
                    with c1: 
                        st.markdown(f"""
                        | Métrica (GERAL) | {row['Home_Team']} | {row['Away_Team']} |
                        | :--- | :---: | :---: |
                        | Gols Marcados | {s_h_g.get('MDM',0):.2f} | {s_a_g.get('MDM',0):.2f} |
                        | Gols Sofridos | {s_h_g.get('MDS',0):.2f} | {s_a_g.get('MDS',0):.2f} |
                        | Média Total | {s_h_g.get('MD',0):.2f} | {s_a_g.get('MD',0):.2f} |
                        | BTS | {s_h_g.get('BTS',0):.0f}% | {s_a_g.get('BTS',0):.0f}% |
                        | Clean Sheet | {s_h_g.get('CS',0):.0f}% | {s_a_g.get('CS',0):.0f}% |
                        """)
    
                    with c2: 
                        st.markdown(f"""
                        | Métrica (CASA/FORA) | {row['Home_Team']} (C) | {row['Away_Team']} (F) |
                        | :--- | :---: | :---: |
                        | Gols Marcados | **{s_h_m.get('MDM',0):.2f}** | **{s_a_m.get('MDM',0):.2f}** |
                        | Gols Sofridos | **{s_h_m.get('MDS',0):.2f}** | **{s_a_m.get('MDS',0):.2f}** |
                        | Média Total | **{s_h_m.get('MD',0):.2f}** | **{s_a_m.get('MD',0):.2f}** |
                        | BTS | **{s_h_m.get('BTS',0):.0f}%** | **{s_a_m.get('BTS',0):.0f}%** |
                        | Clean Sheet | **{s_h_m.get('CS',0):.0f}%** | **{s_a_m.get('CS',0):.0f}%** |
                        """)
    
                    st.markdown("<h5 style='text-align: center; font-size: 19px; margin-bottom: 14px; margin-top: -10px;'>⏱️ Média de Gols HT</h5>", unsafe_allow_html=True)
                    c_esp3, c3, c_vazio2, c4, c_esp4 = st.columns([1, 8, 0.5, 8, 1])
                    
                    with c3:
                        st.markdown(f"""
                        | Métrica (GERAL) | {row['Home_Team']} | {row['Away_Team']} |
                        | :--- | :---: | :---: |
                        | Gols Marcados | {s_h_g.get('MDM_HT',0):.2f} | {s_a_g.get('MDM_HT',0):.2f} |
                        | Gols Sofridos | {s_h_g.get('MDS_HT',0):.2f} | {s_a_g.get('MDS_HT',0):.2f} |
                        | Média Total | {s_h_g.get('MD_HT',0):.2f} | {s_a_g.get('MD_HT',0):.2f} |
                        | +0.5 HT | {s_h_g.get('OVER_05_HT',0):.0f}% | {s_a_g.get('OVER_05_HT',0):.0f}% |
                        | BTS HT | {s_h_g.get('BTS_HT',0):.0f}% | {s_a_g.get('BTS_HT',0):.0f}% |
                        | CS HT | {s_h_g.get('CS_HT',0):.0f}% | {s_a_g.get('CS_HT',0):.0f}% |
                        """)
    
                    with c4:
                        st.markdown(f"""
                        | Métrica (CASA/FORA) | {row['Home_Team']} (C) | {row['Away_Team']} (F) |
                        | :--- | :---: | :---: |
                        | Gols Marcados | **{s_h_m.get('MDM_HT',0):.2f}** | **{s_a_m.get('MDM_HT',0):.2f}** |
                        | Gols Sofridos | **{s_h_m.get('MDS_HT',0):.2f}** | **{s_a_m.get('MDS_HT',0):.2f}** |
                        | Média Total | **{s_h_m.get('MD_HT',0):.2f}** | **{s_a_m.get('MD_HT',0):.2f}** |
                        | +0.5 HT | **{s_h_m.get('OVER_05_HT',0):.0f}%** | **{s_a_m.get('OVER_05_HT',0):.0f}%** |
                        | BTS HT | **{s_h_m.get('BTS_HT',0):.0f}%** | **{s_a_m.get('BTS_HT',0):.0f}%** |
                        | CS HT | **{s_h_m.get('CS_HT',0):.0f}%** | **{s_a_m.get('CS_HT',0):.0f}%** |
                        """)
    
                    # Cálculos de Expectativa
                    exp_over25_g = (s_h_g.get('OVER_25_FT', 0) + s_a_g.get('OVER_25_FT', 0)) / 2
                    exp_over25_m = (s_h_m.get('OVER_25_FT', 0) + s_a_m.get('OVER_25_FT', 0)) / 2
                    exp_gols_g = (s_h_g.get('MD',0) + s_a_g.get('MD',0)) / 2
                    exp_gols_m = ((s_h_m.get('MDM',0) + s_a_m.get('MDS',0))/2 + (s_a_m.get('MDM',0) + s_h_m.get('MDS',0))/2)
                    exp_bts_g = (s_h_g.get('BTS',0) + s_a_g.get('BTS',0)) / 2
                    exp_bts_m = (s_h_m.get('BTS',0) + s_a_m.get('BTS',0)) / 2
    
                    st.markdown("---")
                    col_exp1, col_exp2 = st.columns(2)
    
                    with col_exp1:
                        # Prob. Over 2.5 Jogo
                        st.markdown(f"""
                            <div style='font-size: 13px; color: #bbb; margin-bottom: -6px; margin-top: -55px;'><strong>Prob. Over 2.5 Jogo %</strong></div>
                            <div style='font-size: 18px; font-weight: bold; margin-top: 0;'>🔎 {exp_over25_g:.1f}% &nbsp; | &nbsp; 🏠-✈️ {exp_over25_m:.1f}%</div>
                        """, unsafe_allow_html=True)

                        # Expc Gols Jogo
                        st.markdown(f"""
                            <div style='font-size: 13px; color: #bbb; margin-top: -15px; margin-bottom: -6px;'><strong>Expc. Gols Jogo (Média)</strong></div>
                            <div style='font-size: 18px; font-weight: bold; margin-top: 0;'>⚽ {exp_gols_g:.2f} &nbsp; | &nbsp; 🏠-✈️ {exp_gols_m:.2f}</div>
                        """, unsafe_allow_html=True)
                            
                        # Expc BTS Jogo
                        st.markdown(f"""
                            <div style='font-size: 13px; color: #bbb; margin-top: 3px; margin-bottom: -6px;'><strong>Expc. BTS Jogo %</strong></div>
                            <div style='font-size: 18px; font-weight: bold; margin-top: 0;'>🫂 {exp_bts_g:.1f}% &nbsp; | &nbsp; 🏠-✈️ {exp_bts_m:.1f}%</div>
                        """, unsafe_allow_html=True)

                    with col_exp2:
                        # Calculando para o HT
                        exp_gols_ht_g = (s_h_g.get('MD_HT',0) + s_a_g.get('MD_HT',0)) / 2
                        exp_gols_ht_m = (
                            (s_h_m.get('MDM_HT',0) + s_a_m.get('MDS_HT',0)) / 2 + 
                            (s_a_m.get('MDM_HT',0) + s_h_m.get('MDS_HT',0)) / 2
                        )

                        # Prob. +0.5 HT %
                        st.markdown(f"""
                            <div style='font-size: 13px; color: #bbb; margin-bottom: -6px; margin-top: -55px;'><strong>Prob. +0.5 HT %</strong></div>
                            <div style='font-size: 18px; font-weight: bold; margin-top: 0;'>🔄 {exp_05ht_g:.1f}% &nbsp; | &nbsp; 🏠-✈️ {exp_05ht_m:.1f}%</div>
                        """, unsafe_allow_html=True)

                        # Expc Gols HT (MD)
                        st.markdown(f"""
                            <div style='font-size: 13px; color: #bbb; margin-top: -15px; margin-bottom: -6px;'><strong>Expc. Gols HT (MD)</strong></div>
                            <div style='font-size: 18px; font-weight: bold; margin-top: 0;'>⚽ {exp_gols_ht_g:.2f} &nbsp; | &nbsp; 🏠-✈️ {exp_gols_ht_m:.2f}</div>
                        """, unsafe_allow_html=True) 
                            
                        # Expc BTS HT %
                        exp_bts_ht_g = (s_h_g.get('BTS_HT',0) + s_a_g.get('BTS_HT',0)) / 2
                        exp_bts_ht_m = (s_h_m.get('BTS_HT',0) + s_a_m.get('BTS_HT',0)) / 2
                            
                        st.markdown(f"""
                            <div style='font-size: 13px; color: #bbb; margin-top: 3px; margin-bottom: -6px;'><strong>Expc. BTS HT %</strong></div>
                            <div style='font-size: 18px; font-weight: bold; margin-top: 0;'>🫂 {exp_bts_ht_g:.1f}% &nbsp; | &nbsp; 🏠-✈️ {exp_bts_ht_m:.1f}%</div>
                        """, unsafe_allow_html=True)

                    # Fecha a div customizada
                    st.markdown('</div>', unsafe_allow_html=True)
                else:
                    st.warning("⚠️ Estatísticas históricas não encontradas para este confronto.")
                
                if st.button(f"🔍 Go to league statistics", key=f"btn_{fix_id}_{suffix}"):
                    st.session_state.pais_nav = row['Pais']
                    st.session_state.liga_nav = row['Liga_Nome']
                    st.session_state.pagina = 'stats'
                    st.rerun()

    # --- FUNÇÃO DE RENDERIZAÇÃO DA LISTA ---
    def renderizar_lista_jogos(tabela_nome, df_custom=None):
        col_ord, col_filt = st.columns(2)
        with col_ord:
            ordem = st.radio("Ordenar por:", ["⏰ Horário", "🏆 Campeonato"], horizontal=True, key=f"ord_{tabela_nome}")
        
        with col_filt:
            if tabela_nome == "FAVORITOS":
                exibir_dia = st.radio("Exibir:", ["Hoje", "Amanhã"], horizontal=True, key=f"filter_dia")
            else:
                st.empty()

        if df_custom is None:
            df_jogos = carregar_dados(f'''
                SELECT J.Hora, J.Liga_Nome, J.Home_Team, J.Away_Team, L.Pais, J.ID_Liga, 
                       J.Pos_Home, J.Pos_Away, J.Odd_Home, J.Odd_Away, J.Odd_Draw, J.ID_Fixture
                FROM {tabela_nome} J
                JOIN LIGAS L ON J.ID_Liga = L.ID_Liga
            ''')
        else:
            df_jogos = df_custom

        if tabela_nome == "FAVORITOS" and df_custom is not None:
            df_jogos = df_jogos[df_jogos['Origem'] == exibir_dia.upper()]

        if not df_jogos.empty:
            if ordem == "⏰ Horário":
                df_jogos = df_jogos.sort_values(by=['Hora', 'Pais', 'Liga_Nome'])
                for _, row in df_jogos.iterrows():
                    exibir_card_jogo(row, mostrar_liga_no_label=True, suffix=tabela_nome)
            else:
                df_jogos = df_jogos.sort_values(by=['Pais', 'Liga_Nome', 'Hora'])
                grupos = df_jogos.groupby(['Pais', 'Liga_Nome'], sort=False)
                for (pais, liga), dados in grupos:
                    st.markdown(f'<div class="liga-header">{pais.upper()}: {liga}</div>', unsafe_allow_html=True)
                    for _, row in dados.iterrows():
                        exibir_card_jogo(row, mostrar_liga_no_label=False, suffix=tabela_nome)
        else:
            st.info("Nenhum jogo encontrado para este filtro.")

    # --- ABAS ---
    tab_hoje, tab_amanha, tab_fav = st.tabs(["⚽ Jogos de Hoje", "🔜 Amanhã", "⭐ Salvos"])

    with tab_hoje:
        renderizar_lista_jogos("JOGOS_HOJE")
        
    with tab_amanha:
        renderizar_lista_jogos("JOGOS_AMANHA")

    with tab_fav:
        col_tit, col_btn = st.columns([3, 1])
        with col_tit:
            st.subheader("⭐ Seus Jogos Salvos")
        
        with col_btn:
            with st.popover("🗑️ Limpar Tudo"):
                st.warning("Isso removerá TODOS os favoritos salvos.")
                if st.button("Confirmar Limpeza", type="primary", use_container_width=True):
                    limpar_todos_favoritos()
                    st.session_state.favoritos = set()
                    st.toast("Lista esvaziada com sucesso!")
                    st.rerun()

        df_hoje_fav = carregar_dados("SELECT J.*, L.Pais, 'HOJE' as Origem FROM JOGOS_HOJE J JOIN LIGAS L ON J.ID_Liga = L.ID_Liga")
        df_amanha_fav = carregar_dados("SELECT J.*, L.Pais, 'AMANHÃ' as Origem FROM JOGOS_AMANHA J JOIN LIGAS L ON J.ID_Liga = L.ID_Liga")
        
        df_all = pd.concat([df_hoje_fav, df_amanha_fav], ignore_index=True)
        df_fav_list = df_all[df_all['ID_Fixture'].isin(st.session_state.favoritos)]
        
        if not df_fav_list.empty:
            renderizar_lista_jogos("FAV_CAL", df_custom=df_fav_list)
        else:
            st.info("Sua lista de favoritos está vazia.")

# =========================================================
# 4. PÁGINA PROGNÓSTICOS (REFINADA COM FAVORITOS)
# =========================================================
elif st.session_state.pagina == 'prognosticos':
    st.sidebar.header("Menu de Navegação")
    if st.sidebar.button("⬅️ Voltar ao Início"):
        st.session_state.pagina = 'home'; st.rerun()
    
    if st.sidebar.button("📅 Go to Calendário"):
        st.session_state.pagina = 'jogos_dia'; st.rerun()
    
    st.title("🎯 Prognósticos")
    
    # Seletores de topo: Período e Filtro de Exibição
    col_per, col_exib = st.columns([1, 1])
    
    with col_per:
        periodo = st.radio(
            "Escolha o período:",
            ["⚽ Hoje", "🔜 Amanhã", "🔚 Encerrados"],
            horizontal=True,
            label_visibility="collapsed"
        )
    
    with col_exib:
        exibir_modo = st.radio(
            "Filtrar Jogos:",
            ["Mostrar tudo", "Salvos ⭐"],
            horizontal=True,
            label_visibility="collapsed"
        )
    
    st.write(f"Filtros para: **{periodo}** | Modo: **{exibir_modo}**")
    
    # DEFINA as abas :
    tab_fav, tab_over, tab_bts, tab_ht = st.tabs([
        "🚀 Super Favoritos", 
        "⚽ Over Gols", 
        "🤝 Ambas Marcam", 
        "⏱️ Gol HT"
    ])

    with tab_fav:
        st.subheader(f"🚀 Super favoritos ({periodo})")

        # 1. DEFINIÇÃO DA QUERY ISOLADA
        if periodo == "🔚 Encerrados":
            query_fav = '''
                SELECT 
                    E.ID_Fixture, E.Hora, 
                    L.Liga as Liga, L.Pais,
                    E.Home_Team, E.Away_Team, E.Odd_Home, E.Odd_Away,
                    E.Gols_Home_FT, E.Gols_Away_FT
                FROM JOGOS_ENCERRADOS E
                LEFT JOIN LIGAS L ON E.ID_Liga = L.ID_Liga
                WHERE (E.Odd_Home > 0 AND E.Odd_Home <= 1.72) 
                OR (E.Odd_Away > 0 AND E.Odd_Away <= 1.72)
                ORDER BY E.Hora DESC
            '''
        else:
            tabela_alvo = "JOGOS_HOJE" if periodo == "⚽ Hoje" else "JOGOS_AMANHA"
            query_fav = f'''
                SELECT 
                    J.ID_Fixture, J.Hora, L.Pais, J.Liga_Nome as Liga, 
                    J.Home_Team, J.Away_Team, J.Odd_Home, J.Odd_Away
                FROM {tabela_alvo} J
                LEFT JOIN LIGAS L ON J.ID_Liga = L.ID_Liga
                WHERE (J.Odd_Home > 0 AND J.Odd_Home <= 1.72) 
                OR (J.Odd_Away > 0 AND J.Odd_Away <= 1.72)
                ORDER BY J.Hora ASC
            '''

        df_fav = carregar_dados(query_fav)

        if not df_fav.empty:
            df_fav = df_fav.fillna(0)

            # --- AJUSTE: A coluna de favoritos agora é criada para TODOS os períodos ---
            df_fav['⭐'] = df_fav['ID_Fixture'].apply(lambda x: x in st.session_state.favoritos)

            # 2. PROCESSAMENTO
            if periodo == "🔚 Encerrados":
                def checar_vitoria_fav(row):
                    casa_fav = 0 < row['Odd_Home'] <= 1.72
                    if row['Gols_Home_FT'] == row['Gols_Away_FT']: return "🟰 Empate"
                    if casa_fav:
                        return "✅ Vitória" if row['Gols_Home_FT'] > row['Gols_Away_FT'] else "❌ Derrota"
                    else:
                        return "✅ Vitória" if row['Gols_Away_FT'] > row['Gols_Home_FT'] else "❌ Derrota"

                df_fav['Placar'] = df_fav.apply(lambda r: f"{int(r['Gols_Home_FT'])} x {int(r['Gols_Away_FT'])}", axis=1)
                df_fav['Status'] = df_fav.apply(checar_vitoria_fav, axis=1)
                
                # Adicionado '⭐' e 'Pais' nas colunas de encerrados
                cols_show = ['⭐', 'Hora', 'Pais', 'Liga', 'Home_Team', 'Placar', 'Away_Team', 'Odd_Home', 'Odd_Away', 'Status']
            else:
                cols_show = ['⭐', 'Hora', 'Pais', 'Liga', 'Home_Team', 'Away_Team', 'Odd_Home', 'Odd_Away']

            # 3. FILTRO DE EXIBIÇÃO (MODO SALVOS)
            df_display = df_fav.copy()
            if exibir_modo == "Salvos ⭐":
                df_display = df_display[df_display['⭐'] == True]

            # 4. RENDERIZAÇÃO
            if not df_display.empty:
                df_display = df_display.set_index('ID_Fixture') 
                
                edited_df = st.data_editor(
                    df_display[cols_show],
                    column_config={
                        "⭐": st.column_config.CheckboxColumn("Fav", default=False),
                        "Odd_Home": st.column_config.NumberColumn("Odd C", format="%.2f"),
                        "Odd_Away": st.column_config.NumberColumn("Odd F", format="%.2f"),
                    },
                    disabled=[c for c in cols_show if c != "⭐"],
                    hide_index=True,
                    use_container_width=True,
                    key=f"editor_fav_main_{periodo}"
                )

                # 5. LÓGICA DE SINCRONIZAÇÃO (Funciona para todos, inclusive Encerrados)
                for fix_id, row in edited_df.iterrows():
                    if row['⭐'] and fix_id not in st.session_state.favoritos:
                        st.session_state.favoritos.add(fix_id)
                        salvar_favorito(fix_id)
                        st.rerun()
                    elif not row['⭐'] and fix_id in st.session_state.favoritos:
                        st.session_state.favoritos.remove(fix_id)
                        remover_favorito(fix_id)
                        st.rerun()
            else:
                st.info("Nenhum favorito encontrado para os critérios atuais.")
        else:
            st.info("Nenhum dado disponível.")

    with tab_over:
        st.subheader(f"⚽ Expectativa Over 2.5 Gols ({periodo})")

        # 1. QUERY ISOLADA
        if periodo == "🔚 Encerrados":
            query_over = '''
                SELECT 
                    E.ID_Fixture, E.Hora, 
                    E.Liga as Liga, L.Pais,
                    E.Home_Team, E.Away_Team,
                    E.Gols_Home_FT, E.Gols_Away_FT,
                    S1.MD as MD_Home, S2.MD as MD_Away,
                    S1."2.5+" as Rec_Home, S2."2.5+" as Rec_Away
                FROM JOGOS_ENCERRADOS E
                LEFT JOIN LIGAS L ON E.ID_Liga = L.ID_Liga
                LEFT JOIN STATS_GOLS S1 ON E.ID_Liga = S1.ID_Liga AND E.Home_Team = S1.Equipe
                LEFT JOIN STATS_GOLS S2 ON E.ID_Liga = S2.ID_Liga AND E.Away_Team = S2.Equipe
                ORDER BY E.Hora DESC
            '''
        else:
            tabela_alvo = "JOGOS_HOJE" if periodo == "⚽ Hoje" else "JOGOS_AMANHA"
            query_over = f'''
                SELECT 
                    J.ID_Fixture, J.Hora, L.Pais, J.Liga_Nome as Liga, 
                    J.Home_Team, J.Away_Team,
                    S1.MD as MD_Home, S2.MD as MD_Away,
                    S1."2.5+" as Rec_Home, S2."2.5+" as Rec_Away
                FROM {tabela_alvo} J
                LEFT JOIN LIGAS L ON J.ID_Liga = L.ID_Liga
                LEFT JOIN STATS_GOLS S1 ON J.ID_Liga = S1.ID_Liga AND J.Home_Team = S1.Equipe
                LEFT JOIN STATS_GOLS S2 ON J.ID_Liga = S2.ID_Liga AND J.Away_Team = S2.Equipe
                ORDER BY J.Hora ASC
            '''

        df_over = carregar_dados(query_over)

        if not df_over.empty:
            # Preenche nulos para evitar erros nos cálculos
            df_over[['MD_Home', 'MD_Away', 'Rec_Home', 'Rec_Away']] = df_over[['MD_Home', 'MD_Away', 'Rec_Home', 'Rec_Away']].fillna(0)

            # Cálculos
            df_over['Exp_Gols'] = (df_over['MD_Home'] + df_over['MD_Away']) / 2
            df_over['Rec_25_%'] = (df_over['Rec_Home'] + df_over['Rec_Away']) / 2
            
            # --- AJUSTE: Coluna de favoritos criada antes dos filtros de exibição ---
            df_over['⭐'] = df_over['ID_Fixture'].apply(lambda x: x in st.session_state.favoritos)

            # Aplicação dos Filtros Técnicos
            df_over = df_over[
                (df_over['Exp_Gols'] >= 2.5) & 
                (df_over['Rec_25_%'] >= 61)
            ].copy()

            if not df_over.empty:
                # 2. PROCESSAMENTO DE STATUS PARA ENCERRADOS
                if periodo == "🔚 Encerrados":
                    def validar_over(row):
                        total = row['Gols_Home_FT'] + row['Gols_Away_FT']
                        return "✅ Over 2.5" if total > 2.5 else "❌ Under 2.5"
                    
                    df_over['Placar'] = df_over.apply(lambda r: f"{int(r['Gols_Home_FT'])} x {int(r['Gols_Away_FT'])}", axis=1)
                    df_over['Status'] = df_over.apply(validar_over, axis=1)
                    
                    # Adicionado '⭐' e 'Pais'
                    cols_show = ['⭐', 'Hora', 'Pais', 'Liga', 'Home_Team', 'Placar', 'Away_Team', 'Exp_Gols', 'Rec_25_%', 'Status']
                else:
                    cols_show = ['⭐', 'Hora', 'Pais', 'Liga', 'Home_Team', 'Away_Team', 'Rec_25_%', 'Exp_Gols']

                # 3. FILTRO DE EXIBIÇÃO (MODO SALVOS)
                df_display = df_over.copy()
                if exibir_modo == "Salvos ⭐":
                    df_display = df_display[df_display['⭐'] == True]

                # 4. RENDERIZAÇÃO
                if not df_display.empty:
                    df_display = df_display.set_index('ID_Fixture')
                    
                    edited_over = st.data_editor(
                        df_display[cols_show],
                        column_config={
                            "⭐": st.column_config.CheckboxColumn("Fav", default=False),
                            "Exp_Gols": st.column_config.NumberColumn("Exp. Gols", format="%.2f"),
                            "Rec_25_%": st.column_config.NumberColumn("Rec. 2.5+", format="%.0f%%"),
                        },
                        disabled=[c for c in cols_show if c != "⭐"],
                        hide_index=True,
                        use_container_width=True,
                        key=f"editor_over_{periodo}"
                    )

                    # 5. LÓGICA DE SINCRONIZAÇÃO (Habilitada para todos os períodos)
                    for fix_id, row in edited_over.iterrows(): 
                        if row['⭐'] and fix_id not in st.session_state.favoritos:
                            st.session_state.favoritos.add(fix_id)
                            salvar_favorito(fix_id)
                            st.rerun()
                        elif not row['⭐'] and fix_id in st.session_state.favoritos:
                            st.session_state.favoritos.remove(fix_id)
                            remover_favorito(fix_id)
                            st.rerun()
                else:
                    st.info("Nenhum favorito encontrado nestes critérios.")
            else:
                st.info("Nenhuma partida atende aos critérios de Over 2.5.")
        else:
            st.info("Nenhum dado disponível.")

    with tab_bts:
        st.subheader(f"🤝 Expectativa Ambas Marcam ({periodo})")

        # 1. QUERY ISOLADA
        if periodo == "🔚 Encerrados":
            query_bts = '''
                SELECT 
                    E.ID_Fixture, E.Hora, L.Pais, E.Liga, 
                    E.Home_Team, E.Away_Team,
                    E.Gols_Home_FT, E.Gols_Away_FT,
                    S1.BTS as BTS_Home, S2.BTS as BTS_Away
                FROM JOGOS_ENCERRADOS E
                LEFT JOIN LIGAS L ON E.ID_Liga = L.ID_Liga
                LEFT JOIN STATS_GOLS S1 ON E.ID_Liga = S1.ID_Liga AND E.Home_Team = S1.Equipe
                LEFT JOIN STATS_GOLS S2 ON E.ID_Liga = S2.ID_Liga AND E.Away_Team = S2.Equipe
                ORDER BY E.Hora DESC
            '''
        else:
            tabela_alvo = "JOGOS_HOJE" if periodo == "⚽ Hoje" else "JOGOS_AMANHA"
            query_bts = f'''
                SELECT 
                    J.ID_Fixture, J.Hora, L.Pais, J.Liga_Nome as Liga, 
                    J.Home_Team, J.Away_Team,
                    S1.BTS as BTS_Home, S2.BTS as BTS_Away
                FROM {tabela_alvo} J
                LEFT JOIN LIGAS L ON J.ID_Liga = L.ID_Liga
                LEFT JOIN STATS_GOLS S1 ON J.ID_Liga = S1.ID_Liga AND J.Home_Team = S1.Equipe
                LEFT JOIN STATS_GOLS S2 ON J.ID_Liga = S2.ID_Liga AND J.Away_Team = S2.Equipe
                ORDER BY J.Hora ASC
            '''

        df_bts = carregar_dados(query_bts)

        if not df_bts.empty:
            df_bts = df_bts.fillna(0)
            df_bts['Exp_BTS'] = (df_bts['BTS_Home'] + df_bts['BTS_Away']) / 2
            
            # --- AJUSTE: Coluna de favoritos criada para todos os períodos ---
            df_bts['⭐'] = df_bts['ID_Fixture'].apply(lambda x: x in st.session_state.favoritos)
            
            # Filtro de probabilidade
            df_bts = df_bts[df_bts['Exp_BTS'] >= 65].copy()

            if not df_bts.empty:
                if periodo == "🔚 Encerrados":
                    def validar_bts(row):
                        if row['Gols_Home_FT'] > 0 and row['Gols_Away_FT'] > 0:
                            return "✅ Ambas Sim"
                        return "❌ Ambas Não"
                    
                    df_bts['Placar'] = df_bts.apply(lambda r: f"{int(r['Gols_Home_FT'])} x {int(r['Gols_Away_FT'])}", axis=1)
                    df_bts['Status'] = df_bts.apply(validar_bts, axis=1)
                    
                    # Incluído '⭐' e 'Pais'
                    cols_show = ['⭐', 'Hora', 'Pais', 'Liga', 'Home_Team', 'Placar', 'Away_Team', 'Exp_BTS', 'Status']
                else:
                    cols_show = ['⭐', 'Hora', 'Pais', 'Liga', 'Home_Team', 'Away_Team', 'Exp_BTS']

                # 3. FILTRO DE EXIBIÇÃO (MODO SALVOS)
                df_display = df_bts.copy()
                if exibir_modo == "Salvos ⭐":
                    df_display = df_display[df_display['⭐'] == True]

                if not df_display.empty:
                    df_display = df_display.set_index('ID_Fixture')
                    
                    edited_bts = st.data_editor(
                        df_display[cols_show],
                        column_config={
                            "⭐": st.column_config.CheckboxColumn("Fav", default=False),
                            "Exp_BTS": st.column_config.NumberColumn("Prob. BTS (%)", format="%.1f%%"),
                        },
                        disabled=[c for c in cols_show if c != "⭐"],
                        hide_index=True,
                        use_container_width=True,
                        key=f"editor_bts_{periodo}"
                    )

                    # --- LÓGICA DE SINCRONIZAÇÃO GLOBAL ---
                    for fix_id, row in edited_bts.iterrows(): 
                        if row['⭐'] and fix_id not in st.session_state.favoritos:
                            st.session_state.favoritos.add(fix_id)
                            salvar_favorito(fix_id)
                            st.rerun()
                        elif not row['⭐'] and fix_id in st.session_state.favoritos:
                            st.session_state.favoritos.remove(fix_id)
                            remover_favorito(fix_id)
                            st.rerun()
                else:
                    st.info("Nenhum favorito encontrado para Ambas Marcam.")
            else:
                st.info("Nenhuma partida com probabilidade BTS >= 65%")
        else:
            st.info("Sem dados para Ambas Marcam.")
            
    with tab_ht:
        st.subheader(f"⏱️ Expectativa Gol no 1º Tempo ({periodo})")

        # 1. QUERY ISOLADA
        if periodo == "🔚 Encerrados":
            query_ht = '''
                SELECT 
                    E.ID_Fixture, E.Hora, L.Pais, E.Liga, 
                    E.Home_Team, E.Away_Team,
                    E.Gols_Home_HT, E.Gols_Away_HT,
                    S1.MD_HT as HT_Home, S2.MD_HT as HT_Away,
                    S1."0.5+" as Rec_Home, S2."0.5+" as Rec_Away
                FROM JOGOS_ENCERRADOS E
                LEFT JOIN LIGAS L ON E.ID_Liga = L.ID_Liga
                LEFT JOIN STATS_GOLS_HT S1 ON E.ID_Liga = S1.ID_Liga AND E.Home_Team = S1.Equipe
                LEFT JOIN STATS_GOLS_HT S2 ON E.ID_Liga = S2.ID_Liga AND E.Away_Team = S2.Equipe
                ORDER BY E.Hora DESC
            '''
        else:
            tabela_alvo = "JOGOS_HOJE" if periodo == "⚽ Hoje" else "JOGOS_AMANHA"
            query_ht = f'''
                SELECT 
                    J.ID_Fixture, J.Hora, L.Pais, J.Liga_Nome as Liga, 
                    J.Home_Team, J.Away_Team,
                    S1.MD_HT as HT_Home, S2.MD_HT as HT_Away,
                    S1."0.5+" as Rec_Home, S2."0.5+" as Rec_Away
                FROM {tabela_alvo} J
                LEFT JOIN LIGAS L ON J.ID_Liga = L.ID_Liga
                LEFT JOIN STATS_GOLS_HT S1 ON J.ID_Liga = S1.ID_Liga AND J.Home_Team = S1.Equipe
                LEFT JOIN STATS_GOLS_HT S2 ON J.ID_Liga = S2.ID_Liga AND J.Away_Team = S2.Equipe
                ORDER BY J.Hora ASC
            '''

        df_ht = carregar_dados(query_ht)

        if not df_ht.empty:
            # Preenchimento de nulos e cálculos
            df_ht[['HT_Home', 'HT_Away', 'Rec_Home', 'Rec_Away']] = df_ht[['HT_Home', 'HT_Away', 'Rec_Home', 'Rec_Away']].fillna(0)
            df_ht['Exp_HT'] = (df_ht['HT_Home'] + df_ht['HT_Away']) / 2
            df_ht['Rec_HT_%'] = (df_ht['Rec_Home'] + df_ht['Rec_Away']) / 2
            
            # --- AJUSTE: Coluna de favoritos criada antes dos filtros ---
            df_ht['⭐'] = df_ht['ID_Fixture'].apply(lambda x: x in st.session_state.favoritos)

            # Filtros Técnicos
            df_ht = df_ht[
                (df_ht['Exp_HT'] >= 1.1) &
                (df_ht['Rec_HT_%'] >= 70)
            ].copy()

            if not df_ht.empty:
                if periodo == "🔚 Encerrados":
                    def validar_ht(row):
                        return "✅ Green HT" if (row['Gols_Home_HT'] + row['Gols_Away_HT']) > 0 else "❌ Red HT"
                    
                    df_ht['Placar HT'] = df_ht.apply(lambda r: f"{int(r['Gols_Home_HT'])} x {int(r['Gols_Away_HT'])}", axis=1)
                    df_ht['Status'] = df_ht.apply(validar_ht, axis=1)
                    # Incluído '⭐' e 'Pais'
                    cols_show = ['⭐', 'Hora', 'Pais', 'Liga', 'Home_Team', 'Placar HT', 'Away_Team', 'Exp_HT', 'Status']
                else:
                    cols_show = ['⭐', 'Hora', 'Pais', 'Liga', 'Home_Team', 'Away_Team', 'Exp_HT', 'Rec_HT_%']

                # 3. FILTRO DE EXIBIÇÃO (MODO SALVOS)
                df_display = df_ht.copy()
                if exibir_modo == "Salvos ⭐":
                    df_display = df_display[df_display['⭐'] == True]

                if not df_display.empty:
                    df_display = df_display.set_index('ID_Fixture')
                    
                    edited_ht = st.data_editor(
                        df_display[cols_show],
                        column_config={
                            "⭐": st.column_config.CheckboxColumn("Fav", default=False),
                            "Exp_HT": st.column_config.NumberColumn("Exp. HT", format="%.2f"),
                            "Rec_HT_%": st.column_config.NumberColumn("Rec. 0.5+", format="%.0f%%"),
                        },
                        disabled=[c for c in cols_show if c != "⭐"],
                        hide_index=True,
                        use_container_width=True,
                        key=f"editor_ht_{periodo}"
                    )

                    # --- LÓGICA DE SINCRONIZAÇÃO GLOBAL ---
                    for fix_id, row in edited_ht.iterrows():
                        if row['⭐'] and fix_id not in st.session_state.favoritos:
                            st.session_state.favoritos.add(fix_id)
                            salvar_favorito(fix_id)
                            st.rerun()
                        elif not row['⭐'] and fix_id in st.session_state.favoritos:
                            st.session_state.favoritos.remove(fix_id)
                            remover_favorito(fix_id)
                            st.rerun()
                else:
                    st.info("Nenhum favorito encontrado para HT.")
            else:
                st.info("Nenhuma partida com expectativa HT relevante encontrada.")
        else:
            st.info("Dados de HT não localizados no banco.")
