import io
import unittest
from zipfile import ZipFile

from offline.import_data import read_series
from offline.split_data import SplitBoundaries


class ImportDataTests(unittest.TestCase):
    def test_utc_boundaries_are_inclusive_in_new_partition(self):
        bounds = SplitBoundaries.load()
        self.assertEqual(bounds.partition(bounds.validation_start), "validation")
        self.assertEqual(bounds.partition(bounds.test_start), "test")

    def test_invalid_and_conflicting_rows_keep_their_timestamp(self):
        bounds = SplitBoundaries.load()
        t = bounds.validation_start.timestamp()
        name = "t4.sensor.txt"
        data = f"% comments\nDateTime\tseconds1970\tT_Air\tT_Surf\tH_Air\n"
        data += f"local\t{t + 60}\t20\t8\tNaN\nlocal\t{t}\t20\t8\t50\n"
        data += f"local\t{t + 60}\t20\t8\tNaN\nlocal\t{t + 120}\t20\t8\t50\n"
        data += f"local\t{t + 120}\t21\t8\t50\nlocal\t{t - 60}\t20\t8\t50\n"
        stream = io.BytesIO()
        with ZipFile(stream, "w") as archive:
            archive.writestr(name, data)
        from collections import Counter
        counts = Counter()
        with ZipFile(stream) as archive:
            rows = list(read_series(archive, name, "T4.sensor", "t4", bounds, counts))
        self.assertEqual([row[8:10] for row in rows], [(1, ""), (0, "missing_measurement"),
                                                      (0, "conflicting_duplicate")])
        self.assertEqual(counts["duplicate_rows"], 2)
        self.assertEqual(counts["outside_period_partition"], 1)
