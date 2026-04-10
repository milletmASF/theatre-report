import re
import sys
import json
from datetime import datetime, timezone
import requests

API_URL = "https://boletopolis.com/api/v4/rpc"
URL_PATTERN = re.compile(r"/evento/(\d+)/funcion/(\d+)/")


def parse_url(url):
    match = URL_PATTERN.search(url)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def fetch_seat_data(event_id, funcion_id):
    payload = {
        "jsonrpc": "2.0",
        "method": "evento.tipos_boletos_comprar",
        "params": {"id": event_id, "id_funcion": funcion_id},
        "id": 1,
    }
    resp = requests.post(API_URL, json=payload, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", "Unknown API error"))
    return data["result"]


def format_date(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%A %d %B %Y, %I:%M %p")
    except (ValueError, TypeError):
        return date_str or "Unknown date"


def short_date(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%a %b %d, %I:%M %p")
    except (ValueError, TypeError):
        return date_str or "?"


def count_seats(result):
    total_physical = len(result.get("modelo", {}).get("asientos", []))
    evento = result.get("evento", {})
    event_name = evento.get("nombre", "Unknown Event")
    raw_date = evento.get("inicio", "")
    date = format_date(raw_date)
    date_short = short_date(raw_date)

    tipos = result.get("tipos_boletos", [])
    type_reports = []
    total_sellable = 0
    total_sold = 0
    total_waiting = 0

    for tipo in tipos:
        name = tipo.get("nombre", "Unknown")
        capacity = int(tipo.get("capacidad", 0))
        sold = 0
        waiting = 0

        for seat in tipo.get("asientos", []):
            if str(seat.get("ocupado")) == "1":
                sold += 1
            elif str(seat.get("esperando_pago")) == "1":
                waiting += 1

        type_reports.append({
            "name": name,
            "capacity": capacity,
            "sold": sold,
            "waiting": waiting,
            "available": capacity - sold - waiting,
        })
        total_sellable += capacity
        total_sold += sold
        total_waiting += waiting

    total_available = total_sellable - total_sold - total_waiting
    not_available = total_physical - total_sellable

    return {
        "event_name": event_name,
        "date": date,
        "date_short": date_short,
        "raw_date": raw_date,
        "total_physical": total_physical,
        "total_sellable": total_sellable,
        "total_sold": total_sold,
        "total_waiting": total_waiting,
        "total_available": total_available,
        "not_available": not_available,
        "types": type_reports,
    }


def print_report(data):
    pct = data["total_sold"] / data["total_sellable"] * 100 if data["total_sellable"] > 0 else 0
    print(f"\n  {data['event_name']} - {data['date']}")
    print(f"    Sold: {data['total_sold']}/{data['total_sellable']}  ({pct:.1f}%)    Available: {data['total_available']}")
    for t in data["types"]:
        t_pct = t["sold"] / t["capacity"] * 100 if t["capacity"] > 0 else 0
        line = f"      {t['name']:<20s}  {t['sold']}/{t['capacity']} sold ({t_pct:.1f}%)    Available: {t['available']}"
        if t["waiting"] > 0:
            line += f"    Waiting: {t['waiting']}"
        print(line)


def generate_html(all_data, grand_sold, grand_sellable, updated_at):
    grand_pct = grand_sold / grand_sellable * 100 if grand_sellable > 0 else 0
    grand_available = grand_sellable - grand_sold

    rows_html = ""
    for d in all_data:
        pct = d["total_sold"] / d["total_sellable"] * 100 if d["total_sellable"] > 0 else 0
        bar_color = "#e74c3c" if pct >= 80 else "#f39c12" if pct >= 50 else "#2ecc71"

        types_detail = ""
        for t in d["types"]:
            t_pct = t["sold"] / t["capacity"] * 100 if t["capacity"] > 0 else 0
            waiting_badge = f' <span class="badge-waiting">{t["waiting"]} waiting</span>' if t["waiting"] > 0 else ""
            types_detail += f"""
                <div class="type-row">
                    <span class="type-name">{t["name"]}</span>
                    <span class="type-stats">{t["sold"]}/{t["capacity"]} sold ({t_pct:.0f}%){waiting_badge}</span>
                    <span class="type-avail">{t["available"]} left</span>
                </div>"""

        rows_html += f"""
        <div class="card">
            <div class="card-header">
                <div class="card-date">{d["date_short"]}</div>
                <div class="card-pct">{pct:.0f}%</div>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {pct}%; background: {bar_color};"></div>
            </div>
            <div class="card-stats">
                <div class="stat">
                    <div class="stat-num">{d["total_sold"]}</div>
                    <div class="stat-label">Sold</div>
                </div>
                <div class="stat">
                    <div class="stat-num">{d["total_available"]}</div>
                    <div class="stat-label">Available</div>
                </div>
                <div class="stat">
                    <div class="stat-num">{d["total_sellable"]}</div>
                    <div class="stat-label">Total</div>
                </div>
            </div>
            <div class="types-detail">{types_detail}
            </div>
        </div>"""

    event_name = all_data[0]["event_name"] if all_data else "Theatre Report"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{event_name} - Seat Report</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f1a;
            color: #e0e0e0;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 800px; margin: 0 auto; }}
        .header {{
            text-align: center;
            padding: 30px 0 20px;
        }}
        .header h1 {{
            font-size: 2.2em;
            color: #fff;
            margin-bottom: 5px;
        }}
        .header .subtitle {{
            color: #888;
            font-size: 0.95em;
        }}
        .summary {{
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            border-radius: 16px;
            padding: 25px;
            margin: 20px 0 30px;
            display: flex;
            justify-content: space-around;
            align-items: center;
            border: 1px solid #2a2a4a;
        }}
        .summary-item {{ text-align: center; }}
        .summary-item .big {{
            font-size: 2.5em;
            font-weight: 700;
            color: #fff;
        }}
        .summary-item .big.pct {{ color: {("#e74c3c" if grand_pct >= 80 else "#f39c12" if grand_pct >= 50 else "#2ecc71")}; }}
        .summary-item .label {{
            font-size: 0.85em;
            color: #888;
            margin-top: 4px;
        }}
        .grand-bar {{
            height: 8px;
            background: #2a2a4a;
            border-radius: 4px;
            margin: 15px 0 0;
            overflow: hidden;
        }}
        .grand-bar-fill {{
            height: 100%;
            border-radius: 4px;
            background: {("#e74c3c" if grand_pct >= 80 else "#f39c12" if grand_pct >= 50 else "#2ecc71")};
            width: {grand_pct}%;
            transition: width 0.5s;
        }}
        .cards {{ display: flex; flex-direction: column; gap: 14px; }}
        .card {{
            background: #1a1a2e;
            border-radius: 12px;
            padding: 18px 20px;
            border: 1px solid #2a2a4a;
            transition: transform 0.15s;
        }}
        .card:hover {{ transform: translateY(-2px); border-color: #3a3a5a; }}
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}
        .card-date {{ font-size: 1.1em; font-weight: 600; color: #fff; }}
        .card-pct {{ font-size: 1.4em; font-weight: 700; }}
        .progress-bar {{
            height: 6px;
            background: #2a2a4a;
            border-radius: 3px;
            overflow: hidden;
            margin-bottom: 14px;
        }}
        .progress-fill {{
            height: 100%;
            border-radius: 3px;
            transition: width 0.5s;
        }}
        .card-stats {{
            display: flex;
            justify-content: space-around;
            margin-bottom: 10px;
        }}
        .stat {{ text-align: center; }}
        .stat-num {{ font-size: 1.3em; font-weight: 600; color: #fff; }}
        .stat-label {{ font-size: 0.75em; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }}
        .types-detail {{
            border-top: 1px solid #2a2a4a;
            padding-top: 10px;
            margin-top: 4px;
        }}
        .type-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 4px 0;
            font-size: 0.85em;
        }}
        .type-name {{ color: #aaa; min-width: 120px; }}
        .type-stats {{ color: #ccc; flex: 1; text-align: center; }}
        .type-avail {{ color: #888; min-width: 70px; text-align: right; }}
        .badge-waiting {{
            background: #f39c12;
            color: #000;
            padding: 1px 6px;
            border-radius: 8px;
            font-size: 0.8em;
            font-weight: 600;
        }}
        .footer {{
            text-align: center;
            padding: 30px 0 10px;
            color: #555;
            font-size: 0.8em;
        }}
        @media (max-width: 500px) {{
            body {{ padding: 12px; }}
            .header h1 {{ font-size: 1.6em; }}
            .summary {{ flex-wrap: wrap; gap: 15px; padding: 18px; }}
            .summary-item .big {{ font-size: 1.8em; }}
            .card {{ padding: 14px 16px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{event_name}</h1>
            <div class="subtitle">Seat Availability Report</div>
        </div>

        <div class="summary">
            <div class="summary-item">
                <div class="big pct">{grand_pct:.0f}%</div>
                <div class="label">Overall Sold</div>
            </div>
            <div class="summary-item">
                <div class="big">{grand_sold}</div>
                <div class="label">Tickets Sold</div>
            </div>
            <div class="summary-item">
                <div class="big">{grand_available}</div>
                <div class="label">Still Available</div>
            </div>
            <div class="summary-item">
                <div class="big">{len(all_data)}</div>
                <div class="label">Functions</div>
            </div>
        </div>
        <div class="grand-bar"><div class="grand-bar-fill"></div></div>

        <div class="cards">
            {rows_html}
        </div>

        <div class="footer">
            Last updated: {updated_at}<br>
            Data sourced from Boletopolis
        </div>
    </div>
</body>
</html>"""
    return html


def main():
    links_file = "links.txt"
    html_output = None

    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--html":
            html_output = sys.argv[i + 1] if i + 1 < len(sys.argv) else "index.html"
            i += 2
        else:
            links_file = sys.argv[i]
            i += 1

    try:
        with open(links_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"Error: '{links_file}' not found. Create it with one URL per line.")
        sys.exit(1)

    urls = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    if not urls:
        print(f"No URLs found in '{links_file}'. Add one URL per line.")
        sys.exit(1)

    print(f"Processing {len(urls)} URL(s)...\n")
    print("=" * 60)

    grand_sold = 0
    grand_sellable = 0
    all_data = []

    for url in urls:
        event_id, funcion_id = parse_url(url)
        if not event_id:
            print(f"\n  [SKIP] Invalid URL: {url}")
            continue

        try:
            result = fetch_seat_data(event_id, funcion_id)
            data = count_seats(result)
            print_report(data)
            all_data.append(data)
            grand_sold += data["total_sold"]
            grand_sellable += data["total_sellable"]
        except RuntimeError as e:
            print(f"\n  [ERROR] {url}\n    API error: {e}")
        except requests.RequestException as e:
            print(f"\n  [ERROR] {url}\n    Connection error: {e}")

    print(f"\n{'=' * 60}")
    grand_available = grand_sellable - grand_sold
    grand_pct = grand_sold / grand_sellable * 100 if grand_sellable > 0 else 0
    print(f"  TOTAL across {len(all_data)} functions:")
    print(f"    Sold:      {grand_sold}/{grand_sellable}  ({grand_pct:.1f}%)")
    print(f"    Missing:   {grand_available}")
    print(f"{'=' * 60}")

    if html_output and all_data:
        updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        html = generate_html(all_data, grand_sold, grand_sellable, updated_at)
        with open(html_output, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nHTML report saved to: {html_output}")


if __name__ == "__main__":
    main()
