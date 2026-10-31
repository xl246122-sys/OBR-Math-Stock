from app.research import OutcomeTracker


def test_future_samples_do_not_appear_before_horizon_and_no_future_event_time():
    emitted=[]
    tracker=OutcomeTracker(lambda result,now:emitted.append(result))
    tracker.add({"candidate_id":"x","symbol":"TEST","source_ms":1000,"reference_price":"100"},10000000)
    tracker.sample("TEST","102",300000,300000)
    assert emitted==[]
    tracker.sample("TEST","103",301000,300999)
    assert emitted==[]
    tracker.sample("TEST","103",301000,301000)
    assert emitted[0]["return"]=="0.03" and emitted[0]["horizon_minutes"]==5
    assert emitted[0]["quality"]=="SAMPLED"


def test_missing_prices_are_missing_not_zero_and_state_clears():
    emitted=[]
    tracker=OutcomeTracker(lambda result,now:emitted.append(result))
    tracker.add({"candidate_id":"x","symbol":"TEST","source_ms":0,"reference_price":"100"},4000000)
    tracker.expire(5000000)
    assert len(emitted)==5
    assert all(row["return"] is None and row["quality"]=="MISSING" for row in emitted)
    assert tracker.count==0


def test_restart_preserves_completed_horizons_and_marks_partial_excursions():
    emitted=[]
    tracker=OutcomeTracker(lambda result,now:emitted.append(result))
    tracker.add({"candidate_id":"x","symbol":"TEST","source_ms":0,"reference_price":"100","restored":True},4000000,[5])
    tracker.sample("TEST","101",900000,900000)
    assert emitted[0]["horizon_minutes"]==15
    assert emitted[0]["quality"]=="PARTIAL_AFTER_RESTART"
