from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, List

class GraphEntityType(str, Enum):
    PERSON = "Person",
    SINGER = "Singer",
    SONG = "Song",
    ALBUM = "Album",
    EVENT = "Event",
    LOCATION = "Location",
    ORGANIZATION = "Organization",
    YEAR = "Year",
    GLORY = "Glory",

class GraphRelationType(str, Enum):
    PRODUCED_BY = "produced_by"
    LYRICS_BY = "lyrics_by"
    COMPOSED_BY = "composed_by"
    ARRANGED_BY = "arranged_by"
    SUNG_BY = "sung_by"
    IN_ALBUM = "in_album"
    RELEASED_IN = "released_in"
    WIN_AWARD = "win_award"
    PERFORMED_AT = "performed_at"

entity_name_back_dict = {
    "person": GraphEntityType.PERSON,
    "singer": GraphEntityType.SINGER,
    "song": GraphEntityType.SONG,
    "album": GraphEntityType.ALBUM,
    "event": GraphEntityType.EVENT,
    "location": GraphEntityType.LOCATION,
    "organization": GraphEntityType.ORGANIZATION,
    "year": GraphEntityType.YEAR,
    "glory": GraphEntityType.GLORY,
}

relation_name_back_dict = {
    "UP主": GraphRelationType.PRODUCED_BY,
    "作词": GraphRelationType.LYRICS_BY,
    "作曲": GraphRelationType.COMPOSED_BY,
    "编曲": GraphRelationType.ARRANGED_BY,
    "歌手": GraphRelationType.SUNG_BY,
    "演唱过的活动": GraphRelationType.PERFORMED_AT,
    "收录专辑": GraphRelationType.IN_ALBUM,
}

point_to_entity_type = {
    GraphRelationType.PRODUCED_BY: GraphEntityType.PERSON,
    GraphRelationType.LYRICS_BY: GraphEntityType.PERSON,
    GraphRelationType.COMPOSED_BY: GraphEntityType.PERSON,
    GraphRelationType.ARRANGED_BY: GraphEntityType.PERSON,
    GraphRelationType.SUNG_BY: GraphEntityType.SINGER,
    GraphRelationType.IN_ALBUM: GraphEntityType.ALBUM,
    GraphRelationType.RELEASED_IN: GraphEntityType.YEAR,
    GraphRelationType.WIN_AWARD: GraphEntityType.GLORY,
    GraphRelationType.PERFORMED_AT: GraphEntityType.EVENT,
}

@dataclass
class Entity:
    """实体类"""
    id: str
    name: str
    entity_type: GraphEntityType
    properties: Dict[str, Any]
    
    def __hash__(self):
        return hash(self.id)


@dataclass
class Relation:
    """关系类"""
    id: str
    source_id: str
    target_id: str
    relation_type: GraphRelationType
    properties: Dict[str, Any]
    weight: float = 1.0


@dataclass
class GraphNode:
    """图节点"""
    entity: Entity
    neighbors: List["GraphNode"]
    
    def __hash__(self):
        return hash(self.entity.id)