import io
import re

import pandas as pd
import streamlit as st
from rapidfuzz import fuzz, process

st.set_page_config(page_title="SOM Master Data Automation", page_icon="🧩", layout="wide")

st.title("SOM Master Data Automation")
st.caption("Reconcile CC Team Rate Cards and SAP VBRP extracts, with optional Business Master Data.")
st.info("Demo version: files are processed in this app session only. There is no SAP connection. Use dummy or company-approved data only.")

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
    valid = [(str(x), clean(x)) for x in candidates if clean(x)]
    if not q or not valid:
        return "", 0, None
    result = process.extractOne(q, [x[1] for x in valid], scorer=fuzz.token_set_ratio)
    if not result:
        return "", 0, None
    _, score, idx = result
    original = next((i for i, x in enumerate(candidates) if str(x) == valid[idx][0]), None)
    return valid[idx][0], int(score), original

with st.sidebar:
    st.header("1. Upload source files")
    master_file = st.file_uploader("Business Master Data (.xlsx) — Optional", type=["xlsx"], key="master")
    rate_file = st.file_uploader("CC Team Rate Card (.xlsx) — Required", type=["xlsx"], key="rate")
    vbrp_file = st.file_uploader("SAP VBRP dump (.xlsx) — Required", type=["xlsx"], key="vbrp")
    threshold = st.slider("Minimum match confidence", 50, 100, 85, 1)

if not rate_file or not vbrp_file:
    st.subheader("Getting started")
    st.write("Upload the CC Team Rate Card and SAP VBRP dump to run matching. Business Master Data is optional. If you do not upload it, the app will use each Rate Card row as the starting record and match it against VBRP.")
    st.markdown("- **Business Master Data (optional):** adds business source fields and uses its records as the starting point when provided.")
    st.markdown("- **CC Team Rate Card (required):** reference service and rate-card descriptions.")
    st.markdown("- **SAP VBRP (required):** historical SAP billing item descriptions.")
    st.stop()

rate = pd.read_excel(rate_file, dtype=str).fillna("")
vbrp = pd.read_excel(vbrp_file, dtype=str).fillna("")
master = pd.read_excel(master_file, dtype=str).fillna("") if master_file else None

st.subheader("2. Map matching fields")
if master is not None:
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("**Business Master**")
        m_desc = choose_column("Service description", master, "description", "m_desc")
    with c2:
        st.markdown("**Rate Card**")
        r_desc = choose_column("Service description", rate, "description", "r_desc")
    with c3:
        st.markdown("**SAP VBRP**")
        v_desc = choose_column("Item/service description", vbrp, "description", "v_desc")
    base = master
    base_desc = m_desc
else:
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Rate Card**")
        r_desc = choose_column("Service description", rate, "description", "r_desc")
    with c2:
        st.markdown("**SAP VBRP**")
        v_desc = choose_column("Item/service description", vbrp, "description", "v_desc")
    base = rate
    base_desc = r_desc

st.caption("Business Master Data can be left blank. When it is not supplied, Rate Card rows are matched directly against VBRP.")
if st.button("Run matching", type="primary", use_container_width=True):
    rate_text = rate[r_desc].fillna("").astype(str).tolist()
    vbrp_text = vbrp[v_desc].fillna("").astype(str).tolist()
    results = []
    progress = st.progress(0)
    for i, (_, row) in enumerate(base.iterrows()):
        desc = str(row[base_desc])
        if master is not None:
            rate_name, rate_score, rate_idx = best_match(desc, rate_text)
        else:
            rate_name, rate_score, rate_idx = desc, 100, i if i < len(rate) else None
        vbrp_name, vbrp_score, vbrp_idx = best_match(desc, vbrp_text)
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
        if master is not None and rate_idx is not None:
            for col in rate.columns:
                out["Rate Card | " + str(col)] = rate.iloc[rate_idx].get(col, "")
        if vbrp_idx is not None:
            for col in vbrp.columns:
                out["VBRP | " + str(col)] = vbrp.iloc[vbrp_idx].get(col, "")
        results.append(out)
        progress.progress((i + 1) / max(len(base), 1))
    result_df = pd.DataFrame(results)
    st.session_state["som_results"] = result_df
    st.success(f"Matching complete: {len(result_df)} records processed.")

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
    st.dataframe(result_df[result_df["Match Status"].isin(filter_status)], use_container_width=True, hide_index=True)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        result_df.to_excel(writer, index=False, sheet_name="Match Results")
        result_df[result_df["Match Status"] != "Matched"].to_excel(writer, index=False, sheet_name="Needs Review")
        pd.DataFrame({"Metric": ["Total records", "Matched", "Partial Match", "Needs Review"], "Count": [total, matched, partial, review]}).to_excel(writer, index=False, sheet_name="Summary")
    st.download_button("Download Excel results", data=output.getvalue(), file_name="SOM_Match_Results.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
