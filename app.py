import io
import re
from typing import Optional

import pandas as pd
import streamlit as st
from rapidfuzz import fuzz, process

st.set_page_config(page_title="SOM Master Data Automation", page_icon="🧩", layout="wide")

st.title("SOM Master Data Automation")
st.caption("Reconcile Business Master Data, CC Rate Cards and SAP VBRP extracts.")
st.info("Demo version: files are processed in this app session only. There is no SAP connection. Use dummy or company-approved data only.")

def read_workbook(uploaded_file):
    if uploaded_file is None:
        return None
    try:
        return pd.read_excel(uploaded_file, sheet_name=None, dtype=str).get(
            st.session_state.get(uploaded_file.name + "_sheet", "")
        )
    except Exception:
        try:
            return pd.read_excel(uploaded_file, dtype=str)
        except Exception as exc:
            st.error(f"Could not read {uploaded_file.name}: {exc}")
            return None

def clean(value):
    if pd.isna(value):
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()

def choose_column(label, df, preferred=None, key=None):
    cols = list(df.columns)
    if not cols:
        return None
    default = 0
    if preferred:
        for i, col in enumerate(cols):
            if preferred.lower() in str(col).lower():
                default = i
                break
    return st.selectbox(label, cols, index=default, key=key)

def best_match(value, candidates):
    q = clean(value)
    if not q or not candidates:
        return "", 0
    valid = [(str(x), clean(x)) for x in candidates if clean(x)]
    if not valid:
        return "", 0
    result = process.extractOne(q, [x[1] for x in valid], scorer=fuzz.token_set_ratio)
    if not result:
        return "", 0
    matched_clean, score, idx = result
    return valid[idx][0], int(score)

with st.sidebar:
    st.header("1. Upload source files")
    master_file = st.file_uploader("Business Master Data (.xlsx)", type=["xlsx"], key="master")
    rate_file = st.file_uploader("CC Team Rate Card (.xlsx)", type=["xlsx"], key="rate")
    vbrp_file = st.file_uploader("SAP VBRP dump (.xlsx)", type=["xlsx"], key="vbrp")
    threshold = st.slider("Minimum match confidence", 50, 100, 85, 1)

if not all([master_file, rate_file, vbrp_file]):
    st.subheader("Getting started")
    st.write("Upload all three Excel workbooks in the sidebar. The app will let you select the relevant description columns, compare records, review confidence scores, and export the results.")
    st.markdown("- **Business Master Data**: source records from the business team")
    st.markdown("- **CC Team Rate Card**: reference service and rate-card descriptions")
    st.markdown("- **SAP VBRP**: historical SAP billing item descriptions")
    st.stop()

master = pd.read_excel(master_file, dtype=str).fillna("")
rate = pd.read_excel(rate_file, dtype=str).fillna("")
vbrp = pd.read_excel(vbrp_file, dtype=str).fillna("")

st.subheader("2. Map matching fields")
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("**Business Master**")
    m_desc = choose_column("Service description", master, "description", "m_desc")
    m_tower = choose_column("Tower (optional)", master, "tower", "m_tower")
    m_track = choose_column("Track (optional)", master, "track", "m_track")
with c2:
    st.markdown("**Rate Card**")
    r_desc = choose_column("Service description", rate, "description", "r_desc")
    r_tower = choose_column("Tower (optional)", rate, "tower", "r_tower")
    r_track = choose_column("Track (optional)", rate, "track", "r_track")
with c3:
    st.markdown("**SAP VBRP**")
    v_desc = choose_column("Item/service description", vbrp, "description", "v_desc")
    v_tower = choose_column("Tower (optional)", vbrp, "tower", "v_tower")
    v_track = choose_column("Track (optional)", vbrp, "track", "v_track")

st.caption("Choose the closest equivalent columns in each workbook. Optional Tower and Track fields are included in the comparison when selected.")
if st.button("Run matching", type="primary", use_container_width=True):
    rate_text = rate[r_desc].fillna("").astype(str).tolist()
    vbrp_text = vbrp[v_desc].fillna("").astype(str).tolist()
    results = []
    progress = st.progress(0)
    for i, (_, row) in enumerate(master.iterrows()):
        desc = str(row[m_desc])
        rate_name, rate_score = best_match(desc, rate_text)
        vbrp_name, vbrp_score = best_match(desc, vbrp_text)
        rate_idx = next((j for j, x in enumerate(rate_text) if x == rate_name), None)
        vbrp_idx = next((j for j, x in enumerate(vbrp_text) if x == vbrp_name), None)
        rate_row = rate.iloc[rate_idx] if rate_idx is not None else pd.Series(dtype=object)
        vbrp_row = vbrp.iloc[vbrp_idx] if vbrp_idx is not None else pd.Series(dtype=object)
        status = "Matched" if rate_score >= threshold and vbrp_score >= threshold else (
            "Partial Match" if max(rate_score, vbrp_score) >= threshold else "Needs Review"
        )
        out = row.to_dict()
        out.update({
            "Rate Card Match": rate_name,
            "Rate Card Confidence": rate_score,
            "VBRP Match": vbrp_name,
            "VBRP Confidence": vbrp_score,
            "Match Status": status,
        })
        if rate_idx is not None:
            for col in rate.columns:
                out["Rate Card | " + str(col)] = rate_row.get(col, "")
        if vbrp_idx is not None:
            for col in vbrp.columns:
                out["VBRP | " + str(col)] = vbrp_row.get(col, "")
        results.append(out)
        progress.progress((i + 1) / max(len(master), 1))
    result_df = pd.DataFrame(results)
    st.session_state["som_results"] = result_df
    st.success(f"Matching complete: {len(result_df)} business records processed.")

if "som_results" in st.session_state:
    result_df = st.session_state["som_results"]
    total = len(result_df)
    matched = int((result_df["Match Status"] == "Matched").sum())
    partial = int((result_df["Match Status"] == "Partial Match").sum())
    review = int((result_df["Match Status"] == "Needs Review").sum())
    a, b, c, d = st.columns(4)
    a.metric("Total records", total)
    b.metric("Matched", matched)
    c.metric("Partial match", partial)
    d.metric("Needs review", review)
    st.subheader("3. Match review")
    filter_status = st.multiselect("Filter by status", ["Matched", "Partial Match", "Needs Review"], default=["Matched", "Partial Match", "Needs Review"])
    view = result_df[result_df["Match Status"].isin(filter_status)]
    st.dataframe(view, use_container_width=True, hide_index=True)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        result_df.to_excel(writer, index=False, sheet_name="Match Results")
        result_df[result_df["Match Status"] != "Matched"].to_excel(writer, index=False, sheet_name="Needs Review")
        pd.DataFrame({
            "Metric": ["Total records", "Matched", "Partial Match", "Needs Review"],
            "Count": [total, matched, partial, review],
        }).to_excel(writer, index=False, sheet_name="Summary")
    st.download_button("Download Excel results", data=output.getvalue(), file_name="SOM_Match_Results.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
