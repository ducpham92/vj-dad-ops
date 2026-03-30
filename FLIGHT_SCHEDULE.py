import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="ACD DAD v3.54 - OVERLAP FIX", layout="wide")

now_vn = datetime.now()
now_ts = now_vn.timestamp() * 1000

# ─────────────────────────────────────────────
# 1. HÀM XỬ LÝ LOGIC
# ─────────────────────────────────────────────

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
        arr_str  = str(row.get('ARR', '')).strip()
        dep_str  = str(row.get('DEP', '')).strip()
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
    """
    Trả về set các index bị overlap cho từng role.
    overlap_crs : set of row indices có CRS_ASSIGN bị trùng ca
    overlap_mech: set of row indices có MECH_ASSIGN bị trùng ca
    """
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
                    # Kiểm tra chồng lấp thời gian
                    if ri['START_DT'] < rj['END_DT'] and rj['START_DT'] < ri['END_DT']:
                        overlap_set.add(indices[i])
                        overlap_set.add(indices[j])

    return overlap_crs, overlap_mech


def suggest_replacement(df, idx, role, options):
    """
    Với 1 chuyến bay bị conflict tại idx/role,
    trả về tên nhân viên thay thế phù hợp (không bị trùng ca),
    hoặc None nếu không ai rảnh.
    """
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


# ─────────────────────────────────────────────
# 2. SIDEBAR
# ─────────────────────────────────────────────

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

    if st.button("🗑️ Reset Toàn Bộ"):
        st.session_state.clear()
        st.rerun()

# ─────────────────────────────────────────────
# 3. MAIN
# ─────────────────────────────────────────────

st.title("🚀 ACD DAD v3.54")
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
            if pd.notnull(r['START_DT']) else 0,
            axis=1
        )

        # ── TOOLBAR ──────────────────────────────
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
                    if pd.notnull(row['START_DT']) and row['START_DT'] >= now_vn:
                        # Fix CRS
                        crs_conflict = df[
                            (df['CRS_ASSIGN'] == row['CRS_ASSIGN']) &
                            (df.index != idx) &
                            df['START_DT'].notna() &
                            (df['START_DT'] < row['END_DT']) &
                            (df['END_DT']   > row['START_DT'])
                        ]
                        if not crs_conflict.empty:
                            suggestion = suggest_replacement(df, idx, 'CRS_ASSIGN', crs_opt[1:])
                            if suggestion:
                                df.at[idx, 'CRS_ASSIGN'] = suggestion
                                df.at[idx, 'STATUS']     = "✨ Fix"

                        # Fix MECH
                        mech_conflict = df[
                            (df['MECH_ASSIGN'] == row['MECH_ASSIGN']) &
                            (df.index != idx) &
                            df['START_DT'].notna() &
                            (df['START_DT'] < row['END_DT']) &
                            (df['END_DT']   > row['START_DT'])
                        ]
                        if not mech_conflict.empty:
                            suggestion = suggest_replacement(df, idx, 'MECH_ASSIGN', mech_opt[1:])
                            if suggestion:
                                df.at[idx, 'MECH_ASSIGN'] = suggestion
                                df.at[idx, 'STATUS']      = "✨ Fix"
                st.rerun()

        # ── PHÁT HIỆN OVERLAP ────────────────────
        overlap_crs, overlap_mech = find_overlaps(df)
        all_overlap_idx = overlap_crs | overlap_mech

        # ── HIỂN THỊ BẢNG VỚI TÔ VÀNG ───────────
        st.subheader("📋 Bảng phân công")

        if all_overlap_idx:
            st.warning(
                f"⚠️ Phát hiện **{len(all_overlap_idx)}** chuyến bay bị trùng ca "
                f"(CRS: {len(overlap_crs)}, MECH: {len(overlap_mech)}). "
                "Các ô bị trùng được **tô vàng** bên dưới."
            )

            # Gợi ý thay thế
            suggestions = []
            for idx in sorted(all_overlap_idx):
                row = df.loc[idx]
                flight = row.get('FLIGHT', idx)
                if idx in overlap_crs:
                    sug = suggest_replacement(df, idx, 'CRS_ASSIGN', crs_opt[1:])
                    suggestions.append({
                        'Chuyến': flight,
                        'Role': 'CRS',
                        'Hiện tại': row['CRS_ASSIGN'],
                        'Gợi ý thay': sug if sug else '❌ Không có người rảnh',
                    })
                if idx in overlap_mech:
                    sug = suggest_replacement(df, idx, 'MECH_ASSIGN', mech_opt[1:])
                    suggestions.append({
                        'Chuyến': flight,
                        'Role': 'MECH',
                        'Hiện tại': row['MECH_ASSIGN'],
                        'Gợi ý thay': sug if sug else '❌ Không có người rảnh',
                    })

            with st.expander("💡 Xem gợi ý nhân sự thay thế", expanded=True):
                st.dataframe(pd.DataFrame(suggestions), hide_index=True, use_container_width=True)

        # Tô vàng bằng Styler
        def highlight_overlap(row):
            """Trả về list style cho từng ô trong row."""
            styles = [''] * len(row)
            col_names = list(row.index)
            idx = row.name

            yellow_bg = 'background-color: #FFF176; color: #7A6000;'

            if idx in overlap_crs:
                if 'CRS_ASSIGN' in col_names:
                    styles[col_names.index('CRS_ASSIGN')] = yellow_bg
            if idx in overlap_mech:
                if 'MECH_ASSIGN' in col_names:
                    styles[col_names.index('MECH_ASSIGN')] = yellow_bg

            return styles

        # Chọn cột hiển thị hợp lý
        display_cols = [c for c in df.columns if c not in ['START_DT', 'END_DT', 'DURATION']]
        display_cols = display_cols + ['START_DT', 'END_DT', 'DURATION']

        styled_df = (
            df[display_cols]
            .style
            .apply(highlight_overlap, axis=1)
            .format({
                'START_DT': lambda x: x.strftime('%H:%M') if pd.notnull(x) else '',
                'END_DT':   lambda x: x.strftime('%H:%M') if pd.notnull(x) else '',
            })
        )
        st.dataframe(styled_df, use_container_width=True, hide_index=True)

        # Data editor để chỉnh tay
        st.caption("✏️ Chỉnh phân công bên dưới:")
        edited = st.data_editor(
            df[['CRS_ASSIGN', 'MECH_ASSIGN', 'STATUS']],
            column_config={
                "CRS_ASSIGN":  st.column_config.SelectboxColumn("CRS",    options=crs_opt),
                "MECH_ASSIGN": st.column_config.SelectboxColumn("MECH",   options=mech_opt),
                "STATUS":      st.column_config.TextColumn("Status"),
            },
            hide_index=False,
            use_container_width=True,
            key="editor"
        )
        # Đồng bộ chỉnh sửa về df_final
        df['CRS_ASSIGN']  = edited['CRS_ASSIGN']
        df['MECH_ASSIGN'] = edited['MECH_ASSIGN']
        df['STATUS']      = edited['STATUS']

        # ── MANPOWER CHART ────────────────────────
        st.divider()
        events = []
        for _, r in df.iterrows():
            if pd.notnull(r['START_DT']):
                events.append((r['START_DT'].to_pydatetime(), 1))
                events.append((r['END_DT'].to_pydatetime(), -1))
        events.sort()
        curr, points = 0, []
        for t, v in events:
            points.append({"Time": t, "Count": curr})
            curr += v
            points.append({"Time": t, "Count": curr})

        if points:
            st.subheader("📊 Manpower Report")
            df_p = pd.DataFrame(points)
            fig_p = go.Figure()
            fig_p.add_trace(go.Scatter(
                x=df_p['Time'], y=df_p['Count'],
                fill='tozeroy',
                line=dict(color='#A52A2A', shape='vh'),
                name='Cần'
            ))
            fig_p.add_trace(go.Scatter(
                x=[df_p['Time'].min(), df_p['Time'].max()],
                y=[num_crs, num_crs],
                line=dict(color='green', dash='dash'),
                name='Có'
            ))
            fig_p.add_vline(x=now_ts, line_width=3, line_color="red")
            fig_p.update_layout(height=200, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_p, use_container_width=True)

        # ── TIMELINE CHART ────────────────────────
        c_data = []
        for role, role_label in [('CRS_ASSIGN', 'CRS'), ('MECH_ASSIGN', 'MECH')]:
            for idx, r in df.iterrows():
                if pd.notnull(r['START_DT']) and r[role] and str(r[role]).lower() not in ['nan', 'none', '']:
                    # Xác định có bị overlap không để đánh dấu
                    is_overlap = (
                        (idx in overlap_crs  and role == 'CRS_ASSIGN') or
                        (idx in overlap_mech and role == 'MECH_ASSIGN')
                    )
                    c_data.append({
                        "Nhân viên": r[role],
                        "Bắt đầu":   r['START_DT'],
                        "Kết thúc":  r['END_DT'],
                        "Loại":      role_label,
                        "Chuyến":    str(r.get('FLIGHT', '')),
                        "Tuyến":     str(r.get('ROUTE',  '')),
                        "Reg":       str(r.get('REG',    '')),
                        "Thời lượng": f"{int((r['END_DT'] - r['START_DT']).total_seconds() / 60)} phút",
                        "Overlap":   "⚠️ TRÙNG CA" if is_overlap else "✅ OK",
                    })

        if c_data:
            st.subheader("👨‍🔧 Timeline")
            df_chart = pd.DataFrame(c_data)

            fig_g = px.timeline(
                df_chart,
                x_start="Bắt đầu",
                x_end="Kết thúc",
                y="Nhân viên",
                color="Loại",
                color_discrete_map={"CRS": "#1f77b4", "MECH": "#ff7f0e"},
                # custom_data để tooltip tùy chỉnh
                custom_data=["Chuyến", "Tuyến", "Reg", "Nhân viên", "Bắt đầu", "Kết thúc", "Overlap"],
            )

            # Tooltip tùy chỉnh đầy đủ thông tin
            fig_g.update_traces(
                hovertemplate=(
                    "<b>✈️ Chuyến: %{customdata[0]}</b><br>"
                    "🗺️ Tuyến:   %{customdata[1]}<br>"
                    "🔖 Reg:     %{customdata[2]}<br>"
                    "👤 NV:      %{customdata[3]}<br>"
                    "⏱ Bắt đầu: %{customdata[4]|%H:%M}<br>"
                    "⏹ Kết thúc: %{customdata[5]|%H:%M}<br>"
                    "📌 Trạng thái: %{customdata[6]}"
                    "<extra></extra>"
                )
            )

            # Tô đỏ viền các bar bị overlap
            for i, trace in enumerate(fig_g.data):
                role_label = trace.name  # "CRS" hoặc "MECH"
                role_col   = 'CRS_ASSIGN' if role_label == 'CRS' else 'MECH_ASSIGN'
                overlap_set = overlap_crs if role_label == 'CRS' else overlap_mech

                marker_colors = []
                marker_lines  = []
                for _, row_c in df_chart[df_chart['Loại'] == role_label].iterrows():
                    if row_c['Overlap'] == "⚠️ TRÙNG CA":
                        marker_colors.append('rgba(255,200,0,0.85)')   # vàng đậm
                        marker_lines.append(dict(color='red', width=2))
                    else:
                        # giữ màu mặc định
                        marker_colors.append(
                            "#1f77b4" if role_label == "CRS" else "#ff7f0e"
                        )
                        marker_lines.append(dict(color='rgba(0,0,0,0)', width=0))

                if marker_colors:
                    fig_g.data[i].marker.color = marker_colors
                    fig_g.data[i].marker.line  = dict(
                        color=[ml['color'] for ml in marker_lines],
                        width=[ml['width'] for ml in marker_lines]
                    )

            fig_g.add_vline(x=now_ts, line_width=4, line_color="red")
            fig_g.update_layout(
                xaxis_type='date',
                height=420,
                hovermode='closest',
                hoverlabel=dict(
                    bgcolor="white",
                    font_size=13,
                    font_family="monospace"
                ),
            )
            fig_g.update_yaxes(autorange="reversed")
            st.plotly_chart(fig_g, use_container_width=True)

        # ── XUẤT TÊN ─────────────────────────────
        st.subheader("📋 Dòng tên dán Web")
        cp1, cp2 = st.columns(2)
        with cp1:
            st.code("\n".join(df['CRS_ASSIGN'].fillna('').tolist()),  language="text")
        with cp2:
            st.code("\n".join(df['MECH_ASSIGN'].fillna('').tolist()), language="text")
