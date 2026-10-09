from threading import Lock
import chromadb
from chromadb.config import Settings as ChromaSettings
from app.config import settings


class VectorStore:
    def __init__(self, path=None, embedder=None):
        self.path = path or settings.chroma_path
        self._client = None
        self._model = embedder
        self._lock = Lock()

    @property
    def client(self):
        with self._lock:
            if self._client is None:
                self._client = chromadb.PersistentClient(path=self.path, settings=ChromaSettings(anonymized_telemetry=False))
            return self._client

    def collection(self, name):
        return self.client.get_or_create_collection(name, embedding_function=None, configuration={'hnsw': {'space': 'cosine'}})

    def encode(self, texts):
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(settings.embedding_model, device=settings.embedding_device)
            vectors = self._model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()

    def upsert(self, name, id, text, metadata):
        collection = self.collection(name)
        old = collection.get(ids=[id], include=['metadatas'])
        # MySQL 成功而向量写入失败时，下次仍会补写，不能只比较 MySQL 的 hash。
        if old['ids'] and old['metadatas'][0].get('content_hash') == metadata['content_hash']:
            return
        vector = self.encode([text])
        if len(vector[0]) != settings.embedding_dimension:
            raise ValueError('Embedding 维度与配置不一致，必须使用新的 Collection')
        collection.upsert(ids=[id], documents=[text], embeddings=vector, metadatas=[metadata])

    def query(self, name, query, where=None, limit=30):
        collection = self.collection(name)
        count = collection.count()
        if not count:
            return []
        result = collection.query(query_embeddings=self.encode([query]), where=where, n_results=min(limit, count), include=['documents', 'metadatas', 'distances'])
        return [{'evidence_id': id, 'text': text, 'metadata': meta, 'score': 1 - distance}
                for id, text, meta, distance in zip(result['ids'][0], result['documents'][0], result['metadatas'][0], result['distances'][0])]


vectors = VectorStore()
