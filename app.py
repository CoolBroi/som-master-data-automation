import io
import re
from copy import copy

import pandas as pd
import streamlit as st
from rapidfuzz import fuzz

st.set_page_config(page_title="SOM Master Data Automation", page_icon="🧩", layout="wide")
st.title("SOM Master Data Automation")
st.caption("Generate Business Master Data using CC Rate Card Tower + Track mapped against SAP VBRP Item Description.")
st.info("Demo version: files are processed in this app session only. There is no SAP connection. Use dummy or company-approved data only.")

def norm(value):
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())

def clean(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()

def best_match(query, candidates):
    q = clean(query)
    if not q:
        return "", 0, None
    best_name, best_score, best_idx = "", 0, None
    for idx, candidate in enumerate(candidates):
        c = clean(candidate)
        if not c:
            continue
        score = fuzz.token_set_ratio(q, c)
        if score > best_score:
            best_name, best_score, best_idx = str(candidate), int(score), idx
    return best_name, best_score, best_idx

def find_header(headers, names):
    lookup = {norm(h): h for h in headers}
    for name in names:
        if norm(name) in lookup:
            return lookup[norm(name)]
    for h in headers:
        nh = norm(h)
        if any(norm(n) in nh or nh in norm(n) for n in names if len(norm(n)) >= 4):
            return h
    return None

with st.sidebar:
    st.header("1. Upload source files")
    template_file = st.file_uploader("Business Master Data output template (.xlsx) — Required", type=["xlsx"], key="template")
    rate_file = st.file_uploader("CC Team Rate Card (.xlsx) — Required", type=["xlsx"], key="rate")
    vbrp_file = st.file_uploader("SAP VBRP dump (.xlsx) — Required", type=["xlsx"], key="vbrp")
    threshold = st.slider("Minimum match confidence", 50, 100, 80, 1)

if not all([template_file, rate_file, vbrp_file]):
    st.subheader("Getting started")
    st.write("Upload the blank Business Master Data output template, CC Team Rate Card and SAP VBRP dump. The Business Master Data file is used only as the output structure; it is not used as an input data source.")
    st.markdown("- **Business Master Data template:** determines the columns and layout of the final output.")
    st.markdown("- **CC Team Rate Card:** supplies Tower and Track values.")
    st.markdown("- **SAP VBRP:** supplies historical item descriptions for matching.")
    st.stop()

template_bytes = template_file.getvalue()
rate = pd.read_excel(rate_file, dtype=str).fillna("")
vbrp = pd.read_excel(vbrp_file, dtype=str).fillna("")
template_headers = list(pd.read_excel(io.BytesIO(template_bytes), nrows=0).columns)
rate_headers = list(rate.columns)
vbrp_headers = list(vbrp.columns)

st.subheader("2. Configure matching")
c1, c2 = st.columns(2)
with c1:
    st.markdown("**CC Team Rate Card**")
    tower_col = st.selectbox("Tower column", rate_headers, index=rate_headers.index(find_header(rate_headers, ["Tower"])) if find_header(rate_headers, ["Tower"]) in rate_headers else 0)
    track_col = st.selectbox("Track column", rate_headers, index=rate_headers.index(find_header(rate_headers, ["Track"])) if find_header(rate_headers, ["Track"]) in rate_headers else 0)
with c2:
    st.markdown("**SAP VBRP**")
    item_col = st.selectbox("Item Description column", vbrp_headers, index=vbrp_headers.index(find_header(vbrp_headers, ["Item Description", "ARKTX", "Description"])) if find_header(vbrp_headers, ["Item Description", "ARKTX", "Description"]) in vbrp_headers else 0)

st.caption("Matching key = Rate Card Tower + Track, compared against VBRP Item Description. The output will retain the Business Master Data template's column names.")
with st.expander("Optional: map important output columns"):
    st.write("Choose output columns to receive the matched values. Other output columns are populated automatically when their headers match a source column name.")
    tower_target = st.selectbox("Output column for Tower", ["(Auto-detect)"] + template_headers, index=(template_headers.index(find_header(template_headers, ["Tower"])) + 1) if find_header(template_headers, ["Tower"]) in template_headers else 0)
    track_target = st.selectbox("Output column for Track", ["(Auto-detect)"] + template_headers, index=(template_headers.index(find_header(template_headers, ["Track"])) + 1) if find_header(template_headers, ["Track"]) in template_headers else 0)
    item_target = st.selectbox("Output column for matched VBRP Item Description", ["(Auto-detect)"] + template_headers, index=(template_headers.index(find_header(template_headers, ["SOW Product Name", "Item Description", "Display text"])) + 1) if find_header(template_headers, ["SOW Product Name", "Item Description", "Display text"]) in template_headers else 0)

if st.button("Generate Business Master Data", type="primary", use_container_width=True):
    if not template_headers:
        st.error("The uploaded Business Master Data template has no column headers.")
        st.stop()

    # Build VBRP candidate descriptions and prepare a fresh output row per Rate Card record.
    vbrp_items = vbrp[item_col].fillna("").astype(str).tolist()
    output_rows = []
    review_rows = []
    progress = st.progress(0)

    # Resolve output targets by explicit choice first, then header aliases.
    tower_out = tower_target if tower_target != "(Auto-detect)" else find_header(template_headers, ["Tower"])
    track_out = track_target if track_target != "(Auto-detect)" else find_header(template_headers, ["Track"])
    item_out = item_target if item_target != "(Auto-detect)" else find_header(template_headers, ["SOW Product Name", "Item Description", "Display text"])

    for i, (_, rate_row) in enumerate(rate.iterrows()):
        tower = str(rate_row.get(tower_col, "")).strip()
        track = str(rate_row.get(track_col, "")).strip()
        key = " ".join(x for x in [tower, track] if x)
        matched_desc, score, match_idx = best_match(key, vbrp_items)

        # Start with blank values in the exact Business Master Data template structure.
        out = {h: "" for h in template_headers}

        # Copy Rate Card values into output columns with the same normalized header.
        rate_lookup = {norm(h): h for h in rate_headers}
        for target_header in template_headers:
            source_header = rate_lookup.get(norm(target_header))
            if source_header:
                out[target_header] = rate_row.get(source_header, "")

        # Apply explicit/alias mappings for Tower and Track.
        if tower_out:
            out[tower_out] = tower
        if track_out:
            out[track_out] = track
        if item_out and match_idx is not None:
            out[item_out] = matched_desc

        # Copy VBRP fields only where the target template has the same header name;
        # never overwrite an already populated Rate Card value.
        if match_idx is not None:
            vrow = vbrp.iloc[match_idx]
            vbrp_lookup = {norm(h): h for h in vbrp_headers}
            for target_header in template_headers:
                source_header = vbrp_lookup.get(norm(target_header))
                if source_header and not str(out.get(target_header, "")).strip():
                    out[target_header] = vrow.get(source_header, "")

        out["__Match Confidence"] = score
        out["__Matched VBRP Description"] = matched_desc
        out["__Match Status"] = "Matched" if score >= threshold else "Needs Review"
        output_rows.append(out)
        if score < threshold:
            review_rows.append({
                "Rate Card Tower": tower,
                "Rate Card Track": track,
                "Combined Matching Key": key,
                "Best VBRP Item Description": matched_desc,
                "Confidence": score,
                "Status": "Needs Review",
            })
        progress.progress((i + 1) / max(len(rate), 1))

    result = pd.DataFrame(output_rows)
    status = result["__Match Status"]
    matched_count = int((status == "Matched").sum())
    review_count = int((status == "Needs Review").sum())

    # Remove internal columns from the Business Master output; retain them in the review sheet.
    master_output = result[template_headers].copy()

    # Keep the uploaded workbook and its template sheet/headers; write generated rows below the header.
    try:
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(template_bytes))
        ws = wb[wb.sheetnames[0]]
        header_row = 1
        # Clear existing sample/data rows while preserving header formatting.
        if ws.max_row > header_row:
            ws.delete_rows(header_row + 1, ws.max_row - header_row)
        for row_idx, values in enumerate(master_output.itertuples(index=False, name=None), start=header_row + 1):
            for col_idx, value in enumerate(values, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=None if pd.isna(value) else str(value))
                if row_idx > header_row and ws.cell(row=header_row, column=col_idx).has_style:
                    cell._style = copy(ws.cell(row=header_row, column=col_idx)._style)
        for col_idx in range(1, len(template_headers) + 1):
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = max(
                ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width or 10, 14
            )
        output = io.BytesIO()
        wb.save(output)
    except Exception as exc:
        st.error(f"Could not write the output template: {exc}")
        st.stop()

    st.success(f"Generated {len(master_output)} Business Master Data rows using the uploaded template.")
    a, b, c = st.columns(3)
    a.metric("Output records", len(master_output))
    b.metric("Matched", matched_count)
    c.metric("Needs review", review_count)
    st.subheader("3. Business Master Data output preview")
    st.dataframe(master_output.head(100), use_container_width=True, hide_index=True)
    st.download_button("Download Business Master Data Excel", data=output.getvalue(), file_name="Generated_Business_Master_Data.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")

    st.subheader("4. Matching review")
    review_df = pd.DataFrame(review_rows)
    if review_df.empty:
        st.success("All Rate Card records met the selected confidence threshold.")
    else:
        st.dataframe(review_df, use_container_width=True, hide_index=True)
    review_bytes = io.BytesIO()
    with pd.ExcelWriter(review_bytes, engine="openpyxl") as writer:
        review_df.to_excel(writer, index=False, sheet_name="Needs Review")
        pd.DataFrame({"Metric": ["Total Rate Card rows", "Matched", "Needs Review"], "Count": [len(rate), matched_count, review_count]}).to_excel(writer, index=False, sheet_name="Summary")
    st.download_button("Download matching review", data=review_bytes.getvalue(), file_name="SOM_Matching_Review.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
