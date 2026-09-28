"Live demo:[ https://…streamlit.app](https://permission-aware-bank-assistant-qsfame9ftbcuxdzm7icjan.streamlit.app/) — pick a role and ask a question."# Permission-Aware Enterprise Knowledge Assistant

A retrieval-augmented AI assistant that answers questions from company documents while enforcing role-based access control — the model never receives a document chunk the user isn't authorized to see.

Built as a practice project simulating a bank knowledge base, using entirely fictional data.

## The problem

In a real company, employees need answers pulled from scattered sources — policies, call transcripts, internal chats — but different roles are authorized to see different information. A naive AI assistant that searches everything and then tries to filter the *answer* is unsafe: by the time filtering happens, the sensitive content has already reached the model. This project filters access **before** retrieval, not after.

## What it does

- Ingests documents from three source types: policy documents, customer call transcripts, and internal chat/email exports
- Tags every document with metadata: department, date, status (current/superseded), and access level (Public, Internal, Credit-Confidential, AML-Confidential)
- Authenticates a simulated user role and restricts retrieval to only the access levels that role is permitted to see
- Combines semantic search (ChromaDB + sentence-transformers) and keyword search (BM25) for hybrid retrieval, then reranks results with a cross-encoder
- Generates a grounded, cited answer using Gemini — instructed to flag contradictions between documents, prefer current over superseded sources, refuse when information isn't in the retrieved documents, and warn when confidential content is involved
- Logs every query, role, retrieved sources, and answer to a persistent audit trail
- Supports dynamic access-level changes: a document's classification can escalate after ingestion (e.g., following a compliance event), and all future queries respect the updated classification immediately

## Architecture

```
Documents (policies, calls, chats)
        |
   Chunking + metadata tagging (source, department, date, access_level, status)
        |
   ChromaDB (semantic index) + BM25 (keyword index)
        |
   Role login (simulated) --> permission filter applied BEFORE search
        |
   Hybrid search --> cross-encoder reranking --> top 5 chunks
        |
   Gemini generation (grounded, cited, conflict-aware, confidentiality-warned)
        |
   Answer + audit log entry
```

## Roles simulated

| Role | Can access |
|---|---|
| Branch officer | Public, Internal |
| Credit manager | Public, Internal, Credit-Confidential |
| Compliance officer | Public, Internal, Credit-Confidential, AML-Confidential |

## Tech stack (all free tier)

- Google Colab — execution environment
- ChromaDB — vector storage and semantic search
- sentence-transformers (`all-MiniLM-L6-v2`) — embeddings
- rank_bm25 — keyword search
- Cross-encoder reranker (`ms-marco-MiniLM-L-6-v2`) — result reranking
- Google Gemini API — answer generation
- Google Drive — persistent storage and audit logging

## Test data

40 fictional documents (12 policies, 14 call transcripts, 14 internal chats) for a fictional bank, "Sahyadri Union Bank." All customers, staff, and figures are invented. The dataset deliberately includes:

- 3 pairs of contradicting documents (e.g., two versions of a fee policy)
- 3 superseded documents with current replacements
- 4 customer-facing promises made by staff, later confirmed, reversed, or left unresolved
- 2 cases of confidential information appearing in internal chats that must not reach a customer-facing answer
- 2 topics deliberately absent from every document, to test refusal instead of guessing

See `golden_dataset.csv` for the full 50-question evaluation set and `docs/answer_key.md` for the intended behavior on every planted test case.

## Evaluation results

See `RESULTS.md` for the full writeup. Summary:

- **Permission filtering: zero leaks** across all 50 test questions, including every question specifically designed to probe for confidential content reaching an unauthorized role
- **Conflict handling: 100%** — every contradiction between document versions was flagged, with the current version correctly preferred
- **Refusal on unavailable information: 100%** — no fabricated answers on the two deliberately-absent topics
- Retrieval quality: ~93-100% across most question categories on first pass; one miss (a near-duplicate phrasing issue between an outdated FAQ and its replacement) fixed by widening the candidate pool

## Realistic constraint

Real enterprise data isn't static — a document's sensitivity can change after it's already indexed. This project simulates a compliance event (a customer's AML risk rating being raised) and demonstrates that a document previously visible to a lower-privileged role becomes inaccessible to that role immediately after reclassification, without needing to re-ingest or manually reprocess anything.

## What this is not

This is a learning prototype, not a production system. It does not include real authentication, encryption at rest, role management infrastructure, or handling for documents beyond a few hundred chunks. A production version would need all of these.

## How to run it

1. Open the notebook in Google Colab.
2. Add your own Gemini API key to Colab's Secrets manager as `GEMINI_API_KEY`.
3. Upload the three `.txt` files and `golden_dataset.csv` to a Google Drive folder.
4. Run all cells in order.

## Files in this repository

```
/notebook.ipynb            - the full Colab notebook
/data/batch1_policies.txt  - 12 fictional policy documents
/data/batch2_calls.txt     - 14 fictional call transcripts
/data/batch3_chats.txt     - 14 fictional internal chats/emails
/golden_dataset.csv        - 50-question evaluation set
/evaluation_results.csv    - generated answers with human grading
/docs/answer_key.md        - intended behavior for every planted test case
/RESULTS.md                - evaluation writeup
/README.md                 - this file
```

## Background

This project follows the "permission-aware enterprise knowledge system" pattern for building trustworthy internal AI assistants: ingest from multiple sources, tag with access metadata, filter before retrieval (not after generation), evaluate retrieval and generation quality separately, and build in one realistic operational complication.
