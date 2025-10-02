# app.py
import re
import os
import io
from flask import Flask, request, jsonify, render_template, send_file
import pandas as pd
import oracledb
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, template_folder="templates")

# ------------------ CONEXÃO ORACLE ------------------
def get_connection():
    user = os.getenv("ORACLE_USER", "SANKHYA")
    password = os.getenv("ORACLE_PASSWORD", "laranja")
    host = os.getenv("ORACLE_HOST", "MULTFER.DDNS.ME")
    port = int(os.getenv("ORACLE_PORT", 1521))
    service = os.getenv("ORACLE_SERVICE", "PROD")
    dsn = oracledb.makedsn(host, port, service_name=service)
    return oracledb.connect(user=user, password=password, dsn=dsn)

# ------------------ TRANSFORMAÇÃO HTML ------------------
def transform_html_in_text(full_text: str) -> str:
    # Regra 1: cabeçalho/estilo
    rule1 = (
        "'<html> <style>table{}' || 'th,td{border:1px solid #ccc;padding:6px}' || "
        "'.center{text-align:center};' || '</style>' || '<h2 style=\"font-size:18px ; color:orange ; font-weight: bold\"> '"
    )
    full_text = re.sub(r"(?i)<html>\s*<h[^>]*>", rule1, full_text)

    # Regra 2: tabela
    rule2 = "'<table style=\"font-size:12px;border-collapse:collapse;width:100%\">'"
    full_text = re.sub(r"(?i)<table[^>]*>", rule2, full_text)

    # Regras 3 & 4: células <td>
    rule3 = "'<td class=\"center\" style=\"background:#f2f2f2;font-weight: bold;\"><center>'"
    rule4 = "'<td class=\"center\" style=\"font-weight: normal;\"><center>'"

    def td_replacer(match):
        inner = match.group(1)
        if "||" in inner:
            open_tag = rule4
        else:
            open_tag = rule3
        return f"{open_tag} || {inner} || '</center></td>'"

    full_text = re.sub(r"(?is)<td[^>]*>(.*?)</td>", td_replacer, full_text)
    return full_text

# ------------------ BUSCA DE PROCEDURE ------------------
def fetch_procedure_source(conn, name: str):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT TEXT
        FROM ALL_SOURCE
        WHERE NAME = :name
        ORDER BY LINE
    """, {"name": name.upper()})
    lines = [r[0] for r in cursor.fetchall()]
    return "".join(lines) if lines else None

# ------------------ ENDPOINTS ------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload_excel", methods=["POST"])
def upload_excel():
    if "file" not in request.files:
        return jsonify({"error": "Nenhum arquivo enviado como 'file'"}), 400
    f = request.files["file"]
    try:
        df = pd.read_excel(io.BytesIO(f.read()), engine="openpyxl")
    except Exception as e:
        return jsonify({"error": "Falha ao ler Excel: " + str(e)}), 400

    if "NAME" not in df.columns:
        found = [c for c in df.columns if str(c).strip().upper() == "NAME"]
        if not found:
            return jsonify({"error": "Coluna 'NAME' não encontrada"}), 400
        col = found[0]
    else:
        col = "NAME"

    names = df[col].dropna().astype(str).str.strip().unique().tolist()
    names = [n for n in names if n]
    return jsonify({"names": names})

@app.route("/fetch_procedure", methods=["POST"])
def fetch_procedure():
    data = request.get_json(force=True)
    if not data or "name" not in data:
        return jsonify({"error": "Envie JSON com campo 'name'"}), 400
    name = data["name"].strip()
    conn = get_connection()
    try:
        original = fetch_procedure_source(conn, name)
        if not original:
            return jsonify({"error": f"Procedure {name} não encontrada."}), 404
        transformed = transform_html_in_text(original)
        return jsonify({
            "name": name,
            "original": original,
            "transformed": transformed
        })
    finally:
        conn.close()

@app.route("/save_procedure", methods=["POST"])
def save_procedure():
    data = request.get_json(force=True)
    if not data or "name" not in data or "new_text" not in data:
        return jsonify({"error": "Envie JSON com 'name' e 'new_text'"}), 400
    name = data["name"].strip()
    new_text = data["new_text"]
    conn = get_connection()
    try:
        old_source = fetch_procedure_source(conn, name) or ""
        ddl = f"CREATE OR REPLACE PROCEDURE {name.upper()} AS\n{new_text}\n"
        cursor = conn.cursor()
        cursor.execute(ddl)
        conn.commit()
        return jsonify({"status": "ok", "message": f"Procedure {name} atualizada com sucesso.", "old_source": old_source})
    except Exception as e:
        return jsonify({"error": "Falha ao salvar: " + str(e)}), 500
    finally:
        conn.close()

@app.route("/download_backup", methods=["POST"])
def download_backup():
    data = request.get_json(force=True)
    name = data.get("name")
    if not name:
        return jsonify({"error": "Informe 'name'"}), 400
    conn = get_connection()
    source = fetch_procedure_source(conn, name)
    conn.close()
    if not source:
        return jsonify({"error": f"Nenhum source encontrado para {name}"}), 404
    return send_file(io.BytesIO(source.encode("utf-8")),
                     mimetype="text/plain",
                     as_attachment=True,
                     download_name=f"{name}.sql")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
