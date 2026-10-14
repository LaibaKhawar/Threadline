from app.extraction.text import content_words, normalize_subject, split_sentences, split_signature, stable_hash, strip_quoted_reply


def test_strip_quoted_reply_removes_history() -> None:
    body = "Sounds good.\n\nOn Tue, Sep 15, 2026 at 10:00 Sarah wrote:\n> I'll send it Friday"
    assert strip_quoted_reply(body) == "Sounds good."
    assert strip_quoted_reply("Hi\n> quoted\nreal") == "Hi\nreal"


def test_signature_split() -> None:
    main, sig = split_signature("Hi Laiba,\n\nAttached.\n\nAhmed Khan\nEngineering Manager, Lumen Labs")
    assert main == "Hi Laiba,\n\nAttached."
    assert sig.startswith("Ahmed Khan")
    assert split_signature("Body\n\nThanks,\nSarah")[1] == "Sarah"


def test_sentences_keep_offsets() -> None:
    text = "First one. Second, e.g. with abbreviation. Third?"
    sents = split_sentences(text)
    assert [s.text for s in sents] == ["First one.", "Second, e.g. with abbreviation.", "Third?"]
    for s in sents:
        assert text[s.start : s.end] == s.text


def test_subject_normalisation_and_hash() -> None:
    assert normalize_subject("Re: FW: re: Plan") == "Plan"
    assert stable_hash("a", 1) == stable_hash("a", 1) != stable_hash("a", 2)
    assert content_words("The proposals were reviewed") == {"proposal", "review"}
