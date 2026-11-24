"""InterviewConductor tests: fake clock, frames, finals and ticks in; Actions out."""

from app.modules.interview.composition import TurnRules
from app.modules.interview.conductor import (
    Advanced,
    HideQuestion,
    InterviewConductor,
    ReplayRejected,
    RoundFinished,
    ShowQuestion,
)
from app.modules.interview.questions import FinalUtterance, PlannedQuestion, RubricItem

TEXT = "가나다라마바사"  # 7 chars -> reading 4000 ms
READING = 4000


def question(qid, *, subtype="motivation", round=1):
    return PlannedQuestion(
        id=qid,
        kind="common",
        subtype=subtype,
        text=TEXT,
        intent="",
        source_quote=None,
        rubric_items=[RubricItem.UNDERSTANDING],
        parent_id=None,
        bank_id=qid,
        round=round,
    )


def utterance(uid, start, end, text="답변입니다", voiced=None):
    return FinalUtterance(uid, start, end, text, voiced if voiced is not None else end - start)


def speak(c, start, end, step=500):
    """Feed voiced frames covering [start, end)."""
    actions = []
    t = start
    while t < end:
        actions += c.on_frame(t, min(t + step, end), True)
        t += step
    return actions


def make(*ids, rules=None, subtypes=None):
    subtypes = subtypes or {}
    qs = [question(i, subtype=subtypes.get(i, "motivation")) for i in ids]
    return InterviewConductor(qs, rules or TurnRules())


def test_start_shows_first_question_with_timings():
    c = make("q1", "q2")
    assert c.start(0) == [ShowQuestion("q1", TEXT, READING, 120000)]
    c2 = make("q1", subtypes={"q1": "self_introduction"})
    assert c2.start(0) == [ShowQuestion("q1", TEXT, READING, 90000)]


def test_question_hides_when_reading_time_ends():
    c = make("q1")
    c.start(1000)
    assert c.tick(4999, 0) == []
    assert c.tick(5000, 0) == [HideQuestion("q1")]
    assert c.tick(5200, 0) == []


def test_question_hides_on_first_voiced_frame_before_reading_ends():
    c = make("q1")
    c.start(0)
    assert c.on_frame(1000, 1020, False) == []
    assert c.on_frame(2000, 2020, True) == [HideQuestion("q1")]
    assert c.on_frame(2020, 2040, True) == []
    assert c.tick(READING, 0) == []  # already hidden


def test_silence_advances_after_four_seconds_once_min_answer_time_passed():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 20000)
    assert c.tick(23999, 0) == []
    assert c.tick(24000, 0) == [
        Advanced("q1", "silence"),
        ShowQuestion("q2", TEXT, READING, 120000),
    ]


def test_silence_does_not_advance_before_ten_seconds_of_answer_time():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 6000)  # answer starts at 4000, then silence
    assert c.tick(10000, 0) == []  # 4 s of silence but only 6 s of answer time
    assert c.tick(13999, 0) == []
    assert c.tick(14000, 0) == [
        Advanced("q1", "silence"),
        ShowQuestion("q2", TEXT, READING, 120000),
    ]


def test_time_limit_advances_at_end_of_current_utterance():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 130000)
    assert c.tick(124000, 0) == []  # past the 2 min limit but still speaking
    assert c.tick(130400, 0) == []  # utterance ended less than 500 ms ago
    assert c.tick(130500, 0) == [
        Advanced("q1", "time_limit"),
        ShowQuestion("q2", TEXT, READING, 120000),
    ]


def test_self_introduction_uses_ninety_second_limit():
    c = make("q1", "q2", subtypes={"q1": "self_introduction"})
    c.start(0)
    speak(c, 4000, 95000)
    assert c.tick(93999, 0) == []
    actions = c.tick(95500, 0)
    assert actions[0] == Advanced("q1", "time_limit")


def test_no_response_after_fifteen_seconds_from_reading_end():
    c = make("q1", "q2")
    c.start(0)
    assert c.tick(4000, 0) == [HideQuestion("q1")]
    assert c.tick(18999, 0) == []
    assert c.tick(19000, 0) == [
        Advanced("q1", "no_response"),
        ShowQuestion("q2", TEXT, READING, 120000),
    ]
    record = c.items()[0]
    assert record.advance_reason == "no_response"
    assert record.answer_started_ms is None
    assert record.transcript == "" and record.utterances == []


def test_replay_once_pauses_no_response_clock_and_second_is_rejected():
    c = make("q1", "q2")
    c.start(0)
    c.tick(4000, 0)
    c.tick(5000, 0)
    assert c.on_replay(5000) == [ShowQuestion("q1", TEXT, READING, 120000)]
    assert c.on_replay(6000) == [ReplayRejected("q1")]
    assert c.tick(9000, 0) == [HideQuestion("q1")]
    # No-response deadline moves back by the 4 s the question was on screen again.
    assert c.tick(19000, 0) == []
    assert c.tick(22999, 0) == []
    assert c.tick(23000, 0)[0] == Advanced("q1", "no_response")
    assert c.items()[0].replay_used is True


def test_replay_is_rejected_while_question_is_still_visible_without_using_it_up():
    c = make("q1")
    c.start(0)
    assert c.on_replay(1000) == [ReplayRejected("q1")]
    c.tick(4000, 0)
    assert c.on_replay(4500) == [ShowQuestion("q1", TEXT, READING, 120000)]


def test_replay_pauses_answer_and_silence_clocks():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 10000)
    c.tick(10000, 0)
    assert c.on_replay(10000) == [ShowQuestion("q1", TEXT, READING, 120000)]
    assert c.tick(14000, 0) == [HideQuestion("q1")]
    # Without the pause this would advance at 14000 (4 s silence, 10 s answer).
    assert c.tick(14000 + 3999, 0) == []
    assert c.tick(18000, 0)[0] == Advanced("q1", "silence")


def test_speaking_during_replay_hides_question_and_resumes_clocks():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 6000)
    c.tick(6000, 0)
    c.on_replay(6000)  # would show until 10000
    assert c.on_frame(7000, 7500, True) == [HideQuestion("q1")]
    speak(c, 7500, 20000)
    assert c.tick(23999, 0) == []
    assert c.tick(24000, 0)[0] == Advanced("q1", "silence")


def test_advance_waits_for_pending_finals_up_to_three_second_cap():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 20000)
    assert c.tick(24000, 1) == []
    assert c.tick(26999, 1) == []
    assert c.tick(27000, 1) == [
        Advanced("q1", "silence"),
        ShowQuestion("q2", TEXT, READING, 120000),
    ]


def test_advance_happens_as_soon_as_pending_finals_drain():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 20000)
    assert c.tick(24000, 2) == []
    assert c.tick(25000, 0)[0] == Advanced("q1", "silence")


def test_late_final_attaches_to_original_question():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 20000)
    c.tick(24000, 1)
    c.tick(27000, 1)  # capped, q2 shown at 27000
    c.on_final(utterance("u1", 15000, 19800, "늦게 도착한 답변"))
    c.stop(30000)
    first, second = c.items()
    assert [u.utterance_id for u in first.utterances] == ["u1"]
    assert first.transcript == "늦게 도착한 답변"
    assert second.utterances == []


def test_utterance_straddling_boundary_stays_with_its_start_question():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 20000)
    c.tick(24000, 0)  # q2 shown at 24000
    c.on_final(utterance("u1", 23000, 25000, "경계에 걸친 발화"))  # starts in q1's window
    c.on_final(utterance("u2", 24500, 26000, "다음 질문 답변"))
    c.stop(30000)
    first, second = c.items()
    assert [u.utterance_id for u in first.utterances] == ["u1"]
    assert [u.utterance_id for u in second.utterances] == ["u2"]
    assert second.transcript == "다음 질문 답변"


def test_voiced_frames_from_before_the_question_do_not_start_its_answer():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 20000)
    c.tick(24000, 0)
    assert c.on_frame(23800, 24000, True) == []  # tail of q1's speech
    c.stop(30000)
    assert c.items()[1].answer_started_ms is None


def test_item_records_timing_and_utterances_sorted_by_start():
    c = make("q1")
    c.start(500)
    speak(c, 4000, 20000)
    c.on_final(utterance("u2", 12000, 19000, "둘째"))
    c.on_final(utterance("u1", 4000, 11000, "첫째"))
    c.tick(24000, 0)
    (record,) = c.items()
    assert (record.shown_ms, record.answer_started_ms, record.ended_ms) == (500, 4000, 24000)
    assert [u.utterance_id for u in record.utterances] == ["u1", "u2"]
    assert record.transcript == "첫째 둘째"
    assert record.advance_reason == "silence"


def test_last_question_finishes_the_round_and_second_round_can_be_added():
    c = make("q1")
    c.start(0)
    speak(c, 4000, 20000)
    assert c.tick(24000, 0) == [Advanced("q1", "silence"), RoundFinished(1)]
    assert c.tick(30000, 0) == []
    follow_up = question("f1", subtype="own_role", round=2)
    assert c.add_questions([follow_up], 40000) == [ShowQuestion("f1", TEXT, READING, 120000)]
    assert c.tick(44000, 0) == [HideQuestion("f1")]


def test_second_round_runs_and_finishes():
    c = make("q1")
    c.start(0)
    c.tick(4000, 0)
    c.tick(19000, 0)  # no response -> round 1 finished
    f1 = question("f1", subtype="own_role", round=2)
    assert c.add_questions([f1], 40000) == [ShowQuestion("f1", TEXT, READING, 120000)]
    assert c.tick(44000, 0) == [HideQuestion("f1")]
    assert c.tick(59000, 0) == [Advanced("f1", "no_response"), RoundFinished(2)]
    assert [r.question.id for r in c.items()] == ["q1", "f1"]


def test_add_questions_with_nothing_to_add_finishes_round_two():
    c = make("q1")
    c.start(0)
    c.tick(4000, 0)
    c.tick(19000, 0)
    assert c.add_questions([], 20000) == [RoundFinished(2)]


def test_stop_ends_current_question_with_stopped_reason():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 8000)
    assert c.stop(9000) == [Advanced("q1", "stopped")]
    assert c.tick(40000, 0) == []
    (record,) = c.items()
    assert (record.advance_reason, record.ended_ms) == ("stopped", 9000)


def test_stop_while_question_visible_hides_it_first():
    c = make("q1")
    c.start(0)
    assert c.stop(1000) == [HideQuestion("q1"), Advanced("q1", "stopped")]


def test_stop_during_round_break_or_twice_is_a_no_op():
    c = make("q1")
    c.start(0)
    c.tick(4000, 0)
    c.tick(19000, 0)  # round finished, nothing on screen
    assert c.stop(20000) == []
    c2 = make("q1")
    c2.start(0)
    c2.stop(100)
    assert c2.stop(200) == []


def test_unvoiced_frames_never_start_the_answer():
    c = make("q1")
    c.start(0)
    for t in range(4000, 12000, 20):
        c.on_frame(t, t + 20, False)
    assert c.tick(19000, 0)[1] == Advanced("q1", "no_response")


def advances(actions):
    return [a for a in actions if isinstance(a, Advanced)]


def test_continuous_voice_cannot_keep_a_question_forever():
    c = make("q1", "q2")
    c.start(0)
    found = []
    for t in range(4000, 600000, 500):
        c.on_frame(t, t + 500, True)
        found += advances(c.tick(t + 500, 0))
        if found:
            break
    assert found == [Advanced("q1", "time_limit")]
    # limit (120 s after answer start at 4 s) plus one maximum utterance (8 s)
    assert t + 500 <= 4000 + 120000 + 8000 + 500


def test_lagging_voiced_frame_does_not_cancel_a_fresh_replay():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 8000)
    c.tick(8000, 0)
    assert c.on_replay(8100) == [ShowQuestion("q1", TEXT, READING, 120000)]
    assert c.on_frame(7980, 8000, True) == []  # started before the replay: lagging speech
    assert c.tick(12100, 0) == [HideQuestion("q1")]  # replay still ran its full reading time
    # 4 s of replay are excluded: min answer time (10 s) is reached at 18000, not at 14000.
    assert c.tick(17999, 0) == []
    assert advances(c.tick(18000, 0)) == [Advanced("q1", "silence")]


def test_min_answer_time_runs_on_the_replay_paused_clock():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 6000)
    c.tick(6000, 0)
    c.on_replay(6000)  # clocks stop until 10000
    c.tick(10000, 0)
    # Silence alone would allow 14000; answer time minus replay only reaches 10 s at 18000.
    assert advances(c.tick(14000, 0)) == []
    assert advances(c.tick(17999, 0)) == []
    assert advances(c.tick(18000, 0)) == [Advanced("q1", "silence")]


def test_silence_clock_excludes_replay_between_last_voice_and_now():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 20000)  # 16 s of answer already
    c.tick(20000, 0)
    c.on_replay(20000)  # pause 20000-24000
    assert advances(c.tick(24000, 0)) == []
    assert advances(c.tick(27999, 0)) == []
    assert advances(c.tick(28000, 0)) == [Advanced("q1", "silence")]


def test_speaking_during_replay_ends_the_pause_early():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 6000)
    c.tick(6000, 0)
    c.on_replay(6000)  # would pause until 10000
    assert c.on_frame(7000, 7500, True) == [HideQuestion("q1")]  # pause is cut to 6000-7000
    # Answer time = now - 1 s of pause - 4000, so 10 s is reached at 15000 (18000 if uncut).
    assert advances(c.tick(14999, 0)) == []
    assert advances(c.tick(15000, 0)) == [Advanced("q1", "silence")]


def test_fired_advance_reason_survives_new_speech_while_waiting_for_finals():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 20000)
    assert c.tick(24000, 1) == []  # silence reason fires and is committed
    speak(c, 24500, 25000)
    assert c.tick(25500, 1) == []
    assert advances(c.tick(27000, 1)) == [Advanced("q1", "silence")]


def test_replay_is_rejected_while_an_advance_is_pending():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 20000)
    c.tick(24000, 1)
    assert c.on_replay(24500) == [ReplayRejected("q1")]


def test_speech_carried_over_past_the_wait_cap_does_not_hide_or_answer_next_question():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 20000)
    c.tick(24000, 1)
    speak(c, 24500, 27000)  # user resumes speaking while finals are pending
    assert advances(c.tick(27000, 1)) == [Advanced("q1", "silence")]  # q2 shown at 27000
    assert speak(c, 27000, 29000) == []  # same run that began before q2 appeared
    assert c.on_frame(30000, 30500, True) == [HideQuestion("q2")]  # a new utterance
    c.stop(31000)
    assert c.items()[1].answer_started_ms == 30000


def test_final_whose_preroll_precedes_the_question_goes_to_the_new_question():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 20000)
    c.tick(24000, 0)  # q2 appears at 24000; the user starts talking at 24100
    c.on_final(utterance("u1", 23900, 26000, "새 질문 답변"))  # start_ms includes 200 ms pre-roll
    c.stop(30000)
    first, second = c.items()
    assert first.utterances == []
    assert [u.utterance_id for u in second.utterances] == ["u1"]


def test_carry_over_protection_ends_after_one_maximum_utterance():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 20000)
    c.tick(24000, 1)
    speak(c, 24500, 27000)
    c.tick(27000, 1)  # q2 shown at 27000
    assert speak(c, 27000, 35000) == []  # carried-over run is ignored for 8 s
    assert c.on_frame(35000, 35500, True) == [HideQuestion("q2")]  # endless voice is not ignored


def test_preroll_shift_never_moves_a_final_past_its_own_end():
    c = make("q1", "q2")
    c.start(0)
    speak(c, 4000, 20000)
    c.tick(24000, 0)  # q2 appears at 24000
    c.on_final(utterance("u1", 23900, 23950, "짧은 발화"))  # 23900 + 200 would pass 24000
    c.stop(30000)
    first, second = c.items()
    assert [u.utterance_id for u in first.utterances] == ["u1"]
    assert second.utterances == []
