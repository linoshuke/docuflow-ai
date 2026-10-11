"""Build DocuFlow AI Langflow flows and import them to a running Langflow instance."""
import copy
import json
import sys
import urllib.parse
import urllib.request
import urllib.error

import os
from typing import Any, TypedDict

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DB_FILE = os.path.join(PROJECT_ROOT, "data", "docuflow.db")
DB_URL = f"sqlite:///{DB_FILE.replace(os.sep, '/')}"

BASE = "http://127.0.0.1:7860"
USER, PASS = "langflow", "langflow"

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "openai/gpt-oss-120b"

EXTRACTION_SYSTEM_PROMPT = (
    "Kamu mengekstrak data dokumen bisnis Indonesia (invoice, kwitansi, faktur, formulir) "
    "menjadi JSON terstruktur sesuai skema yang diberikan. Aturan penting: "
    "(1) Ubah semua tanggal seperti '12 Agustus 2026', '03/08/2026', atau '3 Agu 2026' menjadi format YYYY-MM-DD. "
    "(2) Ubah nilai uang seperti 'Rp 10.323.000' atau 'Rp4.000.000' menjadi angka biasa tanpa titik/koma (misal 10323000). "
    "(3) doc_type harus salah satu dari: invoice, receipt, quotation, purchase_order, form, other. "
    "(4) currency gunakan kode ISO 4217, misalnya IDR. "
    "(5) Ekstrak seluruh rincian item barang/jasa ke dalam field 'items' sebagai JSON array string yang memuat objek: "
    "[{\"item_name\": \"...\", \"quantity\": 1, \"unit_price\": 1000, \"total_price\": 1000}]. "
    "(6) Jika sebuah field tidak ditemukan di dokumen, isi null. Jangan pernah mengarang data yang tidak ada di dokumen. "
    "Kembalikan SEMUA objek dokumen yang ditemukan."
)

SCHEMA_ROWS = [
    {"description": "Jenis dokumen: invoice, receipt, quotation, purchase_order, form, atau other",
     "multiple": False, "name": "doc_type", "type": "str"},
    {"description": "Nama perusahaan/pemasok penerbit dokumen",
     "multiple": False, "name": "vendor", "type": "str"},
    {"description": "Nomor dokumen, misal nomor invoice atau nomor kwitansi",
     "multiple": False, "name": "document_number", "type": "str"},
    {"description": "Tanggal dokumen dalam format YYYY-MM-DD",
     "multiple": False, "name": "document_date", "type": "str"},
    {"description": "Ringkasan isi/keperluan dokumen",
     "multiple": False, "name": "description", "type": "str"},
    {"description": "Nilai subtotal sebelum pajak dalam angka",
     "multiple": False, "name": "subtotal", "type": "float"},
    {"description": "Nilai pajak (PPN/VAT) dalam angka",
     "multiple": False, "name": "tax", "type": "float"},
    {"description": "Total akhir tagihan dalam angka",
     "multiple": False, "name": "total_amount", "type": "float"},
    {"description": "Kode mata uang, misal IDR",
     "multiple": False, "name": "currency", "type": "str"},
    {"description": "Kategori transaksi, misal Pembelian Sparepart",
     "multiple": False, "name": "category", "type": "str"},
    {"description": "Daftar rincian barang/jasa dalam format JSON array yang berisi item_name, quantity, unit_price, total_price",
     "multiple": False, "name": "items", "type": "str"},
]

SQL_GEN_TEMPLATE = """Kamu adalah ahli database SQLite. Berikut skema tabel DocuFlow AI:

CREATE TABLE documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_type TEXT, vendor TEXT, document_number TEXT,
  document_date TEXT, description TEXT,
  subtotal REAL, tax REAL, total_amount REAL,
  currency TEXT, category TEXT,
  warnings TEXT, raw_json TEXT,
  created_at TEXT
);

CREATE TABLE document_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER,
  item_name TEXT,
  quantity REAL,
  unit_price REAL,
  total_price REAL,
  created_at TEXT,
  FOREIGN KEY (document_id) REFERENCES documents (id)
);

Pertanyaan pengguna: {user_question}

Tulis SATU query SQLite SELECT yang menjawab pertanyaan tersebut.
ATURAN WAJIB:
- Jika pertanyaan menanyakan rincian barang, kuantitas, harga satuan, atau pembelian spesifik, gunakan JOIN antara documents dan document_items (ON documents.id = document_items.document_id).
- Kolom document_date berformat teks YYYY-MM-DD; untuk filter bulan gunakan strftime('%Y-%m', document_date) = 'YYYY-MM' atau LIKE 'YYYY-MM%'.
- Untuk total pengeluaran gunakan SUM(total_amount) dari tabel documents.
- Untuk pencarian teks gunakan LIKE '%kata%' dengan case-insensitive.
- Keluarkan HANYA satu query SQL, tanpa penjelasan, tanpa blok markdown, tanpa titik koma di akhir."""

ANSWER_TEMPLATE = """Pengguna bertanya: {user_question}

Query SQL yang dijalankan pada database:
{sql_query}

Hasil query:
{query_result}

Jawab pertanyaan pengguna dalam Bahasa Indonesia yang ringkas dan mudah dipahami hanya berdasarkan hasil query di atas.
Format angka uang menjadi tampilan rupiah yang rapi, contoh: Rp10.323.000.
Jika hasil query kosong, sampaikan bahwa belum ada data yang cocok di database."""


def api(path, payload=None, token=None, method=None):
    url = BASE + path
    headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method=method or ("POST" if data else "GET"))
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read()
        if raw[:2] == b"\x1f\x8b":
            import gzip
            raw = gzip.decompress(raw)
        body = raw.decode("utf-8")
    return json.loads(body) if body else None


def login():
    data = urllib.parse.urlencode({"username": USER, "password": PASS}).encode()
    req = urllib.request.Request(BASE + "/api/v1/login", data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())["access_token"]


def get_components(token):
    return api("/api/v1/all", token=token)


def find_comp(components, type_name):
    for cat in components.values():
        if isinstance(cat, dict) and type_name in cat:
            return cat[type_name]
    raise KeyError("Komponen tidak ditemukan: " + type_name)


def hstr(obj, compact=False):
    s = json.dumps(obj, separators=(",", ":") if compact else (", ", ": "))
    return s.replace('"', "o")


def make_input_field(base, **over):
    field = {
        "_input_type": base.get("_input_type", "MessageTextInput"),
        "advanced": base.get("advanced", False),
        "display_name": base.get("display_name", ""),
        "dynamic": False,
        "info": base.get("info", ""),
        "list": False,
        "load_from_db": False,
        "name": base["name"],
        "placeholder": "",
        "required": base.get("required", False),
        "show": True,
        "title_case": False,
        "trace_as_metadata": True,
        "type": base.get("type", "str"),
        "value": base.get("value", ""),
    }
    if base.get("input_types") is not None:
        field["input_types"] = base["input_types"]
    if field["_input_type"] == "HandleInput":
        field.pop("placeholder", None)
        field.pop("trace_as_metadata", None)
    field.update({k: v for k, v in over.items() if v is not None})
    return field


def make_node(node_id, comp_type, comp_meta, x, y, *, display_name=None,
              value_overrides=None, template_extra=None, outputs_override=None,
              base_classes_override=None, code_value=None):
    meta = comp_meta or {}
    template = copy.deepcopy(meta.get("template", {}))
    template.setdefault("_type", "Component")
    for key, val in (value_overrides or {}).items():
        if key in template and isinstance(template[key], dict):
            template[key]["value"] = val
        elif key in template:
            template[key] = val
    if code_value is not None:
        template["code"] = make_input_field(
            {"name": "code", "type": "code", "required": True, "advanced": True,
             "multiline": True, "info": ""},
            _input_type="CodeInput", value=code_value,
        )
        template["code"]["fileTypes"] = []
        template["code"]["file_path"] = ""
        template["code"]["dynamic"] = True
        template["code"]["password"] = False
    if template_extra:
        for key, field in template_extra.items():
            template[key] = field

    outputs = outputs_override or copy.deepcopy(meta.get("outputs", []))
    base_classes = base_classes_override or sorted({
        t for o in outputs for t in o.get("types", [])
    }) or ["Data"]
    display = display_name or meta.get("display_name", comp_type)
    node = {
        "id": node_id,
        "type": "genericNode",
        "position": {"x": x, "y": y},
        "positionAbsolute": {"x": x, "y": y},
        "dragging": False,
        "selected": False,
        "measured": {"height": 250, "width": 320},
        "data": {
            "id": node_id,
            "type": comp_type,
            "op_version": "main",
            "showOutput": True,
            "description": meta.get("description", ""),
            "display_name": display,
            "node": {
                "base_classes": base_classes,
                "beta": bool(meta.get("beta", False)),
                "conditional_paths": [],
                "custom_fields": {},
                "description": meta.get("description", ""),
                "display_name": display,
                "documentation": meta.get("documentation", ""),
                "edited": False,
                "field_order": meta.get("field_order", [k for k in template
                                                        if k not in ("_type", "code")]),
                "frozen": False,
                "full_name": meta.get("full_name"),
                "icon": meta.get("icon", "Langflow"),
                "legacy": False,
                "lf_version": "1.9.2",
                "output_types": [],
                "outputs": outputs,
                "pinned": False,
                "template": template,
            },
            "selected_output": outputs[0]["name"] if outputs else "",
        },
    }
    if not node["data"]["node"]["full_name"]:
        del node["data"]["node"]["full_name"]
    return node


def make_edge(sid, scomp, oname, otypes, tid, tcomp, fname, itypes, ttype):
    sh = {"dataType": scomp, "id": sid, "name": oname, "output_types": otypes}
    th = {"fieldName": fname, "id": tid, "inputTypes": itypes, "type": ttype}
    return {
        "id": "reactflow__edge-" + sid + hstr(sh, compact=True) + "-" + tid + hstr(th, compact=True),
        "source": sid,
        "target": tid,
        "sourceHandle": hstr(sh),
        "targetHandle": hstr(th),
        "data": {"sourceHandle": sh, "targetHandle": th},
        "selected": False,
        "animated": False,
        "className": "",
    }


def make_llm_node(comps, node_id, x, y):
    openai_c = find_comp(comps, "OpenAIModel")
    return make_node(node_id, "OpenAIModel", openai_c, x, y, value_overrides={
        "model_name": GROQ_MODEL,
        "openai_api_base": GROQ_BASE_URL,
        "api_key": GROQ_API_KEY,
        "temperature": 0.1,
        "max_tokens": 2000,
        "max_retries": 4,
    })


WRITER_PATH = os.path.join(PROJECT_ROOT, "components", "sqlite_writer.py")
WRITER_CODE = open(WRITER_PATH, encoding="utf-8").read()

GATEWAY_PATH = os.path.join(PROJECT_ROOT, "components", "input_gateway.py")
GATEWAY_CODE = open(GATEWAY_PATH, encoding="utf-8").read()

SANITIZER_CODE = '''import re

from lfx.custom.custom_component.component import Component
from lfx.io import HandleInput, Output
from lfx.schema.message import Message


class SQLQuerySanitizer(Component):
    display_name = "DocuFlow SQL Guard"
    description = "Membersihkan keluaran LLM menjadi satu query SELECT SQLite yang aman."
    icon = "shield-check"
    name = "SQLQuerySanitizer"

    inputs = [
        HandleInput(
            name="sql_text",
            display_name="SQL Mentah dari Model",
            input_types=["Message"],
            required=True,
        ),
    ]

    outputs = [
        Output(display_name="SQL Bersih", name="clean_sql", method="clean"),
    ]

    def clean(self) -> Message:
        raw = getattr(self.sql_text, "text", None) or str(self.sql_text)
        s = raw.strip()
        s = re.sub(r"^```[a-zA-Z]*\\s*", "", s)
        s = re.sub(r"```\\s*$", "", s)
        s = s.strip().strip(";").strip()
        m = re.search(r"\\b(?:SELECT|WITH)\\b.*", s, flags=re.IGNORECASE | re.DOTALL)
        s = m.group(0).strip().rstrip(";").strip() if m else ""
        if not s.lower().startswith(("select", "with")):
            self.status = "DITOLAK: model tidak menghasilkan query SELECT."
            return Message(text="")
        if re.search(r"\\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|PRAGMA)\\b", s.upper()):
            self.status = "DITOLAK: query mengandung perintah non-SELECT."
            return Message(text="")
        s = s.replace(";", "")
        self.status = s
        return Message(text=s)
'''


def build_field(name, input_types, ftype="other", required=True, display=None):
    return {
        "_input_type": "HandleInput",
        "advanced": False,
        "display_name": display or name.replace("_", " ").title(),
        "dynamic": False,
        "info": "",
        "input_types": input_types,
        "list": False,
        "load_from_db": False,
        "name": name,
        "override_skip": False,
        "placeholder": "",
        "required": required,
        "show": True,
        "title_case": False,
        "trace_as_input": True,
        "tool_mode": False,
        "type": ftype,
        "value": "",
    }


def message_field(name, value="", display=None, advanced=False, multiline=True, required=False):
    return {
        "_input_type": "MultilineInput" if multiline else "MessageTextInput",
        "advanced": advanced,
        "display_name": display or name.replace("_", " ").title(),
        "dynamic": False,
        "info": "",
        "input_types": ["Message"],
        "list": False,
        "load_from_db": False,
        "multiline": multiline,
        "name": name,
        "placeholder": "",
        "required": required,
        "show": True,
        "title_case": False,
        "tool_mode": False,
        "trace_as_input": True,
        "trace_as_metadata": True,
        "type": "str",
        "value": value,
    }


def prompt_dynamic_field(display):
    return {
        "_input_type": "HandleInput",
        "advanced": False,
        "display_name": display,
        "dynamic": False,
        "info": "",
        "input_types": ["Text", "Message", "DataFrame", "Data"],
        "list": False,
        "load_from_db": False,
        "name": display,
        "required": False,
        "show": True,
        "title_case": False,
        "trace_as_input": True,
        "type": "other",
        "value": "",
    }


def build_ingestion(comps):
    file_c = find_comp(comps, "File")
    chatin_c = find_comp(comps, "ChatInput")
    so_c = find_comp(comps, "StructuredOutput")
    chatout_c = find_comp(comps, "ChatOutput")

    n_file = make_node("File-docuflow", "File", file_c, 40, 100,
                       display_name="Upload Dokumen (PDF/TXT)")
    n_chatin = make_node("ChatInput-ingest", "ChatInput", chatin_c, 40, 360,
                         display_name="Input Teks Nota / Chat Langsung")

    gateway_outputs = [{
        "allows_loop": False, "cache": True, "display_name": "Teks Siap Ekstraksi",
        "group_outputs": False, "method": "process_input", "name": "output_text",
        "selected": "Message", "tool_mode": True, "types": ["Message"],
        "value": "__UNDEFINED__",
    }]
    n_gateway = make_node(
        "Gateway-ingest", "DocuFlowInputGateway", {}, 420, 180,
        display_name="DocuFlow Ingestion Gateway",
        outputs_override=gateway_outputs,
        base_classes_override=["Message"],
        code_value=GATEWAY_CODE,
        template_extra={
            "file_message": build_field("file_message", ["Message", "Data", "Text"],
                                        display="File Dokumen (PDF/TXT)", required=False),
            "chat_message": build_field("chat_message", ["Message", "Text"],
                                        display="Teks Chat / Nota Langsung", required=False),
            "fallback_text": message_field("fallback_text", "", "Teks Cadangan", advanced=True),
        },
    )

    n_wx1 = make_llm_node(comps, "LLM-extract-1", 420, 520)

    so_template_extra = {
        "system_prompt": message_field("system_prompt", EXTRACTION_SYSTEM_PROMPT,
                                       "System Prompt"),
        "schema_name": message_field("schema_name", "docuflow_extraction", "Schema Name"),
    }
    n_so = make_node("StructuredOutput-extract", "StructuredOutput", so_c, 780, 180,
                     template_extra=so_template_extra)
    n_so["data"]["node"]["template"]["output_schema"]["value"] = copy.deepcopy(SCHEMA_ROWS)

    writer_outputs = [{
        "allows_loop": False, "cache": True, "display_name": "Status Penyimpanan",
        "group_outputs": False, "method": "write_rows", "name": "status_message",
        "selected": "Message", "tool_mode": True, "types": ["Message"],
        "value": "__UNDEFINED__",
    }]
    n_writer = make_node(
        "SQLiteWriter-save", "SQLiteDocuFlowWriter", {}, 1140, 180,
        display_name="DocuFlow SQLite Writer",
        outputs_override=writer_outputs,
        base_classes_override=["Message"],
        code_value=WRITER_CODE,
        template_extra={
            "rows": build_field("rows", ["DataFrame", "Table", "Data", "JSON"],
                                display="Hasil Ekstraksi"),
            "db_path": message_field("db_path",
                                     DB_FILE,
                                     "Path Database SQLite", advanced=True),
        },
    )
    n_writer["data"]["node"]["template"]["db_path"]["multiline"] = False
    n_writer["data"]["node"]["template"]["db_path"]["_input_type"] = "MessageTextInput"

    n_out = make_node("ChatOutput-ingest", "ChatOutput", chatout_c, 1500, 190)

    nodes = [n_file, n_chatin, n_gateway, n_wx1, n_so, n_writer, n_out]
    edges = [
        make_edge("File-docuflow", "File", "message", ["Message"],
                  "Gateway-ingest", "DocuFlowInputGateway", "file_message",
                  ["Message", "Data", "Text"], "other"),
        make_edge("ChatInput-ingest", "ChatInput", "message", ["Message"],
                  "Gateway-ingest", "DocuFlowInputGateway", "chat_message",
                  ["Message", "Text"], "other"),
        make_edge("Gateway-ingest", "DocuFlowInputGateway", "output_text", ["Message"],
                  "StructuredOutput-extract", "StructuredOutput", "input_value",
                  ["Message", "Text"], "str"),
        make_edge("LLM-extract-1", "OpenAIModel", "model_output", ["LanguageModel"],
                  "StructuredOutput-extract", "StructuredOutput", "model",
                  ["LanguageModel"], "other"),
        make_edge("StructuredOutput-extract", "StructuredOutput", "dataframe_output", ["Table"],
                  "SQLiteWriter-save", "SQLiteDocuFlowWriter", "rows",
                  ["DataFrame", "Table", "Data", "JSON"], "other"),
        make_edge("SQLiteWriter-save", "SQLiteDocuFlowWriter", "status_message", ["Message"],
                  "ChatOutput-ingest", "ChatOutput", "input_value", ["Message", "Text"], "str"),
    ]
    return nodes, edges


def build_query(comps):
    chatin_c = find_comp(comps, "ChatInput")
    chatout_c = find_comp(comps, "ChatOutput")
    prompt_c = find_comp(comps, "Prompt Template")
    sql_c = find_comp(comps, "SQLComponent")

    n_in = make_node("ChatInput-query", "ChatInput", chatin_c, 40, 260)

    n_p1 = make_node("Prompt-sqlgen", "Prompt", prompt_c, 380, 240,
                     template_extra={
                         "user_question": prompt_dynamic_field("user_question"),
                     })
    n_p1["data"]["node"]["template"]["template"]["value"] = SQL_GEN_TEMPLATE

    n_wx1 = make_llm_node(comps, "LLM-sqlgen-2", 700, 220)

    guard_outputs = [{
        "allows_loop": False, "cache": True, "display_name": "SQL Bersih",
        "group_outputs": False, "method": "clean", "name": "clean_sql",
        "selected": "Message", "tool_mode": True, "types": ["Message"],
        "value": "__UNDEFINED__",
    }]
    n_guard = make_node(
        "SQLGuard-clean", "SQLQuerySanitizer", {}, 1010, 230,
        display_name="DocuFlow SQL Guard",
        outputs_override=guard_outputs,
        base_classes_override=["Message"],
        code_value=SANITIZER_CODE,
        template_extra={
            "sql_text": build_field("sql_text", ["Message"], display="SQL Mentah dari Model"),
        },
    )

    n_sql = make_node("SQLDatabase-docuflow", "SQLComponent", sql_c, 1320, 230,
                      value_overrides={"database_url": DB_URL})

    n_p2 = make_node("Prompt-answer", "Prompt", prompt_c, 40, 600,
                     template_extra={
                         "user_question": prompt_dynamic_field("user_question"),
                         "sql_query": prompt_dynamic_field("sql_query"),
                         "query_result": prompt_dynamic_field("query_result"),
                     })
    n_p2["data"]["node"]["template"]["template"]["value"] = ANSWER_TEMPLATE

    n_wx2 = make_llm_node(comps, "LLM-answer-3", 400, 620)

    n_out = make_node("ChatOutput-answer", "ChatOutput", chatout_c, 720, 620)

    nodes = [n_in, n_p1, n_wx1, n_guard, n_sql, n_p2, n_wx2, n_out]
    edges = [
        make_edge("ChatInput-query", "ChatInput", "message", ["Message"],
                  "Prompt-sqlgen", "Prompt", "user_question",
                  ["Text", "Message", "DataFrame", "Data"], "other"),
        make_edge("Prompt-sqlgen", "Prompt", "prompt", ["Message"],
                  "LLM-sqlgen-2", "OpenAIModel", "input_value",
                  ["Message", "Text"], "str"),
        make_edge("LLM-sqlgen-2", "OpenAIModel", "text_output", ["Message"],
                  "SQLGuard-clean", "SQLQuerySanitizer", "sql_text", ["Message"], "other"),
        make_edge("SQLGuard-clean", "SQLQuerySanitizer", "clean_sql", ["Message"],
                  "SQLDatabase-docuflow", "SQLComponent", "query", ["Message"], "str"),
        make_edge("SQLDatabase-docuflow", "SQLComponent", "run_sql_query", ["DataFrame"],
                  "Prompt-answer", "Prompt", "query_result",
                  ["Text", "Message", "DataFrame", "Data"], "other"),
        make_edge("ChatInput-query", "ChatInput", "message", ["Message"],
                  "Prompt-answer", "Prompt", "user_question",
                  ["Text", "Message", "DataFrame", "Data"], "other"),
        make_edge("SQLGuard-clean", "SQLQuerySanitizer", "clean_sql", ["Message"],
                  "Prompt-answer", "Prompt", "sql_query",
                  ["Text", "Message", "DataFrame", "Data"], "other"),
        make_edge("Prompt-answer", "Prompt", "prompt", ["Message"],
                  "LLM-answer-3", "OpenAIModel", "input_value",
                  ["Message", "Text"], "str"),
        make_edge("LLM-answer-3", "OpenAIModel", "text_output", ["Message"],
                  "ChatOutput-answer", "ChatOutput", "input_value",
                  ["Message", "Text"], "str"),
    ]
    return nodes, edges


def build_unified(comps):
    ingest_nodes, ingest_edges = build_ingestion(comps)
    query_nodes, query_edges = build_query(comps)

    for n in ingest_nodes:
        dname = n["data"]["node"]["display_name"]
        if not dname.startswith("[Ingestion]"):
            n["data"]["node"]["display_name"] = f"[Ingestion] {dname}"
            n["data"]["display_name"] = f"[Ingestion] {dname}"

    pos_map = {
        "ChatInput-query": (40, 800),
        "Prompt-sqlgen": (400, 800),
        "LLM-sqlgen-2": (760, 800),
        "SQLGuard-clean": (1120, 800),
        "SQLDatabase-docuflow": (1480, 800),
        "Prompt-answer": (580, 1150),
        "LLM-answer-3": (940, 1150),
        "ChatOutput-answer": (1300, 1150),
    }

    for n in query_nodes:
        nid = n["id"]
        if nid in pos_map:
            n["position"] = {"x": pos_map[nid][0], "y": pos_map[nid][1]}
            n["positionAbsolute"] = {"x": pos_map[nid][0], "y": pos_map[nid][1]}
        dname = n["data"]["node"]["display_name"]
        if not dname.startswith("[Query]"):
            n["data"]["node"]["display_name"] = f"[Query] {dname}"
            n["data"]["display_name"] = f"[Query] {dname}"

    unified_nodes = ingest_nodes + query_nodes
    unified_edges = ingest_edges + query_edges
    return unified_nodes, unified_edges


class FlowConfig(TypedDict):
    name: str
    desc: str
    data: tuple[list[dict[str, Any]], list[dict[str, Any]]]
    files: list[str]
    endpoint: str
    icon_bg: str


def main():
    print("[1/5] Login ke Langflow...")
    token = login()
    print("[2/5] Mengambil registry komponen...")
    comps = get_components(token)

    print("[3/5] Menghapus flow DocuFlow lama (jika ada)...")
    existing = api("/api/v1/flows/", token=token) or []
    for f in existing:
        if isinstance(f, dict) and f.get("name", "").startswith("DocuFlow"):
            flow_id = f.get("id")
            if flow_id:
                req = urllib.request.Request(
                    BASE + "/api/v1/flows/" + str(flow_id),
                    headers={"Authorization": "Bearer " + token},
                    method="DELETE")
                urllib.request.urlopen(req, timeout=30)
                print(f"      Dihapus: {f.get('name')}")

    flow_configs: list[FlowConfig] = [
        {
            "name": "DocuFlow AI - Unified System",
            "desc": "Sistem Terpadu DocuFlow AI dalam 1 Flow: Ingestion Dokumen (Dual-Input) + Query Database Terintegrasi",
            "data": build_unified(comps),
            "files": ["Docuflow - Unified System.json", "docuflow_unified.json"],
            "endpoint": "docuflow-unified",
            "icon_bg": "#3b82f6",
        },
        {
            "name": "DocuFlow 1 - Ingestion Dokumen",
            "desc": "Upload invoice/kwitansi -> ekstraksi LLM -> validasi -> simpan ke SQLite",
            "data": build_ingestion(comps),
            "files": ["Docuflow 1 - Ingestion Dokumen.json", "docuflow_1.json"],
            "endpoint": "docuflow-ingestion",
            "icon_bg": "#dbeafe",
        },
        {
            "name": "DocuFlow 2 - Query Database",
            "desc": "Tanya-jawab natural language ke database dokumen",
            "data": build_query(comps),
            "files": ["Docuflow Query - Chat Database.json", "docuflow_2.json"],
            "endpoint": "docuflow-query",
            "icon_bg": "#dbeafe",
        },
    ]

    for item in flow_configs:
        nodes, edges = item["data"]
        flow_json = {
            "name": item["name"],
            "description": item["desc"],
            "icon": "workflow",
            "icon_bg_color": item["icon_bg"],
            "is_component": False,
            "data": {
                "nodes": nodes,
                "edges": edges,
                "viewport": {"zoom": 0.55, "x": 20, "y": 20},
            },
        }

        for fname in item["files"]:
            path = os.path.join(PROJECT_ROOT, "flows", fname)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(flow_json, f, ensure_ascii=False, indent=2)
            print(f"[4/5] Disimpan file: {fname}")

        try:
            created = api("/api/v1/flows/", flow_json, token=token)
            if not created or not isinstance(created, dict):
                raise RuntimeError("API tidak mengembalikan objek flow yang valid")

            print(f"      Import OK -> id={created['id']} name={created['name']}")
            patch = {"endpoint_name": item["endpoint"]}
            req = urllib.request.Request(
                BASE + "/api/v1/flows/" + str(created["id"]),
                data=json.dumps(patch).encode(),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + token},
                method="PATCH")
            urllib.request.urlopen(req, timeout=30)
            print(f"      endpoint_name -> {patch['endpoint_name']}")
        except Exception as exc:
            print(f"      Import GAGAL untuk {item['name']}: {exc}")

    print("[5/5] Selesai. Seluruh flow (termasuk Unified Flow 1-file) berhasil dibangun dan di-import!")


if __name__ == "__main__":
    main()