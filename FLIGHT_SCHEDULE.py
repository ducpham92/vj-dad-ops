import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="ACD - Điều Hành DAD v3.15", layout="wide")

# --- 1. XỬ LÝ DỮ LIỆU ---
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
        t_arr = parse_time(arr_str, base_date)
        t_dep = parse_time(dep_str, base_date)
        if t_arr and t_dep and t_dep < t_arr: t_dep += timedelta(days=1)
        if not t_arr and t_dep: return t_dep - timedelta(hours=1), t_dep
        if t_arr and not t_dep: return t_arr, t_arr + timedelta(hours=2)
        return t_arr, t_dep
    except: return None, None

def check_overlap(row, current_df, role):
    if not row[role] or pd.isnull(row['START_DT']) or pd.isnull(row['END_DT']): return False
    overlap = current_df[(current_df[role] == row[role]) & (current_df.index != row.name) & 
                        (current_df['START_DT'] < row['END_DT']) & (current_df['END_DT'] > row['START_DT'])]
    return not overlap.empty

def calculate_manpower_chart_data(df):
    if df.empty or 'START_DT' not in df.columns: return 0, None, pd.DataFrame()
    events = []
    for _, r in df.iterrows():
        if pd.notnull(r['START_DT']) and pd.notnull(r['END_DT']):
            events.append((r['START_DT'].to_pydatetime(), 1))
            events.append((r['END_DT'].to_pydatetime(), -1))
    events.sort()
    max_c, curr_c, peak_t = 0, 0, None
    points = []
    if events: points.append({"Time": events[0][0] - timedelta(minutes=1), "Concurrent": 0})
    for t, v in events:
        points.append({"Time": t, "Concurrent": curr_c})
        curr_c += v
        points.append({"Time": t, "Concurrent": curr_c})
        if curr_c > max_c: max_c = curr_c; peak_t = t
    return max_c, peak_t, pd.DataFrame(points)

# --- GIAO DIỆN ---
st.title("🚀 ACD DAD v3.15 - ĐIỀU HÀNH & GIẢI TRÌNH NHÂN LỰC")

with st.sidebar:
    st.header("⚙️ Cấu hình Ca")
    staff_crs = st.text_area("Danh sách CRS", value="A, B, C, D, E")
    staff_mech = st.text_area("Danh sách MECH", value="1, 2, 3, 4, 5")
    crs_list = [s.strip() for s in staff_crs.split(',') if s.strip()]
    mech_list = [s.strip() for s in staff_mech.split(',') if s.strip()]
    num_crs = len(crs_list)
    if st.button("🗑️ Xóa dữ liệu cũ"):
        if 'df_final' in st.session_state: del st.session_state.df_final
        st.rerun()

raw_input = st.text_area("Dán dữ liệu bay từ web điều hành...", height=100)

if raw_input:
    df_raw = parse_raw_data(raw_input)
    if df_raw is not None:
        if 'df_final' not in st.session_state:
            res = df_raw.apply(lambda r: pd.Series(calculate_work_window(r)), axis=1)
            df_raw['START_DT'], df_raw['END_DT'] = res[0], res[1]
            df_raw['CRS_ASSIGN'] = ""; df_raw['MECH_ASSIGN'] = ""
            st.session_state.df_final = df_raw

        # Cập nhật số phút làm việc
        st.session_state.df_final['DURATION'] = st.session_state.df_final.apply(
            lambda r: int((r['END_DT'] - r['START_DT']).total_seconds()/60) if pd.notnull(r['START_DT']) and pd.notnull(r['END_DT']) else 0, axis=1
        )

        # NÚT ĐIỀU KHIỂN
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🪄 Tự động phân lịch (Cân bằng tải)"):
                c_load = {n: 0 for n in crs_list}; m_load = {n: 0 for n in mech_list}
                for idx, row in st.session_state.df_final.iterrows():
                    if pd.isnull(row['START_DT']): continue
                    for n in sorted(c_load, key=c_load.get):
                        if st.session_state.df_final[(st.session_state.df_final['CRS_ASSIGN']==n) & (st.session_state.df_final['START_DT'] < row['END_DT']) & (st.session_state.df_final['END_DT'] > row['START_DT'])].empty:
                            st.session_state.df_final.at[idx, 'CRS_ASSIGN'] = n; c_load[n] += row['DURATION']; break
                    for n in sorted(m_load, key=m_load.get):
                        if st.session_state.df_final[(st.session_state.df_final['MECH_ASSIGN']==n) & (st.session_state.df_final['START_DT'] < row['END_DT']) & (st.session_state.df_final['END_DT'] > row['START_DT'])].empty:
                            st.session_state.df_final.at[idx, 'MECH_ASSIGN'] = n; m_load[n] += row['DURATION']; break
                st.rerun()
        with col2:
            if st.button("🔍 Sửa lỗi trùng giờ"):
                now = datetime.now()
                c_load = {n: st.session_state.df_final[st.session_state.df_final['CRS_ASSIGN']==n]['DURATION'].sum() for n in crs_list}
                m_load = {n: st.session_state.df_final[st.session_state.df_final['MECH_ASSIGN']==n]['DURATION'].sum() for n in mech_list}
                for idx, row in st.session_state.df_final[st.session_state.df_final['END_DT'] > now].iterrows():
                    for role, s_list, load_dict in [('CRS_ASSIGN', crs_list, c_load), ('MECH_ASSIGN', mech_list, m_load)]:
                        if check_overlap(row, st.session_state.df_final, role) or row[role] == "":
                            for cand in sorted(load_dict, key=load_dict.get):
                                if st.session_state.df_final[(st.session_state.df_final[role]==cand) & (st.session_state.df_final['START_DT'] < row['END_DT']) & (st.session_state.df_final['END_DT'] > row['START_DT'])].empty:
                                    st.session_state.df_final.at[idx, role] = cand; load_dict[cand] += row['DURATION']; break
                st.rerun()

        # BẢNG ĐIỀU PHỐI (Cho phép sửa END_DT)
        st.subheader("📊 Bảng Điều Phối Chi Tiết")
        st.session_state.df_final['STATUS'] = st.session_state.df_final.apply(lambda r: "⚠️ TRÙNG" if check_overlap(r, st.session_state.df_final, 'CRS_ASSIGN') or check_overlap(r, st.session_state.df_final, 'MECH_ASSIGN') else "", axis=1)
        
        edited_df = st.data_editor(
            st.session_state.df_final,
            column_config={
                "END_DT": st.column_config.DatetimeColumn("Kết thúc", format="HH:mm (DD/MM)"),
                "CRS_ASSIGN": st.column_config.SelectboxColumn("Phân CRS", options=crs_list),
                "MECH_ASSIGN": st.column_config.SelectboxColumn("Phân MECH", options=mech_list),
            },
            disabled=[c for c in st.session_state.df_final.columns if c not in ["CRS_ASSIGN", "MECH_ASSIGN", "END_DT", "NOTES"]],
            hide_index=True, use_container_width=True
        )
        st.session_state.df_final = edited_df

        # --- PHẦN GIẢI TRÌNH NHÂN LỰC (THEO Ý BẠN THÍCH) ---
        st.divider()
        st.subheader("🗓️ Giải Trình Nhu Cầu Nhân Lực")
        max_req, peak_t, df_chart = calculate_manpower_chart_data(st.session_state.df_final)
        
        m1, m2, m3 = st.columns(3)
        m1.metric("Cần tối thiểu", f"{max_req} người", delta=f"{num_crs} hiện có", delta_color="inverse" if max_req > num_crs else "normal")
        m2.metric("Giờ cao điểm", peak_t.strftime("%H:%M (%d/%m)") if peak_t else "N/A")
        m3.metric("Trạng thái ca", "⚠️ THIẾU NGƯỜI" if max_req > num_crs else "✅ ĐỦ NGƯỜI")

        if not df_chart.empty:
            fig_m = go.Figure()
            fig_m.add_trace(go.Scatter(x=df_chart['Time'], y=df_chart['Concurrent'], name='Nhu cầu (Số máy trùng)', fill='tozeroy', fillcolor='rgba(165, 42, 42, 0.2)', line=dict(color='#A52A2A', width=3, shape='vh')))
            fig_m.add_trace(go.Scatter(x=[df_chart['Time'].min(), df_chart['Time'].max()], y=[num_crs, num_crs], name='Nhân lực hiện có', line=dict(color='green', dash='dash', width=3)))
            fig_m.update_layout(height=300, margin=dict(t=10, b=10))
            st.plotly_chart(fig_m, use_container_width=True)
            
            # ĐOẠN TEXT GIẢI TRÌNH TỰ ĐỘNG
            p_str = peak_t.strftime("%H:%M") if peak_t else ""
            st.info(f"**Báo cáo giải trình:** Tại cao điểm lúc **{p_str}**, hệ thống ghi nhận có **{max_req}** chuyến bay diễn ra đồng thời. Với định biên **{num_crs}** người hiện tại, ca trực đang thiếu **{max_req - num_crs if max_req > num_crs else 0}** nhân sự để đảm bảo an toàn khai thác.")

        # --- TIMELINE NHÂN VIÊN ---
        st.subheader("👨‍🔧 Timeline Điều Phối Nhân Sự")
        c_data = []
        for role in ['CRS_ASSIGN', 'MECH_ASSIGN']:
            for _, r in st.session_state.df_final.iterrows():
                if pd.notnull(r['START_DT']) and r[role]:
                    c_data.append({"Nhân viên": r[role], "Bắt đầu": r['START_DT'], "Kết thúc": r['END_DT'], "Chuyến": r['FLIGHT'], "Loại": "CRS" if role == 'CRS_ASSIGN' else "MECH"})
        if c_data:
            df_g = pd.DataFrame(c_data)
            fig_g = px.timeline(df_g, x_start="Bắt đầu", x_end="Kết thúc", y="Nhân viên", color="Loại", color_discrete_map={"CRS": "#007BFF", "MECH": "#FF8C00"})
            fig_g.update_yaxes(autorange="reversed", type='category', categoryorder='array', categoryarray=sorted(df_g['Nhân viên'].unique()))
            st.plotly_chart(fig_g, use_container_width=True)

        # --- THỐNG KÊ CHI TIẾT (WORKLOAD) ---
        st.divider()
        st.subheader("📈 Thống Kê Tổng Giờ Làm Trong Ca")
        t1, t2 = st.columns(2)
        with t1:
            st.write("**Khối lượng CRS (phút):**")
            for n in crs_list:
                val = st.session_state.df_final[st.session_state.df_final['CRS_ASSIGN'] == n]['DURATION'].sum()
                st.write(f"- {n}: `{int(val)}` phút")
        with t2:
            st.write("**Khối lượng MECH (phút):**")
            for n in mech_list:
                val = st.session_state.df_final[st.session_state.df_final['MECH_ASSIGN'] == n]['DURATION'].sum()
                st.write(f"- {n}: `{int(val)}` phút")