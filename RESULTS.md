# Evaluation Results

## Methodology

Following the principle that retrieval quality and answer quality are different failure modes requiring separate measurement, this project evaluated both independently against a 50-question golden dataset covering six categories: easy lookups, cross-document synthesis, document conflicts, stale/superseded information, permission-based refusals, and questions with no answer in any document.

## Retrieval evaluation (automated)

Measured whether the correct source document appeared among the retrieved chunks, for every question with a known expected source.

| Category | Result |
|---|---|
| Conflict detection | 100% |
| Cross-document synthesis | 100% |
| Stale information | 100% |
| Easy lookup | 93.75% (1 miss, fixed — see below) |
| Refusal / permission-restricted | No unauthorized content retrieved in any case |
| Not-in-document | No unauthorized content retrieved in any case |

**One retrieval issue found and fixed:** a question about savings account minimum balance initially retrieved only the outdated FAQ document instead of also surfacing the current circular, because the two documents used near-identical phrasing that biased both semantic and keyword search toward the older one. Fixed by widening the candidate pool before reranking (`n_candidates` from 15 to 20). Confirmed fixed on re-test.

**Security verification:** every question in the refusal and not-in-document categories was independently checked against actual document access levels. Across all of them, zero chunks from an unauthorized access level were ever retrieved for a lower-privileged role. Permission filtering held even during hybrid search (both the semantic and keyword search paths were checked independently).

## Generation evaluation (manual grading)

All 50 questions were run through the full pipeline (retrieval → reranking → Gemini generation) and manually graded against expected behavior. Grading prioritized the 19 questions specifically designed to test trustworthiness rather than fluency:

| Test category | Questions | Result |
|---|---|---|
| Conflict flagging and resolution | G21-G26, G49 (7 questions) | 100% pass — every conflict was flagged, and the current document was correctly preferred over the superseded one |
| Permission refusal | G31-G37, G47 (8 questions) | 100% pass — no confidential content reached an unauthorized role's answer |
| Refusal on missing information | G38-G40, G50 (4 questions) | 100% pass — no fabricated answers on topics absent from every document |

The remaining 31 questions (easy lookups and cross-document synthesis) were spot-checked with no notable failures observed.

## Realistic constraint: dynamic access-level escalation

Simulated a real operational event: a customer's AML risk rating being raised following a compliance review, which should immediately restrict access to previously Internal-level content about that customer.

- **Before escalation:** a branch-officer-level query successfully retrieved the customer's routine call transcript (Internal access level)
- **Escalation triggered:** the document's access level was updated in place to AML-Confidential
- **After escalation:** the identical query, same role, retrieved zero content from that document; a compliance-officer-level query for the same content succeeded normally

This confirms the system respects a document's *current* classification rather than a static label assigned only at ingestion time.

## Known limitations

- Evaluated at a scale of 40 documents / ~100 chunks; retrieval behavior at enterprise scale (thousands of documents) is untested
- Generation quality was graded manually, not with an automated LLM-as-judge; this would be a natural next step
- The free-tier Gemini API's daily request quota (as low as 20 requests/day per model on some free-tier models) constrained how the 50-question evaluation could be run in a single session; a production system would need a paid tier or self-hosted model to avoid this
- Reranking latency was not benchmarked; acceptable for this project's scale but would need profiling before any real-time use

## Conclusion

The system demonstrates the core requirement of permission-aware retrieval: sensitive content is filtered before it ever reaches the language model, not after generation. Combined with conflict detection, refusal on missing information, and dynamic access-level updates, this addresses the central lesson that a good-looking answer is not the same as a trustworthy system.
