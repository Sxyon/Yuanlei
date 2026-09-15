"""知识库运行时单例。"""

import os

from yuxi.config import get_runtime_dir
from yuxi.knowledge.factory import KnowledgeBaseFactory
from yuxi.knowledge.implementations.dify import DifyKB
from yuxi.knowledge.implementations.milvus import MilvusKB
from yuxi.knowledge.implementations.notion import NotionKB
from yuxi.knowledge.manager import KnowledgeBaseManager

KnowledgeBaseFactory.register(MilvusKB)
KnowledgeBaseFactory.register(DifyKB)
KnowledgeBaseFactory.register(NotionKB)

knowledge_base = KnowledgeBaseManager(os.path.join(get_runtime_dir(), "knowledge_base_data"))
