# DocuFlow AI

**Document to Database AI** - Otomatisasi ekstraksi data dokumen (invoice, kwitansi, formulir) menjadi database terstruktur menggunakan **LLM via Langflow**, lengkap dengan tanya-jawab bahasa natural atas data yang tersimpan.

Dibuat untuk capstone **IBM SkillsBuild University Education X Hacktiv8**.

## Arsitektur Sistem

```
FLOW 1 - INGESTION DOKUMEN
Upload Dokumen -> Prompt Template -> Structured Output (LLM ekstraksi JSON)
                                        |
                                        v
                        Docuflow SQL Writer (validasi + duplikat)
                                        |
                                        v
                       docuflow.db (SQLite)  ->  Chat Output (konfirmasi)

FLOW 2 - QUERY CHAT DATABASE
Pertanyaan -> DocuFlow SQLite Reader (ambil seluruh dokumen)
                    |
                    v
   Prompt Template {documents} + {question} -> LLM -> Jawaban -> Chat Output
```

Alur singkat: Input (unggah dokumen) -> Proses (parser teks, LLM mengekstrak JSON terstruktur, validasi otomatis format tanggal Indonesia / angka Rupiah / duplikat) -> Output (tersimpan di SQLite dengan konfirmasi, lalu bisa ditanya dalam bahasa natural).

## Struktur Project

```
docuflow-ai/
├── flows/
│   ├── Docuflow 1 - Ingestion Dokumen.json     Flow Ingestion
│   └── Docuflow Query - Chat Database.json     Flow Query (tanya database)
├── components/
│   └── sqlite_writer.py       Kode komponen kustom validasi + insert
├── sample_data/
│   ├── invoice_pt_maju_jaya.txt
│   └── kwitansi_atlas_elektronik.txt
├── data/
│   └── docuflow.db            Database SQLite (sudah berisi contoh; dibuat ulang otomatis oleh Writer)
├── tools/
│   └── build_flows.py         Script regenerasi & import ulang flow
└── README.md
```

Catatan: komponen kustom **DocuFlow SQLite Reader** pada Flow 2 tertanam langsung di dalam file flow JSON (kode Python inline pada node), sedangkan SQL Writer tersedia sebagai file terpisah di `components/`.

## Komponen Langflow

| Flow | Komponen | Peran |
|---|---|---|
| 1 | Upload Dokumen (File + Advanced Parser) | Parser dokumen (txt/pdf/gambar via OCR/Docling) |
| 1 | Prompt Template | Instruksi normalisasi (tanggal Indonesia, Rupiah, doc_type, null-safe) |
| 1 | Structured Output | Memaksa keluaran LLM menjadi JSON sesuai skema |
| 1 | Docuflow SQL Writer (kustom) | Validasi + deteksi duplikat + INSERT ke SQLite |
| 2 | Chat Input | Menerima pertanyaan pengguna |
| 2 | DocuFlow SQLite Reader (kustom) | Membaca seluruh dokumen dari database |
| 2 | Prompt Template | Menyusun konteks `{documents}` + `{question}` untuk LLM |
| 2 | Groq | Menjawab pertanyaan, menghitung/menyaring data dari konteks |

## Setup Model LLM (sudah terkonfigurasi)

| Flow | Node | Provider | Model |
|---|---|---|---|
| 1 Ingestion | Structured Output | Google Generative AI | `gemini-2.5-flash` |
| 2 Query | Groq | Groq | `llama-3.1-8b-instant` |

API key diisi langsung pada node masing-masing di Langflow dan **tidak disimpan di repository ini**.

Catatan penting:
- Koneksi internet dan kuota API (Gemini/Groq) harus tersedia saat demo.
- Model dapat ditukar bebas: cukup ganti isi field **Model** pada node LLM — tidak perlu mengubah arsitektur flow.
- Arsitektur siap dipindahkan ke IBM Granite (watsonx.ai): tinggal mengganti node LLM dengan komponen "IBM watsonx.ai" dan mengisi API key + Project ID.

## Cara Menjalankan Demo

### Import flow ke Langflow

Import kedua file di folder `flows/` melalui UI Langflow (**New Flow > Import**), lalu pastikan API key sudah terisi pada node model.

### Ingestion (masukkan data)

1. Buka flow **Docuflow 1 - Ingestion Dokumen**, klik Playground.
2. Klik node **Upload Dokumen**, upload `sample_data/invoice_pt_maju_jaya.txt`.
3. Kirim pesan apa pun di chat (misal "proses dokumen ini") untuk memicu eksekusi.
4. Chat Output akan menampilkan ringkasan: vendor, nomor, tanggal, total, status penyimpanan.

### Query (tanya database)

1. Buka flow **Docuflow Query - Chat Database**, klik Playground.
2. Tanyakan misalnya: `berapa total pengeluaran bulan Agustus?`, `siapa saja vendor yang pernah mengirim invoice?`, `dokumen dengan nilai tertinggi?`
3. Jawaban dirangkum model dari seluruh dokumen yang dibaca dari SQLite.

### Uji via REST API (opsional, untuk slide demo)

Set dulu nama endpoint lewat **Flow Settings > Endpoint Name** (misal `docuflow-query`), lalu:

```powershell
$key = "<LANGFLOW_API_KEY>"          # lihat bagian bawah README
$body = '{"input_value":"berapa total pengeluaran?","output_type":"chat"}'
Invoke-RestMethod -Uri "http://127.0.0.1:7860/api/v1/run/docuflow-query" `
  -Method Post -Headers @{"x-api-key"=$key} -ContentType "application/json" -Body $body
```

### API key Langflow sendiri

Dibuat lewat UI: profil kanan atas > **Settings > Langflow API Keys > Add New**, atau via endpoint `POST /api/v1/api_key/`.

## Keunggulan Teknis (bahan pitch juri)

1. **Arsitektur LLM pluggable**: model dapat ditukar (Gemini, Groq/Llama, IBM Granite watsonx.ai, OpenAI, Ollama) hanya dengan mengganti node - tanpa mengubah flow.
2. **Validasi berlapis**: LLM ekstraksi + prompt normalisasi deterministik (format tanggal Indonesia, parsing angka Rupiah, penanganan field kosong) sebelum data masuk database.
3. **Keamanan bawaan Structured Output**: skema JSON dipaksa sehingga keluaran LLM konsisten dan tidak bisa "mengarang" struktur baru.
4. **Akses data tanpa SQL**: pengguna non-teknis bisa menganalisis data cukup dengan bertanya dalam bahasa Indonesia - tidak perlu tahu nama tabel/kolom.
5. **Alternatif text-to-SQL siap pakai**: kelas `SQLQuerySanitizer` (SQL Guard: hanya SELECT, blokir DROP/DELETE/PRAGMA) tersedia di `tools/build_flows.py` bila ingin query langsung ke database oleh LLM.

## Troubleshooting

| Masalah | Solusi |
|---|---|
| `429 Rate limit exceeded` | Tunggu sebentar lalu jalankan ulang atau cek limit akun Gemini/Groq |
| Model tidak dikenal / 401 | Pastikan API key aktif dan nama model valid untuk provider terpilih |
| Ekstraksi kurang tepat | Turunkan temperature (advanced) ke 0.0 atau ganti ke model yang lebih besar |
| Data tidak masuk | Periksa panel status node SQL Writer; baris tidak valid dilaporkan beserta alasannya |
| Jawaban query kurang akurat | Perbesar **Jumlah Record Maksimal** pada node SQLite Reader agar konteks LLM lebih lengkap |
