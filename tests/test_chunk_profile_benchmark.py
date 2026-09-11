"""Chunk-profile benchmark fixtures stay valid and discriminative."""

from evals.benchmark_chunk_profiles import context_contains_expected, fixed_chunks


def test_fixed_reference_windows_use_requested_size_and_overlap():
    text = "甲" * 700
    chunks = fixed_chunks(text, 500, 50)

    assert [len(chunk) for chunk in chunks] == [500, 250]
    assert chunks[0][-50:] == chunks[1][:50]


def test_context_completeness_normalizes_units_and_list_formatting():
    assert context_contains_expected("每日不超过 25 克。", "25g")
    assert context_contains_expected("包括鱼类、禽类、蛋类与瘦肉。", "鱼、禽、蛋、瘦肉")
