import os
import json
import duckdb
from pathlib import Path
from PIL import Image
import google.generativeai as genai

backend_path = Path("c:/VS_QuanQual_AlphaScan/backend")

# Load API key from .env
root_env = Path("c:/VS_QuanQual_AlphaScan/.env")
k_v = {}
if root_env.exists():
    with open(root_env, 'r', encoding='utf-8') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                k_v[k] = v

genai.configure(api_key=k_v.get("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

artifact_dir = Path(r"C:\Users\ivan0\.gemini\antigravity\brain\144705fc-9b36-4ed6-9052-ca83321b332f")
img_files = ['media__1773058685695.png', 'media__1773058699318.png', 'media__1773058709613.png', 'media__1773058719643.png', 'media__1773058728842.png', 'media__1773059227942.png', 'media__1773059237609.png', 'media__1773059246938.png', 'media__1773059260212.png']

prompt = """
Extract Taiwan warrant trading data as JSON list: 
[{"stock_symbol": "string", "stock_name": "string", "broker": "string", "amount_k": number, "type": "認購"|"認售"}]
Only the top broker per image. Output ONLY JSON.
"""

results = []
for f in img_files:
    p = artifact_dir / f
    if p.exists():
        img = Image.open(p)
        try:
            resp = model.generate_content([prompt, img])
            text = resp.text.strip().replace('```json', '').replace('```', '').strip()
            data = json.loads(text)
            if isinstance(data, list): results.extend(data)
            else: results.append(data)
        except: pass

conn = duckdb.connect(str(backend_path.parent / "data" / "market.duckdb"))
for r in results:
    conn.execute("""
        INSERT INTO warrant_branch_positions (snapshot_date, stock_id, stock_name, branch_name, amount_k, est_pnl, type) 
        VALUES ('2026-03-09', ?, ?, ?, ?, 0, ?) 
        ON CONFLICT DO UPDATE SET amount_k=excluded.amount_k, stock_name=excluded.stock_name
    """, [r['stock_symbol'], r['stock_name'], r['broker'], r['amount_k'], r['type']])
conn.close()
print(f"Done: {len(results)} records.")
