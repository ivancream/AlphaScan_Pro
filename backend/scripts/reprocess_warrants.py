import os
import io
import json
import duckdb
from pathlib import Path
from PIL import Image
import google.generativeai as genai

# Setup paths
backend_path = Path("c:/VS_QuanQual_AlphaScan/backend")
import sys
sys.path.insert(0, str(backend_path))
from engines import engine_chips

# Load API key from .env
root_env = Path("c:/VS_QuanQual_AlphaScan/.env")
if root_env.exists():
    with open(root_env, 'r', encoding='utf-8') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k] = v

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Artifacts directory
artifact_dir = Path(r"C:\Users\ivan0\.gemini\antigravity\brain\144705fc-9b36-4ed6-9052-ca83321b332f")
image_files = [
    "media__1773058685695.png",
    "media__1773058699318.png",
    "media__1773058709613.png",
    "media__1773058719643.png",
    "media__1773058728842.png",
    "media__1773059227942.png",
    "media__1773059237609.png",
    "media__1773059246938.png",
    "media__1773059260212.png"
]

images = []
for filename in image_files:
    path = artifact_dir / filename
    if path.exists():
        images.append(Image.open(path))

if not images:
    print("No images found to process.")
    exit()

print(f"Processing {len(images)} images...")

extracted_results = []
for i, img in enumerate(images):
    print(f"Processing image {i+1}...")
    res = engine_chips.extract_warrant_data_from_image([img])
    if res:
        extracted_results.extend(res)

print(f"Extracted {len(extracted_results)} records.")

# Save to DB with date 2026-03-09
db_path = backend_path.parent / "data" / "market.duckdb"
conn = duckdb.connect(str(db_path))

for item in extracted_results:
    # Force date to 2026-03-09
    target_date = "2026-03-09"
    conn.execute("""
        INSERT INTO warrant_branch_positions (snapshot_date, stock_id, stock_name, branch_name, amount_k, est_pnl, type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (snapshot_date, stock_id, branch_name, type) DO UPDATE SET
            amount_k = excluded.amount_k,
            est_pnl = excluded.est_pnl,
            stock_name = excluded.stock_name
    """, [
        target_date,
        item.get('stock_symbol'),
        item.get('stock_name'),
        item.get('broker'),
        item.get('amount_k'),
        item.get('estimated_pnl', 0),
        item.get('type', '認購')
    ])

conn.close()
print("Successfully re-ingested REAL data into 2026-03-09.")
