import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="ACD DAD v3.55", layout="wide")

now_vn = datetime.now()
now_ts = now_vn.timestamp() * 1000

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
            sep=r'\t|\s{2,}',
            engine='python'
        )
        df.columns = [str(col).strip().upper() for col in df.columns]
        return df.rename(columns={
            'A/C REGN': 'REG',
            'FLT-RADAR': 'ARR_ACT',
            'A/C TYPE': 'AC_TYPE'
        })
    except:
        return None


def calculate_work_window(row):
    try:
        date_val = str(row.get('DATE', '')).strip()
        arr_str  = str(row.get('ARR',  '')).strip()
        dep_str  = str(row.get('DEP',  '')).strip()
        curr_dt  = datetime.now()
        try:
            if '-' in date_val:
                base_date = datetime.strptime(f"{date_val}-{curr_dt.year}", "%d-%b-%Y").date()
            else:
                base_date = datetime.strptime(f"{date_val}/{curr_dt.year}", "%d/%m/%Y").date()
        except:
            base_date = curr_dt.date()

        def parse_time(t_str, b_date):
            if not t_str or t_str in ['____', 'nan', 'None', '', 'nan']:
                return None
            t_str = t_str.replace(':', '')
            return datetime.combine(b_date, datetime.strptime(t_str, '%H%M').time())

        t_arr = parse_time(arr_str, base_date)
        t_dep = parse_time(dep_str, base_date)

        if not t_arr and t_dep:
            return t_dep - timedelta(hours=1), t_dep
        if t_arr and not t_dep:
            return t_arr, t_arr + timedelta(hours=2)
        if t_arr and t_dep:
            if t_dep < t_arr:
                t_dep += timedelta(days=1)
            return t_arr, t_dep
        return t_arr, t_dep
    except:
        return None, None


def find_overlaps(df):
    """Trả về set index bị overlap CRS và MECH."""
    overlap_crs  = set()
    overlap_mech = set()
    for role, overlap_set in [('CRS_ASSIGN', overlap_crs), ('MECH_ASSIGN', overlap_mech)]:
        valid = df[
            df[role].notna() &
            (df[role] != '') &
            (~df[role].astype(str).str.lower().isin(['nan', 'none'])) &
            df['START_DT'].notna()
        ]
        indices = valid.index.tolist()
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                ri = valid.loc[indices[i]]
                rj = valid.loc[indices[j]]
                if ri[role] == rj[role]:
                    if ri['START_DT'] < rj['END_DT'] and rj['START_DT'] < ri['END_DT']:
                        overlap_set.add(indices[i])
                        overlap_set.add(indices[j])
    return overlap_crs, overlap_mech


def suggest_replacement(df, idx, role, options):
    """Tìm nhân viên thay thế không bị trùng ca."""
    row = df.loc[idx]
    if pd.isnull(row['START_DT']):
        return None
    for name in options:
        if not name:
            continue
        conflict = df[
            (df[role] == name) &
            (df.index != idx) &
            df['START_DT'].notna() &
            (df['START_DT'] < row['END_DT']) &
            (df['END_DT']   > row['START_DT'])
        ]
        if conflict.empty:
            return name
    return None


def is_future_flight(row, now):
    """Chuyến bay chưa đáp = START_DT >= now (chưa bắt đầu phục vụ)."""
    if pd.isnull(row['START_DT']):
        return False
    return row['START_DT'] >= now


# ═══════════════════════════════════════════════
# 2. SIDEBAR
# ═══════════════════════════════════════════════

with st.sidebar:
    st.header("⚙️ Cấu hình")

    def process_names(s):
        if not s:
            return []
        for char in ['\n', '\t']:
            s = s.replace(char, ',')
        return [x.strip() for x in s.split(',') if x.strip()]

    raw_crs  = st.text_area("CRS:",  value="Hưng, Hoàng Tr, Cường VII, Thắng VII, Trung")
    raw_mech = st.text_area("MECH:", value="Go, Tài, Phú, Trường, Huy VII")
    crs_opt  = [""] + process_names(raw_crs)
    mech_opt = [""] + process_names(raw_mech)
    num_crs  = len(crs_opt) - 1
    num_mech = len(mech_opt) - 1

    if st.button("🗑️ Reset Toàn Bộ"):
        st.session_state.clear()
        st.rerun()

# ═══════════════════════════════════════════════
# 3. MAIN
# ═══════════════════════════════════════════════

st.title("🚀 ACD DAD v3.55")
st.caption(f"Giờ hiện tại: {now_vn.strftime('%H:%M:%S')} (ICT) | Nhấn 'R' để cập nhật vạch đỏ")

raw_input = st.text_area("Dán lịch bay...", height=80)

if raw_input:
    df_raw = parse_raw_data(raw_input)
    if df_raw is not None:
        if 'df_final' not in st.session_state:
            res = df_raw.apply(
                lambda r: pd.Series(calculate_work_window(r)), axis=1
            )
            df_raw['START_DT'], df_raw['END_DT'] = res[0], res[1]
            df_raw['CRS_ASSIGN']  = ""
            df_raw['MECH_ASSIGN'] = ""
            df_raw['STATUS']      = "⚪"
            st.session_state.df_final = df_raw

        df = st.session_state.df_final
        df['DURATION'] = df.apply(
            lambda r: int((r['END_DT'] - r['START_DT']).total_seconds() / 60)
            if pd.notnull(r['START_DT']) and pd.notnull(r['END_DT']) else 0,
            axis=1
        )

        # ── TOOLBAR ──────────────────────────────────────────
        c1, c2, c3 = st.columns(3)

        with c1:
            if st.button("📋 1. Copy Data gốc", use_container_width=True):
                if 'CRS'  in df.columns:
                    df['CRS_ASSIGN']  = df['CRS'].astype(str).replace('nan', '')
                if 'MECH' in df.columns:
                    df['MECH_ASSIGN'] = df['MECH'].astype(str).replace('nan', '')
                st.rerun()

        with c2:
            if st.button("🪄 2. Tự chia lịch", use_container_width=True):
                c_l = {n: 0 for n in crs_opt  if n}
                m_l = {n: 0 for n in mech_opt if n}
                for idx, row in df.iterrows():
                    if pd.isnull(row['START_DT']):
                        continue
                    for n in sorted(c_l, key=c_l.get):
                        if df[
                            (df['CRS_ASSIGN'] == n) &
                            (df['START_DT'] < row['END_DT']) &
                            (df['END_DT']   > row['START_DT'])
                        ].empty:
                            df.at[idx, 'CRS_ASSIGN'] = n
                            c_l[n] += row['DURATION']
                            break
                    for n in sorted(m_l, key=m_l.get):
                        if df[
                            (df['MECH_ASSIGN'] == n) &
                            (df['START_DT'] < row['END_DT']) &
                            (df['END_DT']   > row['START_DT'])
                        ].empty:
                            df.at[idx, 'MECH_ASSIGN'] = n
                            m_l[n] += row['DURATION']
                            break
                st.rerun()

        with c3:
            if st.button("🔍 3. Fix Tương Lai & Gợi ý", use_container_width=True):
                for idx, row in df.iterrows():
                    # ★ CHỈ fix chuyến CHƯA ĐÁP (START_DT trong tương lai)
                    if not is_future_flight(row, now_vn):
                        continue
                    # Fix CRS
                    crs_overlap = df[
                        (df['CRS_ASSIGN'] == row['CRS_ASSIGN']) &
                        (df.index != idx) &
                        df['START_DT'].notna() &
                        (df['START_DT'] < row['END_DT']) &
                        (df['END_DT']   > row['START_DT'])
                    ]
                    if not crs_overlap.empty:
                        sug = suggest_replacement(df, idx, 'CRS_ASSIGN', crs_opt[1:])
                        if sug:
                            df.at[idx, 'CRS_ASSIGN'] = sug
                            df.at[idx, 'STATUS']     = "✨ Fix"
                    # Fix MECH
                    mech_overlap = df[
                        (df['MECH_ASSIGN'] == row['MECH_ASSIGN']) &
                        (df.index != idx) &
                        df['START_DT'].notna() &
                        (df['START_DT'] < row['END_DT']) &
                        (df['END_DT']   > row['START_DT'])
                    ]
                    if not mech_overlap.empty:
                        sug = suggest_replacement(df, idx, 'MECH_ASSIGN', mech_opt[1:])
                        if sug:
                            df.at[idx, 'MECH_ASSIGN'] = sug
                            df.at[idx, 'STATUS']      = "✨ Fix"
                st.rerun()

        # ── PHÁT HIỆN OVERLAP ─────────────────────────────────
        overlap_crs, overlap_mech = find_overlaps(df)
        all_overlap_idx = overlap_crs | overlap_mech

        # ★ Chỉ gợi ý thay thế cho chuyến TƯƠNG LAI
        future_overlap_crs  = {i for i in overlap_crs  if is_future_flight(df.loc[i], now_vn)}
        future_overlap_mech = {i for i in overlap_mech if is_future_flight(df.loc[i], now_vn)}
        future_overlap_all  = future_overlap_crs | future_overlap_mech

        # ── BẢNG PHÂN CÔNG ────────────────────────────────────
        st.subheader("📋 Bảng phân công")

        if all_overlap_idx:
            past_only = all_overlap_idx - future_overlap_all
            st.warning(
                f"⚠️ Phát hiện **{len(all_overlap_idx)}** chuyến bị trùng ca "
                f"(CRS: {len(overlap_crs)}, MECH: {len(overlap_mech)}) — "
                f"trong đó **{len(future_overlap_all)}** chuyến tương lai cần xử lý, "
                f"**{len(past_only)}** chuyến đã qua (chỉ ghi nhận)."
            )

        if future_overlap_all:
            suggestions = []
            for idx in sorted(future_overlap_all):
                row  = df.loc[idx]
                flt  = str(row.get('FLIGHT', idx))
                t_s  = row['START_DT'].strftime('%H:%M') if pd.notnull(row['START_DT']) else ''
                t_e  = row['END_DT'].strftime('%H:%M')   if pd.notnull(row['END_DT'])   else ''
                if idx in future_overlap_crs:
                    sug = suggest_replacement(df, idx, 'CRS_ASSIGN', crs_opt[1:])
                    suggestions.append({
                        'Chuyến': flt, 'Giờ': f"{t_s}→{t_e}", 'Role': 'CRS',
                        'Hiện tại': row['CRS_ASSIGN'],
                        'Gợi ý thay': sug if sug else '❌ Không có người rảnh',
                    })
                if idx in future_overlap_mech:
                    sug = suggest_replacement(df, idx, 'MECH_ASSIGN', mech_opt[1:])
                    suggestions.append({
                        'Chuyến': flt, 'Giờ': f"{t_s}→{t_e}", 'Role': 'MECH',
                        'Hiện tại': row['MECH_ASSIGN'],
                        'Gợi ý thay': sug if sug else '❌ Không có người rảnh',
                    })
            with st.expander("💡 Gợi ý nhân sự thay thế (chỉ chuyến tương lai)", expanded=True):
                st.dataframe(pd.DataFrame(suggestions), hide_index=True, use_container_width=True)

        # Styler tô vàng
        def highlight_overlap(row):
            styles    = [''] * len(row)
            col_names = list(row.index)
            idx       = row.name
            yellow    = 'background-color: #FFF176; color: #7A6000;'
            orange    = 'background-color: #FFB74D; color: #6D3200;'  # cam = overlap tương lai
            if idx in overlap_crs and 'CRS_ASSIGN' in col_names:
                styles[col_names.index('CRS_ASSIGN')] = orange if idx in future_overlap_crs else yellow
            if idx in overlap_mech and 'MECH_ASSIGN' in col_names:
                styles[col_names.index('MECH_ASSIGN')] = orange if idx in future_overlap_mech else yellow
            return styles

        readonly_cols = [c for c in ['FLIGHT', 'ROUTE', 'REG'] if c in df.columns]
        editor_cols   = readonly_cols + ['START_DT', 'END_DT', 'CRS_ASSIGN', 'MECH_ASSIGN', 'STATUS']
        editor_cols   = [c for c in editor_cols if c in df.columns]

        styled_view = (
            df[editor_cols].style
            .apply(highlight_overlap, axis=1)
            .format({
                'START_DT': lambda x: x.strftime('%H:%M') if pd.notnull(x) else '',
                'END_DT':   lambda x: x.strftime('%H:%M') if pd.notnull(x) else '',
            })
        )
        st.dataframe(styled_view, use_container_width=True, hide_index=True)

        # Data editor để chỉnh tay
        st.caption("✏️ Chỉnh phân công (CRS / MECH):")
        edit_source = df[readonly_cols + ['START_DT', 'END_DT', 'CRS_ASSIGN', 'MECH_ASSIGN', 'STATUS']].copy() \
            if readonly_cols else df[['START_DT', 'END_DT', 'CRS_ASSIGN', 'MECH_ASSIGN', 'STATUS']].copy()
        edit_source['START_DT'] = edit_source['START_DT'].apply(
            lambda x: x.strftime('%H:%M') if pd.notnull(x) else '')
        edit_source['END_DT']   = edit_source['END_DT'].apply(
            lambda x: x.strftime('%H:%M') if pd.notnull(x) else '')

        col_cfg = {
            "CRS_ASSIGN":  st.column_config.SelectboxColumn("CRS",     options=crs_opt),
            "MECH_ASSIGN": st.column_config.SelectboxColumn("MECH",    options=mech_opt),
            "STATUS":      st.column_config.TextColumn("Status"),
            "START_DT":    st.column_config.TextColumn("Bắt đầu",      disabled=True),
            "END_DT":      st.column_config.TextColumn("Kết thúc",     disabled=True),
        }
        for col in readonly_cols:
            col_cfg[col] = st.column_config.TextColumn(col, disabled=True)

        edited = st.data_editor(
            edit_source, column_config=col_cfg,
            hide_index=False, use_container_width=True, key="editor"
        )
        df['CRS_ASSIGN']  = edited['CRS_ASSIGN']
        df['MECH_ASSIGN'] = edited['MECH_ASSIGN']
        df['STATUS']      = edited['STATUS']

        st.divider()

        # ══════════════════════════════════════════════════════
        # MANPOWER REPORT — đầy đủ diễn giải
        # ══════════════════════════════════════════════════════
        st.subheader("📊 Manpower Report")

        # Build step-chart data
        events = []
        for _, r in df.iterrows():
            if pd.notnull(r['START_DT']) and pd.notnull(r['END_DT']):
                events.append((r['START_DT'].to_pydatetime(), 1))
                events.append((r['END_DT'].to_pydatetime(),  -1))
        events.sort()
        curr, points = 0, []
        for t, v in events:
            points.append({"Time": t, "Count": curr})
            curr += v
            points.append({"Time": t, "Count": curr})

        if points:
            df_p    = pd.DataFrame(points)
            peak    = int(df_p['Count'].max())
            t_peak  = df_p.loc[df_p['Count'].idxmax(), 'Time']
            deficit = max(0, peak - num_crs)

            # KPI metrics
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("👥 CRS hiện có",     f"{num_crs} người")
            k2.metric("📈 Đỉnh cần CRS",    f"{peak} người",
                      delta=f"Thiếu {deficit}" if deficit > 0 else "Đủ nhân lực",
                      delta_color="inverse" if deficit > 0 else "normal")
            k3.metric("⏰ Giờ đỉnh điểm",   t_peak.strftime('%H:%M'))
            k4.metric("✈️ Tổng chuyến",     f"{len(df)} chuyến")

            # Biểu đồ step-area
            fig_p = go.Figure()
            fig_p.add_trace(go.Scatter(
                x=df_p['Time'], y=df_p['Count'],
                fill='tozeroy',
                fillcolor='rgba(165,42,42,0.15)',
                line=dict(color='#A52A2A', width=2, shape='vh'),
                name='Nhu cầu CRS',
                hovertemplate='%{x|%H:%M} — Cần %{y} CRS<extra></extra>'
            ))
            fig_p.add_trace(go.Scatter(
                x=[df_p['Time'].min(), df_p['Time'].max()],
                y=[num_crs, num_crs],
                line=dict(color='#2E7D32', dash='dash', width=2),
                name=f'Lực lượng hiện có ({num_crs})',
                hovertemplate=f'Lực lượng: {num_crs} CRS<extra></extra>'
            ))
            # Vùng thiếu nhân lực (tô đỏ nhạt phía trên đường năng lực)
            if deficit > 0:
                fig_p.add_hrect(
                    y0=num_crs, y1=peak + 0.5,
                    fillcolor="rgba(255,0,0,0.07)",
                    line_width=0,
                    annotation_text=f"⚠ Thiếu {deficit} CRS",
                    annotation_position="top left",
                    annotation_font_color="red"
                )
            fig_p.add_vline(
                x=now_ts, line_width=2, line_dash="dot", line_color="red",
                annotation_text="Hiện tại", annotation_position="top right",
                annotation_font_color="red"
            )
            fig_p.update_layout(
                height=260,
                margin=dict(l=10, r=10, t=30, b=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                yaxis=dict(title="Số CRS cần", dtick=1, range=[0, peak + 1.5]),
                xaxis=dict(title=""),
                hovermode="x unified"
            )
            st.plotly_chart(fig_p, use_container_width=True)

            # ── Diễn giải / báo cáo xin thêm nhân lực ──────────
            with st.expander("📝 Diễn giải Manpower — Báo cáo xin thêm nhân lực", expanded=False):
                # Tìm các khoảng thời gian thiếu nhân lực
                shortage_periods = []
                in_shortage = False
                t_start_sh  = None
                max_sh      = 0
                for _, row_p in df_p.iterrows():
                    if row_p['Count'] > num_crs:
                        if not in_shortage:
                            in_shortage = True
                            t_start_sh  = row_p['Time']
                            max_sh      = row_p['Count']
                        else:
                            max_sh = max(max_sh, int(row_p['Count']))
                    else:
                        if in_shortage:
                            shortage_periods.append((t_start_sh, row_p['Time'], max_sh))
                            in_shortage = False
                            max_sh      = 0

                total_flights = len(df)
                total_dur_min = df['DURATION'].sum()
                avg_dur       = int(total_dur_min / total_flights) if total_flights else 0

                st.markdown(f"""
**Đơn vị:** Đội Kỹ thuật máy bay — Cảng hàng không Đà Nẵng (DAD)

**Ngày:** {now_vn.strftime('%d/%m/%Y')}

---

#### 1. Tổng quan lịch bay
- Tổng số chuyến bay cần phục vụ: **{total_flights} chuyến**
- Tổng thời gian phục vụ tích lũy: **{total_dur_min // 60}h{total_dur_min % 60:02d}p**
- Thời lượng phục vụ trung bình mỗi chuyến: **{avg_dur} phút**

#### 2. Lực lượng hiện có
- CRS hiện tại: **{num_crs} người**
- MECH hiện tại: **{num_mech} người**

#### 3. Phân tích nhu cầu
- Nhu cầu CRS cao nhất: **{peak} người** vào lúc **{t_peak.strftime('%H:%M')}**
- {"⚠️ **THIẾU NHÂN LỰC:** Cần bổ sung thêm **" + str(deficit) + " CRS** để đảm bảo công tác." if deficit > 0 else "✅ Lực lượng hiện tại đủ đáp ứng nhu cầu trong ngày."}
""")
                if shortage_periods:
                    st.markdown("#### 4. Các khung giờ thiếu nhân lực")
                    rows_sh = []
                    for (ts, te, mx) in shortage_periods:
                        dur_sh = int((te - ts).total_seconds() / 60)
                        rows_sh.append({
                            "Từ":         ts.strftime('%H:%M'),
                            "Đến":        te.strftime('%H:%M'),
                            "Thời lượng": f"{dur_sh} phút",
                            "Cần tối đa": f"{mx} CRS",
                            "Thiếu":      f"{mx - num_crs} người",
                        })
                    st.dataframe(pd.DataFrame(rows_sh), hide_index=True, use_container_width=True)
                    st.markdown(f"""
#### 5. Kiến nghị
Căn cứ phân tích trên, đề nghị cấp trên xem xét bố trí thêm **{deficit} CRS** \
trong khung giờ cao điểm ({shortage_periods[0][0].strftime('%H:%M')}–{shortage_periods[-1][1].strftime('%H:%M')}) \
nhằm đảm bảo công tác kiểm tra, giám định kỹ thuật tàu bay được thực hiện đúng quy trình và an toàn.
""")
                else:
                    st.success("Không có khung giờ nào vượt quá năng lực CRS hiện có.")

        # ══════════════════════════════════════════════════════
        # TIMELINE CHART
        # ══════════════════════════════════════════════════════
        c_data = []
        for role, role_label in [('CRS_ASSIGN', 'CRS'), ('MECH_ASSIGN', 'MECH')]:
            for idx, r in df.iterrows():
                if pd.notnull(r['START_DT']) and r[role] and str(r[role]).lower() not in ['nan', 'none', '']:
                    is_overlap = (
                        (idx in overlap_crs  and role == 'CRS_ASSIGN') or
                        (idx in overlap_mech and role == 'MECH_ASSIGN')
                    )
                    is_future = is_future_flight(r, now_vn)
                    start_str = r['START_DT'].strftime('%H:%M') if pd.notnull(r['START_DT']) else ''
                    end_str   = r['END_DT'].strftime('%H:%M')   if pd.notnull(r['END_DT'])   else ''
                    c_data.append({
                        "Nhân viên":   r[role],
                        "Bắt đầu":     r['START_DT'],
                        "Kết thúc":    r['END_DT'],
                        "Loại":        role_label,
                        "Chuyến":      str(r.get('FLIGHT', '')),
                        "Tuyến":       str(r.get('ROUTE',  '')),
                        "Reg":         str(r.get('REG',    '')),
                        "Giờ bắt đầu": start_str,
                        "Giờ kết thúc": end_str,
                        "Overlap":     "⚠️ TRÙNG CA" if is_overlap else "✅ OK",
                        "IsFuture":    is_future,
                    })

        if c_data:
            st.subheader("👨‍🔧 Timeline")
            df_chart = pd.DataFrame(c_data)

            fig_g = px.timeline(
                df_chart,
                x_start="Bắt đầu", x_end="Kết thúc",
                y="Nhân viên", color="Loại",
                color_discrete_map={"CRS": "#1f77b4", "MECH": "#ff7f0e"},
                custom_data=["Chuyến", "Tuyến", "Reg", "Nhân viên",
                             "Giờ bắt đầu", "Giờ kết thúc", "Overlap"],
            )
            fig_g.update_traces(
                hovertemplate=(
                    "<b>✈️ %{customdata[0]}</b><br>"
                    "🗺️ Tuyến:    %{customdata[1]}<br>"
                    "🔖 Reg:      %{customdata[2]}<br>"
                    "👤 NV:       %{customdata[3]}<br>"
                    "⏱ Bắt đầu:  %{customdata[4]}<br>"
                    "⏹ Kết thúc: %{customdata[5]}<br>"
                    "📌 %{customdata[6]}"
                    "<extra></extra>"
                )
            )
            # Tô màu bar bị overlap
            for i, trace in enumerate(fig_g.data):
                rl    = trace.name
                slice = df_chart[df_chart['Loại'] == rl]
                colors, lcolors, lwidths = [], [], []
                for _, rc in slice.iterrows():
                    if rc['Overlap'] == "⚠️ TRÙNG CA":
                        colors.append('rgba(255,180,0,0.88)')
                        lcolors.append('red')
                        lwidths.append(2)
                    else:
                        colors.append("#1f77b4" if rl == "CRS" else "#ff7f0e")
                        lcolors.append('rgba(0,0,0,0)')
                        lwidths.append(0)
                if colors:
                    fig_g.data[i].marker.color = colors
                    fig_g.data[i].marker.line  = dict(color=lcolors, width=lwidths)

            fig_g.add_vline(x=now_ts, line_width=4, line_color="red",
                            annotation_text="Hiện tại", annotation_position="top right")
            fig_g.update_layout(
                xaxis_type='date', height=420,
                hovermode='closest',
                hoverlabel=dict(bgcolor="white", font_size=13, font_family="monospace"),
            )
            fig_g.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_g, use_container_width=True)

        st.divider()

        # ══════════════════════════════════════════════════════
        # THỐNG KÊ THEO NHÂN VIÊN
        # ══════════════════════════════════════════════════════
        st.subheader("📈 Thống kê nhân viên")

        def build_stats(df, role_col, role_name, name_list):
            rows = []
            for name in name_list:
                if not name:
                    continue
                mask = (
                    (df[role_col].astype(str) == name) &
                    df['START_DT'].notna()
                )
                sub          = df[mask]
                total_flt    = len(sub)
                total_min    = int(sub['DURATION'].sum())
                done_min     = int(sub[sub['END_DT'] <= now_vn]['DURATION'].sum()) if total_min > 0 else 0
                future_flt   = int(sub[sub['START_DT'] >= now_vn].shape[0])
                past_flt     = total_flt - future_flt
                has_conflict = name_list.index(name) if role_col == 'CRS_ASSIGN' else 0
                # Kiểm tra overlap cho nhân viên này
                overlap_flag = any(
                    df.loc[i, role_col] == name
                    for i in (overlap_crs if role_col == 'CRS_ASSIGN' else overlap_mech)
                )
                rows.append({
                    "Nhân viên":      name,
                    "Role":           role_name,
                    "Tổng chuyến":    total_flt,
                    "Đã xong":        past_flt,
                    "Còn lại":        future_flt,
                    "Tổng giờ (h)":   round(total_min / 60, 1),
                    "Đã làm (h)":     round(done_min  / 60, 1),
                    "⚠️ Overlap":     "⚠️ Có" if overlap_flag else "✅ Không",
                })
            return rows

        stats_rows = (
            build_stats(df, 'CRS_ASSIGN',  'CRS',  crs_opt[1:]) +
            build_stats(df, 'MECH_ASSIGN', 'MECH', mech_opt[1:])
        )

        if stats_rows:
            df_stats = pd.DataFrame(stats_rows)

            # Highlight nhân viên có overlap
            def highlight_stats(row):
                if row['⚠️ Overlap'] == "⚠️ Có":
                    return ['background-color: #FFF3CD;'] * len(row)
                return [''] * len(row)

            st.dataframe(
                df_stats.style.apply(highlight_stats, axis=1),
                hide_index=True,
                use_container_width=True
            )

            # Biểu đồ bar tổng giờ từng người
            fig_bar = go.Figure()
            for role_name, color in [('CRS', '#1f77b4'), ('MECH', '#ff7f0e')]:
                sub = df_stats[df_stats['Role'] == role_name]
                if sub.empty:
                    continue
                fig_bar.add_trace(go.Bar(
                    name=f"{role_name} — đã làm",
                    x=sub['Nhân viên'],
                    y=sub['Đã làm (h)'],
                    marker_color=color,
                    opacity=0.9,
                    hovertemplate="%{x}: %{y}h đã làm<extra></extra>"
                ))
                fig_bar.add_trace(go.Bar(
                    name=f"{role_name} — còn lại",
                    x=sub['Nhân viên'],
                    y=sub['Tổng giờ (h)'] - sub['Đã làm (h)'],
                    marker_color=color,
                    opacity=0.35,
                    hovertemplate="%{x}: %{y}h còn lại<extra></extra>"
                ))

            fig_bar.update_layout(
                barmode='stack',
                height=300,
                margin=dict(l=10, r=10, t=30, b=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                yaxis_title="Giờ làm việc",
                xaxis_title="",
                title="Phân bổ giờ làm việc theo nhân viên (màu đậm = đã làm, nhạt = còn lại)"
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        # ── XUẤT TÊN ──────────────────────────────────────────
        st.divider()
        st.subheader("📋 Dòng tên dán Web")
        cp1, cp2 = st.columns(2)
        with cp1:
            st.code("\n".join(df['CRS_ASSIGN'].fillna('').tolist()),  language="text")
        with cp2:
            st.code("\n".join(df['MECH_ASSIGN'].fillna('').tolist()), language="text")
