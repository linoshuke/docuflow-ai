"""DocuFlow Ingestion Gateway Component for Langflow.
Memungkinkan input fleksibel: Menerima file upload (PDF/TXT) ATAU teks chat langsung
sehingga pengguna tidak harus selalu memiliki/mengunggah file PDF yang sudah jadi.
"""
from lfx.custom.custom_component.component import Component
from lfx.io import HandleInput, MessageTextInput, Output
from lfx.schema.message import Message


class DocuFlowInputGateway(Component):
    display_name = "DocuFlow Ingestion Gateway"
    description = "Pintu gerbang input fleksibel: Menerima File Upload ATAU Teks Chat langsung tanpa harus punya PDF."
    icon = "file-input"
    name = "DocuFlowInputGateway"

    inputs = [
        HandleInput(
            name="file_message",
            display_name="File Dokumen (PDF/TXT)",
            input_types=["Message", "Data", "Text"],
            required=False,
            info="Input dari file yang diunggah (jika ada file fisik/PDF).",
        ),
        HandleInput(
            name="chat_message",
            display_name="Teks Chat / Nota Langsung",
            input_types=["Message", "Text"],
            required=False,
            info="Input langsung dari Playground chat (pengguna dapat mengetik transaksi langsung tanpa PDF).",
        ),
        MessageTextInput(
            name="fallback_text",
            display_name="Teks Cadangan (Opsional)",
            value="",
            advanced=True,
            info="Teks manual jika file dan chat keduanya kosong.",
        ),
    ]

    outputs = [
        Output(display_name="Teks Siap Ekstraksi", name="output_text", method="process_input"),
    ]

    def _extract_text(self, obj):
        if obj is None:
            return ""
        if hasattr(obj, "text") and obj.text:
            return str(obj.text).strip()
        if hasattr(obj, "data") and isinstance(obj.data, dict):
            # Cek field text/content pada data
            for k in ("text", "content", "data", "raw"):
                if k in obj.data and obj.data[k]:
                    return str(obj.data[k]).strip()
        return str(obj).strip()

    def process_input(self) -> Message:
        file_txt = self._extract_text(self.file_message)
        chat_txt = self._extract_text(self.chat_message)
        fallback = str(self.fallback_text or "").strip()

        # Prioritas 1: Jika ada file upload nyata yang tidak kosong
        if file_txt and file_txt.lower() not in ("", "none", "null", "__undefined__"):
            self.status = f"Sumber: File Upload ({len(file_txt)} karakter)"
            return Message(text=file_txt)

        # Prioritas 2: Jika pengguna mengetik teks langsung di chat
        # Abaikan hanya jika teks berupa trigger kosong pendek tanpa informasi transaksi
        dummy_triggers = {"", "proses", "run", "lanjut", "halo", "hi", "test", "start", "ekstrak"}
        if chat_txt and chat_txt.lower() not in dummy_triggers and len(chat_txt) > 5:
            self.status = f"Sumber: Chat Input Langsung ({len(chat_txt)} karakter)"
            return Message(text=chat_txt)

        # Prioritas 3: Fallback text jika diisi
        if fallback:
            self.status = "Sumber: Teks Cadangan Manual"
            return Message(text=fallback)

        # Jika chat hanya berupa trigger aktivasi "proses" tapi file kosong
        if chat_txt:
            return Message(
                text="PERINGATAN: Belum ada file dokumen yang diunggah dan teks chat tidak memuat data transaksi. "
                     "Silakan lampirkan file invoice/kwitansi ATAU ketik langsung rincian transaksinya di chat ini."
            )

        self.status = "Menunggu input (upload file atau ketik teks di chat)..."
        return Message(text="")
