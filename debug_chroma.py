
import sys
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import json

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.memory.vector_store import ChromaVectorStore
from src.memory.embedding import SiliconFlowEmbeddings

# Mock requests
def mock_post(url, headers, json):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": [
            {"embedding": [0.1] * 1024} # Assuming 1024 dim
        ]
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp

@patch('requests.post', side_effect=mock_post)
def test_search(mock_post):
    print("Testing search with mocked requests...")
    
    config = {
        "vector_store_path": "./data/debug_chroma_db",
        "collection_name": "debug_collection",
        "embedding_model": "test_model",
        "api_key": "test_key"
    }
    
    try:
        store = ChromaVectorStore(config)
        
        # Add a doc first
        store.add_documents([MagicMock(get_content=lambda: "test", get_metadata=lambda: {})])
        
        # Search
        results = store.search("test query")
        print(f"Search results: {len(results)}")
        
    except Exception as e:
        print(f"Caught exception: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_search()
