import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="ACD DAD v3.26 - Time Fix", layout="wide")

# --- 1. HÀM XỬ LÝ LOGIC THỜI GIAN (QUAN TRỌNG) ---
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
        
        # Tự động lấy năm hiện tại
        now_dt = datetime.now()
        curr_year = now_dt.year
        
        # Xử lý DATE (Chấp nhận cả 30-Mar hoặc 30/03)
        try:
            if '-' in date_val:
                base_date = datetime.strptime(f"{date_val}-{curr_year}", "%d-%b-%Y").date()
            else:
                base_date = datetime.strptime(f"{date_val}/{curr_year}", "%d/%m/%Y").date()
        except:
            base_date = now_dt.date()

        def parse_time(t_str, b_date):
            if not t_str or t_str in ['____', 'nan', 'None', '', 'nan']: return None
            # Hỗ trợ cả định dạng HH:MM hoặc HHMM
            t_str = t_str.replace(':', '')
            return datetime.combine(b_date, datetime.strptime(t_str, '%H%M').time())

        t_arr = parse_time(arr_str, base_date)
        t_dep = parse_time(dep_str, base_date)

        # Xử lý qua đêm (Dep < Arr)
        if t_arr and t_dep and t_dep < t_arr:
            t_dep += timedelta(days=1)
        
        # Fallback nếu thiếu 1 trong 2 giờ
        if not t_arr and t_dep: t_arr = t_dep - timedelta(hours=1.5)
        if t_arr and not t_dep: t_dep = t_arr + timedelta(hours=2)
        
        return t_arr, t_dep
    except Exception as e:
        return None, None

def check_overlap(row, current_df, role):
    name = row.get(role)
    if not name or name == "" or str(name).lower() in ['nan', 'none', '']: return False
    if pd.isnull(row['START_DT']) or pd.isnull(row['END_DT']): return False
    
    overlap = current_df[
        (current_df[role] == name) & (current_df.index != row.name) & 
        (pd.notnull(current_df['START_DT'])) &
        (current_df['START_DT'] < row['END_DT']) & (current_df['END_DT'] > row['START_DT'])
    ]
    return not overlap.empty

# --- 2. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Nhân sự Ca Trực")
    def process_names(s):
        if not s: return []
        for char in ['\n', '\t']: s = s.replace(char, ',')
        return [x.strip() for x in s.split(',') if x.strip()]
    raw_crs = st.text_area("Danh sách CRS:", value="Hưng, Hoàng Tr, Cường VII, Thắng VII, Trung")
    raw_mech = st.text_area("Danh sách MECH:", value="Go, Tài, Phú, Trường, Huy VII")
    crs_opt = [""] + process_names(raw_crs)
    mech_opt = [""] + process_names(raw_mech)
    if st.button("🗑️ Reset Dữ Liệu"):
        st.session_state.clear()
        st.rerun()

# --- 3. GIAO DIỆN CHÍNH ---
st.title("🚁 ACD DAD v3.26 - FIX TIME & TIMELINE")
raw_input = st.text_area("Dán lịch bay từ Web điều hành...", height=80)

if raw_input:
    df_raw = parse_raw_data(raw_input)
    if df_raw is not None:
        if 'df_final' not in st.session_state:
            # ÉP TÍNH TOÁN THỜI GIAN NGAY KHI DÁN
            res = df_raw.apply(lambda r: pd.Series(calculate_work_window(r)), axis=1)
            df_raw['START_DT'], df_raw['END_DT'] = res[0], res[1]
            df_raw['CRS_ASSIGN'] = ""; df_raw['MECH_ASSIGN'] = ""; df_raw['NOTES'] = ""
            st.session_state.df_final = df_raw

        df = st.session_state.df_final
        
        # Tính Duration (Phút) - Nếu ra 0 hoặc None là do START_DT/END_DT lỗi
        df['DURATION'] = df.apply(lambda r: int((r['END_DT'] - r['START_DT']).total_seconds()/60) if pd.notnull(r['START_DT']) and pd.notnull(r['END_DT']) else 0, axis=1)
        
        # Check lỗi 2 cột
        df['CHECK_CRS'] = df.apply(lambda r: "⚠️ TRÙNG" if check_overlap(r, df, 'CRS_ASSIGN') else ("✅ OK" if r['CRS_ASSIGN'] else "⚪"), axis=1)
        df['CHECK_MECH'] = df.apply(lambda r: "⚠️ TRÙNG" if check_overlap(r, df, 'MECH_ASSIGN') else ("✅ OK" if r['MECH_ASSIGN'] else "⚪"), axis=1)

        # Bộ công cụ
        st.subheader("🛠️ Công Cụ Nhanh")
        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("📋 1. Copy Data gốc", use_container_width=True):
                if 'CRS' in df.columns: df['CRS_ASSIGN'] = df['CRS'].astype(str).replace('nan', '').replace('None', '')
                if 'MECH' in df.columns: df['MECH_ASSIGN'] = df['MECH'].astype(str).replace('nan', '').replace('None', '')
                st.rerun()
        with c2:
            if st.button("🪄 2. Tự chia lịch", use_container_width=True):
                c_l = {n: 0 for n in crs_opt if n}; m_l = {n: 0 for n in mech_opt if n}
                for idx, row in df.iterrows():
                    if pd.isnull(row['START_DT']): continue
                    for n in sorted(c_l, key=c_l.get):
                        if df[(df['CRS_ASSIGN']==n) & (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])].empty:
                            df.at[idx, 'CRS_ASSIGN'] = n; c_l[n] += row['DURATION']; break
                    for n in sorted(m_l, key=m_l.get):
                        if df[(df['MECH_ASSIGN']==n) & (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])].empty:
                            df.at[idx, 'MECH_ASSIGN'] = n; m_l[n] += row['DURATION']; break
                st.rerun()
        with c3:
            if st.button("🔍 3. Fix trùng lịch", use_container_width=True):
                st.rerun()

        # Bảng dữ liệu chính
        st.data_editor(
            df,
            column_config={
                "CHECK_CRS": st.column_config.TextColumn("Lỗi CRS", width="small"),
                "CHECK_MECH": st.column_config.TextColumn("Lỗi MECH", width="small"),
                "CRS_ASSIGN": st.column_config.SelectboxColumn("Phân CRS", options=crs_opt),
                "MECH_ASSIGN": st.column_config.SelectboxColumn("Phân MECH", options=mech_opt),
                "START_DT": st.column_config.DatetimeColumn("Bắt đầu", format="HH:mm"),
                "END_DT": st.column_config.DatetimeColumn("Kết thúc", format="HH:mm"),
            },
            disabled=[c for c in df.columns if c not in ["CRS_ASSIGN", "MECH_ASSIGN", "END_DT", "NOTES"]],
            hide_index=True, use_container_width=True
        )

        # --- PHẦN QUAN TRỌNG: TIMELINE & MANPOWER ---
        st.divider()
        now = datetime.now()
        
        # Thu thập dữ liệu cho Timeline
        c_data = []
        for role in ['CRS_ASSIGN', 'MECH_ASSIGN']:
            for _, r in df.iterrows():
                if pd.notnull(r['START_DT']) and r[role] and str(r[role]).lower() not in ['nan', 'none', '']:
                    c_data.append({
                        "Nhân viên": r[role], 
                        "Bắt đầu": r['START_DT'], 
                        "Kết thúc": r['END_DT'], 
                        "Loại": "CRS" if role == 'CRS_ASSIGN' else "MECH",
                        "Tàu": r.get('REG', 'AC')
                    })
        
        if c_data:
            st.subheader("👨‍🔧 Timeline Công Việc (Now-line màu đỏ)")
            df_g = pd.DataFrame(c_data)
            fig_g = px.timeline(df_g, x_start="Bắt đầu", x_end="Kết thúc", y="Nhân viên", color="Loại", hover_data=["Tàu"])
            fig_g.add_vline(x=now, line_width=4, line_color="red")
            fig_g.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_g, use_container_width=True)
            
            # Biểu đồ Manpower
            st.subheader("📋 Phân tích Manpower (Giải trình v3.12)")
            events = []
            for _, r in df.iterrows():
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
                fig_p.add_trace(go.Scatter(x=df_p['Time'], y=df_p['Count'], fill='tozeroy', fillcolor='rgba(165, 42, 42, 0.1)', line=dict(color='#A52A2A', shape='vh'), name='Nhu cầu'))
                fig_p.add_trace(go.Scatter(x=[df_p['Time'].min(), df_p['Time'].max()], y=[len(crs_opt)-1, len(crs_opt)-1], line=dict(color='green', dash='dash'), name='Hiện có'))
                fig_p.add_vline(x=now, line_width=2, line_color="red", line_dash="dot")
                st.plotly_chart(fig_p, use_container_width=True)
                st.info(f"Giải trình: Cao điểm lúc {peak_t.strftime('%H:%M') if peak_t else 'N/A'} cần {max_req} người.")
        else:
            st.warning("⚠️ CHƯA CÓ DỮ LIỆU NHÂN SỰ: Hãy nhấn 'Copy Data gốc' hoặc chọn tên trong bảng để hiện Timeline.")

        # Thống kê phút
        st.divider()
        st.subheader("📈 Thống kê phút làm việc")
        w1, w2 = st.columns(2)
        with w1:
            for n in process_names(raw_crs):
                m = df[df['CRS_ASSIGN']==n]['DURATION'].sum()
                st.write(f"- {n}: `{int(m)}` m")
        with w2:
            for n in process_names(raw_mech):
                m = df[df['MECH_ASSIGN']==n]['DURATION'].sum()
                st.write(f"- {n}: `{int(m)}` m")
