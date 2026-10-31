"""Transactional paper state. A failed save rolls back memory and latches a halt."""
import json
import threading
from app.execution import PaperBroker


class PaperAccount:
    METHODS = frozenset({"submit","submit_exit","cancel","expire","on_quote","protect_positions","rollover","cycle"})

    def __init__(self, store, initial=None):
        self.store = store
        self.lock = threading.Lock()
        self.failure = None
        state = store.load_paper_state()
        if state is None:
            if initial is None:
                raise ValueError("PAPER_BUDGET_REQUIRED")
            self.broker = initial
            store.save_paper_state(initial.snapshot())
        else:
            self.broker = PaperBroker.restore(state)

    def execute(self, method, *args, **kwargs):
        if method not in self.METHODS:
            raise ValueError("UNSUPPORTED_PAPER_OPERATION")
        with self.lock:
            if self.failure:
                raise RuntimeError(self.failure)
            before = json.loads(json.dumps(self.broker.snapshot(), default=str))
            try:
                result = getattr(self.broker, method)(*args, **kwargs)
            except Exception:
                self.broker = PaperBroker.restore(before)
                raise
            try:
                after = json.loads(json.dumps(self.broker.snapshot(), default=str))
                if after != before:
                    self.store.save_paper_state(after)
            except Exception:
                self.broker = PaperBroker.restore(before)
                self.failure = "PAPER_STORAGE_FAILED"
                raise RuntimeError(self.failure) from None
            return result
