import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="ACD DAD v3.22 - Full Tools", layout="wide")

# --- 1. HÀM XỬ LÝ DỮ LIỆU ---
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
        date_str = str(row.get('DATE', '')).strip()
        arr_str = str(row.get('ARR', '')).strip()
        dep_str = str(row.get('DEP', '')).strip()
        current_year = datetime.now().year
        base_date = datetime.strptime(f"{date_str}-{current_year}", "%d-%b-%Y").date() if date_str and date_str != 'nan' else datetime.now().date()
        def parse_time(t_str, b_date):
            if not t_str or t_str in ['____', 'nan', 'None', '']: return None
            return datetime.combine(b_date, datetime.strptime(t_str, '%H:%M').time())
        t_arr = parse_time(arr_str, base_date); t_dep = parse_time(dep_str, base_date)
        if t_arr and t_dep and t_dep < t_arr: t_dep += timedelta(days=1)
        if not t_arr and t_dep: return t_dep - timedelta(hours=1.5), t_dep
        if t_arr and not t_dep: return t_arr, t_arr + timedelta(hours=2)
        return t_arr, t_dep
    except: return None, None

def check_overlap(row, current_df, role):
    name = row.get(role)
    if not name or name == "" or str(name).lower() == 'nan': return False
    overlap = current_df[
        (current_df[role] == name) & (current_df.index != row.name) & 
        (pd.notnull(current_df['START_DT'])) &
        (current_df['START_DT'] < row['END_DT']) & (current_df['END_DT'] > row['START_DT'])
    ]
    return not overlap.empty

# --- 2. SIDEBAR CẤU HÌNH ---
with st.sidebar:
    st.header("⚙️ Cấu hình Nhân sự")
    def process_names(s):
        if not s: return []
        for char in ['\n', '\t']: s = s.replace(char, ',')
        return [x.strip() for x in s.split(',') if x.strip()]

    raw_crs = st.text_area("Danh sách CRS khả dụng:", value="A,B,C,D,E")
    raw_mech = st.text_area("Danh sách MECH khả dụng:", value="1,2,3,4,5")
    
    crs_options = [""] + process_names(raw_crs)
    mech_options = [""] + process_names(raw_mech)
    num_crs = len(crs_options) - 1

    if st.button("🗑️ Reset App"):
        st.session_state.clear()
        st.rerun()

# --- 3. GIAO DIỆN CHÍNH ---
st.title("🚁 ACD DAD v3.22 - ĐIỀU HÀNH TỔNG LỰC")

raw_input = st.text_area("Dán dữ liệu lịch bay (Nhấn Ctrl + Enter)...", height=100)

if raw_input:
    df_raw = parse_raw_data(raw_input)
    if df_raw is not None:
        if 'df_final' not in st.session_state:
            res = df_raw.apply(lambda r: pd.Series(calculate_work_window(r)), axis=1)
            df_raw['START_DT'], df_raw['END_DT'] = res[0], res[1]
            df_raw['CRS_ASSIGN'] = ""; df_raw['MECH_ASSIGN'] = ""; df_raw['NOTES'] = ""
            st.session_state.df_final = df_raw

        df = st.session_state.df_final
        df['DURATION'] = df.apply(lambda r: int((r['END_DT'] - r['START_DT']).total_seconds()/60) if pd.notnull(r['START_DT']) else 0, axis=1)
        
        # STATUS REAL-TIME
        def get_status(r):
            if not r['CRS_ASSIGN'] or str(r['CRS_ASSIGN']) == 'nan' or r['CRS_ASSIGN'] == "": return "⚪ Trống"
            if check_overlap(r, df, 'CRS_ASSIGN') or check_overlap(r, df, 'MECH_ASSIGN'): return "⚠️ TRÙNG"
            return "✅ OK"
        df['STATUS'] = df.apply(get_status, axis=1)

        # --- 🛠️ BỘ CÔNG CỤ ĐIỀU PHỐI (3 NÚT TỔNG HỢP) ---
        st.subheader("🛠️ Bộ Công Cụ Điều Phối")
        tool1, tool2, tool3 = st.columns(3)
        
        with tool1:
            if st.button("📋 1. Copy từ Data gốc", use_container_width=True):
                if 'CRS' in df.columns: df['CRS_ASSIGN'] = df['CRS'].astype(str).replace('nan', '')
                if 'MECH' in df.columns: df['MECH_ASSIGN'] = df['MECH'].astype(str).replace('nan', '')
                st.rerun()
        
        with tool2:
            if st.button("🪄 2. Tự động chia mới", use_container_width=True):
                c_l = {n: 0 for n in crs_options if n}; m_l = {n: 0 for n in mech_options if n}
                for idx, row in df.iterrows():
                    for n in sorted(c_l, key=c_l.get):
                        if df[(df['CRS_ASSIGN']==n) & (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])].empty:
                            df.at[idx, 'CRS_ASSIGN'] = n; c_l[n] += row['DURATION']; break
                    for n in sorted(m_l, key=m_l.get):
                        if df[(df['MECH_ASSIGN']==n) & (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])].empty:
                            df.at[idx, 'MECH_ASSIGN'] = n; m_l[n] += row['DURATION']; break
                st.rerun()

        with tool3:
            if st.button("🔍 3. Rà soát lỗi trùng", use_container_width=True):
                c_l = {n: df[df['CRS_ASSIGN']==n]['DURATION'].sum() for n in crs_options if n}
                m_l = {n: df[df['MECH_ASSIGN']==n]['DURATION'].sum() for n in mech_options if n}
                for idx, row in df.iterrows():
                    for role, l_dict in [('CRS_ASSIGN', c_l), ('MECH_ASSIGN', m_l)]:
                        if check_overlap(row, df, role) or not row[role] or str(row[role]) == 'nan':
                            for cand in sorted(l_dict, key=l_dict.get):
                                if df[(df[role]==cand) & (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])].empty:
                                    df.at[idx, role] = cand; l_dict[cand] += row['DURATION']; break
                st.rerun()

        # BẢNG DỮ LIỆU
        st.data_editor(
            df,
            column_config={
                "STATUS": st.column_config.TextColumn("Lỗi", width="small"),
                "CRS_ASSIGN": st.column_config.SelectboxColumn("Phân CRS", options=crs_options),
                "MECH_ASSIGN": st.column_config.SelectboxColumn("Phân MECH", options=mech_options),
                "END_DT": st.column_config.DatetimeColumn("Kết thúc", format="HH:mm"),
            },
            disabled=[c for c in df.columns if c not in ["CRS_ASSIGN", "MECH_ASSIGN", "END_DT", "NOTES"]],
            hide_index=True, use_container_width=True
        )

        # --- GIẢI TRÌNH v3.12 ---
        st.divider()
        st.subheader("📋 GIẢI TRÌNH NHÂN LỰC CA TRỰC")
        def get_peak(df_in):
            events = []
            for _, r in df_in.iterrows():
                if pd.notnull(r['START_DT']):
                    events.append((r['START_DT'].to_pydatetime(), 1))
                    events.append((r['END_DT'].to_pydatetime(), -1))
            events.sort()
            max_c, curr_c, peak_t, points = 0, 0, None, []
            for t, v in events:
                points.append({"Time": t, "Concurrent": curr_c})
                curr_c += v
                points.append({"Time": t, "Concurrent": curr_c})
                if curr_c > max_c: max_c = curr_c; peak_t = t
            return max_c, peak_t, pd.DataFrame(points)

        max_req, peak_time, df_chart = get_peak(st.session_state.df_final)
        peak_str = peak_time.strftime("%H:%M") if peak_time else "N/A"

        m1, m2, m3 = st.columns(3)
        m1.metric("Nhân lực Peak", f"{max_req} người", delta=f"{num_crs} hiện có")
        m2.metric("Thời điểm Peak", peak_str)
        m3.metric("Kết quả", "✅ ĐỦ" if max_req <= num_crs else "⚠️ THIẾU")

        if not df_chart.empty:
            fig_m = go.Figure()
            fig_m.add_trace(go.Scatter(x=df_chart['Time'], y=df_chart['Concurrent'], fill='tozeroy', fillcolor='rgba(165, 42, 42, 0.1)', line=dict(color='#A52A2A', width=3, shape='vh'), name='Nhu cầu'))
            fig_m.add_trace(go.Scatter(x=[df_chart['Time'].min(), df_chart['Time'].max()], y=[num_crs, num_crs], line=dict(color='green', dash='dash'), name='Hiện có'))
            fig_m.add_vline(x=datetime.now(), line_width=2, line_color="red")
            st.plotly_chart(fig_m, use_container_width=True)
            st.info(f"Giải trình: Tại lúc {peak_str}, cần {max_req} người. Ca trực hiện có {num_crs} người.")

        # TIMELINE
        st.subheader("👨‍🔧 Timeline Công Việc")
        c_data = []
        for role in ['CRS_ASSIGN', 'MECH_ASSIGN']:
            for _, r in st.session_state.df_final.iterrows():
                if pd.notnull(r['START_DT']) and r[role] and str(r[role]) != 'nan':
                    c_data.append({"Nhân viên": r[role], "Bắt đầu": r['START_DT'], "Kết thúc": r['END_DT'], "Loại": role[:3]})
        if c_data:
            fig_g = px.timeline(pd.DataFrame(c_data), x_start="Bắt đầu", x_end="Kết thúc", y="Nhân viên", color="Loại")
            fig_g.add_vline(x=datetime.now(), line_width=3, line_color="red")
            st.plotly_chart(fig_g, use_container_width=True)
