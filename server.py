# server.py
from flask import Flask, render_template, request, jsonify, make_response, Response
import requests
import socket
import os
import matplotlib.pyplot as plt
import base64
from io import BytesIO
import weasyprint
from datetime import datetime
import json

app = Flask(__name__, static_folder='static', template_folder='templates')

DOMAINS_FILE = "domains.txt"
RESULTS_FILE = "results.txt"


def check_domain(domain):
    """Check if domain is live and get its IP"""
    d = domain.strip().lower()
    d = d.replace("http://", "").replace("https://", "").replace("www.", "")
    d = d.split("/")[0].split("#")[0].split("?")[0].strip()
    if not d or '.' not in d:
        return {"domain": domain, "ip": "N/A", "status": "INVALID"}

    host = d
    ip = "N/A"
    status = "DOWN"

    try:
        ip = socket.gethostbyname(host)
        # Try HTTPS
        try:
            requests.get(f"https://{host}", timeout=8, allow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0"
            })
            status = "LIVE"
        except:
            # Try HTTP
            requests.get(f"http://{host}", timeout=8, allow_redirects=True)
            status = "LIVE"
    except:
        pass

    return {"domain": d, "ip": ip, "status": status}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/load")
def load_domains():
    """Load clean domains from domains.txt"""
    if not os.path.exists(DOMAINS_FILE):
        return jsonify([])
    domains = []
    with open(DOMAINS_FILE, 'r') as f:
        for line in f:
            d = line.strip().lower()
            d = d.replace("http://", "").replace("https://", "").replace("www.", "")
            d = d.split("/")[0].split("#")[0].split("?")[0].strip()
            if d and '.' in d:
                domains.append(d)
    return jsonify(domains)


@app.route("/api/save", methods=["POST"])
def save_domains():
    """Save only clean domains to domains.txt"""
    data = request.get_json()
    domains = data.get("domains", [])
    cleaned = []
    for d in domains:
        d = str(d).strip().lower()
        d = d.replace("http://", "").replace("https://", "").replace("www.", "")
        d = d.split("/")[0].split("#")[0].split("?")[0].strip()
        if d and '.' in d and d not in cleaned:
            cleaned.append(d)

    with open(DOMAINS_FILE, "w") as f:
        f.write("\n".join(cleaned))

    return jsonify({"saved": len(cleaned)})


@app.route("/api/check", methods=["POST"])
def check_domains():
    """Stream domain check results using proper format"""
    data = request.get_json()
    domains = data.get("domains", [])
    
    if not domains:
        def gen():
            yield "data: " + json.dumps({"error": "No domains provided"}) + "\n\n"
        return Response(gen(), content_type="text/plain")

    def event_stream():
        results = []
        for domain in domains:
            result = check_domain(domain)
            results.append(result)
            yield "data: " + json.dumps({
                "type": "result",
                "data": result,
                "progress": {
                    "completed": len(results),
                    "total": len(domains)
                }
            }) + "\n\n"

        # Save final results
        with open(RESULTS_FILE, "w") as f:
            f.write(f"{'Domain':<30} {'IP':<20} {'Status':<15}\n")
            f.write("-" * 70 + "\n")
            for r in results:
                f.write(f"{r['domain']:<30} {r['ip']:<20} {r['status']:<15}\n")

        yield "data: " + json.dumps({
            "type": "complete",
            "message": f"All {len(results)} domains checked."
        }) + "\n\n"

    return Response(event_stream(), content_type="text/plain")


@app.route("/api/check-single", methods=["POST"])
def check_single():
    """Check one domain manually"""
    data = request.get_json()
    domain = data.get("domain", "").strip()
    if not domain:
        return jsonify({"error": "No domain provided"}), 400
    result = check_domain(domain)
    return jsonify(result)


def generate_chart(results):
    """Generate a pie chart and return as base64 string"""
    status_count = {"LIVE": 0, "DOWN": 0, "INVALID": 0}
    for r in results:
        status = r["status"]
        if status in status_count:
            status_count[status] += 1
        else:
            status_count["DOWN"] += 1

    labels = [k for k, v in status_count.items() if v > 0]
    sizes = [v for v in status_count.values() if v > 0]
    colors = ['#4CAF50', '#F44336', '#FFC107']

    plt.figure(figsize=(6, 4))
    plt.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%', startangle=90)
    plt.title("Domain Status Distribution", fontsize=14, fontweight='bold')
    plt.tight_layout()

    img = BytesIO()
    plt.savefig(img, format='png', dpi=150, bbox_inches='tight')
    img.seek(0)
    chart_url = base64.b64encode(img.read()).decode()
    plt.close()

    return chart_url


@app.route("/report")
def report():
    """Display a visual report with chart and results"""
    if not os.path.exists(RESULTS_FILE):
        return "<h3>No results found. Please check domains first.</h3>", 404

    results = []
    with open(RESULTS_FILE, "r") as f:
        lines = f.readlines()[2:]
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 3:
                ip = parts[1] if len(parts) > 1 and '.' in parts[1] else "N/A"
                domain = parts[0]
                status = parts[-1]
                results.append({"domain": domain, "ip": ip, "status": status})

    chart_image = generate_chart(results)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return render_template("report.html", results=results, chart_image=chart_image, timestamp=timestamp)


@app.route("/report/pdf")
def report_pdf():
    """Generate and download PDF report"""
    if not os.path.exists(RESULTS_FILE):
        return "No results to export.", 404

    results = []
    with open(RESULTS_FILE, "r") as f:
        lines = f.readlines()[2:]
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 3:
                ip = parts[1] if len(parts) > 1 and '.' in parts[1] else "N/A"
                domain = parts[0]
                status = parts[-1]
                results.append({"domain": domain, "ip": ip, "status": status})

    chart_image = generate_chart(results)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = render_template("report.html", results=results, chart_image=chart_image, timestamp=timestamp)

    pdf = weasyprint.HTML(string=html).write_pdf()

    response = make_response(pdf)
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename=domain_report_{int(datetime.now().timestamp())}.pdf"

    return response


if __name__ == "__main__":
    print("🌍 Starting server at http://localhost:5000")
    print("💡 Open your browser and go to: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
