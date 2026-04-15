import os
import json
import duckdb
from pathlib import Path
from PIL import Image
import google.generativeai as genai

backend_path = Path("c:/VS_QuanQual_AlphaScan/backend")

# API Key directly for script
api_key = 'AIzaSyAIwt3PELgDlZ45Q2Scau-Au_I8jY1-nRQ'
genai.configure(api_key=api_key)
model = genai.GenerativeModel("gemini-1.5-pro")




artifact_dir = Path(r"C:\Users\ivan0\.gemini\antigravity\brain\144705fc-9b36-4ed6-9052-ca83321b332f")
img_files = [
    'media__1773058685695.png', 
    'media__1773058699318.png', 
    'media__1773058709613.png', 
    'media__1773058719643.png', 
    'media__1773058728842.png', 
    'media__1773059227942.png', 
    'media__1773059237609.png', 
    'media__1773059246938.png', 
    'media__1773059260212.png'
]

prompt = """
Extract Taiwan warrant trading data as JSON list. 
Top broker per image only. 
Return ONLY JSON: [{"stock_symbol": "string", "stock_name": "string", "broker": "string", "amount_k": number, "type": "認購"|"認售"}]
"""

results = []
for f in img_files:
    p = artifact_dir / f
    if p.exists():
        print(f"Reading {f}...")
        img = Image.open(p)
        try:
            resp = model.generate_content([prompt, img])
            text = resp.text.strip().replace('```json', '').replace('```', '').strip()
            data = json.loads(text)
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
        except Exception as e:
            print(f"Error processing {f}: {e}")
        import time
        time.sleep(5) # avoid rate limits


print(f"Total extracted: {len(results)}")

db_path = backend_path.parent / "data" / "market.duckdb"
conn = duckdb.connect(str(db_path))

conn.execute("""
    CREATE TABLE IF NOT EXISTS warrant_branch_positions (
        snapshot_date DATE,
        stock_id VARCHAR,
        stock_name VARCHAR,
        branch_name VARCHAR,
        position_shares BIGINT,   
        est_pnl DOUBLE,           
        est_pnl_pct DOUBLE,       
        amount_k DOUBLE,          
        type VARCHAR,             
        PRIMARY KEY (snapshot_date, stock_id, branch_name, type)
    );
""")

for r in results:

    s_id = r.get('stock_symbol')
    s_name = r.get('stock_name')
    b_name = r.get('broker')
    amt = r.get('amount_k')
    t = r.get('type', '認購')
    
    if s_id and b_name:
        print(f"Saving {s_id} - {b_name}...")
        conn.execute("""
            INSERT INTO warrant_branch_positions (snapshot_date, stock_id, stock_name, branch_name, amount_k, est_pnl, type) 
            VALUES ('2026-03-09', ?, ?, ?, ?, 0, ?) 
            ON CONFLICT (snapshot_date, stock_id, branch_name, type) DO UPDATE SET 
                amount_k = excluded.amount_k, 
                stock_name = excluded.stock_name
        """, [s_id, s_name, b_name, amt, t])

conn.close()
print("Process completed.")
