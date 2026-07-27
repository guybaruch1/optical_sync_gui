from gui.widgets.stats_panel import StatsPanel


def test_add_field_and_set_value_updates_label_text(qapp):
    panel = StatsPanel()
    panel.add_field("frame_index", "Frame Index")
    panel.set_value("frame_index", 42)
    assert "42" in panel._value_labels["frame_index"].text()


def test_set_value_on_unregistered_key_is_ignored(qapp):
    panel = StatsPanel()
    panel.set_value("nonexistent", 123)  # must not raise


def test_multiple_fields_are_independent(qapp):
    panel = StatsPanel()
    panel.add_field("pairing_gap_us", "Pairing Gap (us)")
    panel.add_field("switch_time_ms", "Switch Time (ms)")
    panel.set_value("pairing_gap_us", -12.5)
    panel.set_value("switch_time_ms", 1.0)
    assert "-12.5" in panel._value_labels["pairing_gap_us"].text()
    assert "1.0" in panel._value_labels["switch_time_ms"].text()


def test_add_section_header_does_not_raise_and_is_a_separate_widget(qapp):
    panel = StatsPanel()
    panel.add_section_header("Live Data")
    panel.add_field("frame_index", "Frame Index")
    panel.add_section_header("Stats")
    panel.add_field("hw_ts_sync_summary", "HW TS Sync avg / std / max")
    # 2 headers + 2 field tiles = 4 top-level items in the layout
    assert panel._layout.count() == 4
    assert panel._value_labels["hw_ts_sync_summary"].text() == "-"
