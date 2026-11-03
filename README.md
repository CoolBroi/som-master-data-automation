# SOM Master Data Automation

A browser-based Streamlit demo for reconciling SAP SOM business master data, CC rate cards, and SAP VBRP extracts.

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud
1. Open https://share.streamlit.io/
2. Sign in with GitHub and authorise access to this repository.
3. Choose **New app**.
4. Select repository `CoolBroi/som-master-data-automation`, branch `main`, and main file `app.py`.
5. Click **Deploy**.

This demo processes uploaded workbooks in the app session and does not connect to SAP. Use dummy or approved non-confidential data only; this repository is public.
