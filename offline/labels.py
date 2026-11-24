"""Adım 3: risk olayları ve ham pozitif ölçümlerin referans etiketleri."""

import argparse
import csv
import json
from bisect import bisect_right
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
from itertools import groupby
from pathlib import Path

from offline.events import Sample, continuity_blocks, find_events
from offline.import_data import publish_file
from offline.split_data import RESEARCH_CONFIG, SplitBoundaries

ROOT = RESEARCH_CONFIG.parents[1]
PARTITIONS = ("train", "validation", "test")


def label_at(timestamp, horizon_seconds, duration_seconds, block_end, partition_end, event_starts):
    horizon_end = timestamp + horizon_seconds
    coverage_end = horizon_end + duration_seconds
    if partition_end is not None and coverage_end >= partition_end:
        return None, "partition_boundary"
    if block_end < coverage_end:
        return None, "incomplete_followup"
    index = bisect_right(event_starts, timestamp)
    return int(index < len(event_starts) and event_starts[index] <= horizon_end), ""


def series_from_csv(path):
    with path.open(encoding="utf-8", newline="") as stream:
        for series_id, rows in groupby(csv.DictReader(stream), key=lambda row: row["series_id"]):
            yield series_id, [Sample(datetime.fromisoformat(row["timestamp"]).timestamp(),
                                     float(row["dpu_c"]) if row["valid"] == "1" else None) for row in rows]


def utc(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat() if timestamp is not None else ""


def process_partition(source, partition, partition_end, settings, event_writer, label_writer):
    horizons = settings["horizons_minutes"]
    primary = settings["event_min_duration_seconds"]
    durations = [primary, *settings["alternative_event_durations_seconds"]]
    counts = {duration: {"events": 0, "labels": {h: Counter() for h in horizons}} for duration in durations}
    series_intervals = {}
    for series_id, samples in series_from_csv(source):
        nominal, blocks = continuity_blocks(samples, settings["max_measurement_age_median_multiplier"])
        series_intervals[series_id] = nominal
        for block in blocks:
            events_by_duration = {duration: find_events(block, duration) for duration in durations}
            starts = {duration: [event.start for event in events] for duration, events in events_by_duration.items()}
            for duration, events in events_by_duration.items():
                counts[duration]["events"] += len(events)
                event_writer.writerows((partition, series_id, duration, utc(event.start), utc(event.confirmed),
                                        utc(event.end), utc(event.previous_nonnegative)) for event in events)
            for sample in block:
                if sample.dpu <= 0:
                    continue
                primary_results = []
                for duration in durations:
                    for h in horizons:
                        label, issue = label_at(sample.timestamp, h * 60, duration, block[-1].timestamp,
                                                partition_end, starts[duration])
                        counts[duration]["labels"][h][issue or ("positive" if label == 1 else "negative")] += 1
                        if duration == primary:
                            primary_results.extend((label, issue))
                label_writer.writerow((partition, series_id, utc(sample.timestamp), *primary_results))
    return {"median_interval_seconds_by_series": series_intervals, "by_event_duration_seconds": counts}


def build_labels(source, output):
    settings = json.loads(RESEARCH_CONFIG.read_text(encoding="utf-8"))
    boundaries = SplitBoundaries.load()
    ends = (boundaries.validation_start.timestamp(), boundaries.test_start.timestamp(), None)
    output.mkdir(parents=True, exist_ok=True)
    with ExitStack() as stack:
        def writer(name):
            return csv.writer(stack.enter_context((output / f"{name}.tmp").open("w", encoding="utf-8", newline="")))

        event_writer = writer("risk_events.csv")
        event_writer.writerow(("partition", "series_id", "duration_seconds", "start_utc", "confirmed_utc",
                               "last_negative_utc", "previous_nonnegative_utc"))
        label_writer = writer("reference_labels.csv")
        label_writer.writerow(("partition", "series_id", "timestamp", *(field for h in settings["horizons_minutes"]
                                for field in (f"label_{h}m", f"issue_{h}m"))))
        report = {partition: process_partition(source / f"{partition}.csv", partition, end, settings,
                                               event_writer, label_writer)
                  for partition, end in zip(PARTITIONS, ends, strict=True)}
    (output / "label_report.json.tmp").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for name in ("risk_events.csv", "reference_labels.csv", "label_report.json"):
        publish_file(output / f"{name}.tmp", output / name)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/processed")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed")
    args = parser.parse_args()
    report = build_labels(args.source, args.output)
    print(json.dumps({split: result["by_event_duration_seconds"] for split, result in report.items()}, indent=2))


if __name__ == "__main__":
    main()
