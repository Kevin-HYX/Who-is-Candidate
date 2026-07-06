# Use in-memory brute-force retrieval for candidate search

Search embeds each soft-preference query text at request time, loads the local embedding cache, and computes similarity against all indexed candidates in memory. The project targets candidate sets around the thousand-record scale, so a vector database, ANN index, or external retrieval service would add operational complexity without solving a current scale problem.

Build Index still precomputes candidate-side embeddings, but retrieval itself is a deterministic local pass over those embeddings. Search does not use a thread pool for recall/ranking; concurrency controls belong to CLI build steps that call LLM or embedding models.

