"""
Permission-Aware Bank Knowledge Assistant
A Streamlit front end for the retrieval pipeline built and tested in Colab.

Run locally with:
    streamlit run app.py

Deploy for free on Streamlit Community Cloud by connecting this repo
and setting GEMINI_API_KEY in the app's Secrets.
"""

import os
import time
import streamlit as st
import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder
from google import genai

# ---------------------------------------------------------------------------
# PAGE CONFIG (must be the first Streamlit command)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Sahyadri Union Bank - Knowledge Assistant",
    page_icon="🏦",
    layout="centered"
)

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------
DATA_DIR = "data"
DATA_FILES = ["batch1_policies.txt", "batch2_calls.txt", "batch3_chats.txt"]

ROLE_PERMISSIONS = {
    "Branch Officer": ["Public", "Internal"],
    "Credit Manager": ["Public", "Internal", "Credit-Confidential"],
    "Compliance Officer": ["Public", "Internal", "Credit-Confidential", "AML-Confidential"],
}

CANDIDATE_MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-flash-latest",
]

SYSTEM_INSTRUCTION = """You are an internal assistant for Sahyadri Union Bank staff.

STRICT RULES:
1. Answer ONLY using the document excerpts provided below. Do not use any
   outside knowledge, even if you think you know the answer.
2. For every factual claim, cite the source document ID in square brackets,
   like this: [POL-002] or [CALL-007].
3. If the excerpts contain conflicting information (e.g. two different fee
   amounts), point out the conflict explicitly, and prefer the document
   with the most recent date or the one marked "status: current" over one
   marked "status: superseded".
4. If the answer is not contained in the excerpts provided, say clearly:
   "I don't have this information in the documents available to me." Do
   not guess or fill gaps with general knowledge.
5. If any excerpt is marked access_level "Credit-Confidential" or
   "AML-Confidential", add a warning at the end of your answer:
   "Note: this answer includes confidential internal information and
   must not be shared with the customer."
6. Be concise and factual. Do not add opinions or advice beyond what the
   documents state.
"""

# ---------------------------------------------------------------------------
# ONE-TIME SETUP (cached so it only runs once, not on every question)
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner="Loading and indexing documents...")
def load_and_index_documents():
    """Reads the three source files, chunks them, and builds both the
    semantic (ChromaDB) and keyword (BM25) search indexes."""

    all_text = ""
    for fname in DATA_FILES:
        path = os.path.join(DATA_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            all_text += f.read() + "\n"

    raw_docs = [d.strip() for d in all_text.split("=====DOC=====") if d.strip()]
    documents = []
    for raw in raw_docs:
        header_part, body_part = raw.split("text:", 1)
        metadata = {}
        for line in header_part.strip().splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                metadata[key.strip()] = value.strip()
        metadata["text"] = body_part.strip()
        documents.append(metadata)

    def split_into_chunks(text, max_words=100):
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        chunks, current_chunk, current_word_count = [], [], 0
        for para in paragraphs:
            para_word_count = len(para.split())
            if current_word_count + para_word_count > max_words and current_chunk:
                chunks.append(" ".join(current_chunk))
                current_chunk, current_word_count = [], 0
            current_chunk.append(para)
            current_word_count += para_word_count
        if current_chunk:
            chunks.append(" ".join(current_chunk))
        return chunks

    all_chunks, all_metadata, all_ids = [], [], []
    for doc in documents:
        chunks = split_into_chunks(doc["text"], max_words=100)
        for i, chunk_text in enumerate(chunks):
            all_ids.append(f"{doc['doc_id']}-chunk{i+1}")
            all_chunks.append(chunk_text)
            all_metadata.append({k: v for k, v in doc.items() if k != "text"})

    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    chroma_client = chromadb.Client()
    try:
        chroma_client.delete_collection("sahyadri_bank_docs")
    except Exception:
        pass
    collection = chroma_client.create_collection(
        name="sahyadri_bank_docs", embedding_function=embedding_fn
    )
    collection.add(ids=all_ids, documents=all_chunks, metadatas=all_metadata)

    tokenized_chunks = [chunk.lower().split() for chunk in all_chunks]
    bm25_index = BM25Okapi(tokenized_chunks)

    return collection, all_chunks, all_metadata, bm25_index


@st.cache_resource(show_spinner="Loading reranker model...")
def load_reranker():
    return CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")


@st.cache_resource(show_spinner="Connecting to Gemini...")
def load_gemini_client():
    api_key = os.environ.get("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY", None)
    if not api_key:
        st.error(
            "No Gemini API key found. Set GEMINI_API_KEY as an environment "
            "variable (local) or in Streamlit Secrets (cloud deployment)."
        )
        st.stop()
    return genai.Client(api_key=api_key)


@st.cache_resource(show_spinner="Finding an available model...")
def find_working_model(_client):
    """Tries each candidate model once and caches whichever one works,
    so this check only happens once per app session, not per question."""
    for model_name in CANDIDATE_MODELS:
        try:
            _client.models.generate_content(model=model_name, contents="Say OK")
            return model_name
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# CORE LOGIC (same as the Colab notebook)
# ---------------------------------------------------------------------------

def get_allowed_access_levels(role):
    return ROLE_PERMISSIONS[role]


def hybrid_search_with_rerank(question, role, collection, all_chunks, all_metadata,
                                bm25_index, reranker, n_candidates=20, n_final=6):
    allowed_levels = get_allowed_access_levels(role)

    semantic_results = collection.query(
        query_texts=[question],
        n_results=n_candidates,
        where={"access_level": {"$in": allowed_levels}}
    )
    semantic_chunks = semantic_results["documents"][0]
    semantic_metas = semantic_results["metadatas"][0]

    tokenized_question = question.lower().split()
    bm25_scores = bm25_index.get_scores(tokenized_question)
    top_bm25_indices = sorted(
        range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True
    )[:n_candidates]

    bm25_chunks, bm25_metas = [], []
    for i in top_bm25_indices:
        if all_metadata[i]["access_level"] in allowed_levels:
            bm25_chunks.append(all_chunks[i])
            bm25_metas.append(all_metadata[i])

    combined = list(zip(semantic_chunks, semantic_metas)) + list(zip(bm25_chunks, bm25_metas))
    seen, unique_combined = set(), []
    for chunk, meta in combined:
        key = meta.get("doc_id", "") + chunk[:50]
        if key not in seen:
            seen.add(key)
            unique_combined.append((chunk, meta))

    if not unique_combined:
        return [], []

    pairs = [[question, chunk] for chunk, meta in unique_combined]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(unique_combined, scores), key=lambda x: x[1], reverse=True)

    top_results = ranked[:n_final]
    return [item[0][0] for item in top_results], [item[0][1] for item in top_results]


def build_prompt(question, chunks, metas):
    excerpt_text = ""
    for chunk, meta in zip(chunks, metas):
        excerpt_text += (
            f"\n--- Excerpt from {meta['doc_id']} "
            f"(title: {meta['title']}, date: {meta['date']}, "
            f"status: {meta['status']}, access_level: {meta['access_level']}) ---\n"
            f"{chunk}\n"
        )
    return f"""{SYSTEM_INSTRUCTION}

DOCUMENT EXCERPTS:
{excerpt_text}

QUESTION: {question}

ANSWER:"""


def ask_bank_assistant(question, role, client, model, collection, all_chunks,
                         all_metadata, bm25_index, reranker, max_retries=3):
    chunks, metas = hybrid_search_with_rerank(
        question, role, collection, all_chunks, all_metadata, bm25_index, reranker
    )

    if not chunks:
        return (
            "I don't have this information in the documents available to me, "
            "or you are not authorized to view documents relevant to this question.",
            []
        )

    prompt = build_prompt(question, chunks, metas)

    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            return response.text, metas
        except Exception as e:
            err = str(e)
            if "503" in err or "UNAVAILABLE" in err:
                time.sleep(attempt * 3)
                continue
            elif "429" in err or "RESOURCE_EXHAUSTED" in err:
                return (
                    "The AI model's free daily usage limit has been reached. "
                    "Please try again later.",
                    metas
                )
            else:
                return f"An unexpected error occurred: {err}", metas

    return "The model is currently busy. Please try again in a moment.", metas


# ---------------------------------------------------------------------------
# STREAMLIT UI
# ---------------------------------------------------------------------------

st.title("🏦 Sahyadri Union Bank")
st.subheader("Permission-Aware Knowledge Assistant")

st.caption(
    "A practice project demonstrating role-based access control in a "
    "retrieval-augmented AI system. All data is fictional."
)

with st.spinner("Setting up..."):
    collection, all_chunks, all_metadata, bm25_index = load_and_index_documents()
    reranker = load_reranker()
    client = load_gemini_client()
    working_model = find_working_model(client)

if not working_model:
    st.error("No Gemini model is currently available. The free-tier daily quota may be exhausted.")
    st.stop()

st.divider()

role = st.selectbox(
    "Log in as:",
    options=list(ROLE_PERMISSIONS.keys()),
    help="Different roles can access different categories of documents."
)

with st.expander("What can this role see?"):
    st.write(", ".join(get_allowed_access_levels(role)))

question = st.text_area(
    "Ask a question:",
    placeholder="e.g. What is the processing fee for a home loan?",
    height=100
)

if st.button("Ask", type="primary"):
    if not question.strip():
        st.warning("Please enter a question.")
    else:
        with st.spinner("Searching documents and generating an answer..."):
            answer, sources = ask_bank_assistant(
                question, role, client, working_model,
                collection, all_chunks, all_metadata, bm25_index, reranker
            )

        st.markdown("### Answer")
        st.write(answer)

        if sources:
            st.markdown("### Sources used")
            for meta in sources:
                st.caption(
                    f"**{meta['doc_id']}** | {meta['title']} | "
                    f"Access level: {meta['access_level']} | Status: {meta['status']}"
                )
        else:
            st.caption("No documents were retrieved for this question and role.")

st.divider()
st.caption(
    "This is a portfolio demonstration project using entirely fictional "
    "banking data. It is not connected to any real bank."
)
