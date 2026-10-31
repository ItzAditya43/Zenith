

def test_reindex_waits_while_a_reply_is_live():
    import threading
    import time

    from app.services import rag_service

    done = threading.Event()
    with rag_service.live_reply():
        t = threading.Thread(target=lambda: (rag_service._wait_for_idle(5), done.set()))
        t.start()
        time.sleep(0.4)
        assert not done.is_set()
    t.join(2)
    assert done.is_set()
