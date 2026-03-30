import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="ACD DAD v3.59 - GIỮ NGUYÊN CẤU TRÚC", layout="wide")

# Lấy giờ hiện tại chuẩn Việt Nam (ICT)
now_vn = datetime.now()
now_ts = now_vn.timestamp() * 1000

# ═══════════════════════════════════════════════
# 1. HÀM XỬ LÝ LOGIC (ÉP DATE VÀO TIME)
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
        # Ép ngày từ cột DATE
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
        valid_role = v[v[role].notna() & (v[role] != '')]
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

# ═══════════════════════════════════════════════
# 2. GIAO DIỆN CHÍNH (GIỮ NGUYÊN CẤU TRÚC V3.56)
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
    if st.button("🗑️ Reset"): st.session_state.clear(); st.rerun()

st.title("🚀 ACD DAD v3.59")
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

        # TOOLBAR FIX LỖI
        c1, c2, c3 = st.columns(3)
        with c3:
            if st.button("🔍 Fix Tương Lai & Gợi ý", use_container_width=True):
                for idx, row in df.iterrows():
                    if not is_future(row, now_vn): continue # CHỈ FIX TƯƠNG LAI
                    for role, opt in [('CRS_ASSIGN', crs_opt[1:]), ('MECH_ASSIGN', mech_opt[1:])]:
                        # Check trùng cho dòng hiện tại
                        if row[role] and not df[(df[role]==row[role])&(df.index!=idx)&(df['START_DT']<row['END_DT'])&(df['END_DT']>row['START_DT'])].empty:
                            sug = suggest_replacement(df, idx, role, opt)
                            if sug: df.at[idx, role]=sug; df.at[idx, 'STATUS']="✨ Fix"
                st.rerun()

        # HIỂN THỊ BẢNG (Dùng st.data_editor như gốc của bạn)
        ov_crs, ov_mech = find_overlaps(df)
        
        # Hàm tô màu (Cam đậm cho tương lai, Vàng cho quá khứ)
        def styler(row):
            styles = [''] * len(row)
            idx, fut = row.name, is_future(df.loc[row.name], now_vn)
            ORANGE, YELLOW = 'background-color: #FF8C00; color: white;', 'background-color: #FFF176; color: black;'
            if idx in ov_crs: styles[list(row.index).index('CRS_ASSIGN')] = ORANGE if fut else YELLOW
            if idx in ov_mech: styles[list(row.index).index('MECH_ASSIGN')] = ORANGE if fut else YELLOW
            return styles

        # GIỮ NGUYÊN ST.DATA_EDITOR
        st.data_editor(
            df.style.apply(styler, axis=1),
            column_config={
                "START_DT": st.column_config.DatetimeColumn("Bắt đầu", format="HH:mm"),
                "END_DT": st.column_config.DatetimeColumn("Kết thúc", format="HH:mm"),
                "CRS_ASSIGN": st.column_config.SelectboxColumn("CRS", options=crs_opt),
                "MECH_ASSIGN": st.column_config.SelectboxColumn("MECH", options=mech_opt),
            },
            disabled=[c for c in df.columns if c not in ["CRS_ASSIGN", "MECH_ASSIGN", "END_DT", "NOTES", "STATUS"]],
            hide_index=True, use_container_width=True
        )

        # ─── BIỂU ĐỒ BAR CHART (THỐNG KÊ GIỜ LÀM - GIỮ NGUYÊN) ───
        st.divider()
        st.subheader("📊 Thống kê tải công việc")
        # Logic tính toán giờ đã làm/còn lại (như bản 3.56 bạn đưa)
        stats = []
        for n in crs_opt[1:]:
            d_done = df[(df['CRS_ASSIGN']==n) & (~is_future(df, now_vn))]['DURATION'].sum()/60
            d_rem = df[(df['CRS_ASSIGN']==n) & (is_future(df, now_vn))]['DURATION'].sum()/60
            stats.append({'Nhân viên': n, 'Role': 'CRS', 'Đã làm (h)': d_done, 'Còn lại (h)': d_rem})
        for n in mech_opt[1:]:
            d_done = df[(df['MECH_ASSIGN']==n) & (~is_future(df, now_vn))]['DURATION'].sum()/60
            d_rem = df[(df['MECH_ASSIGN']==n) & (is_future(df, now_vn))]['DURATION'].sum()/60
            stats.append({'Nhân viên': n, 'Role': 'MECH', 'Đã làm (h)': d_done, 'Còn lại (h)': d_rem})
        
        df_stats = pd.DataFrame(stats)
        fig_bar = go.Figure()
        for role_name, color in [('CRS','#1f77b4'),('MECH','#ff7f0e')]:
            sub = df_stats[df_stats['Role']==role_name]
            fig_bar.add_trace(go.Bar(name=f"{role_name} Đã làm", x=sub['Nhân viên'], y=sub['Đã làm (h)'], marker_color=color, opacity=0.9))
            fig_bar.add_trace(go.Bar(name=f"{role_name} Còn lại", x=sub['Nhân viên'], y=sub['Còn lại (h)'], marker_color=color, opacity=0.4))
        fig_bar.update_layout(barmode='stack', height=300)
        st.plotly_chart(fig_bar, use_container_width=True)

        # (Các phần Manpower và Timeline phía dưới giữ nguyên như file bạn gửi)
