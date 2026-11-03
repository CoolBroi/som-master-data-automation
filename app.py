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

def expand_terms(value):
    # Normalize common business abbreviations and grammatical variants before
    # comparing Rate Card Track text with historical VBRP Item Descriptions.
    replacements = {
        "hw": "hardware",
        "mgmt": "management",
        "mgt": "management",
        "perf": "performance",
        "app": "application",
        "apps": "applications",
        "svc": "service",
        "svcs": "services",
        "maint": "maintenance",
        "infra": "infrastructure",
        "ops": "operations",
        "admin": "administration",
        "sec": "security",
        "net": "network",
        "dev": "development",
        "supp": "support",
        "manuf": "manufacturing",
    }
    tokens = clean(value).split()
    expanded = [replacements.get(token, token) for token in tokens]
    # Treat common verb/noun endings consistently (manage/management).
    normalized = []
    singular_forms = {
        "terminals": "terminal",
        "devices": "device",
        "applications": "application",
        "services": "service",
        "clients": "client",
        "printers": "printer",
        "descriptions": "description",
        "assets": "asset",
        "technologies": "technology",
    }
    for token in expanded:
        if token == "manage":
            token = "management"
        elif token == "perform":
            token = "performance"
        token = singular_forms.get(token, token)
        normalized.append(token)
    return " ".join(normalized)

def best_match(track_query, candidates, tower_query="", min_confidence=80):
    # Matching order:
    # 1) Track alone (including compact exact match such as AlwaysONVPN = ALWAYS ON VPN).
    # 2) If Track alone is not sufficiently confident, retry with Tower + Track.
    # This prevents Tower wording from diluting an otherwise exact Track match.
    track_raw = str(track_query or "").strip()
    tower_raw = str(tower_query or "").strip()
    track = expand_terms(track_raw)
    tower = expand_terms(tower_raw)
    if not track and not tower:
        return "", 0, None

    prepared = []
    for idx, candidate in enumerate(candidates):
        raw_candidate = str(candidate or "").strip()
        candidate_text = expand_terms(raw_candidate)
        if candidate_text:
            prepared.append((idx, raw_candidate, candidate_text))

    # Exact compact comparison ignores spaces, hyphens and punctuation.
    # Example: "AlwaysONVPN" matches "ALWAYS ON VPN".
    compact_track = norm(track_raw)
    if compact_track:
        for idx, raw_candidate, candidate_text in prepared:
            if norm(raw_candidate) == compact_track:
                return raw_candidate, 100, idx

    def score_query(query_text, allow_specificity_guard=True):
        query_tokens = set(query_text.split())
        best_name, best_score, best_idx = "", 0, None
        if not query_tokens:
            return best_name, best_score, best_idx

        for idx, raw_candidate, candidate_text in prepared:
            candidate_tokens = set(candidate_text.split())
            coverage = (
                len(query_tokens.intersection(candidate_tokens)) / len(query_tokens)
                if query_tokens else 0
            )
            raw_score = max(
                fuzz.ratio(query_text, candidate_text),
                fuzz.token_sort_ratio(query_text, candidate_text),
                fuzz.token_set_ratio(query_text, candidate_text),
                fuzz.WRatio(query_text, candidate_text),
            )
            score = (raw_score * 0.80) + (coverage * 20)

            if query_tokens.issubset(candidate_tokens):
                if candidate_text == query_text:
                    score = 100
                elif allow_specificity_guard and len(query_tokens) == 1:
                    # "Dispatch" must not be auto-matched to "Smart Dispatch - Italy".
                    score = min(score, 79)
                else:
                    score = max(score, 92)

            score = int(round(score))
            if score > best_score:
                best_name, best_score, best_idx = raw_candidate, score, idx
        return best_name, best_score, best_idx

    # PASS 1: search using Track alone. Return immediately if it clears the
    # configured confidence threshold.
    track_name, track_score, track_idx = score_query(track)
    if track_idx is not None and track_score >= min_confidence:
        return track_name, track_score, track_idx

    # PASS 2: only if Track alone is not confident enough, try Tower + Track.
    combined_query = " ".join(x for x in [tower, track] if x)
    combined_name, combined_score, combined_idx = score_query(
        combined_query, allow_specificity_guard=False
    )

    # Preserve SD service-code recognition as a fallback, but require the
    # candidate description (after removing SD code) to agree with Track.
    tower_codes = re.findall(r"\\bsd\\s*[- ]?\\s*0?[0-9]+\\b", tower_raw.lower())
    tower_code = re.sub(r"[^a-z0-9]", "", tower_codes[0]) if tower_codes else ""
    if tower_code:
        for idx, raw_candidate, candidate_text in prepared:
            candidate_codes = re.findall(r"\\bsd\\s*[- ]?\\s*0?[0-9]+\\b", raw_candidate.lower())
            candidate_code = re.sub(r"[^a-z0-9]", "", candidate_codes[0]) if candidate_codes else ""
            if candidate_code == tower_code:
                remainder_raw = re.sub(r"\\bsd\\s*[- ]?\\s*0?[0-9]+\\b", " ", raw_candidate, flags=re.I)
                remainder = expand_terms(remainder_raw)
                if not remainder:
                    return raw_candidate, 100, idx
                if track:
                    desc_score = max(fuzz.token_sort_ratio(track, remainder), fuzz.WRatio(track, remainder))
                    if desc_score >= min_confidence and desc_score > combined_score:
                        combined_name, combined_score, combined_idx = raw_candidate, int(desc_score), idx

    # Keep the better result for the review screen if neither pass cleared threshold.
    if track_score > combined_score:
        return track_name, track_score, track_idx
    return combined_name, combined_score, combined_idx

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

    # Detect project/company fields so descriptions are matched only within
    # the same SAP project and company code whenever those fields are available.
    rate_project_col = find_header(rate_headers, ["Project Code", "Project definition", "PSPID"])
    rate_company_col = find_header(rate_headers, ["Company Code", "CoCd", "BUKRS"])
    vbrp_project_col = find_header(vbrp_headers, ["Project definition", "Project Code", "PSPID"])
    vbrp_company_col = find_header(vbrp_headers, ["CoCd", "Company Code", "BUKRS"])

    # Build VBRP candidate descriptions and prepare a fresh output row per Rate Card record.
    vbrp_items = vbrp[item_col].fillna("").astype(str).tolist()
    output_rows = []
    review_rows = []
    progress = st.progress(0)

    # Resolve output targets by explicit choice first, then header aliases.
    tower_out = tower_target if tower_target != "(Auto-detect)" else find_header(template_headers, ["Tower"])
    track_out = track_target if track_target != "(Auto-detect)" else find_header(template_headers, ["Track"])
    item_out = item_target if item_target != "(Auto-detect)" else find_header(template_headers, ["SOW Product Name", "Item Description", "Display text"])

    # The first Business Master Data template column stores Migration Key.
    # Keys are assigned only AFTER the final output rows and SOW Product Name
    # values have been generated.
    migration_key_col = template_headers[0]

    for i, (_, rate_row) in enumerate(rate.iterrows()):
        tower = str(rate_row.get(tower_col, "")).strip()
        track = str(rate_row.get(track_col, "")).strip()
        key = " ".join(x for x in [tower, track] if x)

        # Restrict VBRP candidates to the same Project Code and Company Code.
        # This prevents a similar description from another project/customer
        # from being selected accidentally.
        candidate_positions = list(range(len(vbrp)))
        if rate_project_col and vbrp_project_col:
            rate_project = norm(rate_row.get(rate_project_col, ""))
            if rate_project:
                candidate_positions = [
                    pos for pos in candidate_positions
                    if norm(vbrp.iloc[pos].get(vbrp_project_col, "")) == rate_project
                ]
        if rate_company_col and vbrp_company_col:
            rate_company = norm(rate_row.get(rate_company_col, ""))
            if rate_company:
                candidate_positions = [
                    pos for pos in candidate_positions
                    if norm(vbrp.iloc[pos].get(vbrp_company_col, "")) == rate_company
                ]

        scoped_items = [vbrp_items[pos] for pos in candidate_positions]
        matched_desc, score, scoped_match_idx = best_match(track, scoped_items, tower_query=tower, min_confidence=threshold)
        match_idx = candidate_positions[scoped_match_idx] if scoped_match_idx is not None else None

        # Start with blank values in the exact Business Master Data template structure.
        out = {h: "" for h in template_headers}

        # Copy Rate Card values into output columns with the same normalized header.
        rate_lookup = {norm(h): h for h in rate_headers}
        for target_header in template_headers:
            source_header = rate_lookup.get(norm(target_header))
            if source_header:
                out[target_header] = rate_row.get(source_header, "")

        # Apply Migration Key and explicit/alias mappings.
        out[migration_key_col] = ""
        if tower_out:
            out[tower_out] = tower
        if track_out:
            out[track_out] = track
        # Replace the Rate Card product name with the VBRP description only
        # when the Track-based match meets the confidence threshold.
        # A weak Bronze-vs-Silver match must not incorrectly reuse Silver.
        if item_out and match_idx is not None and score >= threshold:
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

        out["__Migration Key"] = ""
        out["__Match Confidence"] = score
        out["__Matched VBRP Description"] = matched_desc
        out["__Match Status"] = "Matched" if score >= threshold else "Needs Review"
        output_rows.append(out)
        progress.progress((i + 1) / max(len(rate), 1))

    result = pd.DataFrame(output_rows)

    # IMPORTANT: assign Migration Keys from the FINAL generated Business
    # Master Data product-name column, after VBRP matching/population.
    # Therefore the final SOW Product Name is the single source of truth.
    final_product_name_col = item_out
    if not final_product_name_col or final_product_name_col not in result.columns:
        st.error("Could not identify the final SOW Product Name output column. Please map the output column in the optional mapping section and try again.")
        st.stop()

    name_to_migration_key = {}
    migration_keys = []
    next_key_number = 1
    for row_number, final_name in enumerate(result[final_product_name_col].fillna("").astype(str)):
        normalized_name = clean(final_name)
        # Empty final names must not be grouped together.
        group_identity = normalized_name if normalized_name else f"__blank_final_name_row_{row_number}"
        if group_identity not in name_to_migration_key:
            name_to_migration_key[group_identity] = f"MK{next_key_number:03d}"
            next_key_number += 1
        migration_keys.append(name_to_migration_key[group_identity])

    result["__Migration Key"] = migration_keys
    result[migration_key_col] = migration_keys

    # Build review rows after Migration Keys have been assigned from final output names.
    review_rows = []
    for _, row in result[result["__Match Status"] == "Needs Review"].iterrows():
        review_rows.append({
            "Migration Key": row["__Migration Key"],
            "Product Name": row[final_product_name_col],
            "Rate Card Tower": row.get(tower_out, ""),
            "Rate Card Track": row.get(track_out, ""),
            "Best VBRP Item Description": row.get(item_out, ""),
            "Confidence": row["__Match Confidence"],
            "Status": row["__Match Status"],
        })

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
