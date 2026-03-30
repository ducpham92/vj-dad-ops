import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

# Cấu hình trang
st.set_page_config(page_title="ACD DAD v3.53 - PERFECT TIME", layout="wide")

# --- XỬ LÝ MÚI GIỜ CHUẨN ---
# Lấy giờ hiện tại của máy tính người dùng (Local Time - VN)
now_vn = datetime.now() 
now_ts = now_vn.timestamp() * 1000

# --- 1. HÀM XỬ LÝ LOGIC ---
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
        arr_str = str(row.get('ARR', '')).strip()
        dep_str = str(row.get('DEP', '')).strip()
        curr_dt = datetime.now()
        try:
            if '-' in date_val: base_date = datetime.strptime(f"{date_val}-{curr_dt.year}", "%d-%b-%Y").date()
            else: base_date = datetime.strptime(f"{date_val}/{curr_dt.year}", "%d/%m/%Y").date()
        except: base_date = curr_dt.date()

        def parse_time(t_str, b_date):
            if not t_str or t_str in ['____', 'nan', 'None', '', 'nan']: return None
            t_str = t_str.replace(':', '')
            return datetime.combine(b_date, datetime.strptime(t_str, '%H%M').time())

        t_arr = parse_time(arr_str, base_date)
        t_dep = parse_time(dep_str, base_date)
        if not t_arr and t_dep: return t_dep - timedelta(hours=1), t_dep
        if t_arr and not t_dep: return t_arr, t_arr + timedelta(hours=2)
        if t_arr and t_dep:
            if t_dep < t_arr: t_dep += timedelta(days=1)
            return t_arr, t_dep
        return t_arr, t_dep
    except: return None, None

def check_overlap(row, current_df, role):
    name = row.get(role)
    if not name or name == "" or str(name).lower() in ['nan', 'none']: return False
    if pd.isnull(row['START_DT']): return False
    overlap = current_df[
        (current_df[role] == name) & (current_df.index != row.name) & 
        (pd.notnull(current_df['START_DT'])) &
        (current_df['START_DT'] < row['END_DT']) & (current_df['END_DT'] > row['START_DT'])
    ]
    return not overlap.empty

# --- 2. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Cấu hình")
    def process_names(s):
        if not s: return []
        for char in ['\n', '\t']: s = s.replace(char, ',')
        return [x.strip() for x in s.split(',') if x.strip()]
    
    raw_crs = st.text_area("CRS:", value="Hưng, Hoàng Tr, Cường VII, Thắng VII, Trung")
    raw_mech = st.text_area("MECH:", value="Go, Tài, Phú, Trường, Huy VII")
    crs_opt = [""] + process_names(raw_crs)
    mech_opt = [""] + process_names(raw_mech)
    num_crs = len(crs_opt) - 1
    if st.button("🗑️ Reset Toàn Bộ"):
        st.session_state.clear()
        st.rerun()

# --- 3. MAIN ---
st.title("🚀 ACD DAD v3.53")
st.caption(f"Giờ hiện tại: {now_vn.strftime('%H:%M:%S')} (ICT) | Nhấn 'R' để cập nhật vạch đỏ")

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
        df['DURATION'] = df.apply(lambda r: int((r['END_DT'] - r['START_DT']).total_seconds()/60) if pd.notnull(r['START_DT']) else 0, axis=1)

        # --- TOOLBAR ---
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("📋 1. Copy Data gốc", use_container_width=True):
                if 'CRS' in df.columns: df['CRS_ASSIGN'] = df['CRS'].astype(str).replace('nan', '')
                if 'MECH' in df.columns: df['MECH_ASSIGN'] = df['MECH'].astype(str).replace('nan', '')
                st.rerun()
        with c2:
            if st.button("🪄 2. Tự chia lịch", use_container_width=True):
                c_l, m_l = {n: 0 for n in crs_opt if n}, {n: 0 for n in mech_opt if n}
                for idx, row in df.iterrows():
                    for n in sorted(c_l, key=c_l.get):
                        if df[(df['CRS_ASSIGN']==n) & (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])].empty:
                            df.at[idx, 'CRS_ASSIGN'] = n; c_l[n] += row['DURATION']; break
                    for n in sorted(m_l, key=m_l.get):
                        if df[(df['MECH_ASSIGN']==n) & (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])].empty:
                            df.at[idx, 'MECH_ASSIGN'] = n; m_l[n] += row['DURATION']; break
                st.rerun()
        with c3:
            if st.button("🔍 3. Fix Tương Lai & Gợi ý", use_container_width=True):
                for idx, row in df.iterrows():
                    if pd.notnull(row['START_DT']) and row['START_DT'] >= now_vn:
                        if check_overlap(row, df, 'CRS_ASSIGN'):
                            for n in crs_opt[1:]:
                                if df[(df['CRS_ASSIGN']==n) & (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])].empty:
                                    df.at[idx, 'CRS_ASSIGN'] = n; df.at[idx, 'STATUS'] = "✨ Fix"; break
                        if check_overlap(row, df, 'MECH_ASSIGN'):
                            for n in mech_opt[1:]:
                                if df[(df['MECH_ASSIGN']==n) & (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])].empty:
                                    df.at[idx, 'MECH_ASSIGN'] = n; df.at[idx, 'STATUS'] = "✨ Fix"; break
                st.rerun()

        # Data Editor
        st.data_editor(df, column_config={
            "START_DT": st.column_config.DatetimeColumn("Bắt đầu", format="HH:mm"),
            "END_DT": st.column_config.DatetimeColumn("Kết thúc", format="HH:mm"),
            "CRS_ASSIGN": st.column_config.SelectboxColumn("CRS", options=crs_opt),
            "MECH_ASSIGN": st.column_config.SelectboxColumn("MECH", options=mech_opt),
        }, disabled=[c for c in df.columns if c not in ["CRS_ASSIGN", "MECH_ASSIGN", "END_DT", "NOTES", "STATUS"]], hide_index=True, use_container_width=True)

        # --- MANPOWER CHART ---
        st.divider()
        events = []
        for _, r in df.iterrows():
            if pd.notnull(r['START_DT']):
                events.append((r['START_DT'].to_pydatetime(), 1))
                events.append((r['END_DT'].to_pydatetime(), -1))
        events.sort()
        curr, points = 0, []
        for t, v in events:
            points.append({"Time": t, "Count": curr}); curr += v; points.append({"Time": t, "Count": curr})
        
        if points:
            st.subheader("📊 Manpower Report")
            df_p = pd.DataFrame(points)
            fig_p = go.Figure()
            fig_p.add_trace(go.Scatter(x=df_p['Time'], y=df_p['Count'], fill='tozeroy', line=dict(color='#A52A2A', shape='vh'), name='Cần'))
            fig_p.add_trace(go.Scatter(x=[df_p['Time'].min(), df_p['Time'].max()], y=[num_crs, num_crs], line=dict(color='green', dash='dash'), name='Có'))
            fig_p.add_vline(x=now_ts, line_width=3, line_color="red")
            fig_p.update_layout(height=200, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_p, use_container_width=True)

        # --- TIMELINE CHART ---
        c_data = []
        for role in ['CRS_ASSIGN', 'MECH_ASSIGN']:
            for _, r in df.iterrows():
                if pd.notnull(r['START_DT']) and r[role]:
                    c_data.append({
                        "Nhân viên": r[role], "Bắt đầu": r['START_DT'], "Kết thúc": r['END_DT'], "Loại": role[:3],
                        "Chuyến": r.get('FLIGHT',''), "Tuyến": r.get('ROUTE',''), "Reg": r.get('REG','')
                    })
        if c_data:
            st.subheader("👨‍🔧 Timeline")
            fig_g = px.timeline(pd.DataFrame(c_data), x_start="Bắt đầu", x_end="Kết thúc", y="Nhân viên", color="Loại", hover_data=["Chuyến", "Reg"])
            fig_g.update_layout(xaxis_type='date', height=400)
            # Quan trọng: Add vạch đỏ trùng khớp với trục X
            fig_g.add_vline(x=now_ts, line_width=4, line_color="red")
            fig_g.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_g, use_container_width=True)

        # Xuất code copy
        st.subheader("📋 Dòng tên dán Web")
        cp1, cp2 = st.columns(2)
        with cp1: st.code("\n".join(df['CRS_ASSIGN'].fillna('').tolist()), language="text")
        with cp2: st.code("\n".join(df['MECH_ASSIGN'].fillna('').tolist()), language="text")
