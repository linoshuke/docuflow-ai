import os
import sqlite3
from datetime import datetime

from lfx.custom.custom_component.component import Component
from lfx.io import MessageTextInput, Output
from lfx.schema.message import Message


class SQLiteDocuFlowReader(Component):
    display_name = "DocuFlow SQLite Reader"
    description = "Baca data dari database DocuFlow (termasuk rincian item) untuk dijawab LLM"
    icon = "database"
    name = "SQLiteDocuFlowReader"

    inputs = [
        MessageTextInput(
            name="db_path",
            display_name="Path Database SQLite",
            value="",
            advanced=True,
        ),
        MessageTextInput(
            name="limit",
            display_name="Jumlah Record Maksimal",
            value="50",
            advanced=True,
        ),
    ]

    outputs = [
        Output(display_name="Data Dokumen", name="documents_data", method="read_documents"),
    ]

    def _resolve_db_path(self, given_path):
        if os.environ.get("DOCUFLOW_DB_PATH"):
            return os.environ["DOCUFLOW_DB_PATH"]
        p = str(given_path or "").strip()
        if p and os.path.exists(os.path.dirname(p)):
            return p
        cwd = os.getcwd()
        for c in [
            os.path.join(cwd, "data", "docuflow.db"),
            os.path.abspath(os.path.join(os.path.dirname(__file__) if "__file__" in globals() else cwd, "..", "data", "docuflow.db")),
            r"C:\Users\ASUS\docuflow-ai\data\docuflow.db",
            os.path.join(cwd, "docuflow.db"),
        ]:
            c_abs = os.path.abspath(c)
            if os.path.exists(os.path.dirname(c_abs)):
                return c_abs
        return os.path.abspath(os.path.join(cwd, "data", "docuflow.db"))

    def read_documents(self) -> Message:
        db_path = self._resolve_db_path(self.db_path)
        limit = int(self.limit or 50)

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            cur.execute(
                """CREATE TABLE IF NOT EXISTS document_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER,
                    item_name TEXT,
                    quantity REAL,
                    unit_price REAL,
                    total_price REAL,
                    created_at TEXT DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
                )"""
            )

            cur.execute("SELECT COUNT(*), SUM(total_amount) FROM documents")
            row_agg = cur.fetchone()
            total_docs = row_agg[0] if row_agg else 0
            total_sum = row_agg[1] if row_agg and row_agg[1] else 0

            cur.execute(
                """SELECT id, doc_type, vendor, document_number, document_date, 
                   description, subtotal, tax, total_amount, currency, category, 
                   warnings, created_at
                   FROM documents 
                   ORDER BY created_at DESC 
                   LIMIT ?""",
                (limit,),
            )
            rows = cur.fetchall()

            cur.execute("SELECT document_id, item_name, quantity, unit_price, total_price FROM document_items")
            items_by_doc = {}
            for it in cur.fetchall():
                doc_id = it["document_id"]
                if doc_id not in items_by_doc:
                    items_by_doc[doc_id] = []
                items_by_doc[doc_id].append(dict(it))

            conn.close()

            if not rows:
                return Message(
                    text="Database masih kosong. Silakan upload dokumen di flow 'DocuFlow 1 - Ingestion' atau input melalui dashboard terlebih dahulu."
                )

            lines = [
                f"RINGKASAN DATABASE DOCUFLOW:",
                f"- Total Dokumen: {total_docs or 0}",
                f"- Total Akumulasi Pengeluaran: Rp {total_sum or 0:,.2f}",
                f"- Menampilkan {len(rows)} dokumen terbaru:\n",
                "=" * 80
            ]

            for row in rows:
                doc = dict(row)
                lines.append(f"\n[ID: {doc['id']}]")
                lines.append(f"Jenis: {doc['doc_type'] or '-'}")
                lines.append(f"Vendor: {doc['vendor'] or '-'}")
                lines.append(f"Nomor: {doc['document_number'] or '-'}")
                lines.append(f"Tanggal: {doc['document_date'] or '-'}")
                lines.append(f"Deskripsi: {doc['description'] or '-'}")
                sub = f"{doc['subtotal']:,.2f} {doc['currency'] or ''}" if doc['subtotal'] is not None else "0.00"
                tax = f"{doc['tax']:,.2f} {doc['currency'] or ''}" if doc['tax'] is not None else "0.00"
                tot = f"{doc['total_amount']:,.2f} {doc['currency'] or ''}" if doc['total_amount'] is not None else "0.00"
                lines.append(f"Subtotal: {sub}")
                lines.append(f"Pajak: {tax}")
                lines.append(f"Total: {tot}")
                lines.append(f"Kategori: {doc['category'] or '-'}")

                doc_items = items_by_doc.get(doc['id'], [])
                if doc_items:
                    lines.append("Rincian Item:")
                    for it in doc_items:
                        lines.append(f"  - {it['item_name']} (Qty: {it['quantity']}, Satuan: {it['unit_price']:,.2f}, Total: {it['total_price']:,.2f})")

                if doc['warnings']:
                    lines.append(f"⚠️ Peringatan: {doc['warnings']}")
                lines.append(f"Dibuat: {doc['created_at']}")
                lines.append("-" * 80)

            result_text = "\n".join(lines)
            self.status = f"Berhasil membaca {len(rows)} dokumen dari database"
            return Message(text=result_text)

        except sqlite3.Error as e:
            return Message(text=f"Error database: {str(e)}")
        except Exception as e:
            return Message(text=f"Error tidak terduga: {str(e)}")
