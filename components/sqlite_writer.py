import json
import os
import re
import sqlite3
from datetime import datetime

from lfx.custom.custom_component.component import Component
from lfx.io import HandleInput, MessageTextInput, Output
from lfx.schema.message import Message


class SQLiteDocuFlowWriter(Component):
    display_name = "DocuFlow SQLite Writer"
    description = "Validasi hasil ekstraksi AI lalu simpan ke database SQLite (lengkap dengan line items)."
    icon = "database"
    name = "SQLiteDocuFlowWriter"

    inputs = [
        HandleInput(
            name="rows",
            display_name="Hasil Ekstraksi",
            input_types=["DataFrame", "Table", "Data", "JSON"],
            required=True,
        ),
        MessageTextInput(
            name="db_path",
            display_name="Path Database SQLite",
            value="",
            advanced=True,
        ),
    ]

    outputs = [
        Output(display_name="Status Penyimpanan", name="status_message", method="write_rows"),
    ]

    ALIASES = {
        "doc_type": ["doc_type", "document_type", "jenis_dokumen", "tipe_dokumen", "type"],
        "vendor": ["vendor", "supplier", "penjual", "pemasok", "dari", "perusahaan", "company", "issuer"],
        "document_number": ["document_number", "invoice_number", "no_invoice", "nomor_invoice", "nomor",
                            "receipt_number", "no_kwitansi", "number", "no"],
        "document_date": ["document_date", "invoice_date", "tanggal", "tanggal_invoice", "date", "issue_date"],
        "description": ["description", "deskripsi", "keterangan", "notes", "catatan", "untuk_pembayaran"],
        "subtotal": ["subtotal", "sub_total", "jumlah_sebelum_pajak"],
        "tax": ["tax", "ppn", "vat", "pajak"],
        "total_amount": ["total_amount", "total", "grand_total", "total_dibayar", "jumlah_total", "amount"],
        "currency": ["currency", "mata_uang", "satuan_mata_uang"],
        "category": ["category", "kategori", "klasifikasi"],
        "items": ["items", "line_items", "daftar_barang", "rincian", "detail_barang", "products", "rincian_barang"],
    }

    MONTHS_ID = {
        "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
        "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
        "ags": 8, "agt": 8, "sep": 9, "okt": 10, "nov": 11, "des": 12,
    }
    MONTHS_EN = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }

    def _resolve_db_path(self, given_path):
        if os.environ.get("DOCUFLOW_DB_PATH"):
            return os.environ["DOCUFLOW_DB_PATH"]
        p = str(given_path or "").strip()
        if p and os.path.exists(os.path.dirname(p)):
            return p
        # Cari jalur database relatif secara otomatis
        cwd = os.getcwd()
        candidates = [
            os.path.join(cwd, "data", "docuflow.db"),
            os.path.join(os.path.dirname(__file__) if "__file__" in globals() else cwd, "..", "data", "docuflow.db"),
            r"C:\Users\ASUS\docuflow-ai\data\docuflow.db",
            os.path.join(cwd, "docuflow.db"),
        ]
        for c in candidates:
            c_abs = os.path.abspath(c)
            if os.path.exists(os.path.dirname(c_abs)):
                return c_abs
        return os.path.abspath(os.path.join(cwd, "data", "docuflow.db"))

    def _row_to_dict(self, item):
        if isinstance(item, dict):
            return item
        data = getattr(item, "data", None)
        if data is not None:
            try:
                return dict(data)
            except Exception:
                pass
        try:
            return dict(item)
        except Exception:
            return None

    def _canonical_key(self, key):
        k = str(key).strip().lower().replace(" ", "_")
        for canon, aliases in self.ALIASES.items():
            if k in aliases:
                return canon
        return None

    def _parse_amount(self, value):
        if value is None or value == "":
            return None
        if isinstance(value, (int, float)):
            return float(value)
        s = re.sub(r"[^\d,.\-]", "", str(value))
        if not s:
            return None
        neg = s.startswith("-")
        s = s.lstrip("-")
        if "." in s and "," in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        elif "," in s:
            parts = s.split(",")
            if len(parts[-1]) == 3 and len(parts) > 1:
                s = s.replace(",", "")
            else:
                s = s.replace(",", ".")
        else:
            whole = s.split(".")
            if len(whole) > 2 or (len(whole) == 2 and len(whole[1]) == 3):
                s = s.replace(".", "")
        try:
            num = float(s)
            return -num if neg else num
        except ValueError:
            return None

    def _parse_date(self, value):
        if value is None or str(value).strip() in ("", "None"):
            return None, ""
        raw = str(value).strip()
        s = raw.lower().replace("/", "-").replace(".", "-")
        for name, num in {**self.MONTHS_ID, **self.MONTHS_EN}.items():
            if name in s:
                parts = re.findall(r"\d+|[a-z]+", s)
                day = next((int(p) for p in parts if p.isdigit() and 1 <= int(p) <= 31), None)
                year = next((int(p) for p in parts if len(p) == 4 and p.isdigit()), None)
                if day and year:
                    try:
                        return datetime(year, num, day).strftime("%Y-%m-%d"), ""
                    except ValueError:
                        break
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%m-%y"):
            try:
                return datetime.strptime(s, fmt).strftime("%Y-%m-%d"), ""
            except ValueError:
                continue
        return None, f"format tanggal '{raw}' tidak dikenali"

    def _parse_items(self, raw_items):
        if not raw_items:
            return []
        if isinstance(raw_items, str):
            try:
                raw_items = json.loads(raw_items)
            except Exception:
                return []
        if not isinstance(raw_items, list):
            if isinstance(raw_items, dict):
                raw_items = [raw_items]
            else:
                return []

        parsed = []
        for it in raw_items:
            if not isinstance(it, dict):
                continue
            name = it.get("item_name") or it.get("name") or it.get("nama_barang") or it.get("deskripsi") or it.get("description")
            if not name:
                continue
            qty = self._parse_amount(it.get("quantity") or it.get("qty") or it.get("jumlah") or 1)
            unit_p = self._parse_amount(it.get("unit_price") or it.get("price") or it.get("harga_satuan") or it.get("harga"))
            tot_p = self._parse_amount(it.get("total_price") or it.get("subtotal") or it.get("total") or it.get("jumlah_harga"))

            if tot_p is None and qty is not None and unit_p is not None:
                tot_p = qty * unit_p
            elif unit_p is None and qty and tot_p:
                unit_p = tot_p / qty

            parsed.append({
                "item_name": str(name).strip(),
                "quantity": qty or 1.0,
                "unit_price": unit_p or 0.0,
                "total_price": tot_p or 0.0,
            })
        return parsed

    def _normalize_str(self, s):
        if not s:
            return ""
        # Bersihkan spasi, tanda baca untuk pencocokan toleran
        return re.sub(r"[^\w]", "", str(s).lower())

    def _validate_and_normalize(self, row):
        record, warnings = {}, []
        for key, val in row.items():
            canon = self._canonical_key(key)
            if canon:
                record[canon] = val
        for field in ("doc_type", "vendor", "document_number", "description", "currency", "category"):
            v = record.get(field)
            record[field] = str(v).strip() if v is not None and str(v).strip().lower() != "null" else None

        date_val, date_warn = self._parse_date(record.get("document_date"))
        if date_warn:
            record["document_date"] = str(record.get("document_date"))
            warnings.append(date_warn)
        else:
            record["document_date"] = date_val

        for field in ("subtotal", "tax", "total_amount"):
            num = self._parse_amount(record.get(field))
            if record.get(field) is not None and num is None:
                warnings.append(f"nilai {field} tidak dapat dibaca")
            record[field] = num
            if num is not None and num < 0:
                warnings.append(f"{field} bernilai negatif")

        # Parse Line Items
        line_items = self._parse_items(record.get("items"))
        record["_items"] = line_items

        # Fallback jika total_amount kosong namun ada line items
        if record.get("total_amount") is None and line_items:
            sum_items = sum(it["total_price"] for it in line_items if it.get("total_price"))
            if sum_items > 0:
                record["total_amount"] = sum_items
                if record.get("subtotal") is None:
                    record["subtotal"] = sum_items

        if record.get("currency") is None and any(
            record.get(f) is not None for f in ("subtotal", "tax", "total_amount")
        ):
            record["currency"] = "IDR"

        if not any([record.get("vendor"), record.get("document_number"),
                    record.get("total_amount") is not None]):
            return None, ["baris kosong / tanpa informasi penting"], ""
        return record, warnings, json.dumps(row, ensure_ascii=False, default=str)

    def _is_duplicate(self, cur, rec):
        vendor_norm = self._normalize_str(rec.get("vendor"))
        doc_no = (rec.get("document_number") or "").strip()
        doc_date = (rec.get("document_date") or "").strip()
        total = rec.get("total_amount")

        # Jika nomor dokumen ada dan bermakna: periksa nomor + normalisasi vendor
        if doc_no and len(doc_no) >= 3:
            cur.execute("SELECT id, vendor, document_number FROM documents WHERE document_number = ?", (doc_no,))
            rows = cur.fetchall()
            for _, v, _ in rows:
                if not vendor_norm or not v or self._normalize_str(v) == vendor_norm:
                    return True

        # Jika nomor dokumen tidak ada: HANYA anggap duplikat jika vendor, tanggal, DAN total cocok persis
        if vendor_norm and doc_date and total is not None:
            cur.execute(
                "SELECT id, vendor, document_date, total_amount FROM documents WHERE document_date = ? AND ABS(total_amount - ?) < 0.01",
                (doc_date, total)
            )
            rows = cur.fetchall()
            for _, v, _, _ in rows:
                if self._normalize_str(v) == vendor_norm:
                    return True

        return False

    def write_rows(self) -> Message:
        db_path = self._resolve_db_path(self.db_path)
        items = self.rows
        if hasattr(items, "value") and not hasattr(items, "__iter__"):
            items = [items]
        if items is None:
            items = []
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = [items]
        if isinstance(items, dict):
            for wrap in ("result", "results", "data", "items", "rows"):
                if wrap in items and isinstance(items[wrap], (list, dict)):
                    items = items[wrap]
                    break
            if isinstance(items, dict):
                items = [items]
        if not isinstance(items, list):
            items = [items]

        records, all_warnings = [], []
        for item in items:
            d = self._row_to_dict(item)
            if not d:
                continue
            rec, warns, raw = self._validate_and_normalize(d)
            if rec is None:
                all_warnings.append(f"dilewati: {warns[0] if warns else 'tidak valid'}")
                continue
            rec["_raw"] = raw
            records.append(rec)
            all_warnings.extend(warns)

        if not records:
            return Message(
                text="GAGAL: tidak ada data valid yang bisa disimpan.\n"
                     "Pastikan dokumen berisi invoice/kwitansi yang jelas lalu jalankan ulang flow."
            )

        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Buat tabel documents dan document_items
        cur.execute(
            """CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_type TEXT, vendor TEXT, document_number TEXT,
                document_date TEXT, description TEXT,
                subtotal REAL, tax REAL, total_amount REAL,
                currency TEXT, category TEXT,
                warnings TEXT, raw_json TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )"""
        )
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

        saved, duplicates = [], []
        for rec in records:
            raw = rec.pop("_raw", None)
            line_items = rec.pop("_items", [])

            if self._is_duplicate(cur, rec):
                duplicates.append(rec.get("document_number") or rec.get("vendor") or "tanpa nomor")
                continue

            cur.execute(
                """INSERT INTO documents (doc_type, vendor, document_number, document_date,
                   description, subtotal, tax, total_amount, currency, category, warnings, raw_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rec.get("doc_type"), rec.get("vendor"), rec.get("document_number"),
                    rec.get("document_date"), rec.get("description"),
                    rec.get("subtotal"), rec.get("tax"), rec.get("total_amount"),
                    rec.get("currency"), rec.get("category"),
                    "; ".join(all_warnings) if all_warnings else None, raw,
                ),
            )
            doc_id = cur.lastrowid

            # Simpan rincian barang/jasa (line items)
            if line_items:
                cur.executemany(
                    """INSERT INTO document_items (document_id, item_name, quantity, unit_price, total_price)
                       VALUES (?, ?, ?, ?, ?)""",
                    [(doc_id, it["item_name"], it["quantity"], it["unit_price"], it["total_price"])
                     for it in line_items]
                )

            rec["id"] = doc_id
            rec["items_count"] = len(line_items)
            saved.append(rec)

        conn.commit()
        last_id = cur.lastrowid
        conn.close()

        lines = []
        if saved:
            lines.append(f"BERHASIL: {len(saved)} dokumen tersimpan ke database DocuFlow.")
            for i, r in enumerate(saved, 1):
                total = f"{r['total_amount']:,.2f} {r.get('currency') or ''}".strip() \
                    if r.get("total_amount") is not None else "n/a"
                items_info = f" ({r['items_count']} rincian item)" if r.get("items_count") else ""
                lines.append(
                    f"[{i}] {r.get('doc_type') or '-'} | {r.get('vendor') or '-'} | "
                    f"No: {r.get('document_number') or '-'} | Tgl: {r.get('document_date') or '-'} | "
                    f"Total: {total}{items_info}"
                )
        if duplicates:
            lines.append(f"DILEWATI (duplikat): {len(duplicates)} -> {', '.join(duplicates)}")
        if all_warnings:
            lines.append("Peringatan validasi: " + " | ".join(dict.fromkeys(all_warnings)))
        if saved:
            lines.append(f"Record terakhir id={last_id}. Silakan lanjut bertanya di flow 'DocuFlow Query'.")

        self.status = "\n".join(lines)
        return Message(text=self.status)
