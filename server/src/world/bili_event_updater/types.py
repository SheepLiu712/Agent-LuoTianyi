from dataclasses import dataclass
from typing import List, Optional

@dataclass
class OfficialDynamic:
    uid: str
    account_name: str
    character: str
    platform: str
    dynamic_id: str
    dynamic_type: str
    content: str
    raw_content: str
    pics: List[str]
    publish_time: str
    source_url: str

    def __repr__(self):
        return f"OfficialDynamic(uid={self.uid}, platform={self.platform}, dynamic_id={self.dynamic_id}, content={self.content[:30]}...)"