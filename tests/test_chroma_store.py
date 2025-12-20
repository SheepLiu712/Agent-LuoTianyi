
import unittest
from unittest.mock import MagicMock, patch
import sys
import os
from pathlib import Path
import shutil

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.memory.vector_store import ChromaVectorStore, Document
from chromadb.api.types import Documents, Embeddings

class MockEmbeddingFunction:

    def __call__(self, input: Documents) -> Embeddings:
        return [[0.1] * 384 for _ in input]
    
    def embed_documents(self, texts):
        return self(texts)
        
    def embed_query(self, *args, **kwargs):
        input_val = kwargs.get('input')
        if input_val is None and args:
            input_val = args[0]
            
        if isinstance(input_val, list):
             return [[0.1] * 384 for _ in input_val]
        return [0.1] * 384
        
    @staticmethod
    def name():
        return "mock_embedding_function"
    
    def is_legacy(self):
        return False

import uuid

class TestChromaVectorStore(unittest.TestCase):
    def setUp(self):
        self.test_dir = f"./data/test_chroma_db_{uuid.uuid4()}"
        self.config = {
            "vector_store_path": self.test_dir,
            "collection_name": "test_collection",
            "embedding_model": "test_model",
            "api_key": "test_key"
        }
        
        # Patch SiliconFlowEmbeddings
        self.patcher = patch('src.memory.vector_store.SiliconFlowEmbeddings')
        self.MockEmbeddingsClass = self.patcher.start()
        
        # Setup mock instance to be our custom class with correct signature
        self.MockEmbeddingsClass.return_value = MockEmbeddingFunction()

    def tearDown(self):
        self.patcher.stop()
        # Clean up test directory
        # Force close any open handlers if possible (Chroma client might hold file lock)
        # In a real scenario we might need to close the client explicitly if exposed
        import gc
        gc.collect() 
        
        if os.path.exists(self.test_dir):
            try:
                shutil.rmtree(self.test_dir)
            except Exception as e:
                print(f"Failed to delete test dir: {e}")

    def test_add_search_delete(self):
        print("\nTesting ChromaVectorStore...")
        store = ChromaVectorStore(self.config)
        
        # Test Add
        print("Testing add_documents...")
        docs = [
            Document(content="Hello world", metadata={"source": "test"}),
            Document(content="Luo Tianyi is a singer", metadata={"source": "vocaloid"})
        ]
        ids = store.add_documents(docs)
        self.assertEqual(len(ids), 2)
        print(f"Added {len(ids)} documents.")
        
        # Test Search
        print("Testing search...")
        # Since embeddings are mocked to be identical, search results order depends on Chroma's internal logic
        # But we should get results.
        results = store.search("Tianyi", k=2)
        self.assertEqual(len(results), 2)
        print(f"Search returned {len(results)} results.")
        
        # Test Delete
        print("Testing delete_documents...")
        print(f"IDs to delete: {ids}")
        success = store.delete_documents(ids)
        self.assertTrue(success)
        print("Deleted documents.")
        
        print(f"Collection count after delete: {store.collection.count()}")
        
        # Verify deletion
        results_after = store.search("Tianyi", k=2)
        print(f"Results after delete: {len(results_after)}")
        self.assertEqual(len(results_after), 0)
        print("Verified deletion (search returned 0 results).")

if __name__ == '__main__':
    unittest.main()
