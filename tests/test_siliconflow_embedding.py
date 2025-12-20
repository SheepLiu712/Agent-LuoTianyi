
import unittest
from unittest.mock import MagicMock, patch
import sys
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.memory.embedding import SiliconFlowEmbeddings

class TestSiliconFlowEmbeddings(unittest.TestCase):
    def setUp(self):
        self.api_key = "test_key"
        self.embeddings = SiliconFlowEmbeddings(api_key=self.api_key)

    @patch('requests.post')
    def test_embed_single_string(self, mock_post):
        # Mock response for single string
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2, 0.3]}
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = self.embeddings.embed_query("test")
        
        self.assertEqual(result, [0.1, 0.2, 0.3])
        # Verify payload
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs['json']['input'], "test")

    @patch('requests.post')
    def test_embed_list_strings(self, mock_post):
        # Mock response for list of strings
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": [
                {"embedding": [0.1, 0.2, 0.3]},
                {"embedding": [0.4, 0.5, 0.6]}
            ]
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        input_list = ["test1", "test2"]
        result = self.embeddings.embed_query(input_list)
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], [0.1, 0.2, 0.3])
        self.assertEqual(result[1], [0.4, 0.5, 0.6])
        
        # Verify payload
        args, kwargs = mock_post.call_args
        self.assertEqual(kwargs['json']['input'], input_list)

if __name__ == '__main__':
    unittest.main()
