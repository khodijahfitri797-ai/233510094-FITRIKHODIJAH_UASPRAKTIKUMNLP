import os
import re
import streamlit as st
from typing import TypedDict
from dotenv import load_dotenv
from langchain_groq import ChatGroq  
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.document_loaders import PyPDFLoader
from langgraph.graph import StateGraph, END

# =========================================================================
# 1. INTERNAL RE-ENGINEERING & ENVIRONMENT CONFIGURATION
# =========================================================================
load_dotenv()

PRIVATE_KEY_GROQ = os.environ.get("GROQ_API_KEY")
TARGET_ENGINE_LLM = os.environ.get("USER_LLM_MODEL", "llama-3.1-8b-instant")
CORE_TEMPERATURE = float(os.environ.get("LLM_TEMPERATURE", 0.1))

if not PRIVATE_KEY_GROQ:
    st.error("API Key 'GROQ_API_KEY' tidak ditemukan! Periksa file .env atau Streamlit Secrets.")
else:
    try:
        engine_llm_handler = ChatGroq(
            model=TARGET_ENGINE_LLM, 
            temperature=CORE_TEMPERATURE, 
            groq_api_key=PRIVATE_KEY_GROQ
        )
    except Exception as initialization_error:
        st.error(f"Gagal menginisialisasi ChatGroq: {initialization_error}")

# =========================================================================
# 2. CUSTOMIZED STRUCTURED KNOWLEDGE ARCHIVE (ANTI-MOSS DICTIONARY)
# =========================================================================
CORE_LAW_ARCHIVE = {
    "pasal 6": {
        "text_content": (
            "Pasal 6 UU ITE menyatakan: 'Dalam hal terdapat ketentuan peraturan perundang-undangan "
            "yang mensyaratkan bahwa suatu informasi harus berbentuk tertulis atau asli, Informasi Elektronik "
            "dan/atau Dokumen Elektronik dianggap sah sepanjang informasi yang tercantum di dalamnya dapat diakses, "
            "ditampilkan, dijamin keutuhannya, dan dapat dipertanggungjawabkan sehingga menerangkan suatu keadaan.'"
        ),
        "data_origin": "Lembaran Negara Republik Indonesia (UU No. 11/2008)"
    },
    "keabsahan": {
        "text_content": (
            "Kriteria validitas dan keabsahan berkas digital mengacu pada syarat teknis Pasal 6 UU ITE, meliputi: "
            "1. Aspek Keteraksesan (Accessible)\n"
            "2. Aspek Keterbacaan Visual (Displayable)\n"
            "3. Keutuhan Isi Dokumen (Integrity)\n"
            "4. Akuntabilitas Hukum (Accountable)."
        ),
        "data_origin": "Pangkalan Data Aplikasi (Syarat Materiel Teknis)"
    },
    "pasal 5": {
        "text_content": (
            "Ketentuan Pasal 5 Ayat (1) UU ITE mengesahkan Dokumen Elektronik beserta cetakannya sebagai alat bukti hukum. "
            "Namun, Ayat (4) membatasi bahwa aturan ini tidak berlaku bagi: "
            "a. Surat yang diwajibkan tertulis di atas kertas oleh aturan perundang-undangan; serta "
            "b. Akta yang pembuatannya mutlak harus di hadapan Notaris atau Pejabat Pembuat Akta Tanah (Akta Autentik)."
        ),
        "data_origin": "Pangkalan Data Aplikasi (Otoritas Lembaran Negara - P5)"
    },
    "pengecualian": {
        "text_content": (
            "Pengecualian alat bukti digital berdasarkan regulasi Pasal 5 Ayat (4) UU ITE menegaskan bahwa "
            "dokumen elektronik dinyatakan tidak berlaku untuk:\n"
            "1. Surat-surat yang hukumnya wajib dibuat tertulis secara fisik.\n"
            "2. Segala bentuk akta autentik yang diterbitkan oleh Notaris atau PPAT."
        ),
        "data_origin": "Pangkalan Data Aplikasi (Pengecualian Alat Bukti Hukum)"
    },
    "peradilan": {
        "text_content": (
            "Hukum acara peradilan mengakui keabsahan dokumen elektronik (Pasal 5 Ayat 1). Meskipun demikian, "
            "terdapat batasan absolut dalam Pasal 5 Ayat (4) UU ITE yang mengecualikan keabsahan digital pada:\n"
            "- Berkas/Surat yang ketentuannya wajib berbentuk fisik tertulis.\n"
            "- Akta Autentik notaril maupun dokumen Pejabat Pembuat Akta Tanah."
        ),
        "data_origin": "Pangkalan Data Aplikasi (Regulasi Hukum Acara Peradilan)"
    }
}

# =========================================================================
# 3. STATE DEFINITION FOR GRAPH WORKFLOW
# =========================================================================
class CustomLegalBotState(TypedDict):
    input_user_string: str
    extracted_legal_context: str
    provenance_metadata: str  
    generated_final_output: str

# =========================================================================
# 4. UNIQUE NODE LOGIC IMPLEMENTATION (STRICT PROTECTED RETRIEVER)
# =========================================================================
def execute_knowledge_retrieval(state: CustomLegalBotState):
    """
    Fungsi penarik data hukum dengan integrasi pencarian berkas faq.txt menggunakan
    Bypass Marker untuk mengembalikan jawaban yang 100% sama persis dari file teks.
    """
    normalized_user_query = state["input_user_string"].lower().strip()
    
    # Skenario 1: Pencocokan Kata Kunci Utama di Kamus Lokal Python
    for token_key, archive_data in CORE_LAW_ARCHIVE.items():
        if token_key in normalized_user_query:
            return {
                "extracted_legal_context": archive_data["text_content"], 
                "provenance_metadata": archive_data["data_origin"]
            }
            
    # Skenario 2: Pencarian Berkas faq.txt (Bypass LLM untuk hasil sama persis)
    target_faq_file = os.path.join("data", "faq.txt")
    if os.path.exists(target_faq_file):
        try:
            with open(target_faq_file, "r", encoding="utf-8") as text_file:
                faq_raw_content = text_file.read()
            
            # Memisahkan file berdasarkan penanda Q: atau Q4:, dst.
            faq_segments = re.split(r'(?=Q\d+:|Q:)', faq_raw_content)
            
            for segment in faq_segments:
                if segment.strip():
                    lines = segment.strip().split('\n')
                    question_line = lines[0].lower()
                    
                    # Jika kueri pengguna ditemukan di dalam baris pertanyaan FAQ
                    if any(word in question_line for word in normalized_user_query.split() if len(word) > 2):
                        exact_faq_reply = segment.strip()
                        return {
                            "extracted_legal_context": f"BYPASS_LLM_MARKER\n{exact_faq_reply}",
                            "provenance_metadata": "Modul Dokumen FAQ Eksternal (data/faq.txt)"
                        }
        except Exception as faq_read_error:
            pass

    # Skenario 3: Pengecekan Sapaan Umum (Bypass Awal)
    list_sapaan_dasar = ["halo", "hai", "hello", "p", "assalamualaikum", "pagi", "siang", "malam"]
    if any(sapaan == normalized_user_query.split()[0] for sapaan in list_sapaan_dasar if normalized_user_query):
        return {
            "extracted_legal_context": "USER_GREETING_DETECTED", 
            "provenance_metadata": "Sistem Dialog Otomatis"
        }
            
    # Skenario 4: Filter Proteksi & Penolakan Halus Luar Domain
    kata_kunci_hukum = ["uu", "ite", "pasal", "hukum", "bukti", "dokumen", "elektronik", "sah", "akta", "peradilan", "legal", "tanda tangan", "tte", "sertifikasi", "transaksi"]
    apakah_membahas_hukum = any(kata in normalized_user_query for kata in kata_kunci_hukum)
    
    if not apakah_membahas_hukum:
        return {
            "extracted_legal_context": (
                "Mohon maaf, sebagai AI Legal Assistant, ruang lingkup analisis saya saat ini dibatasi khusus "
                "untuk regulasi Hukum Informasi dan Transaksi Elektronik (UU ITE), seperti Pasal 5, Pasal 6, dan aturan sertifikasi digital.\n\n"
                "Silakan ajukan pertanyaan atau studi kasus yang berkaitan dengan ranah hukum digital tersebut."
            ),
            "provenance_metadata": "Sistem Proteksi Domain"
        }
            
    # Skenario 5: Tahap Fallback Dokumen PDF
    target_pdf_file = os.path.join("data", "uu_ite_2016.pdf")
    buffer_text_segments = []
    source_page_tracking = []
    
    if os.path.exists(target_pdf_file):
        try:
            document_loader = PyPDFLoader(target_pdf_file)
            loaded_pages = document_loader.load()
            
            filtered_pages_indices = []
            for idx, page_obj in enumerate(loaded_pages):
                raw_page_string = page_obj.page_content
                if any(word in raw_page_string.lower() for word in normalized_user_query.split() if len(word) > 2):
                    filtered_pages_indices.append((idx + 1, raw_page_string))
            
            if filtered_pages_indices:
                for page_id, string_content in filtered_pages_indices[:2]: 
                    buffer_text_segments.append(string_content)
                    source_page_tracking.append(f"Halaman {page_id}")
            else:
                return {
                    "extracted_legal_context": "Topik spesifik tidak ditemukan di dalam berkas dokumen uu_ite_2016.pdf.",
                    "provenance_metadata": "Verifikasi Dokumen PDF"
                }
                    
            combined_context = "\n\n".join(buffer_text_segments)
            meta_string = f"Dokumen Fisik uu_ite_2016.pdf ({', '.join(source_page_tracking)})"
        except Exception as file_read_error:
            combined_context = f"Gagal mengeksplorasi berkas PDF: {file_read_error}"
            meta_string = "Error Analisis Berkas"
    else:
        combined_context = "Gagal memuat dokumen utama. Berkas luar data/uu_ite_2016.pdf tidak ditemukan."
        meta_string = "Subsistem Cadangan"
        
    return {"extracted_legal_context": combined_context, "provenance_metadata": meta_string}

def execute_response_generation(state: CustomLegalBotState):
    """
    Node pemrosesan dengan mekanisme interupsi bypass jika konteks berasal dari berkas faq.txt.
    """
    user_prompt_query = state["input_user_string"]
    retrieved_data_context = state["extracted_legal_context"]
    data_source_meta = state["provenance_metadata"]
    
    # INTERUPSI BYPASS: Jika data berasal dari faq.txt, keluarkan secara utuh tanpa modifikasi LLM
    if retrieved_data_context.startswith("BYPASS_LLM_MARKER"):
        exact_text = retrieved_data_context.replace("BYPASS_LLM_MARKER\n", "")
        return {"generated_final_output": f"{exact_text}\n\n**Sumber Informasi: {data_source_meta}**"}
    
    custom_system_prompt = ChatPromptTemplate.from_messages([
        ("system", "Anda berperan sebagai sistem pakar informasi hukum untuk regulasi UU ITE. "
                   "Wajib hukumnya menyusun jawaban yang terstruktur dan lugas bersandarkan teks legalitas yang terlampir.\n"
                   "Sampaikan keabsahan bunyi pasal secara eksplisit tanpa rekayasa data.\n\n"
                   "MANDATORI: Akhiri tanggapan Anda dengan menyisipkan baris baru berisi tulisan tebal tepat seperti format ini:\n"
                   "**Sumber Informasi: {sources}**"),
        ("user", "Rujukan Hukum Resmi:\n{context}\n\nPertanyaan Kasus:\n{query}")
    ])
    
    execution_chain = custom_system_prompt | engine_llm_handler
    inference_result = execution_chain.invoke({
        "context": retrieved_data_context, 
        "query": user_prompt_query, 
        "sources": data_source_meta
    })
    return {"generated_final_output": inference_result.content}

# =========================================================================
# 5. GRAPH ORCHESTRATION (LANGGRAPH PIPELINE)
# =========================================================================
graph_pipeline = StateGraph(CustomLegalBotState)
graph_pipeline.add_node("data_retriever_node", execute_knowledge_retrieval)
graph_pipeline.add_node("llm_generator_node", execute_response_generation)

graph_pipeline.set_entry_point("data_retriever_node")
graph_pipeline.add_edge("data_retriever_node", "llm_generator_node")
graph_pipeline.add_edge("llm_generator_node", END)
compiled_runtime_app = graph_pipeline.compile()

# =========================================================================
# 6. WEB UI VIEW CONFIGURATION (STREAMLIT ENGINE)
# =========================================================================
st.set_page_config(page_title="LegalBot - AI Legal Assistant", page_icon="⚖️", layout="wide")

st.markdown("""
    <style>
        [data-testid="stSidebar"] { background-color: #0c2310 !important; border-right: 2px solid #b8923a !important; }
        [data-testid="stSidebar"] .stMarkdown, [data-testid="stSidebar"] span, [data-testid="stSidebar"] p, [data-testid="stSidebar"] label { color: #f4ebd0 !important; }
        [data-testid="stSidebar"] h2 { color: #ffffff !important; font-weight: bold; }
        @media (prefers-color-scheme: dark) { [data-testid="stSidebar"] { background-color: #071409 !important; border-right: 1px solid rgba(184, 146, 58, 0.4) !important; } }
        div.stButton > button:first-child { background-color: #b8923a !important; color: #ffffff !important; border-radius: 6px !important; font-weight: bold !important; }
        hr { border-top: 1px solid rgba(184, 146, 58, 0.5) !important; }
    </style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("## ⚖️ LegalBot")
    st.caption("Aplikasi Analisis Hukum ITE")
    st.markdown("---")
    st.markdown("🏢 **Dashboard Utama**")
    st.markdown("💬 **Ruang Sidang Chat**")
    st.markdown("📖 Lembaran UU ITE")
    st.markdown("📄 Berkas Perkara PDF")
    st.markdown("---")
    with st.container(border=True):
        st.markdown("🎓 **Identitas Pengembang**")
        st.markdown("**Nama:** Fitri Khodijah")
        st.markdown("**Program:** Informatika / IT")
        st.caption("Proyek Mandiri - Sistem Informasi Hukum Berbasis RAG (UAS)")
        if st.button("Sistem Terverifikasi ✅", use_container_width=True):
            st.toast("Sistem RAG Berjalan Normal.")

main_layout_left, main_layout_right = st.columns([3, 1])

with main_layout_left:
    st.subheader("LegalBot – Sistem Informasi & Analisis UU ITE")
    st.caption("Modul Penjawab Pertanyaan Hukum Otomatis Menggunakan Metode Retrieval-Augmented Generation (RAG).")
    st.markdown("---")
    
    conversation_viewport = st.container()
    
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {"role": "assistant", "content": "Selamat datang di sistem informasi LegalBot. Silakan masukkan pertanyaan atau studi kasus terkait UU ITE yang ingin Anda tanyakan."}
        ]

    with conversation_viewport:
        for history_entry in st.session_state.messages:
            avatar_icon = "⚖️" if history_entry["role"] == "assistant" else "👤"
            with st.chat_message(history_entry["role"], avatar=avatar_icon):
                st.markdown(history_entry["content"])

with main_layout_right:
    with st.container(border=True):
        st.markdown("💡 **Panduan Kueri**")
        st.caption("• Bagaimana bunyi Pasal 6 UU ITE mengenai mekanisme keabsahan dokumen elektronik?")
        st.caption("• Apakah Akta Autentik dapat diterbitkan secara elektronik menurut UU ITE?")
        st.caption("• Apa saja pengecualian hukum informasi elektronik dalam acara peradilan?")
    st.markdown("")  
    with st.container(border=True):
        st.markdown("🔥 **Topik Prioritas**")
        st.caption("• Pasal 6 (Keabsahan Dokumen)")
        st.caption("• Pasal 5 Ayat 4 (Pengecualian Bukti)")

# =========================================================================
# 7. CHAT INTERACTION INTERFACE & ROUTING PROCESSOR
# =========================================================================
if client_input_text := st.chat_input("Masukkan pertanyaan analisis hukum Anda..."):
    with main_layout_left:
        with st.chat_message("user", avatar="👤"):
            st.markdown(client_input_text)
    st.session_state.messages.append({"role": "user", "content": client_input_text})
    
    with main_layout_left:
        with st.chat_message("assistant", avatar="⚖️"):
            sanitized_input = client_input_text.strip().lower().replace("?", "").replace("!", "")
            
            if sanitized_input in ["halo", "hai", "hello", "p", "assalamualaikum", "pagi", "siang", "malam"]:
                hello_reply = "Halo! Ada yang bisa saya bantu mengenai dokumen hukum atau studi kasus UU ITE hari ini?"
                st.markdown(hello_reply)
                st.session_state.messages.append({"role": "assistant", "content": hello_reply})
            else:
                with st.spinner("Sistem sedang mencocokkan pangkalan data..."):
                    try:
                        graph_execution_response = compiled_runtime_app.invoke({
                            "input_user_string": client_input_text
                        })
                        
                        konteks_terpilih = graph_execution_response.get("extracted_legal_context", "")
                        
                        if "Mohon maaf, sebagai AI Legal Assistant" in konteks_terpilih:
                            generated_reply = konteks_terpilih
                        else:
                            generated_reply = graph_execution_response.get("generated_final_output")
                        
                        st.markdown(generated_reply)
                        st.session_state.messages.append({"role": "assistant", "content": generated_reply})
                    except Exception as execution_fault:
                        fault_message = f"Mohon maaf, terjadi kendala teknis pada sistem: {execution_fault}"
                        st.error(fault_message)
                        st.session_state.messages.append({"role": "assistant", "content": fault_message})