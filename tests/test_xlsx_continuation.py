import zipfile
from xml.etree import ElementTree as ET

import pytest

from tv_scan_studio.export import export_task_xlsx, _xlsx_cell, _XLSX_STYLES, _xlsx_width


def cells(sheet):
    return {c.attrib['r']: c.find('{*}is/{*}t').text or ''
            for c in sheet.findall('.//{*}c') if c.find('{*}is/{*}t') is not None}


@pytest.mark.parametrize('text', ['=' + 'x' * 96000, '😀' * 20000,
                                 ('line\n' * 400), ('line\r\n' * 400),
                                 ' ' + 'x' * 32767 + ' '],
                         ids=['ascii', 'nonbmp', 'newlines', 'crlf', 'spaces'])
def test_long_text_preserved_in_ordered_associated_details(tmp_path, text):
    record = {'task_id': 7, 'task_key': 'stable', 'status': 'failed',
              'classification': 'sonuç yok', 'error': text,
              'verified': False, 'attempts': 1, 'started_at': None, 'finished_at': None,
              'payload': {}, 'metrics': {}, 'evidence': {}}
    path = tmp_path / 'long.xlsx'
    assert export_task_xlsx(iter([record]), path, []) == 1
    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        assert [s.attrib['name'] for s in workbook.findall('.//{*}sheet')] == ['Tarama 1', 'Teknik ayrıntılar']
        main = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        values = cells(main)
        error_header = next(ref for ref, value in values.items() if value == 'error')
        assert values[error_header[:-1] + '2'].startswith('[Tam metin: Teknik ayrıntılar;')
        detail = ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
        chunks = []
        for row in detail.findall('.//{*}row')[1:]:
            number = row.attrib['r']
            strings = cells(row)
            assert strings['A' + number] == 'Tarama 1'
            assert row.find(f"{{*}}c[@r='B{number}']/{{*}}v").text == '2'
            assert strings['C' + number] == 'error'
            assert row.find(f"{{*}}c[@r='F{number}']/{{*}}v").text == '7'
            assert strings['G' + number] == 'stable'
            assert int(row.find(f"{{*}}c[@r='D{number}']/{{*}}v").text) == len(chunks) + 1
            chunks.append(strings['E' + number])
        assert ''.join(chunks) == text
        for sheet in (main, detail):
            assert sheet.find('.//{*}f') is None  # Literal '=' cannot become a formula.
            for value in cells(sheet).values():
                assert len(value.encode('utf-16-le')) // 2 <= 32767
                assert value.count('\n') <= 253


def test_empty_export_has_no_continuation_artifact(tmp_path):
    path = tmp_path / 'empty.xlsx'
    assert export_task_xlsx([], path, []) == 0
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        assert len(workbook.findall('.//{*}sheet')) == 1
        assert 'xl/worksheets/sheet2.xml' not in archive.namelist()


def test_header_limit_fails_explicitly_and_xml_character_sanitization_is_unchanged():
    with pytest.raises(ValueError, match='Excel hücre metni sınırı'):
        _xlsx_cell('A1', 'x' * 32768, header=True)
    cell = ET.fromstring(_xlsx_cell('A1', 'a\x00\ud800\ufffeb\r\n'))
    assert cell.find('is/t').text == 'ab\r\n'


def test_legacy_non_scalar_text_is_continued(tmp_path):
    error = {'legacy': 'x' * 40000}
    record = {'task_id': 7, 'task_key': 'stable', 'status': 'failed',
              'classification': 'sonuç yok', 'error': error,
              'verified': False, 'attempts': 1, 'started_at': None, 'finished_at': None,
              'payload': {}, 'metrics': {}, 'evidence': {}}
    path = tmp_path / 'legacy.xlsx'
    assert export_task_xlsx([record], path, []) == 1
    with zipfile.ZipFile(path) as archive:
        details = ET.fromstring(archive.read('xl/worksheets/sheet2.xml'))
        assert ''.join(cells(row)['E' + row.attrib['r']]
                       for row in details.findall('.//{*}row')[1:]) == str(error)


def test_excel_reserved_fill_slots_and_readable_detail_widths():
    styles = ET.fromstring(_XLSX_STYLES)
    fills = styles.find('{*}fills')
    assert fills.attrib['count'] == '3'
    assert [fill.find('{*}patternFill').attrib['patternType'] for fill in fills] == [
        'none', 'gray125', 'solid']
    assert styles.find('{*}cellXfs')[1].attrib['fillId'] == '2'
    assert _xlsx_width('Metin') == 48
    assert _xlsx_width('Alan') == _xlsx_width('Görev anahtarı') == 28
    assert _xlsx_width('net_profit') == 16
