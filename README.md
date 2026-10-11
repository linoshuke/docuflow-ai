# DocuFlow AI

**Document to Database AI** - Otomatisasi ekstraksi data dokumen (invoice, kwitansi, formulir, nota kas kecil) menjadi database terstruktur menggunakan **LLM via Langflow**, lengkap dengan tanya-jawab bahasa natural atas data yang tersimpan.

Dibuat untuk capstone **IBM SkillsBuild University Education X Hacktiv8**.

## Arsitektur Sistem

```
FLOW 1 - INGESTION DOKUMEN (DUAL-INPUT MODE)
[ Upload Dokumen (PDF/TXT) ] ----+
                                 |---> [ DocuFlow Ingestion Gateway ] ---> [ Structured Output ] ---> [ DocuFlow SQL Writer ]
[ Input Chat Langsung (Tanpa PDF) ]+                                           ^                             |
                                                                               |                             v
                                                                        [ Language Model ]             docuflow.db
                                                                                                    (documents + items)
                                                                                                             |
                                                                                                             v
                                                                                                    [ Chat Output ]

FLOW 2 - QUERY CHAT DATABASE
Pertanyaan Pengguna -> DocuFlow SQL Guard / SQLite Reader
                               |
                               v
           Query SQL Aman / Agregat Dokumen + Rincian Barang
                               |
                               v
                     LLM (Jawaban Bahasa Indonesia) -> Chat Output
```

### Keunggulan Alur Perbaikan (Solusi Kelabilan Lingkungan Langflow)
1. **Tidak Wajib Punya PDF Jadi (Dual-Input Ingestion Gateway):** Pengguna tidak lagi dipaksa harus mengunggah file PDF/dokumen fisik. Pengguna dapat langsung **mengetik atau menempelkan teks transaksi/nota kas kecil di Playground chat**. Komponen `DocuFlowInputGateway` akan otomatis mendeteksi sumber data (file upload atau teks chat langsung).1
2. **Dukungan Rincian Barang Relasional (1-to-Many Line Items):** Menyimpan data ke dua tabel terhubung: `documents` (header tagihan) dan `document_items` (rincian nama barang, kuantitas, harga satuan, dan subtotal).
3. **De-duplikasi Cerdas & Toleran:** Memeriksa duplikasi dengan normalisasi vendor dan nomor dokumen, serta tidak menolak kwitansi yang tidak memiliki nomor kwitansi selama tanggal/nominal berbeda.
4. **Portabilitas Lintas Platform:** Bebas dari *hardcoded path* Windows `C:\Users\ASUS\...`. Komponen otomatis mendeteksi direktori database relatif (`data/docuflow.db`) atau variabel lingkungan `DOCUFLOW_DB_PATH`.

---

## Struktur Project

```
docuflow-ai/
├── flows/
│   ├── Docuflow 1 - Ingestion Dokumen.json     Flow Ingestion (Dual-Input + Line Items)
│   ├── Docuflow Query - Chat Database.json     Flow Query (Tanya Database + Rincian Item)
│   ├── docuflow_1.json                         Salinan flow 1 hasil regenerasi
│   └── docuflow_2.json                         Salinan flow 2 hasil regenerasi
├── components/
│   ├── input_gateway.py       Komponen Gateway (File Upload ATAU Chat Langsung)
│   ├── sqlite_writer.py       Komponen Writer (Validasi + Relasi document_items)
│   └── sqlite_reader.py       Komponen Reader (Agregasi SQL akurat + items)
├── sample_data/
│   ├── invoice_pt_maju_jaya.txt
│   └── kwitansi_atlas_elektronik.txt
├── data/
│   └── docuflow.db            Database SQLite (berisi tabel documents & document_items)
├── tools/
│   └── build_flows.py         Script regenerasi & auto-import flow ke Langflow
└── README.md
```

---

## Komponen Langflow

| Flow | Komponen | Peran |
|---|---|---|
| 1 | **Upload Dokumen (PDF/TXT)** | Parser file dokumen (PDF/TXT) jika pengguna memiliki file fisik |
| 1 | **Input Teks Nota / Chat Langsung** | Menerima ketikan nota/transaksi langsung di Playground chat tanpa perlu upload PDF |
| 1 | **DocuFlow Ingestion Gateway** (kustom) | Memilih secara cerdas sumber input (file atau chat) lalu meneruskannya ke LLM |
| 1 | **Structured Output** | Memaksa keluaran LLM menjadi JSON terstruktur lengkap dengan array `items` |
| 1 | **DocuFlow SQL Writer** (kustom) | Validasi, normalisasi rupiah/tanggal, deteksi duplikat, dan simpan ke `documents` + `document_items` |
| 2 | **Chat Input** | Menerima pertanyaan pengguna dalam bahasa natural |
| 2 | **DocuFlow SQL Guard / Reader** (kustom) | Membaca dokumen, menghitung agregat pengeluaran, serta menarik rincian barang/jasa |
| 2 | **LLM (Groq / Gemini / IBM Granite)** | Menganalisis konteks database dan menjawab pertanyaan pengguna |

---

## Setup Model LLM

| Flow | Node | Provider | Model |
|---|---|---|---|
| 1 Ingestion | Structured Output / LLM | Google Generative AI / Groq | `gemini-2.5-flash` / `llama-3.3-70b-versatile` |
| 2 Query | LLM | Groq / Gemini | `llama-3.1-8b-instant` / `gemini-2.5-flash` |

*Catatan:* Model dapat ditukar bebas di UI Langflow (Gemini, Groq, IBM watsonx Granite, Ollama lokal) tanpa perlu merombak arsitektur flow.

---

## Cara Menjalankan di Langflow

### 1. Sinkronisasi & Import Otomatis (Opsional)
Jika Langflow sedang berjalan di komputer lokal (`http://127.0.0.1:7860`), Anda dapat menjalankan:
```bash
python tools/build_flows.py
```
Script akan otomatis membangun flow dengan komponen terbaru dan mengimpornya langsung ke instance Langflow Anda.

Atau impor manual melalui UI Langflow:
- Buka Langflow > **New Flow** > **Import** > pilih file dari folder `flows/`.

---

### 2. Ingestion (Dua Cara Penggunaan)

Buka flow **DocuFlow 1 - Ingestion Dokumen**, lalu buka **Playground**:

#### Cara A: Jika Punya File Dokumen (PDF / TXT)
1. Unggah file dokumen di node **Upload Dokumen**.
2. Ketik `proses` di chat Playground lalu tekan Enter.
3. Dokumen akan diekstrak dan disimpan ke SQLite lengkap dengan rincian barangnya.

#### Cara B: Tanpa File Dokumen (Input Langsung via Chat Playground)
Pengguna **tidak perlu membuat atau mengupload PDF**. Cukup ketik rincian transaksi langsung di chat Playground, misalnya:
> *"Telah dibayar kwitansi Toko Berkah No 908 tanggal 10 Oktober 2026. Pembelian 5 pcs lampu LED @ Rp35.000 (total 175.000) dan kabel roll 10m Rp50.000. Total dibayar Rp225.000. Kategori: Perlengkapan Kantor."*

Gateway akan mendeteksi teks chat tersebut, LLM mengekstrak datanya menjadi JSON terstruktur, dan SQL Writer menyimpannya langsung ke database SQLite.

---

### 3. Query (Tanya Database)

Buka flow **DocuFlow 2 - Query Database**, lalu buka **Playground**:
Contoh pertanyaan yang didukung:
* *"Berapa total seluruh pengeluaran yang tercatat di database?"*
* *"Siapa saja vendor yang pernah kita bayar?"*
* *"Berapa unit sparepart mesin GX-200 yang dibeli dan berapa total harganya?"*
* *"Tampilkan transaksi dengan pengeluaran terbesar."*

---

## Skema Database SQLite (`data/docuflow.db`)

Sistem menggunakan relasi **1-ke-Banyak (One-to-Many)**:

```sql
-- Tabel Dokumen Utama (Header)
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_type TEXT,
    vendor TEXT,
    document_number TEXT,
    document_date TEXT,
    description TEXT,
    subtotal REAL,
    tax REAL,
    total_amount REAL,
    currency TEXT DEFAULT 'IDR',
    category TEXT,
    warnings TEXT,
    raw_json TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- Tabel Rincian Barang / Jasa (Line Items)
CREATE TABLE document_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER,
    item_name TEXT,
    quantity REAL DEFAULT 1.0,
    unit_price REAL DEFAULT 0.0,
    total_price REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE
);
```

---

## Troubleshooting di Lingkungan Langflow

| Gejala | Penyebab Umum | Solusi |
|---|---|---|
| `429 Rate limit exceeded` | Kuota gratis Groq/Gemini habis sementara | Tunggu 1 menit atau ganti API key / model di node LLM |
| Pesan "Dokumen kosong" | File belum diunggah dan teks chat kurang dari 5 karakter | Lampirkan file pada node Upload ATAU ketik transaksi langsung di chat Playground |
| Data item tidak muncul | Dokumen tidak memuat rincian tabel per baris | Model tetap menyimpan total nominal dokumen di tabel `documents` |
| SQLite locked | Proses lain sedang mengakses file DB | Pastikan tidak ada script eksternal yang membuka transaksi SQLite secara bersamaan |
