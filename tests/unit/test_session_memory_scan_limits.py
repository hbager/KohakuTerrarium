from kohakuterrarium.session.memory import SessionMemory


class _FakeFTS:
    def __init__(self):
        self.keys_limit = None
        self.deleted = []

    def __len__(self):
        return 12345

    def keys(self, limit=None):
        self.keys_limit = limit
        return [1, 2, 3]

    def get_by_id(self, row_id):
        payloads = {
            1: {"agent": "target"},
            2: {"agent": "other"},
            3: {"agent": "target"},
        }
        return row_id, payloads[row_id]

    def delete(self, row_id):
        self.deleted.append(row_id)


class _FakeState(dict):
    def enable_auto_pack(self):
        pass


def test_clear_fts_scans_past_default_limit(monkeypatch, tmp_path):
    fake_fts = _FakeFTS()

    monkeypatch.setattr(
        "kohakuterrarium.session.memory.TextVault", lambda *a, **k: fake_fts
    )
    monkeypatch.setattr(
        "kohakuterrarium.session.memory.KVault", lambda *a, **k: _FakeState()
    )

    memory = SessionMemory(str(tmp_path / "x.kohakutr"))
    memory._clear_fts("target")

    assert fake_fts.keys_limit == len(fake_fts) + 1
    assert fake_fts.deleted == [1, 3]
