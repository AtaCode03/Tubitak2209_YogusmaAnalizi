"""Mendeley v2 arşivinden zaman sıralı, bölüm bazlı ölçüm CSV'leri üretir."""

import argparse
import csv
import io
import json
import re
import time
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from zipfile import ZipFile

from offline.split_data import SplitBoundaries
from offline.validate_data import parse_timestamp, parse_values

PERIOD_PARTITION = {"t2": "train", "t3": "train", "t4": "validation", "t5": "test"}
FIELDS = ("series_id", "source_period", "timestamp", "air_temperature_c", "relative_humidity_pct",
          "surface_temperature_c", "dew_point_c", "dpu_c", "valid", "issue", "source_line")
ROOT = Path(__file__).resolve().parents[1]


def publish_file(temporary, destination):
    for attempt in range(6):
        try:
            temporary.replace(destination)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) != 32 or attempt == 5:
                raise
            time.sleep(0.2 * (attempt + 1))


def series_files(archive, period):
    prefix = f"TTH_ColdRoom/{period}/{period}."
    members = {re.sub(r"[^a-z0-9]", "", path[len(prefix):-4].lower()): path
               for path in archive.namelist() if path.startswith(prefix) and path.endswith(".txt")}
    sensor_list = prefix + "_SensorList.txt"
    with archive.open(sensor_list) as raw:
        for line in io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace"):
            fields = line.split("\t")
            if len(fields) < 5 or fields[4].strip().lower() != "y":
                continue
            device = fields[0].strip()
            key = re.sub(r"[^a-z0-9]", "", device.lower())
            yield device, members.get(key)


def read_series(archive, member, series_id, period, boundaries, counts):
    rows = {}
    columns = ("seconds1970", "T_Air", "T_Surf", "H_Air")
    with archive.open(member) as raw:
        reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace"), delimiter="\t")
        indices = None
        for line_number, fields in enumerate(reader, 1):
            if not fields or not any(field.strip() for field in fields):
                continue
            fields = [field.strip() for field in fields]
            if indices is None:
                if all(name in fields for name in columns):
                    indices = [fields.index(name) for name in columns]
                elif not fields[0].startswith("%"):
                    raise ValueError(f"{member}: gerekli başlıklar yok: {columns}")
                continue
            if fields[0].startswith("%"):
                continue
            try:
                timestamp = parse_timestamp(fields[indices[0]])
            except (IndexError, ValueError, OverflowError, OSError):
                raise ValueError(f"{member}:{line_number}: geçersiz zaman, satır konumlandırılamadı") from None
            partition = boundaries.partition(timestamp)
            if partition != PERIOD_PARTITION[period]:
                counts["outside_period_partition"] += 1
                continue
            values = tuple(fields[i] if i < len(fields) else "" for i in indices[1:])
            if timestamp in rows:
                counts["duplicate_rows"] += 1
                first_values, first_line, conflicted = rows[timestamp]
                rows[timestamp] = first_values, first_line, conflicted or values != first_values
            else:
                rows[timestamp] = values, line_number, False
        if indices is None:
            raise ValueError(f"{member}: ölçüm başlığı bulunamadı")

    for timestamp, (values, line_number, conflicted) in sorted(rows.items()):
        result, issue = (None, "conflicting_duplicate") if conflicted else parse_values(
            series_id, timestamp, *values)
        counts[issue or "valid"] += 1
        numbers = [""] * 5
        if result is not None:
            measurement = result.measurement
            numbers = [measurement.air_temperature_c, measurement.relative_humidity_pct,
                       measurement.surface_temperature_c, result.dew_point_c, result.dpu_c]
        yield (series_id, period.upper(), timestamp.isoformat(), *numbers, int(result is not None), issue, line_number)


def import_archive(source: Path, output: Path):
    boundaries = SplitBoundaries.load()
    output.mkdir(parents=True, exist_ok=True)
    report = {"series": {}, "missing_sensor_files": [], "partitions": {}}
    names = ("train", "validation", "test")
    with ZipFile(source) as archive, ExitStack() as files:
        writers = {name: csv.writer(files.enter_context((output / f"{name}.csv.tmp").open(
            "w", encoding="utf-8", newline=""))) for name in names}
        for writer in writers.values():
            writer.writerow(FIELDS)
        for period, partition in PERIOD_PARTITION.items():
            totals = Counter(report["partitions"].get(partition, {}))
            for device, member in sorted(series_files(archive, period)):
                series_id = f"{period.upper()}.{device}"
                if member is None:
                    report["missing_sensor_files"].append(series_id)
                    continue
                counts = Counter()
                writers[partition].writerows(read_series(archive, member, series_id, period, boundaries, counts))
                report["series"][series_id] = dict(counts)
                totals.update(counts)
                totals["series"] += 1
            report["partitions"][partition] = dict(totals)
    report_path = output / "import_report.json.tmp"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for name in names:
        publish_file(output / f"{name}.csv.tmp", output / f"{name}.csv")
    publish_file(report_path, output / "import_report.json")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/raw/TTH_ColdRoom_June19.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "data/processed")
    args = parser.parse_args()
    report = import_archive(args.source, args.output)
    print(json.dumps(report["partitions"], indent=2))


if __name__ == "__main__":
    main()
