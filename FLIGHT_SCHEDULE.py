import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="ACD DAD v3.58 - FULL & PRECISE", layout="wide")

# Lấy giờ hiện tại chuẩn Việt Nam (ICT)
now_vn = datetime.now()
now_ts = now_vn.timestamp() * 1000

# ═══════════════════════════════════════════════
# 1. HÀM XỬ LÝ LOGIC (ĐÃ ĐỒNG BỘ NGÀY-GIỜ)
# ═══════════════════════════════════════════════

def parse_raw_data(data_string):
    if not data_string.strip(): return None
    try:
        lines = data_string.strip().split('\n')
        header_line = lines[0]
        filtered_lines = [header_line]
        for line in lines[1:]:
            if line.strip() != header_line.strip(): filtered_lines.append(line)
        df = pd.read_csv(io.StringIO("\n".join(filtered_lines)), sep=r'\t|\s{2,}', engine='python')
        df.columns = [str(col).strip().upper() for col in df.columns]
        return df.rename(columns={'A/C REGN': 'REG', 'FLT-RADAR': 'ARR_ACT', 'A/C TYPE': 'AC_TYPE'})
    except: return None

def calculate_work_window(row):
    try:
        date_val = str(row.get('DATE', '')).strip()
        arr_str, dep_str = str(row.get('ARR', '')).strip(), str(row.get('DEP', '')).strip()
        curr_dt = datetime.now()
        try:
            if '-' in date_val: base_date = datetime.strptime(f"{date_val}-{curr_dt.year}", "%d-%b-%Y").date()
            else: base_date = datetime.strptime(f"{date_val}/{curr_dt.year}", "%d/%m/%Y").date()
        except: base_date = curr_dt.date()

        def parse_to_dt(t_str, b_date):
            if not t_str or t_str in ['____', 'nan', 'None', '', 'nan']: return None
            return datetime.combine(b_date, datetime.strptime(t_str.replace(':', ''), '%H%M').time())

        dt_a, dt_d = parse_to_dt(arr_str, base_date), parse_to_dt(dep_str, base_date)
        if not dt_a and dt_d: return dt_d - timedelta(hours=1), dt_d
        if dt_a and not dt_d: return dt_a, dt_a + timedelta(hours=2)
        if dt_a and dt_d:
            if dt_d < dt_a: dt_d += timedelta(days=1)
            return dt_a, dt_d
        return None, None
    except: return None, None

def is_future(row, now):
    if pd.isnull(row['START_DT']): return False
    return row['START_DT'] > now

def find_overlaps(df):
    res_crs, res_mech = set(), set()
    v = df[df['START_DT'].notna() & df['END_DT'].notna()]
    for role, ov_set in [('CRS_ASSIGN', res_crs), ('MECH_ASSIGN', res_mech)]:
        valid_role = v[v[role].notna() & (v[role] != '') & (~v[role].astype(str).str.lower().isin(['nan','none']))]
        idxs = valid_role.index.tolist()
        for i in range(len(idxs)):
            for j in range(i+1, len(idxs)):
                ri, rj = valid_role.loc[idxs[i]], valid_role.loc[idxs[j]]
                if ri[role] == rj[role] and ri['START_DT'] < rj['END_DT'] and rj['START_DT'] < ri['END_DT']:
                    ov_set.add(idxs[i]); ov_set.add(idxs[j])
    return res_crs, res_mech

def suggest_replacement(df, idx, role, options):
    row = df.loc[idx]
    for name in options:
        if not name: continue
        conflict = df[(df[role] == name) & (df.index != idx) & df['START_DT'].notna() & 
                      (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])]
        if conflict.empty: return name
    return None

def build_step_events(df_src, role):
    events = []
    for _, r in df_src.iterrows():
        if pd.notnull(r['START_DT']) and r[role] and str(r[role]).lower() not in ['nan','none','']:
            events.append((r['START_DT'].to_pydatetime(), 1))
            events.append((r['END_DT'].to_pydatetime(), -1))
    events.sort()
    curr, points = 0, []
    for t, v in events:
        points.append({'Time': t, 'Count': curr}); curr += v; points.append({'Time': t, 'Count': curr})
    return pd.DataFrame(points) if points else pd.DataFrame(columns=['Time','Count'])

# ═══════════════════════════════════════════════
# 2. GIAO DIỆN & SIDEBAR
# ═══════════════════════════════════════════════

with st.sidebar:
    st.header("⚙️ Cấu hình")
    def process_names(s):
        if not s: return []
        for c in ['\n','\t']: s = s.replace(c, ',')
        return [x.strip() for x in s.split(',') if x.strip()]

    raw_crs = st.text_area("CRS:", value="Hưng, Hoàng Tr, Cường VII, Thắng VII, Trung")
    raw_mech = st.text_area("MECH:", value="Go, Tài, Phú, Trường, Huy VII")
    crs_opt, mech_opt = [""] + process_names(raw_crs), [""] + process_names(raw_mech)
    num_crs, num_mech = len(crs_opt)-1, len(mech_opt)-1
    if st.button("🗑️ Reset"): st.session_state.clear(); st.rerun()

st.title("🚀 ACD DAD v3.58")
st.caption(f"Giờ hiện tại: {now_vn.strftime('%d/%m/%Y %H:%M:%S')} (ICT)")

raw_input = st.text_area("Dán lịch bay...", height=80)

if raw_input:
    df_raw = parse_raw_data(raw_input)
    if df_raw is not None:
        if 'df_final' not in st.session_state:
            res = df_raw.apply(lambda r: pd.Series(calculate_work_window(r)), axis=1)
            df_raw['START_DT'], df_raw['END_DT'] = res[0], res[1]
            df_raw['CRS_ASSIGN'] = ""; df_raw['MECH_ASSIGN'] = ""; df_raw['STATUS'] = "⚪"
            st.session_state.df_final = df_raw

        df = st.session_state.df_final
        df['DURATION'] = df.apply(lambda r: int((r['END_DT']-r['START_DT']).total_seconds()/60) if pd.notnull(r['START_DT']) else 0, axis=1)

        # --- TOOLBAR ---
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("📋 1. Copy Data gốc", use_container_width=True):
                if 'CRS' in df.columns: df['CRS_ASSIGN'] = df['CRS'].astype(str).replace('nan','')
                if 'MECH' in df.columns: df['MECH_ASSIGN'] = df['MECH'].astype(str).replace('nan','')
                st.rerun()
        with c2:
            if st.button("🪄 2. Tự chia lịch", use_container_width=True):
                c_l, m_l = {n:0 for n in crs_opt if n}, {n:0 for n in mech_opt if n}
                for idx, row in df.iterrows():
                    if not is_future(row, now_vn) or pd.isnull(row['START_DT']): continue
                    for n in sorted(c_l, key=c_l.get):
                        if df[(df['CRS_ASSIGN']==n)&(df['START_DT']<row['END_DT'])&(df['END_DT']>row['START_DT'])].empty:
                            df.at[idx,'CRS_ASSIGN']=n; c_l[n]+=row['DURATION']; break
                    for n in sorted(m_l, key=m_l.get):
                        if df[(df['MECH_ASSIGN']==n)&(df['START_DT']<row['END_DT'])&(df['END_DT']>row['START_DT'])].empty:
                            df.at[idx,'MECH_ASSIGN']=n; m_l[n]+=row['DURATION']; break
                st.rerun()
        with c3:
            if st.button("🔍 3. Fix Tương Lai & Gợi ý", use_container_width=True):
                for idx, row in df.iterrows():
                    if not is_future(row, now_vn): continue
                    for role, opt in [('CRS_ASSIGN', crs_opt[1:]), ('MECH_ASSIGN', mech_opt[1:])]:
                        if row[role] and not df[(df[role]==row[role])&(df.index!=idx)&(df['START_DT']<row['END_DT'])&(df['END_DT']>row['START_DT'])].empty:
                            sug = suggest_replacement(df, idx, role, opt)
                            if sug: df.at[idx, role]=sug; df.at[idx, 'STATUS']="✨ Fix"
                st.rerun()

        # --- HIỂN THỊ BẢNG ---
        ov_crs, ov_mech = find_overlaps(df)
        def styler(row):
            styles = [''] * len(row)
            idx, fut = row.name, is_future(df.loc[row.name], now_vn)
            ORANGE, YELLOW = 'background-color: #FF8C00; color: white;', 'background-color: #FFF176; color: black;'
            if idx in ov_crs: styles[list(row.index).index('CRS_ASSIGN')] = ORANGE if fut else YELLOW
            if idx in ov_mech: styles[list(row.index).index('MECH_ASSIGN')] = ORANGE if fut else YELLOW
            return styles

        st.subheader("📋 Bảng phân công")
        st.dataframe(df.style.apply(styler, axis=1), use_container_width=True)

        # --- MANPOWER ---
        st.divider()
        st.subheader("📊 Manpower Report")
        col_c, col_m = st.columns(2)
        for col, role, num, label, color in [(col_c, 'CRS_ASSIGN', num_crs, 'CRS', '#A52A2A'), (col_m, 'MECH_ASSIGN', num_mech, 'MECH', '#1964B4')]:
            with col:
                df_s = build_step_events(df, role)
                if not df_s.empty:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=df_s['Time'], y=df_s['Count'], fill='tozeroy', line=dict(color=color, shape='vh'), name='Cần'))
                    fig.add_trace(go.Scatter(x=[df_s['Time'].min(), df_s['Time'].max()], y=[num, num], line=dict(color='green', dash='dash'), name='Có'))
                    fig.add_vline(x=now_ts, line_width=2, line_color="red")
                    fig.update_layout(height=220, title=f"Nhu cầu {label}", margin=dict(l=10,r=10,t=30,b=10))
                    st.plotly_chart(fig, use_container_width=True)

        # --- TIMELINE ---
        st.subheader("👨‍🔧 Timeline")
        c_data = []
        for role, label in [('CRS_ASSIGN','CRS'), ('MECH_ASSIGN','MECH')]:
            for idx, r in df.iterrows():
                if pd.notnull(r['START_DT']) and r[role]:
                    c_data.append({"NV": r[role], "Bắt đầu": r['START_DT'], "Kết thúc": r['END_DT'], "Loại": label, "Chuyến": r.get('FLIGHT','')})
        if c_data:
            fig_g = px.timeline(pd.DataFrame(c_data), x_start="Bắt đầu", x_end="Kết thúc", y="NV", color="Loại")
            fig_g.add_vline(x=now_ts, line_width=4, line_color="red")
            fig_g.update_yaxes(autorange="reversed")
            fig_g.update_layout(height=400)
            st.plotly_chart(fig_g, use_container_width=True)

        # Copy tên
        st.subheader("📋 Dòng tên dán Web")
        cp1, cp2 = st.columns(2)
        with cp1: st.code("\n".join(df['CRS_ASSIGN'].fillna('').tolist()))
        with cp2: st.code("\n".join(df['MECH_ASSIGN'].fillna('').tolist()))
