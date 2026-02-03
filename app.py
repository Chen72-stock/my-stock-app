import streamlit as st
import pandas as pd
import time
import io
import requests
import random

# --- 頁面配置 ---
st.set_page_config(page_title="台股籌碼評分系統", layout="wide")

# --- CSS 視覺優化 ---
st.markdown("""
    <style>
    html, body, [class*="ViewContainer"] { font-size: 15px !important; }
    [data-testid="stDataFrame"] td, [data-testid="stDataFrame"] th { font-size: 18px !important; }
    h1 { font-size: 1.8rem !important; color: #1E88E5; }
    div[data-testid="stDataFrame"] > div { height: 75vh !important; }
    </style>
    """, unsafe_allow_html=True)

st.title("📊 台股籌碼評分系統 (量能性質強化版)")

# --- 核心工具函數 ---
@st.cache_data(ttl=3600)
def fetch_yahoo_data(sid):
    symbol_sid = str(sid).zfill(4)
    for suffix in [".TW", ".TWO"]:
        symbol = f"{symbol_sid}{suffix}"
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        headers = {"User-Agent": "Mozilla/5.0"}
        try:
            time.sleep(random.uniform(0.05, 0.1))
            resp = requests.get(url, params={"range": "1y", "interval": "1d"}, headers=headers, timeout=5)
            if resp.status_code == 200:
                r = resp.json()['chart']['result'][0]
                df = pd.DataFrame({
                    'Close': r['indicators']['quote'][0]['close'], 
                    'Volume': r['indicators']['quote'][0]['volume']
                }, index=pd.to_datetime(r['timestamp'], unit='s'))
                return df.dropna()
        except: continue
    return None

def deep_clean(val):
    s = str(val).replace('=', '').replace('"', '').replace("'", "").strip()
    digits = "".join(filter(str.isdigit, s))
    return digits.zfill(4) if len(digits) > 0 else ""

def force_num(val):
    if pd.isna(val) or val == "" or val == "-": return 0.0
    try:
        s = str(val).replace(',', '').replace('"', '').strip()
        return float(s)
    except: return 0.0

def ultra_clean_read(file):
    if file is None: return None
    file.seek(0)
    raw_bytes = file.read()
    for enc in ['utf-8-sig', 'cp950', 'big5', 'utf-8']:
        try:
            content = raw_bytes.decode(enc).splitlines()
            header_idx = -1
            for i, line in enumerate(content):
                clean_line = line.replace('"', '').replace(' ', '').replace('=', '')
                if '代號' in clean_line and '名稱' in clean_line:
                    header_idx = i
                    break
            if header_idx != -1:
                df = pd.read_csv(io.StringIO("\n".join(content[header_idx:])), engine='python', on_bad_lines='skip', skipfooter=10)
                df.columns = [str(c).replace('"', '').replace(' ', '').replace('=', '').strip() for c in df.columns]
                cols = df.columns.tolist()
                if len(cols) >= 7:
                    df = df.rename(columns={cols[0]: "股票代號", cols[1]: "名稱", cols[5]: "融資_前日餘額", cols[6]: "融資_今日餘額"})
                return df
        except: continue
    return None

# --- 側邊欄 ---
with st.sidebar:
    st.header("數據導入")
    f_inst = st.file_uploader("三大法人買賣超 (T86)", type="csv")
    f_margin = st.file_uploader("融資融券餘額 (MI_MARGN)", type="csv")

# --- 主程式 ---
if st.button("🚀 啟動完整分析"):
    if f_inst and f_margin:
        with st.spinner('正在分析量能本質與籌碼中...'):
            df_inst = ultra_clean_read(f_inst)
            df_margin = ultra_clean_read(f_margin)

        if df_inst is not None and df_margin is not None:
            inst_id_col = [c for c in df_inst.columns if '代號' in c][0]
            inst_name_col = [c for c in df_inst.columns if '名稱' in c][0]
            
            results = []
            top_stocks = df_inst.head(60) 
            p_bar = st.progress(0)

            for i, (idx, row) in enumerate(top_stocks.iterrows()):
                sid = deep_clean(row[inst_id_col]); sname = str(row[inst_name_col])
                if not sid: continue
                
                # --- 1. 融資籌碼分析 ---
                m_mask = df_margin['股票代號'].astype(str).apply(deep_clean) == sid
                m_row = df_margin[m_mask]
                z_val, m_diff = "❌", 0
                if not m_row.empty:
                    m_diff = force_num(m_row.iloc[0]["融資_今日餘額"]) - force_num(m_row.iloc[0]["融資_前日餘額"])
                    if m_diff > 0: z_val = "✅"
                
                # --- 2. 技術與量能性質分析 ---
                df_y = fetch_yahoo_data(sid)
                t_data = {
                    "score": 0, "趨勢": "❌", "乖離": "正常", "量能性質": "量平", 
                    "trap": "正常", "bias_str": "0%"
                }
                
                if df_y is not None and len(df_y) >= 20:
                    c = df_y['Close']; v = df_y['Volume']
                    curr_c = c.iloc[-1]; prev_c = c.iloc[-2]
                    curr_v = v.iloc[-1]; v_ma5 = v.rolling(5).mean().iloc[-1]
                    ma5 = c.rolling(5).mean().iloc[-1]; ma20 = c.rolling(20).mean().iloc[-1]
                    
                    # 乖離與趨勢
                    bias = ((curr_c - ma20) / ma20) * 100
                    t_data["bias_str"] = f"{int(round(bias))}%"
                    
                    # --- 量能本質判斷邏輯 ---
                    price_up = curr_c > prev_c
                    vol_up = curr_v > v_ma5 * 1.1 # 量大於均量 10%
                    
                    if price_up and vol_up:
                        t_data["量能性質"] = "🔥攻擊買量"
                        t_data["score"] += 2
                    elif not price_up and vol_up:
                        t_data["量能性質"] = "🚨恐慌賣壓"
                        t_data["score"] -= 2
                    elif price_up and not vol_up:
                        t_data["量能性質"] = "⚠️量縮價漲"
                        t_data["score"] += 0.5
                    else:
                        t_data["量能性質"] = "💎縮量洗盤"
                        t_data["score"] += 1

                    # 陷阱偵測：資增 + 價跌 + 大量 = 散戶接刀
                    if m_diff > 0 and not price_up and vol_up:
                        t_data["trap"] = "💀散戶接刀"
                        t_data["score"] -= 3

                    t_data.update({
                        "趨勢": "✅" if curr_c > ma5 and ma5 > ma20 else "❌",
                        "score": t_data["score"] + (1 if curr_c > ma5 else 0) + (1 if curr_c > ma20 else 0)
                    })

                # 綜合評分計算
                final_score = t_data["score"] + (1 if z_val == "✅" else 0)

                results.append({
                    "代號": sid, "名稱": sname, "資增": z_val, "張數": int(m_diff),
                    "趨勢": t_data["趨勢"], "乖離": t_data["bias_str"], 
                    "量能本質": t_data["量能性質"], "籌碼警示": t_data["trap"],
                    "綜合評分": final_score
                })
                p_bar.progress((i + 1) / len(top_stocks))

            final_df = pd.DataFrame(results).sort_values("綜合評分", ascending=False)
            st.divider()
            st.subheader("📋 綜合掃描結果 (含量能診斷)")
            
            # 渲染表格
            st.dataframe(final_df.style.map(
                lambda x: 'color: #D32F2F; font-weight: bold' if any(k in str(x) for k in ["❌", "🚨", "💀", "賣壓"]) else 
                          'color: #388E3C; font-weight: bold' if any(k in str(x) for k in ["✅", "🔥", "買量", "攻擊"]) else '',
                subset=['資增', '趨勢', '量能本質', '籌碼警示']
            ), height=800, use_container_width=True)
            
        else:
            st.error("讀取失敗，請確認 CSV 檔案格式。")
