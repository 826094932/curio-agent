"""Download or warm the configured embedding model and validate its dimension."""
from app.db.chroma import vectors
from app.config import settings

if __name__ == '__main__':
    result = vectors.encode(['电子产品规格与使用体验'])
    if len(result[0]) != settings.embedding_dimension:
        raise SystemExit('Embedding dimension mismatch')
    print(f'Embedding ready: {settings.embedding_model}, dimension={len(result[0])}')
