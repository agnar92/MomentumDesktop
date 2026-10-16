from desktop import session


def test_touch_order_prune(tmp_path):
    sess = session.load(tmp_path)
    assert sess == {"recent": [], "open": [], "launcher": False, "main_hidden": False, "symbols": [], "darvas_pure": False, "chart": {}}
    for sid in ("a", "b", "a", "c"):
        session.touch(sess, sid)
    assert sess["recent"] == ["c", "a", "b"]
    items = [{"id": "z", "name": "Zeta"}, {"id": "a", "name": "Alfa"}, {"id": "b", "name": "Beta"}, {"id": "c", "name": "Ce"}, {"id": "y", "name": "Yankee"}]
    assert [s["id"] for s in session.order(items, sess)] == ["c", "a", "b", "y", "z"]   # nieotwierane na końcu alfabetycznie
    sess["open"] = ["a", "gone"]
    session.prune(sess, ["a", "c"])
    assert sess["recent"] == ["c", "a"] and sess["open"] == ["a"]
    session.save(tmp_path, sess)
    assert session.load(tmp_path)["recent"] == ["c", "a"]
