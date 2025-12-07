# analyst_context.py
import os
import pandas as pd
from typing import Dict, List, Optional, Tuple

# Make path robust regardless of where app is started from
BASE_DATA_DIR = "./data"


def _discover_topology() -> Dict[str, List[str]]:
    """
    Scan BASE_DATA_DIR and return mapping:
    {
      "Bangalore": ["BLR_C1", "BLR_C2", ...],
      ...
    }
    """
    topology: Dict[str, List[str]] = {}

    if not os.path.exists(BASE_DATA_DIR):
        print(f"Data directory {BASE_DATA_DIR} does not exist.")
        return topology

    for city in os.listdir(BASE_DATA_DIR):
        city_dir = os.path.join(BASE_DATA_DIR, city)
        if not os.path.isdir(city_dir):
            continue

        cell_ids: List[str] = []
        for fname in os.listdir(city_dir):
            if fname.endswith(".csv"):
                cell_ids.append(fname.replace(".csv", ""))
        if cell_ids:
            topology[city] = cell_ids

    return topology


def _infer_scope_from_query(
    user_query: Optional[str],
    topology: Dict[str, List[str]]
) -> Tuple[Optional[str], Optional[str]]:
    """
    Try to infer (city, cell_id) from the user's natural language question.
    If we find a cell, we also fix the city to the one that owns that cell.
    Returns (city or None, cell_id or None).
    """
    if not user_query:
        return None, None

    q = user_query.lower()

    # 1) Try to detect city by name
    detected_city: Optional[str] = None
    for city in topology.keys():
        if city.lower() in q:
            detected_city = city
            break

    # 2) Try to detect a specific cell ID by exact substring (case-insensitive)
    detected_cell: Optional[str] = None
    for city, cells in topology.items():
        for cid in cells:
            if cid.lower() in q:
                detected_cell = cid
                detected_city = city  # force-align city if cell is found
                break
        if detected_cell:
            break

    return detected_city, detected_cell


def _load_data_for_scope(
    topology: Dict[str, List[str]],
    city: Optional[str],
    cell_id: Optional[str],
    last_n: int = 100,
) -> Optional[pd.DataFrame]:
    """
    Load the latest data according to the chosen scope:
    - If cell_id given -> just that cell
    - Else if city given -> all cells in that city
    - Else -> all cells in all cities
    Returns a pandas DataFrame or None if nothing found.
    """
    rows = []

    # Case 1: specific cell
    if cell_id:
        # city must also be known here
        city_cells = topology.get(city, [])
        if cell_id not in city_cells:
            return None

        city_dir = os.path.join(BASE_DATA_DIR, city)
        path = os.path.join(city_dir, f"{cell_id}.csv")
        if not os.path.exists(path):
            return None

        df = pd.read_csv(path).tail(last_n)
        df["city"] = city
        df["cell_id"] = cell_id
        rows.append(df)

    else:
        # Case 2: city-wide or global
        if city:
            cities = [city]
        else:
            cities = list(topology.keys())

        for c in cities:
            city_dir = os.path.join(BASE_DATA_DIR, c)
            for cell in topology.get(c, []):
                path = os.path.join(city_dir, f"{cell}.csv")
                if not os.path.exists(path):
                    continue
                df = pd.read_csv(path).tail(last_n)
                df["city"] = c
                df["cell_id"] = cell
                rows.append(df)

    if not rows:
        return None

    return pd.concat(rows, ignore_index=True)


def _classify_health(latency_ms: float, packet_loss: float, users: float) -> str:
    """
    Simple heuristic for text classification of current health.
    """
    if latency_ms > 200 or packet_loss > 3:
        return "Severe degradation (likely incident)."
    if latency_ms > 80 or packet_loss > 1:
        return "Degraded performance (monitor closely)."
    if users > 150 and latency_ms > 50:
        return "High load, mild congestion."
    return "Healthy / normal behavior."


def build_network_summary(user_query: Optional[str] = None) -> str:
    """
    Build a human-readable summary of the network based on the latest CSV data.
    If the user query mentions a specific city/tower, we focus there.
    Otherwise we compute a global summary.
    This function is stateless and always reads from disk, so it reflects
    the latest metrics written by live_node_generator.py.
    """
    topology = _discover_topology()
    print("Discovered topology:", topology)
    if not topology:
        return "No network data available yet."

    city, cell_id = _infer_scope_from_query(user_query, topology)
    scope_desc = (
        f"cell {cell_id} in {city}"
        if cell_id
        else f"city {city}" if city
        else "the entire network"
    )

    df = _load_data_for_scope(topology, city, cell_id, last_n=100)
    if df is None or df.empty:
        return f"No recent data found for {scope_desc}."

    # Basic aggregates
    avg_latency = df["latency_ms"].mean()
    avg_throughput = df["throughput_mbps"].mean()
    avg_packet_loss = df["packet_loss_pct"].mean()
    avg_users = df["users_connected"].mean()

    latest = df.sort_values("timestamp").iloc[-1]

    lines = []
    lines.append(f"Scope: {scope_desc}.")
    lines.append(
        f"Average latency: {avg_latency:.1f} ms, "
        f"average throughput: {avg_throughput:.1f} Mbps."
    )
    lines.append(
        f"Average packet loss: {avg_packet_loss:.3f}%, "
        f"average connected users: {avg_users:.1f}."
    )

    # If multiple cells, highlight best/worst by latency
    if cell_id is None:
        by_cell = df.groupby(["city", "cell_id"]).agg(
            avg_latency=("latency_ms", "mean"),
            avg_throughput=("throughput_mbps", "mean"),
        )

        worst = by_cell.sort_values("avg_latency", ascending=False).head(1)
        best = by_cell.sort_values("avg_latency", ascending=True).head(1)

        worst_row = worst.iloc[0]
        best_row = best.iloc[0]

        worst_city, worst_cell = worst.index[0]
        best_city, best_cell = best.index[0]

        lines.append(
            f"Worst latency currently at {worst_city}/{worst_cell}: "
            f"{worst_row['avg_latency']:.1f} ms, "
            f"{worst_row['avg_throughput']:.1f} Mbps throughput."
        )
        lines.append(
            f"Best latency currently at {best_city}/{best_cell}: "
            f"{best_row['avg_latency']:.1f} ms, "
            f"{best_row['avg_throughput']:.1f} Mbps throughput."
        )

    # Latest sample insight for the focused scope
    health = _classify_health(
        latest["latency_ms"],
        latest["packet_loss_pct"],
        latest["users_connected"],
    )
    lines.append(
        "Most recent sample: "
        f"{latest['timestamp']} – latency {latest['latency_ms']:.1f} ms, "
        f"throughput {latest['throughput_mbps']:.1f} Mbps, "
        f"packet loss {latest['packet_loss_pct']:.3f}%, "
        f"{latest['users_connected']} users connected."
    )
    lines.append(f"Health assessment: {health}")

    return "\n".join(lines)
