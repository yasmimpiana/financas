import streamlit as st
import pandas as pd
from pymongo import MongoClient
from datetime import datetime, date
import plotly.express as px
from urllib.parse import quote_plus
import uuid
from dateutil.relativedelta import relativedelta

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Minhas Finanças", layout="centered")

# --- CONEXÃO COM O MONGO DB ---
# ==========================================
username = st.secrets["db_username"]
password = st.secrets["db_password"]
cluster_address = st.secrets["db_cluster"]

username_escaped = quote_plus(username)
password_escaped = quote_plus(password)
URI = f"mongodb+srv://{username_escaped}:{password_escaped}@{cluster_address}/?retryWrites=true&w=majority"

@st.cache_resource
def init_connection():
    return MongoClient(URI)

client = init_connection()
db = client['financas_db']
collection_transacoes = db['transacoes']
collection_categorias = db['categorias']
collection_tags = db['tags']

# --- FUNÇÕES AUXILIARES ---
def get_categorias():
    cats = list(collection_categorias.find({}, {'_id': 0, 'nome': 1}))
    lista = [c['nome'] for c in cats]
    if not lista: 
        return ["Alimentação", "Transporte", "Lazer", "Contas Fixas", "Salário", "Renda Extra"] 
    return sorted(lista)

def get_tags():
    tags = list(collection_tags.find({}, {'_id': 0, 'nome': 1}))
    lista = [t['nome'] for t in tags]
    return sorted(lista)

# --- INTERFACE ---
st.title("💰 Controle Financeiro")

aba_add, aba_dash, aba_config = st.tabs(["➕ Nova Movimentação", "📊 Dashboard", "⚙️ Cadastros"])

# ==============================================================================
# ABA 1: ADICIONAR (COM SELETOR RECEITA/DESPESA)
# ==============================================================================
with aba_add:
    st.header("Lançamento")
    
    # Seletor Principal
    tipo_transacao = st.radio("Tipo de Movimentação", ["Despesa 📉", "Receita 📈"], horizontal=True)
    eh_despesa = (tipo_transacao == "Despesa 📉")

    with st.form("form_transacao", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            data_mov = st.date_input("Data", datetime.today(), format="DD/MM/YYYY")
        
        with col2:
            valor_total = st.number_input("Valor (R$)", min_value=0.0, format="%.2f", value=None, placeholder="0,00")

        descricao = st.text_input("Descrição")
        
        # Carregando listas
        categoria = st.selectbox("Categoria", get_categorias())
        tags_selecionadas = st.multiselect("Tags", get_tags())
        
        st.divider()
        
        # Lógica Condicional: Parcelamento só aparece se for DESPESA e CRÉDITO
        forma_pagamento = "Dinheiro"
        qtd_parcelas = 1
        
        if eh_despesa:
            col3, col4 = st.columns(2)
            with col3:
                forma_pagamento = st.selectbox("Pagamento", ["Crédito", "Débito", "Pix", "Dinheiro"])
            with col4:
                if forma_pagamento == "Crédito":
                    qtd_parcelas = st.number_input("Quantas vezes?", min_value=1, value=1, step=1)
        else:
            # Se for Receita, simplifica
            forma_pagamento = st.selectbox("Recebido via", ["Pix", "Transferência", "Dinheiro", "Outros"])
        
        submitted = st.form_submit_button(f"💾 Salvar {tipo_transacao.split()[0]}", type="primary")
        
        if submitted:
            if valor_total is None:
                st.warning("⚠️ Insira um valor.")
            else:
                tipo_db = "Despesa" if eh_despesa else "Receita"
                valor_parcela = valor_total / qtd_parcelas
                id_grupo = str(uuid.uuid4())
                
                try:
                    lista_insercoes = []
                    
                    for i in range(qtd_parcelas):
                        # Data (soma meses se for parcelado)
                        data_final = data_mov + relativedelta(months=i)
                        
                        desc_final = descricao
                        if qtd_parcelas > 1:
                            desc_final = f"{descricao} ({i+1}/{qtd_parcelas})"
                        
                        documento = {
                            "data": datetime.combine(data_final, datetime.min.time()),
                            "descricao": desc_final,
                            "categoria": categoria,
                            "valor": round(valor_parcela, 2),
                            "tipo": tipo_db, # Novo campo fundamental!
                            "pagamento": forma_pagamento,
                            "parcela_atual": i + 1,
                            "total_parcelas": qtd_parcelas,
                            "group_id": id_grupo,
                            "tags": tags_selecionadas,
                            "criado_em": datetime.now()
                        }
                        lista_insercoes.append(documento)
                    
                    collection_transacoes.insert_many(lista_insercoes)
                    
                    if qtd_parcelas > 1:
                        st.success(f"✅ {tipo_db} parcelada em {qtd_parcelas}x salva!")
                    else:
                        st.success(f"✅ {tipo_db} salva com sucesso!")
                        
                except Exception as e:
                    st.error(f"Erro: {e}")

# ==============================================================================
# ABA 2: DASHBOARD (COM SALDO E LUCRO)
# ==============================================================================
with aba_dash:
    st.header("Fluxo de Caixa")
    
    dados = list(collection_transacoes.find())
    
    if not dados:
        st.info("Sem dados.")
    else:
        df = pd.DataFrame(dados)
        df['data'] = pd.to_datetime(df['data'])
        
        # Tratamento para dados antigos que não tinham o campo 'tipo'
        if 'tipo' not in df.columns:
            df['tipo'] = 'Despesa'
        else:
            df['tipo'].fillna('Despesa', inplace=True)
        
        # --- FILTROS ---
        with st.expander("🔍 Filtros de Período", expanded=True):
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                hoje = date.today()
                inicio_mes = hoje.replace(day=1)
                fim_padrao = hoje + relativedelta(months=1)
                intervalo = st.date_input("Período", (inicio_mes, fim_padrao), format="DD/MM/YYYY")
            with col_f2:
                filtro_tags = st.multiselect("Filtrar Tags", get_tags())

        # Aplica Filtros
        if isinstance(intervalo, tuple) and len(intervalo) == 2:
            s, e = intervalo
            df = df[(df['data'].dt.date >= s) & (df['data'].dt.date <= e)]
        
        if filtro_tags:
            def check_tags(row_tags):
                if not isinstance(row_tags, list): return False
                return bool(set(row_tags) & set(filtro_tags))
            df = df[df['tags'].apply(check_tags)]
            
        st.divider()
        
        # --- CÁLCULO DE KPI (INDICADORES) ---
        # Separa DataFrames
        df_rec = df[df['tipo'] == 'Receita']
        df_desp = df[df['tipo'] == 'Despesa']
        
        total_rec = df_rec['valor'].sum()
        total_desp = df_desp['valor'].sum()
        saldo = total_rec - total_desp
        
        kpi1, kpi2, kpi3 = st.columns(3)
        
        kpi1.metric("Entradas (Receitas)", f"R$ {total_rec:,.2f}", delta_color="normal")
        kpi2.metric("Saídas (Despesas)", f"R$ {total_desp:,.2f}", delta="-"+f"{total_desp:,.2f}", delta_color="inverse")
        kpi3.metric("Saldo do Período", f"R$ {saldo:,.2f}", delta=f"{saldo:,.2f}")
        
        st.divider()

        # --- GRÁFICOS ---
        if not df.empty:
            graf1, graf2 = st.columns(2)
            
            with graf1:
                # Gráfico de Barras Agrupadas (Entrada vs Saída por Mês)
                df['mes_ano'] = df['data'].dt.strftime('%m/%Y')
                # Agrupa por mês e por tipo
                df_grouped = df.groupby(['mes_ano', 'tipo'])['valor'].sum().reset_index()
                
                # Cores personalizadas: Verde para Receita, Vermelho para Despesa
                cores = {'Receita': '#2ecc71', 'Despesa': '#e74c3c'}
                
                fig_barras = px.bar(
                    df_grouped.sort_values('mes_ano'), # Ordenação básica (pode precisar de ajuste fino se virar o ano)
                    x='mes_ano', 
                    y='valor', 
                    color='tipo', 
                    barmode='group',
                    title='Entradas vs Saídas (Mensal)',
                    color_discrete_map=cores
                )
                st.plotly_chart(fig_barras, use_container_width=True)
                
            with graf2:
                # Pizza somente das despesas (para entender onde gastou)
                if not df_desp.empty:
                    fig_cat = px.pie(df_desp, values='valor', names='categoria', title='Onde gastei meu dinheiro?', hole=0.4)
                    st.plotly_chart(fig_cat, use_container_width=True)
                else:
                    st.info("Sem despesas para gerar gráfico de categorias.")
            
            # --- TABELA EXTRATO ---
            st.subheader("Extrato Detalhado")
            
            # Prepara tabela bonita
            df_show = df[['data', 'tipo', 'descricao', 'categoria', 'valor']].copy()
            df_show['data'] = df_show['data'].dt.strftime('%d/%m/%Y')
            
            # Formata valor com sinal
            def formata_valor(row):
                val = f"R$ {row['valor']:.2f}"
                if row['tipo'] == 'Receita':
                    return f"+ {val}"
                return f"- {val}"
            
            df_show['valor_fmt'] = df_show.apply(formata_valor, axis=1)
            
            # Mostra colunas finais
            st.dataframe(
                df_show[['data', 'tipo', 'descricao', 'categoria', 'valor_fmt']].sort_values(by='data', ascending=False),
                hide_index=True, 
                use_container_width=True
            )
        else:
            st.warning("Nenhum dado encontrado.")

# ==============================================================================
# ABA 3: CADASTROS
# ==============================================================================
with aba_config:
    st.header("Gerenciar Cadastros")
    col_c1, col_c2 = st.columns(2)
    
    with col_c1:
        st.subheader("Categorias")
        nova_cat = st.text_input("Nova Categoria (Ex: Salário, Mercado)")
        if st.button("Adicionar Categoria"):
            if nova_cat and not collection_categorias.find_one({"nome": nova_cat}):
                collection_categorias.insert_one({"nome": nova_cat})
                st.success("Adicionado!")
                st.rerun()
        st.caption(f"Existentes: {', '.join(get_categorias())}")

    with col_c2:
        st.subheader("Tags")
        nova_tag = st.text_input("Nova Tag")
        if st.button("Adicionar Tag"):
            if nova_tag:
                tag_lower = nova_tag.lower().strip()
                if not collection_tags.find_one({"nome": tag_lower}):
                    collection_tags.insert_one({"nome": tag_lower})
                    st.success("Tag criada!")
                    st.rerun()
        st.caption(f"Existentes: {', '.join(get_tags())}")