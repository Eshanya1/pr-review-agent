import numpy as np

from pr_review_agent.rag.chunking import Chunk
from pr_review_agent.rag.vectorstore import VectorStore


def _chunk(id_: str) -> Chunk:
    return Chunk(id=id_, source=f"{id_}.py", kind="function", name=id_, text=f"body of {id_}")


def test_search_returns_closest_vector_first():
    chunks = [_chunk("a"), _chunk("b"), _chunk("c")]
    vectors = np.array(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [0.7, 0.7],
        ],
        dtype=np.float32,
    )
    store = VectorStore()
    store.build(chunks, vectors)

    results = store.search(np.array([1.0, 0.0], dtype=np.float32), k=2)
    assert results[0].chunk.id == "a"
    assert results[0].score > results[1].score


def test_search_on_empty_store_returns_nothing():
    store = VectorStore()
    results = store.search(np.array([1.0, 0.0], dtype=np.float32), k=5)
    assert results == []


def test_save_and_load_round_trip(tmp_path):
    chunks = [_chunk("a"), _chunk("b")]
    vectors = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    store = VectorStore()
    store.build(chunks, vectors)
    store.save(tmp_path / "index")

    assert VectorStore.exists(tmp_path / "index")
    loaded = VectorStore.load(tmp_path / "index")
    assert [c.id for c in loaded.chunks] == ["a", "b"]
    np.testing.assert_array_equal(loaded.vectors, vectors)
