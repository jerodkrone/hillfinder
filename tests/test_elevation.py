from app.services.elevation import _chunk_coordinates


def test_chunk_coordinates_count():
    coords = [(float(i), float(i)) for i in range(1100)]
    chunks = _chunk_coordinates(coords, chunk_size=500)
    assert len(chunks) == 3


def test_chunk_coordinates_boundary_overlap():
    coords = [(float(i), float(i)) for i in range(1100)]
    chunks = _chunk_coordinates(coords, chunk_size=500)
    assert chunks[0][-1] == chunks[1][0], "Boundary overlap missing between chunks 0 and 1"
    assert chunks[1][-1] == chunks[2][0], "Boundary overlap missing between chunks 1 and 2"


def test_chunk_coordinates_reassembly_count():
    coords = [(float(i), float(i)) for i in range(1100)]
    chunks = _chunk_coordinates(coords, chunk_size=500)
    total = len(chunks[0]) + sum(len(c) - 1 for c in chunks[1:])
    assert total == 1100, f"Reassembly count mismatch: {total}"


def test_chunk_coordinates_under_chunk_size():
    coords = [(float(i), float(i)) for i in range(100)]
    chunks = _chunk_coordinates(coords, chunk_size=500)
    assert len(chunks) == 1
    assert chunks[0] == coords


def test_chunk_coordinates_501_stays_within_limit():
    # Regression: 501 coords triggered the tail-absorption guard on the first chunk,
    # placing all 501 points in one chunk and exceeding ORS's 500-point hard limit.
    coords = [(float(i), float(i)) for i in range(501)]
    chunks = _chunk_coordinates(coords, chunk_size=500)
    assert len(chunks) == 2, f"Expected 2 chunks, got {len(chunks)}"
    assert len(chunks[0]) == 500, "First chunk must not exceed chunk_size"
    total = len(chunks[0]) + sum(len(c) - 1 for c in chunks[1:])
    assert total == 501, f"Reassembly count mismatch: {total}"


def test_chunk_coordinates_exact_multiple():
    # 1000 coords with chunk_size=500: the trailing 1-new-point chunk must be absorbed
    coords = [(float(i), float(i)) for i in range(1000)]
    chunks = _chunk_coordinates(coords, chunk_size=500)
    assert len(chunks) == 2, f"Expected 2 chunks, got {len(chunks)}"
    assert chunks[0][-1] == chunks[1][0], "Boundary overlap missing between chunks"
    total = len(chunks[0]) + sum(len(c) - 1 for c in chunks[1:])
    assert total == 1000, f"Reassembly count mismatch: {total}"
