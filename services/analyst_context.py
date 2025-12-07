import os
import pandas as pd

BASE_DATA_DIR = "./data"

def build_network_summary():
    # Very simple: load last N rows from all CSVs and summarize basic stats
    rows = []
    for city in os.listdir(BASE_DATA_DIR):
        city_dir = os.path.join(BASE_DATA_DIR, city)
        for fname in os.listdir(city_dir):
            if not fname.endswith(".csv"):
                continue
            path = os.path.join(city_dir, fname)
            df = pd.read_csv(path).tail(50)  # last 50 samples
            df["city"] = city
            df["cell_id"] = fname.replace(".csv", "")
            rows.append(df)

    if not rows:
        return "No network data available."

    all_df = pd.concat(rows, ignore_index=True)

    # Example simple aggregations:
    summary = []

    avg_latency = all_df["latency_ms"].mean()
    avg_throughput = all_df["throughput_mbps"].mean()
    worst_cell = all_df.sort_values("latency_ms", ascending=False).head(1)

    summary.append(f"Average latency across all cells: {avg_latency:.1f} ms.")
    summary.append(f"Average throughput across all cells: {avg_throughput:.1f} Mbps.")

    row = worst_cell.iloc[0]
    summary.append(
        f"Worst latency currently at {row['city']} / {row['cell_id']} with "
        f"{row['latency_ms']:.1f} ms and throughput {row['throughput_mbps']:.1f} Mbps."
    )

    return "\n".join(summary)
