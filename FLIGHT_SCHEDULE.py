import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="ACD DAD v3.24 - Full Report", layout="wide")

# --- 1. HÀM LOGIC ---
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
    if not name or name == "" or str(name).lower() in ['nan', 'none']: return False
    overlap = current_df[
        (current_df[role] == name) & (current_df.index != row.name) & 
        (pd.notnull(current_df['START_DT'])) &
        (current_df['START_DT'] < row['END_DT']) & (current_df['END_DT'] > row['START_DT'])
    ]
    return not overlap.empty

# --- 2. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Nhân sự")
    def process_names(s):
        if not s: return []
        for char in ['\n', '\t']: s = s.replace(char, ',')
        return [x.strip() for x in s.split(',') if x.strip()]
    raw_crs = st.text_area("CRS:", value="Hưng, Hoàng Tr, Cường VII, Thắng VII, Trung")
    raw_mech = st.text_area("MECH:", value="Go, Tài, Phú, Trường, Huy VII")
    crs_options = [""] + process_names(raw_crs)
    mech_options = [""] + process_names(raw_mech)
    num_crs_cap = len(crs_options) - 1
    if st.button("🗑️ Reset App"):
        st.session_state.clear()
        st.rerun()

# --- 3. GIAO DIỆN CHÍNH ---
st.title("🚁 ACD DAD v3.24 - FULL DASHBOARD")
raw_input = st.text_area("Dán lịch bay vào đây...", height=100)

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
        
        # Check lỗi riêng biệt
        df['CHECK_CRS'] = df.apply(lambda r: "⚠️ TRÙNG" if check_overlap(r, df, 'CRS_ASSIGN') else ("✅ OK" if r['CRS_ASSIGN'] else "⚪ Trống"), axis=1)
        df['CHECK_MECH'] = df.apply(lambda r: "⚠️ TRÙNG" if check_overlap(r, df, 'MECH_ASSIGN') else ("✅ OK" if r['MECH_ASSIGN'] else "⚪ Trống"), axis=1)

        # Bộ công cụ
        st.subheader("🛠️ Bộ Công Cụ")
        t1, t2, t3 = st.columns(3)
        with t1:
            if st.button("📋 1. Copy từ Data gốc", use_container_width=True):
                if 'CRS' in df.columns: df['CRS_ASSIGN'] = df['CRS'].astype(str).replace('nan', '')
                if 'MECH' in df.columns: df['MECH_ASSIGN'] = df['MECH'].astype(str).replace('nan', '')
                st.rerun()
        with t2:
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
        with t3:
            if st.button("🔍 3. Sửa trùng lịch", use_container_width=True):
                c_l = {n: df[df['CRS_ASSIGN']==n]['DURATION'].sum() for n in crs_options if n}
                m_l = {n: df[df['MECH_ASSIGN']==n]['DURATION'].sum() for n in mech_options if n}
                for idx, row in df.iterrows():
                    for role, l_dict in [('CRS_ASSIGN', c_l), ('MECH_ASSIGN', m_l)]:
                        if check_overlap(row, df, role) or not row[role]:
                            for cand in sorted(l_dict, key=l_dict.get):
                                if df[(df[role]==cand) & (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])].empty:
                                    df.at[idx, role] = cand; l_dict[cand] += row['DURATION']; break
                st.rerun()

        # Bảng dữ liệu
        st.subheader("📊 Bảng Phân Công Chi Tiết")
        edited_df = st.data_editor(
            df,
            column_config={
                "CHECK_CRS": st.column_config.TextColumn("Lỗi CRS", width="small"),
                "CHECK_MECH": st.column_config.TextColumn("Lỗi MECH", width="small"),
                "CRS_ASSIGN": st.column_config.SelectboxColumn("Phân CRS", options=crs_options),
                "MECH_ASSIGN": st.column_config.SelectboxColumn("Phân MECH", options=mech_options),
                "END_DT": st.column_config.DatetimeColumn("Kết thúc", format="HH:mm"),
            },
            disabled=[c for c in df.columns if c not in ["CRS_ASSIGN", "MECH_ASSIGN", "END_DT", "NOTES"]],
            hide_index=True, use_container_width=True
        )
        st.session_state.df_final = edited_df

        # --- PHẦN 1: TIMELINE NHÂN VIÊN ---
        st.divider()
        st.subheader("👨‍🔧 Timeline Công Việc & Now-line")
        now = datetime.now()
        c_data = []
        for role in ['CRS_ASSIGN', 'MECH_ASSIGN']:
            for _, r in st.session_state.df_final.iterrows():
                if pd.notnull(r['START_DT']) and r[role] and str(r[role]) != 'nan':
                    c_data.append({"Nhân viên": r[role], "Bắt đầu": r['START_DT'], "Kết thúc": r['END_DT'], "Loại": role[:3], "Tàu": r['REG']})
        
        if c_data:
            df_g = pd.DataFrame(c_data)
            t_min = df_g['Bắt đầu'].min() - timedelta(minutes=30)
            t_max = df_g['Kết thúc'].max() + timedelta(minutes=30)
            fig_g = px.timeline(df_g, x_start="Bắt đầu", x_end="Kết thúc", y="Nhân viên", color="Loại", hover_data=["Tàu"], range_x=[t_min, t_max])
            fig_g.add_vline(x=now, line_width=4, line_color="red", line_dash="solid")
            fig_g.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_g, use_container_width=True)

        # --- PHẦN 2: BÁO CÁO MANPOWER (GIẢI TRÌNH) ---
        st.subheader("📋 Phân tích Nhu cầu Nhân lực (Manpower)")
        events = []
        for _, r in st.session_state.df_final.iterrows():
            if pd.notnull(r['START_DT']):
                events.append((r['START_DT'].to_pydatetime(), 1))
                events.append((r['END_DT'].to_pydatetime(), -1))
        events.sort()
        curr, max_req, peak_t, points = 0, 0, None, []
        for t, v in events:
            points.append({"Time": t, "Count": curr})
            curr += v
            points.append({"Time": t, "Count": curr})
            if curr > max_req: max_req = curr; peak_t = t
        
        if points:
            df_p = pd.DataFrame(points)
            fig_p = go.Figure()
            fig_p.add_trace(go.Scatter(x=df_p['Time'], y=df_p['Count'], fill='tozeroy', fillcolor='rgba(165, 42, 42, 0.1)', line=dict(color='#A52A2A', shape='vh'), name='Cần thiết'))
            fig_p.add_trace(go.Scatter(x=[df_p['Time'].min(), df_p['Time'].max()], y=[num_crs_cap, num_crs_cap], line=dict(color='green', dash='dash', width=3), name=f'Hiện có ({num_crs_cap})'))
            fig_p.add_vline(x=now, line_width=2, line_color="red", line_dash="dot")
            fig_p.update_layout(height=300)
            st.plotly_chart(fig_p, use_container_width=True)
            
            peak_str = peak_t.strftime("%H:%M") if peak_t else "N/A"
            st.info(f"**Giải trình:** Lúc cao điểm **{peak_str}**, chúng ta cần **{max_req}** người. Hiện có **{num_crs_cap}** người. Trạng thái: **{'⚠️ THIẾU' if max_req > num_crs_cap else '✅ ĐỦ'}**.")

        # --- PHẦN 3: THỐNG KÊ GIỜ LÀM (WORKLOAD) ---
        st.divider()
        st.subheader("📈 Thống kê khối lượng công việc (Phút)")
        w1, w2 = st.columns(2)
        with w1:
            st.markdown("**Tổng phút CRS:**")
            for n in process_names(raw_crs):
                m = st.session_state.df_final[st.session_state.df_final['CRS_ASSIGN']==n]['DURATION'].sum()
                st.write(f"- {n}: `{int(m)}` phút")
        with w2:
            st.markdown("**Tổng phút MECH:**")
            for n in process_names(raw_mech):
                m = st.session_state.df_final[st.session_state.df_final['MECH_ASSIGN']==n]['DURATION'].sum()
                st.write(f"- {n}: `{int(m)}` phút")
