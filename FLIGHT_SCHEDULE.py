import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta, timezone
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="ACD DAD v3.57 (Optimized)", layout="wide")

# 1. CỐ ĐỊNH MÚI GIỜ VIỆT NAM (UTC+7)
now_vn = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
# Plotly add_vline/add_shape cần timestamp chuẩn để không bị lỗi TypeError
now_line = now_vn

# ═══════════════════════════════════════════════
# 1. HÀM XỬ LÝ LOGIC
# ═══════════════════════════════════════════════

def parse_raw_data(data_string):
    if not data_string.strip():
        return None
    try:
        lines = data_string.strip().split('\n')
        header_line = lines[0]
        filtered_lines = [header_line]
        for line in lines[1:]:
            if line.strip() != header_line.strip():
                filtered_lines.append(line)
        df = pd.read_csv(
            io.StringIO("\n".join(filtered_lines)),
            sep=r'\t|\s{2,}', engine='python'
        )
        df.columns = [str(col).strip().upper() for col in df.columns]
        return df.rename(columns={
            'A/C REGN': 'REG', 'FLT-RADAR': 'ARR_ACT', 'A/C TYPE': 'AC_TYPE'
        })
    except:
        return None


def calculate_work_window(row):
    try:
        date_val = str(row.get('DATE', '')).strip()
        arr_str  = str(row.get('ARR',  '')).strip()
        dep_str  = str(row.get('DEP',  '')).strip()
        
        # Sử dụng now_vn để đồng bộ múi giờ
        try:
            if '-' in date_val:
                # Định dạng 30-Mar-2026 hoặc 30-Mar
                if len(date_val.split('-')) == 3:
                    base_date = datetime.strptime(date_val, "%d-%b-%Y").date()
                else:
                    base_date = datetime.strptime(f"{date_val}-{now_vn.year}", "%d-%b-%Y").date()
            else:
                # Định dạng 30/03/2026 hoặc 30/03
                if len(date_val.split('/')) == 3:
                    base_date = datetime.strptime(date_val, "%d/%m/%Y").date()
                else:
                    base_date = datetime.strptime(f"{date_val}/{now_vn.year}", "%d/%m/%Y").date()
        except:
            base_date = now_vn.date()

        def parse_time(t_str, b_date):
            if not t_str or t_str in ['____', 'nan', 'None', '', 'nan']:
                return None
            t_str = t_str.replace(':', '')
            try:
                # Xử lý trường hợp giờ là 2400 hoặc 0000
                if t_str == '2400':
                    return datetime.combine(b_date, datetime.min.time()) + timedelta(days=1)
                return datetime.combine(b_date, datetime.strptime(t_str, '%H%M').time())
            except:
                return None

        t_arr = parse_time(arr_str, base_date)
        t_dep = parse_time(dep_str, base_date)

        # Logic xử lý qua đêm: Nếu DEP < ARR thì DEP là ngày hôm sau
        if t_arr and t_dep:
            if t_dep < t_arr: 
                t_dep += timedelta(days=1)
            return t_arr, t_dep
        
        # Nếu chỉ có ARR hoặc chỉ có DEP
        if not t_arr and t_dep: return t_dep - timedelta(hours=1), t_dep
        if t_arr and not t_dep: return t_arr, t_arr + timedelta(hours=2)
        
        return None, None
    except:
        return None, None


def find_overlaps(df):
    """Trả về (overlap_crs, overlap_mech) — set index bị trùng ca."""
    result = {}
    for role in ['CRS_ASSIGN', 'MECH_ASSIGN']:
        s = set()
        valid = df[
            df[role].notna() & (df[role] != '') &
            (~df[role].astype(str).str.lower().isin(['nan','none'])) &
            df['START_DT'].notna()
        ].copy()
        
        idxs = valid.index.tolist()
        for i in range(len(idxs)):
            for j in range(i+1, len(idxs)):
                ri, rj = valid.loc[idxs[i]], valid.loc[idxs[j]]
                # Hỗ trợ kiểm tra nhiều nhân viên trong cùng 1 chuyến
                names_i = process_names(str(ri[role]))
                names_j = process_names(str(rj[role]))
                common = set(names_i) & set(names_j)
                if common:
                    if ri['START_DT'] < rj['END_DT'] and rj['START_DT'] < ri['END_DT']:
                        s.add(idxs[i]); s.add(idxs[j])
        result[role] = s
    return result['CRS_ASSIGN'], result['MECH_ASSIGN']


def suggest_replacement(df, idx, role, options):
    """Tìm người thay thế không bị trùng ca với chuyến idx."""
    row = df.loc[idx]
    if pd.isnull(row['START_DT']): return None
    
    # Tính tải trọng cho tất cả nhân sự rảnh
    candidates = []
    for name in options:
        if not name: continue
        conflict = df[
            (df[role] == name) & (df.index != idx) &
            df['START_DT'].notna() &
            (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])
        ]
        if conflict.empty:
            workload = int(df[df[role] == name]['DURATION'].sum())
            candidates.append((name, workload))
    
    # Ưu tiên người ít việc nhất
    if candidates:
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]
    return None


def get_available_ranked(df, idx, role, options):
    """Trả về danh sách tất cả người rảnh, kèm tải trọng, đã xếp hạng."""
    row = df.loc[idx]
    if pd.isnull(row['START_DT']): return []
    
    res = []
    for name in options:
        if not name: continue
        
        # Kiểm tra xung đột: name có nằm trong bất kỳ chuyến nào trùng giờ không
        conflict = df[
            df['START_DT'].notna() &
            (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT']) &
            (df[role].apply(lambda x: name in process_names(str(x))))
        ]
        
        if conflict.empty:
            # Tính tải trọng: sum duration của tất cả chuyến mà name tham gia
            workload = int(df[df[role].apply(lambda x: name in process_names(str(x)))]['DURATION'].sum())
            res.append({'Tên': name, 'Tải trọng (phút)': workload})
    return sorted(res, key=lambda x: x['Tải trọng (phút)'])


def is_future(row, now):
    """True nếu chuyến chưa bắt đầu (START_DT > now).
    START_DT đã mang đủ ngày từ calculate_work_window nên so sánh datetime là chính xác."""
    if pd.isnull(row['START_DT']): return False
    try:
        start = row['START_DT']
        if hasattr(start, 'to_pydatetime'): start = start.to_pydatetime()
        if hasattr(start, 'tzinfo') and start.tzinfo is not None:
            start = start.replace(tzinfo=None)
        return start > now
    except:
        return False


def build_step_events(df_src, role, buffer_per_maint=0):
    """
    Tạo danh sách (time, +1/-1) cho step-chart manpower.
    Tính toán nhu cầu dựa trên số lượng nhân sự được gán.
    Mỗi chuyến bay mặc định cần ít nhất 1 người.
    buffer_per_maint: Số lượng người cần thêm cho các chuyến được đánh dấu MAINT.
    """
    events = []
    for _, r in df_src.iterrows():
        if pd.notnull(r['START_DT']) and pd.notnull(r['END_DT']):
            # Đếm số lượng nhân sự đã gán
            assigned_names = process_names(str(r[role])) if pd.notnull(r[role]) else []
            # Nhu cầu = số người đã gán (hoặc 1 nếu trống) + số người dự phòng nếu là MAINT
            demand = max(len(assigned_names), 1)
            if r.get('MAINT', False):
                demand += buffer_per_maint
            
            events.append((r['START_DT'].to_pydatetime(),  demand))
            events.append((r['END_DT'].to_pydatetime(),   -demand))
    events.sort()
    curr, points = 0, []
    for t, v in events:
        points.append({'Time': t, 'Count': curr})
        curr += v
        points.append({'Time': t, 'Count': curr})
    return pd.DataFrame(points) if points else pd.DataFrame(columns=['Time','Count'])


def auto_assign_fairly(df, crs_names, mech_names):
    """
    Thuật toán phân công thông minh và công bằng hơn:
    1. Sắp xếp chuyến bay theo thời gian bắt đầu.
    2. Cân bằng tải dựa trên cả tổng thời gian (Duration) và số lượng chuyến bay (Count).
    3. Đảm bảo không trùng ca.
    """
    # Chỉ xét những dòng có giờ hợp lệ
    valid_df = df[df['START_DT'].notna()].sort_values('START_DT').copy()
    
    # Khởi tạo bảng theo dõi tải trọng
    crs_load = {n: {'duration': 0, 'count': 0} for n in crs_names if n}
    mech_load = {n: {'duration': 0, 'count': 0} for n in mech_names if n}

    def get_best_person(current_row, role_col, load_dict):
        start, end = current_row['START_DT'], current_row['END_DT']
        # Sắp xếp nhân viên theo tải trọng: duration trước, count sau
        sorted_names = sorted(load_dict.keys(), 
                             key=lambda x: (load_dict[x]['duration'], load_dict[x]['count']))
        
        for name in sorted_names:
            conflict = df[
                (df[role_col] == name) & 
                (df['START_DT'] < end) & 
                (df['END_DT'] > start)
            ]
            if conflict.empty:
                return name
        return ""

    for idx, row in valid_df.iterrows():
        # Phân công CRS
        best_crs = get_best_person(row, 'CRS_ASSIGN', crs_load)
        if best_crs:
            df.at[idx, 'CRS_ASSIGN'] = best_crs
            df.at[idx, 'STATUS'] = "🪄 Auto"
            crs_load[best_crs]['duration'] += row.get('DURATION', 0)
            crs_load[best_crs]['count'] += 1
            
        # Phân công MECH
        best_mech = get_best_person(row, 'MECH_ASSIGN', mech_load)
        if best_mech:
            df.at[idx, 'MECH_ASSIGN'] = best_mech
            df.at[idx, 'STATUS'] = "🪄 Auto"
            mech_load[best_mech]['duration'] += row.get('DURATION', 0)
            mech_load[best_mech]['count'] += 1
    
    return df


# ═══════════════════════════════════════════════
# 2. SIDEBAR
# ═══════════════════════════════════════════════

with st.sidebar:
    st.header("⚙️ Cấu hình")

    def process_names(s):
        if not s: return []
        for c in ['\n','\t']: s = s.replace(c, ',')
        return [x.strip() for x in s.split(',') if x.strip()]

    raw_crs  = st.text_area("CRS:",  value="A, B, C, D, E")
    raw_mech = st.text_area("MECH:", value="1, 2, 3, 4, 5")
    crs_opt  = [""] + process_names(raw_crs)
    mech_opt = [""] + process_names(raw_mech)
    num_crs  = len(crs_opt)  - 1
    num_mech = len(mech_opt) - 1

    st.divider()
    st.subheader("🔮 Dự toán nhân lực (Simulation)")
    st.caption("Dự phòng nhân lực cho các chuyến Bảo dưỡng (Maint)")
    buffer_crs = st.number_input("Thêm CRS/chuyến bảo dưỡng:", min_value=0, max_value=3, value=1)
    buffer_mech = st.number_input("Thêm MECH/chuyến bảo dưỡng:", min_value=0, max_value=5, value=2)

    if st.button("🗑️ Reset Toàn Bộ"):
        st.session_state.clear()
        st.rerun()

# ═══════════════════════════════════════════════
# 3. MAIN
# ═══════════════════════════════════════════════

st.title("🚀 ACD DAD v3.57 (Optimized)")
st.caption(f"Giờ hiện tại: {now_vn.strftime('%H:%M:%S')} (ICT) | Nhấn R để cập nhật vạch đỏ")

raw_input = st.text_area("Dán lịch bay...", height=80)

if raw_input:
    df_raw = parse_raw_data(raw_input)
    if df_raw is not None:

        if 'df_final' not in st.session_state:
            res = df_raw.apply(lambda r: pd.Series(calculate_work_window(r)), axis=1)
            df_raw['START_DT'], df_raw['END_DT'] = res[0], res[1]
            df_raw['CRS_ASSIGN'] = ""; df_raw['MECH_ASSIGN'] = ""; df_raw['STATUS'] = "⚪"
            df_raw['MAINT'] = False  # Cột đánh dấu bảo dưỡng
            st.session_state.df_final = df_raw

        df = st.session_state.df_final

        # ─── XỬ LÝ CẬP NHẬT TỪ EDITOR (Đưa lên đầu) ────────────────
        if 'editor' in st.session_state and st.session_state.editor.get('edited_rows'):
            edited_rows = st.session_state.editor['edited_rows']
            for idx_str, changes in edited_rows.items():
                idx = int(idx_str)
                row_now = df.loc[idx]
                
                # Cập nhật giờ nếu có thay đổi
                def parse_editor_time(time_str, original_dt):
                    if not time_str or not original_dt: return original_dt
                    try:
                        time_str = time_str.replace(':', '')
                        if len(time_str) != 4: return original_dt
                        new_time = datetime.strptime(time_str, '%H%M').time()
                        return datetime.combine(original_dt.date(), new_time)
                    except: return original_dt

                if 'START_DT' in changes:
                    df.at[idx, 'START_DT'] = parse_editor_time(changes['START_DT'], row_now['START_DT'])
                if 'END_DT' in changes:
                    df.at[idx, 'END_DT']   = parse_editor_time(changes['END_DT'],   row_now['END_DT'])
                
                # Xử lý qua đêm sau khi cập nhật giờ
                if df.at[idx, 'END_DT'] < df.at[idx, 'START_DT']:
                    df.at[idx, 'END_DT'] += timedelta(days=1)
                
                # Cập nhật các cột khác
                if 'MAINT' in changes:       df.at[idx, 'MAINT']       = bool(changes['MAINT'])
                if 'CRS_ASSIGN' in changes:  df.at[idx, 'CRS_ASSIGN']  = ", ".join(changes['CRS_ASSIGN'])
                if 'MECH_ASSIGN' in changes: df.at[idx, 'MECH_ASSIGN'] = ", ".join(changes['MECH_ASSIGN'])
                if 'STATUS' in changes:      df.at[idx, 'STATUS']      = changes['STATUS']
                
                # Tính lại duration
                df.at[idx, 'DURATION'] = int((df.at[idx, 'END_DT'] - df.at[idx, 'START_DT']).total_seconds() / 60)
            
            st.session_state.df_final = df

        # Thêm cột STT nếu chưa có
        if 'STT' not in df.columns:
            df.insert(0, 'STT', range(1, len(df) + 1))
        
        df['DURATION'] = df.apply(
            lambda r: int((r['END_DT']-r['START_DT']).total_seconds()/60)
            if pd.notnull(r['START_DT']) and pd.notnull(r['END_DT']) else 0, axis=1
        )

        # ─── TOOLBAR ──────────────────────────────────────────────
        c1, c2, c3 = st.columns(3)

        with c1:
            if st.button("📋 1. Copy Data gốc", use_container_width=True):
                if 'CRS'  in df.columns: df['CRS_ASSIGN']  = df['CRS'].astype(str).replace('nan','')
                if 'MECH' in df.columns: df['MECH_ASSIGN'] = df['MECH'].astype(str).replace('nan','')
                st.rerun()

        with c2:
            if st.button("🪄 2. Tự chia lịch", use_container_width=True):
                st.session_state.df_final = auto_assign_fairly(df, crs_opt, mech_opt)
                st.rerun()

        with c3:
            if st.button("🔍 3. Fix Tương Lai & Gợi ý", use_container_width=True):
                # ★★★ CHỈ xét & ghi đè chuyến TƯƠNG LAI (START_DT > now_vn)
                # Lấy snapshot giá trị hiện tại của quá khứ để bảo toàn
                past_crs  = {idx: row['CRS_ASSIGN']  for idx, row in df.iterrows() if not is_future(row, now_vn)}
                past_mech = {idx: row['MECH_ASSIGN'] for idx, row in df.iterrows() if not is_future(row, now_vn)}

                for idx, row in df.iterrows():
                    if not is_future(row, now_vn): continue   # bỏ qua quá khứ & đang phục vụ

                    # Fix CRS tương lai
                    if row['CRS_ASSIGN'] and str(row['CRS_ASSIGN']).lower() not in ['nan','none','']:
                        conflict = df[
                            (df['CRS_ASSIGN'] == row['CRS_ASSIGN']) & (df.index != idx) &
                            df['START_DT'].notna() &
                            (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])
                        ]
                        if not conflict.empty:
                            sug = suggest_replacement(df, idx, 'CRS_ASSIGN', crs_opt[1:])
                            if sug: df.at[idx,'CRS_ASSIGN']=sug; df.at[idx,'STATUS']="✨ Fix"

                    # Fix MECH tương lai
                    if row['MECH_ASSIGN'] and str(row['MECH_ASSIGN']).lower() not in ['nan','none','']:
                        conflict = df[
                            (df['MECH_ASSIGN'] == row['MECH_ASSIGN']) & (df.index != idx) &
                            df['START_DT'].notna() &
                            (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])
                        ]
                        if not conflict.empty:
                            sug = suggest_replacement(df, idx, 'MECH_ASSIGN', mech_opt[1:])
                            if sug: df.at[idx,'MECH_ASSIGN']=sug; df.at[idx,'STATUS']="✨ Fix"

                # ★★★ Khôi phục giá trị quá khứ (phòng khi bị ghi đè do side-effect)
                for idx, val in past_crs.items():  df.at[idx,'CRS_ASSIGN']  = val
                for idx, val in past_mech.items(): df.at[idx,'MECH_ASSIGN'] = val
                st.rerun()

        # ─── PHÁT HIỆN OVERLAP ────────────────────────────────────
        overlap_crs, overlap_mech = find_overlaps(df)
        all_overlap_idx = overlap_crs | overlap_mech

        # Phân loại: tương lai vs quá khứ
        future_ov_crs  = {i for i in overlap_crs  if is_future(df.loc[i], now_vn)}
        future_ov_mech = {i for i in overlap_mech if is_future(df.loc[i], now_vn)}
        past_ov_crs    = overlap_crs  - future_ov_crs
        past_ov_mech   = overlap_mech - future_ov_mech
        future_ov_all  = future_ov_crs | future_ov_mech
        past_ov_all    = all_overlap_idx - future_ov_all

        # ─── BẢNG PHÂN CÔNG (Hợp nhất) ──────────────────────────────
        readonly_cols = [c for c in ['DATE', 'FLIGHT','ROUTE','REG'] if c in df.columns]
        view_cols = ['STT'] + readonly_cols + ['START_DT','END_DT','DURATION','MAINT','CRS_ASSIGN','MECH_ASSIGN','STATUS']
        view_cols = [c for c in view_cols if c in df.columns]

        # ─── GIẢI QUYẾT XUNG ĐỘT & BẢO DƯỠNG ────────────────────────
        # Tìm các chuyến được đánh dấu bảo dưỡng (MAINT) hoặc có xung đột tương lai
        maint_flights = df[df.get('MAINT', False) == True].index.tolist()
        fix_needed_idx = sorted(list(future_ov_all | set(maint_flights)))

        if fix_needed_idx:
            st.markdown("### 💡 Gợi ý điều phối nhân sự")
            for idx in fix_needed_idx:
                row = df.loc[idx]
                flt = str(row.get('FLIGHT', idx))
                reg = str(row.get('REG', ''))
                dur = row['DURATION']
                t_s = row['START_DT'].strftime('%H:%M') if pd.notnull(row['START_DT']) else ''
                t_e = row['END_DT'].strftime('%H:%M')   if pd.notnull(row['END_DT'])   else ''
                
                is_overlap = idx in future_ov_all
                is_maint   = row.get('MAINT', False)
                
                label = "🛠️ BẢO DƯỠNG" if is_maint else "⚠️ TRÙNG LỊCH"
                if is_overlap and is_maint: label = "🛠️ BẢO DƯỠNG & ⚠️ TRÙNG"

                with st.container(border=True):
                    c_info, c_fix_crs, c_fix_mech = st.columns([1.2, 2, 2])
                    with c_info:
                        st.markdown(f"**{label}**")
                        st.markdown(f"**{flt}** ({reg})")
                        st.caption(f"🕒 {t_s} → {t_e} ({dur}p)")
                        if is_overlap: st.error("Xung đột!")

                    for role_label, role_col, opt, col_ui in [
                        ('CRS', 'CRS_ASSIGN', crs_opt, c_fix_crs),
                        ('MECH', 'MECH_ASSIGN', mech_opt, c_fix_mech)
                    ]:
                        with col_ui:
                            current_staff_list = process_names(str(row[role_col]))
                            candidates = get_available_ranked(df, idx, role_col, opt)
                            st.markdown(f"**{role_label}**: `{', '.join(current_staff_list) if current_staff_list else 'Trống'}`")
                            if candidates:
                                available_new = [c for c in candidates if c['Tên'] not in current_staff_list]
                                if available_new:
                                    st.caption("Gợi ý bổ sung (tải thấp):")
                                    for cand in available_new[:3]:
                                        name, load = cand['Tên'], cand['Tải trọng (phút)']
                                        if st.button(f"+ {name} ({load}p)", key=f"add_{idx}_{role_col}_{name}"):
                                            new_list = current_staff_list + [name]
                                            df.at[idx, role_col] = ", ".join(new_list)
                                            df.at[idx, 'STATUS'] = "✨ Support"
                                            st.rerun()
                                else: st.warning("Hết người rảnh")
                            else: st.warning("Không có người rảnh")
        st.divider()

        # Chuẩn bị dữ liệu cho editor
        edit_src = df[view_cols].copy()
        edit_src['START_DT'] = edit_src['START_DT'].apply(lambda x: x.strftime('%H:%M') if pd.notnull(x) else '')
        edit_src['END_DT']   = edit_src['END_DT'].apply(  lambda x: x.strftime('%H:%M') if pd.notnull(x) else '')
        edit_src['CRS_ASSIGN'] = edit_src['CRS_ASSIGN'].apply(lambda x: process_names(str(x)) if pd.notnull(x) else [])
        edit_src['MECH_ASSIGN'] = edit_src['MECH_ASSIGN'].apply(lambda x: process_names(str(x)) if pd.notnull(x) else [])

        col_cfg = {
            "STT":         st.column_config.NumberColumn("STT", disabled=True),
            "DATE":        st.column_config.TextColumn("Ngày", disabled=True),
            "DURATION":    st.column_config.NumberColumn("Dur", disabled=True, format="%d p"),
            "MAINT":       st.column_config.CheckboxColumn("Maint", help="Đánh dấu chuyến cần làm bảo dưỡng bổ sung"),
            "CRS_ASSIGN":  st.column_config.MultiselectColumn("CRS", options=crs_opt[1:]),
            "MECH_ASSIGN": st.column_config.MultiselectColumn("MECH", options=mech_opt[1:]),
            "STATUS":      st.column_config.TextColumn("Status"),
            "START_DT":    st.column_config.TextColumn("Bắt đầu"),
            "END_DT":      st.column_config.TextColumn("Kết thúc"),
        }
        for col in [c for c in readonly_cols if c != 'DATE']:
            col_cfg[col] = st.column_config.TextColumn(col, disabled=True)

        st.caption("✏️ **Bảng phân công trực tiếp**: Chỉnh giờ, chọn người rảnh, đánh dấu Maint ngay tại đây.")
        
        # Tăng chiều cao bảng phân công (ví dụ 600)
        edited = st.data_editor(edit_src, column_config=col_cfg,
                                hide_index=True, use_container_width=True, key="editor",
                                height=600)

        # Logic cập nhật cũ đã được đưa lên đầu, không cần lặp lại ở đây.
        st.divider()

        st.divider()

        # ═══════════════════════════════════════════════════════════
        # MANPOWER REPORT — CRS & MECH riêng biệt
        # ═══════════════════════════════════════════════════════════
        st.subheader("📊 Manpower Report & Simulation")

        df_crs_step  = build_step_events(df, 'CRS_ASSIGN', buffer_crs)
        df_mech_step = build_step_events(df, 'MECH_ASSIGN', buffer_mech)

        def get_peak(df_step):
            if df_step.empty: return 0, None
            pk = int(df_step['Count'].max())
            tp = df_step.loc[df_step['Count'].idxmax(), 'Time']
            return pk, tp

        peak_crs,  t_peak_crs  = get_peak(df_crs_step)
        peak_mech, t_peak_mech = get_peak(df_mech_step)
        def_crs  = max(0, peak_crs  - num_crs)
        def_mech = max(0, peak_mech - num_mech)

        total_flights = len(df)
        total_dur_min = int(df['DURATION'].sum())
        avg_dur       = int(total_dur_min / total_flights) if total_flights else 0

        # KPI row
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("👷 CRS có",    f"{num_crs}",  delta=f"Đỉnh cần {peak_crs}",
                  delta_color="inverse" if def_crs > 0 else "off")
        k2.metric("⏰ Đỉnh CRS",  t_peak_crs.strftime('%H:%M')  if t_peak_crs  else "—",
                  delta=f"Thiếu {def_crs}" if def_crs > 0 else "✅ Đủ",
                  delta_color="inverse" if def_crs > 0 else "normal")
        k3.metric("🔧 MECH có",   f"{num_mech}", delta=f"Đỉnh cần {peak_mech}",
                  delta_color="inverse" if def_mech > 0 else "off")
        k4.metric("⏰ Đỉnh MECH", t_peak_mech.strftime('%H:%M') if t_peak_mech else "—",
                  delta=f"Thiếu {def_mech}" if def_mech > 0 else "✅ Đủ",
                  delta_color="inverse" if def_mech > 0 else "normal")
        k5.metric("✈️ Tổng chuyến", f"{total_flights}")

        # ── Biểu đồ CRS ──────────────────────────────────────────
        def make_manpower_fig(df_step, capacity, label, color_fill, color_line, color_cap):
            if df_step.empty: return None
            pk = int(df_step['Count'].max())
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_step['Time'], y=df_step['Count'],
                fill='tozeroy', fillcolor=color_fill,
                line=dict(color=color_line, width=2, shape='vh'),
                name=f'Nhu cầu {label}',
                hovertemplate=f'%{{x|%H:%M}} — Cần %{{y}} {label}<extra></extra>'
            ))
            fig.add_trace(go.Scatter(
                x=[df_step['Time'].min(), df_step['Time'].max()],
                y=[capacity, capacity],
                line=dict(color=color_cap, dash='dash', width=2),
                name=f'{label} hiện có ({capacity})',
                hovertemplate=f'{label} hiện có: {capacity}<extra></extra>'
            ))
            deficit = max(0, pk - capacity)
            if deficit > 0:
                fig.add_hrect(
                    y0=capacity, y1=pk + 0.5,
                    fillcolor="rgba(255,0,0,0.07)", line_width=0,
                    annotation_text=f"⚠ Thiếu {deficit} {label}",
                    annotation_position="top left", annotation_font_color="red"
                )
            
            # Sử dụng add_vline không có annotation_text để tránh lỗi sum(x) trên một số môi trường (Streamlit Cloud)
            fig.add_vline(x=now_line, line_width=2, line_dash="dot", line_color="red")
            
            # Thêm nhãn thời gian riêng biệt bằng add_annotation
            fig.add_annotation(
                x=now_line, y=pk + 1,
                text=f"◀ {now_vn.strftime('%H:%M')}",
                showarrow=False,
                xanchor="right",
                font=dict(color="red", size=12),
                bgcolor="rgba(255,255,255,0.8)"
            )
            fig.update_layout(
                height=220, margin=dict(l=10,r=10,t=30,b=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                yaxis=dict(title=f"Số {label}", dtick=1, range=[0, pk+1.5]),
                xaxis=dict(title="", type='date'), hovermode="x unified"
            )
            return fig

        col_crs, col_mech = st.columns(2)
        with col_crs:
            st.markdown("**CRS**")
            fig_crs = make_manpower_fig(df_crs_step, num_crs, "CRS",
                                        'rgba(165,42,42,0.15)', '#A52A2A', '#2E7D32')
            if fig_crs: st.plotly_chart(fig_crs, use_container_width=True)

        with col_mech:
            st.markdown("**MECH**")
            fig_mech = make_manpower_fig(df_mech_step, num_mech, "MECH",
                                         'rgba(25,100,180,0.15)', '#1964B4', '#B45309')
            if fig_mech: st.plotly_chart(fig_mech, use_container_width=True)

        # ── Báo cáo diễn giải ─────────────────────────────────────
            with st.expander("📝 Báo cáo Manpower — Diễn giải & Xin thêm nhân lực", expanded=False):

                def find_shortage_periods(df_step, capacity):
                    periods, in_sh, t0, mx = [], False, None, 0
                    for _, rp in df_step.iterrows():
                        if rp['Count'] > capacity:
                            if not in_sh: in_sh=True; t0=rp['Time']; mx=rp['Count']
                            else: mx = max(mx, int(rp['Count']))
                        else:
                            if in_sh: periods.append((t0, rp['Time'], int(mx))); in_sh=False; mx=0
                    return periods

                sh_crs  = find_shortage_periods(df_crs_step,  num_crs)  if not df_crs_step.empty  else []
                sh_mech = find_shortage_periods(df_mech_step, num_mech) if not df_mech_step.empty else []

                report_text = f"Đơn vị: VJ DAD-LINE MAINTENANCE\n"
                report_text += f"BÁO CÁO NHU CẦU NHÂN LỰC CA LÀM {now_vn.strftime('%d/%m/%Y')}\n"
                report_text += f"{'='*40}\n\n"
                report_text += f"1. TỔNG QUAN LỊCH BAY:\n"
                report_text += f"   - Tổng số chuyến: {total_flights} chuyến\n"
                report_text += f"   - CRS hiện có: {num_crs} | MECH hiện có: {num_mech}\n\n"

                st.markdown(f"""
**Đơn vị:** VJ DAD-LINE MAINTENANCE, CA LÀM {now_vn.strftime('%d/%m/%Y')}

---
#### 1. Tổng quan lịch bay
| Chỉ tiêu | Giá trị |
|---|---|
| Tổng số chuyến | **{total_flights} chuyến** |

#### 2. Lực lượng hiện có
| Role | Số người | Đỉnh cần | Thiếu |
|---|---|---|---|
| CRS | **{num_crs}** | **{peak_crs}** | **{def_crs if def_crs>0 else "—"}** |
| MECH | **{num_mech}** | **{peak_mech}** | **{def_mech if def_mech>0 else "—"}** |
""")

                for label, sh_list, capacity, deficit, buf_val in [
                    ("CRS", sh_crs, num_crs, def_crs, buffer_crs),
                    ("MECH", sh_mech, num_mech, def_mech, buffer_mech)
                ]:
                    report_text += f"2. NHU CẦU {label}:\n"
                    if sh_list:
                        st.markdown(f"#### 3. Khung giờ thiếu {label}")
                        rows_sh = [{'Từ': ts.strftime('%H:%M'), 'Đến': te.strftime('%H:%M'),
                                    'Thời lượng': f"{int((te-ts).total_seconds()//60)} phút",
                                    'Cần tối đa': f"{mx} {label}", 'Thiếu': f"{mx-capacity} người"}
                                   for ts, te, mx in sh_list]
                        st.dataframe(pd.DataFrame(rows_sh), hide_index=True, use_container_width=True)
                        
                        # Tìm các tàu MAINT trong khung giờ thiếu
                        t0_str = sh_list[0][0].strftime('%H:%M')
                        t1_str = sh_list[-1][1].strftime('%H:%M')
                        
                        maint_details = []
                        for ts, te, mx in sh_list:
                            m_ships = df[
                                (df['MAINT'] == True) & 
                                (df['START_DT'] < te) & (df['END_DT'] > ts)
                            ]
                            for _, ms in m_ships.iterrows():
                                detail = f"Tàu {ms['REG']} ({ms['FLIGHT']}) bảo dưỡng {ms['START_DT'].strftime('%H:%M')}–{ms['END_DT'].strftime('%H:%M')}"
                                if detail not in maint_details:
                                    maint_details.append(detail)
                        
                        reason_str = ""
                        if maint_details:
                            reason_str = "\n   * Lý do: Có gói bảo dưỡng phát sinh:\n     - " + "\n     - ".join(maint_details)
                        
                        rec_msg = (
                            f"Đề nghị bổ sung thêm {deficit} {label} trong khung giờ cao điểm {t0_str}–{t1_str}."
                            f"{reason_str}\n"
                            f"   * Ghi chú dự toán: Đã bao gồm định mức dự phòng +{buf_val} {label}/chuyến bảo dưỡng."
                        )
                        
                        st.info(f"**Kiến nghị {label}:** {rec_msg}")
                        report_text += f"   - Tình trạng: THIẾU {deficit} người\n"
                        report_text += f"   - Kiến nghị: {rec_msg}\n\n"
                    else:
                        st.success(f"✅ {label}: Lực lượng hiện tại đủ đáp ứng cả ngày.")
                        report_text += f"   - Tình trạng: Đủ đáp ứng.\n\n"

                report_text += f"{'='*40}\n"
                report_text += f"Báo cáo được trích xuất từ ACD DAD v3.57 (Optimized)"

                st.divider()
                st.subheader("📋 Copy Báo cáo gửi sếp")
                st.caption("Nhấn nút Copy ở góc phải khối code dưới đây và dán vào Zalo/Email")
                st.code(report_text, language="text")

        # ═══════════════════════════════════════════════════════════
        # TIMELINE CHART
        # ═══════════════════════════════════════════════════════════
        c_data = []
        for role, role_label in [('CRS_ASSIGN','CRS'), ('MECH_ASSIGN','MECH')]:
            ov_set = overlap_crs if role == 'CRS_ASSIGN' else overlap_mech
            for idx, r in df.iterrows():
                if pd.notnull(r['START_DT']) and r[role] and str(r[role]).lower() not in ['nan','none','']:
                    is_ov  = idx in ov_set
                    is_fut = is_future(r, now_vn)
                    s_str  = r['START_DT'].strftime('%H:%M') if pd.notnull(r['START_DT']) else ''
                    e_str  = r['END_DT'].strftime('%H:%M')   if pd.notnull(r['END_DT'])   else ''
                    c_data.append({
                        "Nhân viên": r[role], "Bắt đầu": r['START_DT'], "Kết thúc": r['END_DT'],
                        "Loại": role_label,
                        "Chuyến": str(r.get('FLIGHT','')), "Tuyến": str(r.get('ROUTE','')),
                        "Reg": str(r.get('REG','')),
                        "Giờ bắt đầu": s_str, "Giờ kết thúc": e_str,
                        "Overlap": ("🟠 TRÙNG-TƯƠNG LAI" if (is_ov and is_fut)
                                    else "🟡 TRÙNG-QUÁ KHỨ" if (is_ov and not is_fut)
                                    else "✅ OK"),
                    })

        if c_data:
            st.subheader("👨‍🔧 Timeline")
            df_chart = pd.DataFrame(c_data)
            fig_g = px.timeline(
                df_chart, x_start="Bắt đầu", x_end="Kết thúc",
                y="Nhân viên", color="Loại",
                color_discrete_map={"CRS":"#1f77b4","MECH":"#ff7f0e"},
                custom_data=["Chuyến","Tuyến","Reg","Nhân viên","Giờ bắt đầu","Giờ kết thúc","Overlap"],
            )
            fig_g.update_traces(hovertemplate=(
                "<b>✈️ %{customdata[0]}</b><br>"
                "🗺️ Tuyến:    %{customdata[1]}<br>"
                "🔖 Reg:      %{customdata[2]}<br>"
                "👤 NV:       %{customdata[3]}<br>"
                "⏱ Bắt đầu:  %{customdata[4]}<br>"
                "⏹ Kết thúc: %{customdata[5]}<br>"
                "📌 %{customdata[6]}<extra></extra>"
            ))
            # Tô màu bar theo trạng thái overlap
            for i, trace in enumerate(fig_g.data):
                rl    = trace.name
                slice_df = df_chart[df_chart['Loại'] == rl]
                colors, lc, lw = [], [], []
                default_color = "#1f77b4" if rl == "CRS" else "#ff7f0e"
                for _, rc in slice_df.iterrows():
                    if rc['Overlap'].startswith("🟠"):       # tương lai
                        colors.append('rgba(255,130,0,0.90)'); lc.append('red');  lw.append(2)
                    elif rc['Overlap'].startswith("🟡"):     # quá khứ
                        colors.append('rgba(255,230,50,0.80)'); lc.append('#B8860B'); lw.append(1)
                    else:
                        colors.append(default_color); lc.append('rgba(0,0,0,0)'); lw.append(0)
                if colors:
                    fig_g.data[i].marker.color = colors
                    fig_g.data[i].marker.line  = dict(color=lc, width=lw)

            # Vẽ vạch hiện tại (đỏ) - Không dùng annotation trong add_vline để tránh lỗi TypeError
            fig_g.add_vline(x=now_line, line_width=4, line_color="red")
            
            # Thêm nhãn riêng biệt
            fig_g.add_annotation(
                x=now_line, y=0,
                text=f"◀ {now_vn.strftime('%H:%M')}",
                showarrow=False,
                xanchor="right",
                yref="paper", yanchor="top",
                font=dict(color="red", size=13),
                bgcolor="rgba(255,255,255,0.85)"
            )
            fig_g.update_layout(
                xaxis_type='date', height=600, hovermode='closest',
                hoverlabel=dict(bgcolor="white", font_size=13, font_family="monospace"),
            )
            fig_g.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_g, use_container_width=True)

        st.divider()

        # ═══════════════════════════════════════════════════════════
        # THỐNG KÊ NHÂN VIÊN
        # ═══════════════════════════════════════════════════════════
        st.subheader("📈 Thống kê nhân viên")

        def build_stats(df, role_col, role_name, name_list, ov_set):
            rows = []
            for name in name_list:
                if not name: continue
                # Sử dụng apply để kiểm tra name trong danh sách phân công đa nhiệm
                mask = df[role_col].apply(lambda x: name in process_names(str(x))) & df['START_DT'].notna()
                sub  = df[mask]
                total_flt  = len(sub)
                total_min  = int(sub['DURATION'].sum())
                done_min   = int(sub[sub['END_DT'] <= now_vn]['DURATION'].sum()) if total_min else 0
                future_flt = int(sub[sub['START_DT'] > now_vn].shape[0])
                past_flt   = total_flt - future_flt
                # Kiểm tra overlap: nếu bất kỳ chuyến nào name tham gia nằm trong ov_set
                has_ov     = any(idx in ov_set for idx in sub.index)
                rows.append({
                    "Nhân viên":   name,
                    "Role":        role_name,
                    "Tổng chuyến": total_flt,
                    "Đã xong":     past_flt,
                    "Còn lại":     future_flt,
                    "Tổng giờ":    round(total_min/60, 1),
                    "Đã làm (h)":  round(done_min/60,  1),
                    "Còn lại (h)": round((total_min-done_min)/60, 1),
                    "⚠️ Overlap":  "⚠️ Có" if has_ov else "—",
                })
            return rows

        stats_rows = (
            build_stats(df,'CRS_ASSIGN','CRS',  crs_opt[1:],  overlap_crs) +
            build_stats(df,'MECH_ASSIGN','MECH', mech_opt[1:], overlap_mech)
        )

        if stats_rows:
            df_stats = pd.DataFrame(stats_rows)

            def hi_stats(row):
                if row['⚠️ Overlap'] == "⚠️ Có":
                    return ['background-color:#FFF3CD;']*len(row)
                return ['']*len(row)

            st.dataframe(
                df_stats.style.apply(hi_stats, axis=1),
                hide_index=True, use_container_width=True
            )

            # Biểu đồ bar stack giờ làm việc
            fig_bar = go.Figure()
            for role_name, color in [('CRS','#1f77b4'),('MECH','#ff7f0e')]:
                sub = df_stats[df_stats['Role']==role_name]
                if sub.empty: continue
                fig_bar.add_trace(go.Bar(
                    name=f"{role_name} — đã làm", x=sub['Nhân viên'], y=sub['Đã làm (h)'],
                    marker_color=color, opacity=0.9,
                    hovertemplate="%{x}: %{y}h đã làm<extra></extra>"
                ))
                fig_bar.add_trace(go.Bar(
                    name=f"{role_name} — còn lại", x=sub['Nhân viên'], y=sub['Còn lại (h)'],
                    marker_color=color, opacity=0.35,
                    hovertemplate="%{x}: %{y}h còn lại<extra></extra>"
                ))
            fig_bar.update_layout(
                barmode='stack', height=300,
                margin=dict(l=10,r=10,t=40,b=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                yaxis_title="Giờ làm việc", xaxis_title="",
                title="Phân bổ giờ làm việc (màu đậm = đã làm · màu nhạt = còn lại)"
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        # ─── XUẤT TÊN ─────────────────────────────────────────────
        st.divider()
        st.subheader("📋 Dòng tên dán Web")
        cp1, cp2 = st.columns(2)
        with cp1: st.code("\n".join(df['CRS_ASSIGN'].fillna('').tolist()),  language="text")
        with cp2: st.code("\n".join(df['MECH_ASSIGN'].fillna('').tolist()), language="text")
