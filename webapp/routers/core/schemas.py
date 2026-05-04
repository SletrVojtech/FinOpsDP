from pydantic import BaseModel
from typing import List, Optional, Any

class RootEntity(BaseModel):
    id: int
    name: str
    provider: Optional[str] = None
    has_children: bool

class ChildEntity(BaseModel):
    id: int
    name: str
    type: str
    has_children: bool

class RootsResponse(BaseModel):
    status: str
    data: List[RootEntity]

class ChildrenResponse(BaseModel):
    status: str
    data: List[ChildEntity]

class TagValue(BaseModel):
    value: str
    count: int

class TagValuesResponse(BaseModel):
    status: str
    data: List[TagValue]

class TagRule(BaseModel):
    id: int
    pattern: str

class TagRulesResponse(BaseModel):
    status: str
    data: List[TagRule]

class CreateTagRuleRequest(BaseModel):
    pattern: str

class SuccessResponse(BaseModel):
    status: str
