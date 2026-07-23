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
