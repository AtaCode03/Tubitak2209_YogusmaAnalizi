"""Aynı zaman bloğundaki sensör ve yöntem sonuçlarını birlikte örnekler."""

import numpy as np


def block_counts(times, labels, forest, threshold, start, blocks, block_seconds):
    ids = (np.asarray(times) - start) // block_seconds
    keep = (ids >= 0) & (ids < blocks)
    indices = ids[keep].astype(int)
    output = np.zeros((blocks, 2, 3), dtype=np.int64)
    target = labels[keep]
    for method, decisions in enumerate((forest[keep], threshold[keep])):
        for field, mask in enumerate((target & decisions, ~target & decisions, target & ~decisions)):
            np.add.at(output[:, method, field], indices[mask], 1)
    return output


def differences(counts):
    tp, fp, fn = np.moveaxis(counts, -1, 0)
    denominator = 2 * tp + fp + fn
    values = np.divide(2 * tp, denominator, out=np.full(denominator.shape, np.nan), where=denominator > 0)
    return values[..., 0] - values[..., 1]


def paired_bootstrap(counts, event_blocks, seed, minimum_event_blocks=20, repetitions=2000):
    blocks = len(counts)
    point = float(differences(counts.sum(axis=0)))
    result = dict(full_blocks=blocks, blocks_with_eligible_events=event_blocks,
                  f1_difference=point if np.isfinite(point) else None, interval_95=None, undefined_repetitions=None)
    if not blocks:
        return {**result, 'reason': 'no_full_blocks'}
    draws = np.random.default_rng(seed).integers(0, blocks, (repetitions, blocks))
    values = differences(counts[draws].sum(axis=1))
    valid = values[np.isfinite(values)]
    missing = repetitions - len(valid)
    result['undefined_repetitions'] = missing
    if event_blocks < minimum_event_blocks:
        return {**result, 'reason': 'insufficient_event_blocks'}
    if missing / repetitions >= 0.05:
        return {**result, 'reason': 'too_many_undefined_repetitions'}
    return {**result, 'interval_95': np.percentile(valid, [2.5, 97.5]).tolist()}


def time_block_analysis(times, labels, forest, threshold, event_times, start, observed_end, seed):
    day = 86400
    full_days = max(0, int((observed_end - start) // day))

    def evaluate(blocks, seconds, minimum):
        covered_end = start + blocks * seconds
        event_blocks = {int((time - start) // seconds) for time in event_times if start <= time < covered_end}
        counts = block_counts(times, labels, forest, threshold, start, blocks, seconds)
        return paired_bootstrap(counts, len(event_blocks), seed, minimum)

    primary = evaluate(full_days, day, 20)
    same_days = full_days - full_days % 2
    daily = evaluate(same_days, day, 20)
    longer = evaluate(same_days // 2, 2 * day, 0)
    interval = primary['interval_95']
    conclusion = 'hesaplanamadi' if interval is None else (
        'desteklendi' if interval[0] > 0 else 'desteklenmedi' if interval[1] < 0 else 'belirsiz')
    return dict(primary_24h=primary, sensitivity_same_period_24h=daily, sensitivity_48h=longer, conclusion=conclusion)
