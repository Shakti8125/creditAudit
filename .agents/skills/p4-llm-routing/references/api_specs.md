# LLM Provider API Specifications and Constants

## NVIDIA Provider
**Base URL:** `https://integrate.api.nvidia.com/v1`

### Model Constants
- **Generation Model:** `nvidia/llama-3.1-nemotron-70b-instruct`
- **Embedding Model:** `nvidia/nv-embedqa-e5-v5`
- **Reranking Model:** `nvidia/nv-rerankqa-mistral-4b-v3`

### Reranking API Endpoint (NVIDIA)
- **Method:** POST
- **Endpoint:** `/v1/ranking`
- **Payload Structure:**
  ```json
  {
    "model": "nvidia/nv-rerankqa-mistral-4b-v3",
    "query": "Your search query",
    "passages": ["Passage 1 text", "Passage 2 text"]
  }
  ```

---

## Gemini Provider

### Model Constants (Must be pinned as module-level constants)
- **Generation Model:** `gemini-2.0-flash`
- **Embedding Model:** `models/text-embedding-004`
- **Reranking Model:** (No native reranker, fallback to using `gemini-2.0-flash` with a custom prompt evaluating relevance scores).
