import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="ACD DAD v3.56", layout="wide")

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
        if not t_arr and t_dep:  return t_dep - timedelta(hours=1), t_dep
        if t_arr and not t_dep:  return t_arr, t_arr + timedelta(hours=2)
        if t_arr and t_dep:
            if t_dep < t_arr: t_dep += timedelta(days=1)
            return t_arr, t_dep
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
        ]
        idxs = valid.index.tolist()
        for i in range(len(idxs)):
            for j in range(i+1, len(idxs)):
                ri, rj = valid.loc[idxs[i]], valid.loc[idxs[j]]
                if ri[role] == rj[role]:
                    if ri['START_DT'] < rj['END_DT'] and rj['START_DT'] < ri['END_DT']:
                        s.add(idxs[i]); s.add(idxs[j])
        result[role] = s
    return result['CRS_ASSIGN'], result['MECH_ASSIGN']


def suggest_replacement(df, idx, role, options):
    """Tìm người thay thế không bị trùng ca với chuyến idx."""
    row = df.loc[idx]
    if pd.isnull(row['START_DT']): return None
    for name in options:
        if not name: continue
        conflict = df[
            (df[role] == name) & (df.index != idx) &
            df['START_DT'].notna() &
            (df['START_DT'] < row['END_DT']) & (df['END_DT'] > row['START_DT'])
        ]
        if conflict.empty: return name
    return None


def is_future(row, now):
    """True nếu chuyến chưa bắt đầu (START_DT > now)."""
    if pd.isnull(row['START_DT']): return False
    return row['START_DT'] > now          # > now: hoàn toàn trong tương lai


def build_step_events(df_src, role):
    """Tạo danh sách (time, +1/-1) cho step-chart manpower của 1 role."""
    events = []
    for _, r in df_src.iterrows():
        if pd.notnull(r['START_DT']) and pd.notnull(r['END_DT']):
            if r[role] and str(r[role]).lower() not in ['nan','none','']:
                events.append((r['START_DT'].to_pydatetime(),  1))
                events.append((r['END_DT'].to_pydatetime(),   -1))
    events.sort()
    curr, points = 0, []
    for t, v in events:
        points.append({'Time': t, 'Count': curr})
        curr += v
        points.append({'Time': t, 'Count': curr})
    return pd.DataFrame(points) if points else pd.DataFrame(columns=['Time','Count'])


# ═══════════════════════════════════════════════
# 2. SIDEBAR
# ═══════════════════════════════════════════════

with st.sidebar:
    st.header("⚙️ Cấu hình")

    def process_names(s):
        if not s: return []
        for c in ['\n','\t']: s = s.replace(c, ',')
        return [x.strip() for x in s.split(',') if x.strip()]

    raw_crs  = st.text_area("CRS:",  value="Hưng, Hoàng Tr, Cường VII, Thắng VII, Trung")
    raw_mech = st.text_area("MECH:", value="Go, Tài, Phú, Trường, Huy VII")
    crs_opt  = [""] + process_names(raw_crs)
    mech_opt = [""] + process_names(raw_mech)
    num_crs  = len(crs_opt)  - 1
    num_mech = len(mech_opt) - 1

    if st.button("🗑️ Reset Toàn Bộ"):
        st.session_state.clear()
        st.rerun()

# ═══════════════════════════════════════════════
# 3. MAIN
# ═══════════════════════════════════════════════

st.title("🚀 ACD DAD v3.56")
st.caption(f"Giờ hiện tại: {now_vn.strftime('%H:%M:%S')} (ICT) | Nhấn R để cập nhật vạch đỏ")

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
                c_l = {n:0 for n in crs_opt  if n}
                m_l = {n:0 for n in mech_opt if n}
                for idx, row in df.iterrows():
                    if pd.isnull(row['START_DT']): continue
                    for n in sorted(c_l, key=c_l.get):
                        if df[(df['CRS_ASSIGN']==n)&(df['START_DT']<row['END_DT'])&(df['END_DT']>row['START_DT'])].empty:
                            df.at[idx,'CRS_ASSIGN']=n; c_l[n]+=row['DURATION']; break
                    for n in sorted(m_l, key=m_l.get):
                        if df[(df['MECH_ASSIGN']==n)&(df['START_DT']<row['END_DT'])&(df['END_DT']>row['START_DT'])].empty:
                            df.at[idx,'MECH_ASSIGN']=n; m_l[n]+=row['DURATION']; break
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

        # ─── BẢNG PHÂN CÔNG ───────────────────────────────────────
        st.subheader("📋 Bảng phân công")

        if all_overlap_idx:
            st.warning(
                f"⚠️ Trùng ca: **{len(all_overlap_idx)}** chuyến  "
                f"(CRS: {len(overlap_crs)}, MECH: {len(overlap_mech)})  |  "
                f"🟠 Tương lai cần xử lý: **{len(future_ov_all)}**  |  "
                f"🟡 Quá khứ ghi nhận: **{len(past_ov_all)}**"
            )

        # Gợi ý thay thế — CHỈ cho chuyến tương lai
        if future_ov_all:
            suggestions = []
            for idx in sorted(future_ov_all):
                row = df.loc[idx]
                flt = str(row.get('FLIGHT', idx))
                t_s = row['START_DT'].strftime('%H:%M') if pd.notnull(row['START_DT']) else ''
                t_e = row['END_DT'].strftime('%H:%M')   if pd.notnull(row['END_DT'])   else ''
                if idx in future_ov_crs:
                    sug = suggest_replacement(df, idx, 'CRS_ASSIGN', crs_opt[1:])
                    suggestions.append({'Chuyến': flt, 'Giờ': f"{t_s}→{t_e}", 'Role': 'CRS',
                                        'Hiện tại': row['CRS_ASSIGN'],
                                        'Gợi ý thay': sug or '❌ Không có người rảnh'})
                if idx in future_ov_mech:
                    sug = suggest_replacement(df, idx, 'MECH_ASSIGN', mech_opt[1:])
                    suggestions.append({'Chuyến': flt, 'Giờ': f"{t_s}→{t_e}", 'Role': 'MECH',
                                        'Hiện tại': row['MECH_ASSIGN'],
                                        'Gợi ý thay': sug or '❌ Không có người rảnh'})
            with st.expander("💡 Gợi ý nhân sự thay thế (chỉ chuyến tương lai)", expanded=True):
                st.dataframe(pd.DataFrame(suggestions), hide_index=True, use_container_width=True)

        # ── Styler tô màu ──────────────────────────────────────────
        # 🟠 Cam đậm  = overlap tương lai (cần fix ngay)
        # 🟡 Vàng nhạt = overlap quá khứ  (chỉ ghi nhận)
        def highlight_overlap(row):
            styles    = [''] * len(row)
            col_names = list(row.index)
            i         = row.name
            ORANGE = 'background-color: #FF8C00; color: #fff; font-weight:600;'   # cam đậm tương lai
            YELLOW = 'background-color: #FFF176; color: #7A6000;'                  # vàng nhạt quá khứ
            if 'CRS_ASSIGN' in col_names:
                c = col_names.index('CRS_ASSIGN')
                if   i in future_ov_crs: styles[c] = ORANGE
                elif i in past_ov_crs:   styles[c] = YELLOW
            if 'MECH_ASSIGN' in col_names:
                c = col_names.index('MECH_ASSIGN')
                if   i in future_ov_mech: styles[c] = ORANGE
                elif i in past_ov_mech:   styles[c] = YELLOW
            return styles

        readonly_cols = [c for c in ['FLIGHT','ROUTE','REG'] if c in df.columns]
        view_cols = readonly_cols + ['START_DT','END_DT','CRS_ASSIGN','MECH_ASSIGN','STATUS']
        view_cols = [c for c in view_cols if c in df.columns]

        styled_view = (
            df[view_cols].style
            .apply(highlight_overlap, axis=1)
            .format({
                'START_DT': lambda x: x.strftime('%H:%M') if pd.notnull(x) else '',
                'END_DT':   lambda x: x.strftime('%H:%M') if pd.notnull(x) else '',
            })
        )
        st.dataframe(styled_view, use_container_width=True, hide_index=True)

        # ── Data editor chỉnh tay ─────────────────────────────────
        st.caption("✏️ Chỉnh phân công (CRS / MECH)  —  ô 🟠 cam = tương lai cần fix  |  🟡 vàng = quá khứ")
        edit_src = df[readonly_cols + ['START_DT','END_DT','CRS_ASSIGN','MECH_ASSIGN','STATUS']].copy() \
            if readonly_cols else df[['START_DT','END_DT','CRS_ASSIGN','MECH_ASSIGN','STATUS']].copy()
        edit_src['START_DT'] = edit_src['START_DT'].apply(lambda x: x.strftime('%H:%M') if pd.notnull(x) else '')
        edit_src['END_DT']   = edit_src['END_DT'].apply(  lambda x: x.strftime('%H:%M') if pd.notnull(x) else '')

        col_cfg = {
            "CRS_ASSIGN":  st.column_config.SelectboxColumn("CRS",    options=crs_opt),
            "MECH_ASSIGN": st.column_config.SelectboxColumn("MECH",   options=mech_opt),
            "STATUS":      st.column_config.TextColumn("Status"),
            "START_DT":    st.column_config.TextColumn("Bắt đầu",     disabled=True),
            "END_DT":      st.column_config.TextColumn("Kết thúc",    disabled=True),
        }
        for col in readonly_cols:
            col_cfg[col] = st.column_config.TextColumn(col, disabled=True)

        edited = st.data_editor(edit_src, column_config=col_cfg,
                                hide_index=False, use_container_width=True, key="editor")

        # ★★★ Khi user chỉnh tay: chỉ cho phép thay đổi chuyến TƯƠNG LAI
        for idx in df.index:
            row_now = df.loc[idx]
            if is_future(row_now, now_vn):
                df.at[idx, 'CRS_ASSIGN']  = edited.at[idx, 'CRS_ASSIGN']
                df.at[idx, 'MECH_ASSIGN'] = edited.at[idx, 'MECH_ASSIGN']
                df.at[idx, 'STATUS']      = edited.at[idx, 'STATUS']
            # Quá khứ: KHÔNG ghi đè — giữ nguyên giá trị trong df

        st.divider()

        # ═══════════════════════════════════════════════════════════
        # MANPOWER REPORT — CRS & MECH riêng biệt
        # ═══════════════════════════════════════════════════════════
        st.subheader("📊 Manpower Report")

        df_crs_step  = build_step_events(df, 'CRS_ASSIGN')
        df_mech_step = build_step_events(df, 'MECH_ASSIGN')

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
        k1, k2, k3, k4, k5, k6 = st.columns(6)
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
        k6.metric("⌛ TB/chuyến",   f"{avg_dur} phút")

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
            fig.add_vline(x=now_ts, line_width=2, line_dash="dot", line_color="red",
                          annotation_text="Hiện tại", annotation_position="top right",
                          annotation_font_color="red")
            fig.update_layout(
                height=220, margin=dict(l=10,r=10,t=30,b=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                yaxis=dict(title=f"Số {label}", dtick=1, range=[0, pk+1.5]),
                xaxis=dict(title=""), hovermode="x unified"
            )
            return fig

        col_crs, col_mech = st.columns(2)
        with col_crs:
            st.markdown("**CRS — Giám định viên**")
            fig_crs = make_manpower_fig(df_crs_step, num_crs, "CRS",
                                        'rgba(165,42,42,0.15)', '#A52A2A', '#2E7D32')
            if fig_crs: st.plotly_chart(fig_crs, use_container_width=True)

        with col_mech:
            st.markdown("**MECH — Thợ máy**")
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

            st.markdown(f"""
**Đơn vị:** Đội Kỹ thuật máy bay — Cảng hàng không Đà Nẵng (DAD)
**Ngày:** {now_vn.strftime('%d/%m/%Y %H:%M')}

---
#### 1. Tổng quan lịch bay
| Chỉ tiêu | Giá trị |
|---|---|
| Tổng số chuyến | **{total_flights} chuyến** |
| Tổng giờ phục vụ tích lũy | **{total_dur_min//60}h{total_dur_min%60:02d}p** |
| Thời lượng TB/chuyến | **{avg_dur} phút** |

#### 2. Lực lượng hiện có
| Role | Số người | Đỉnh cần | Thiếu |
|---|---|---|---|
| CRS (Giám định viên) | **{num_crs}** | **{peak_crs}** | **{def_crs if def_crs>0 else "—"}** |
| MECH (Thợ máy) | **{num_mech}** | **{peak_mech}** | **{def_mech if def_mech>0 else "—"}** |
""")

            for label, sh_list, capacity, deficit in [
                ("CRS", sh_crs, num_crs, def_crs),
                ("MECH", sh_mech, num_mech, def_mech)
            ]:
                if sh_list:
                    st.markdown(f"#### 3. Khung giờ thiếu {label}")
                    rows_sh = [{'Từ': ts.strftime('%H:%M'), 'Đến': te.strftime('%H:%M'),
                                'Thời lượng': f"{int((te-ts).total_seconds()//60)} phút",
                                'Cần tối đa': f"{mx} {label}", 'Thiếu': f"{mx-capacity} người"}
                               for ts, te, mx in sh_list]
                    st.dataframe(pd.DataFrame(rows_sh), hide_index=True, use_container_width=True)
                    t0_str = sh_list[0][0].strftime('%H:%M')
                    t1_str = sh_list[-1][1].strftime('%H:%M')
                    st.info(
                        f"**Kiến nghị {label}:** Đề nghị bổ sung thêm **{deficit} {label}** "
                        f"trong khung giờ cao điểm **{t0_str}–{t1_str}** "
                        f"nhằm đảm bảo công tác kỹ thuật tàu bay đúng quy trình và an toàn."
                    )
                else:
                    st.success(f"✅ {label}: Lực lượng hiện tại đủ đáp ứng cả ngày.")

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

            fig_g.add_vline(x=now_ts, line_width=4, line_color="red",
                            annotation_text="Hiện tại", annotation_position="top right")
            fig_g.update_layout(
                xaxis_type='date', height=420, hovermode='closest',
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
                mask = (df[role_col].astype(str)==name) & df['START_DT'].notna()
                sub  = df[mask]
                total_flt  = len(sub)
                total_min  = int(sub['DURATION'].sum())
                done_min   = int(sub[sub['END_DT'] <= now_vn]['DURATION'].sum()) if total_min else 0
                future_flt = int(sub[sub['START_DT'] > now_vn].shape[0])
                past_flt   = total_flt - future_flt
                has_ov     = any(df.loc[i, role_col] == name for i in ov_set if i in df.index)
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
