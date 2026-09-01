import asyncio
import os
import uuid
from pathlib import Path

from app.services.document_extractor import DocumentExtractor
from app.services.chunker import MarkdownChunker
from app.services.llm.router import LLMRouter
from app.services.retrieval.pinecone_store import PineconeStore
from app.schemas.retrieval import ChunkData
from app.config import settings

async def main():
    base_docs_dir = Path(__file__).parent.parent / "base_documents"
    if not base_docs_dir.exists():
        print(f"Directory not found: {base_docs_dir}")
        return

    extractor = DocumentExtractor()
    chunker = MarkdownChunker(chunk_size=2400, overlap=400)
    llm_router = LLMRouter()
    pinecone_store = PineconeStore(
        api_key=settings.pinecone_api_key, 
        index_name=settings.pinecone_index_name
    )
    
    namespace = "cbuae-manuals"
    
    # First, let's make sure the namespace is clear or we just append
    # pinecone_store.delete_namespace(namespace)

    for pdf_file in base_docs_dir.glob("*.pdf"):
        print(f"Processing {pdf_file.name}...")
        
        with open(pdf_file, "rb") as f:
            file_bytes = f.read()
            
        print("Extracting markdown...")
        markdown_text = await extractor.extract_to_markdown(file_bytes, pdf_file.name)
        
        print("Chunking...")
        raw_chunks = chunker.chunk(markdown_text)
        
        # Prepare ChunkData
        chunk_data_list = []
        for i, text in enumerate(raw_chunks):
            # Parse section if we prepended it with ">"
            section = f"Chunk {i}"
            if ":" in text and " > " in text.split(":")[0]:
                section = text.split(":")[0]
                
            chunk_data_list.append(ChunkData(
                source=pdf_file.name,
                section=section,
                text=text,
                page=None
            ))
            
        print(f"Extracted {len(chunk_data_list)} chunks. Embedding and Upserting...")
        
        # Process in batches
        batch_size = 50
        for i in range(0, len(chunk_data_list), batch_size):
            batch = chunk_data_list[i:i+batch_size]
            texts_to_embed = [c.text for c in batch]
            
            embeddings = await llm_router.embed(texts_to_embed, input_type="document")
            
            ids = [str(uuid.uuid4()) for _ in batch]
            
            pinecone_store.upsert_vectors(
                ids=ids,
                vectors=embeddings,
                chunks=batch,
                namespace=namespace
            )
            print(f"Upserted batch {i//batch_size + 1}/{(len(chunk_data_list)-1)//batch_size + 1}")

    print("Indexing complete.")

if __name__ == "__main__":
    asyncio.run(main())
