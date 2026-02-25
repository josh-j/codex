"""Tests for csv_export module."""

import csv


from ncs_reporter.csv_export import export_csv, header_to_key


class TestHeaderToKey:
    def test_simple(self):
        assert header_to_key("App Name") == "app_name"

    def test_single_word(self):
        assert header_to_key("Server") == "server"

    def test_multiple_spaces(self):
        assert header_to_key("Current  Version") == "current_version"

    def test_leading_trailing_spaces(self):
        assert header_to_key("  Publisher  ") == "publisher"


class TestExportCsv:
    def _read_csv(self, path):
        with open(path, newline="") as f:
            return list(csv.reader(f))

    def test_basic_export(self, tmp_path):
        rows = [
            {"server": "host1", "app_name": "Foo", "version": "1.0"},
            {"server": "host1", "app_name": "Bar", "version": "2.0"},
        ]
        headers = ["Server", "App Name", "Version"]
        out = tmp_path / "report.csv"
        export_csv(rows, headers, out)
        result = self._read_csv(out)
        assert result[0] == ["Server", "App Name", "Version"]
        assert len(result) == 3

    def test_sort_by(self, tmp_path):
        rows = [
            {"app_name": "Zeta", "version": "1"},
            {"app_name": "Alpha", "version": "2"},
        ]
        headers = ["App Name", "Version"]
        out = tmp_path / "sorted.csv"
        export_csv(rows, headers, out, sort_by="App Name")
        result = self._read_csv(out)
        assert result[1][0] == "Alpha"
        assert result[2][0] == "Zeta"

    def test_list_value_joining(self, tmp_path):
        rows = [{"tags": ["a", "b", "c"], "name": "x"}]
        headers = ["Name", "Tags"]
        out = tmp_path / "lists.csv"
        export_csv(rows, headers, out)
        result = self._read_csv(out)
        assert result[1][1] == "a; b; c"

    def test_commas_and_quotes_escaped(self, tmp_path):
        rows = [{"name": 'Foo, "Bar"', "version": "1.0"}]
        headers = ["Name", "Version"]
        out = tmp_path / "escape.csv"
        export_csv(rows, headers, out)
        result = self._read_csv(out)
        assert result[1][0] == 'Foo, "Bar"'

    def test_empty_data_header_only(self, tmp_path):
        out = tmp_path / "empty.csv"
        export_csv([], ["A", "B"], out)
        result = self._read_csv(out)
        assert len(result) == 1
        assert result[0] == ["A", "B"]

    def test_missing_key_produces_blank(self, tmp_path):
        rows = [{"app_name": "Foo"}]
        headers = ["App Name", "Version"]
        out = tmp_path / "missing.csv"
        export_csv(rows, headers, out)
        result = self._read_csv(out)
        assert result[1] == ["Foo", ""]

    def test_custom_key_map(self, tmp_path):
        rows = [{"custom_key": "val"}]
        headers = ["My Header"]
        out = tmp_path / "keymap.csv"
        export_csv(rows, headers, out, key_map={"My Header": "custom_key"})
        result = self._read_csv(out)
        assert result[1][0] == "val"

    def test_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "deep" / "nested" / "report.csv"
        export_csv([], ["A"], out)
        assert out.exists()

    def test_newline_stripping(self, tmp_path):
        rows = [{"name": "line1\nline2\r\nline3"}]
        headers = ["Name"]
        out = tmp_path / "newlines.csv"
        export_csv(rows, headers, out)
        result = self._read_csv(out)
        assert result[1][0] == "line1 line2 line3"
