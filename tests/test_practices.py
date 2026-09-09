from journal.practices import DEFAULT, list_practices, load_practice

NEW_SLUGS = {"avoiding", "decision", "week", "morning"}


def test_every_practice_is_well_formed():
    for practice in list_practices():
        assert practice.name and practice.name.strip()
        assert isinstance(practice.arc, int) and practice.arc >= 0
        # `free` is the deliberately blank default: a page with no frame at
        # all. Every practice that does supply a frame must supply the whole
        # frame -- an opening to seed the day and an addendum for the question.
        if practice.slug != DEFAULT:
            assert len(practice.openings) >= 1
            assert practice.addendum and practice.addendum.strip()


def test_the_four_new_practices_are_present():
    slugs = {p.slug for p in list_practices()}
    assert NEW_SLUGS <= slugs


def test_free_writing_comes_first():
    assert list_practices()[0].slug == "free"


def test_arcs_are_what_the_files_declare():
    assert load_practice("week").arc == 7
    assert load_practice("decision").arc == 1
    assert load_practice("avoiding").is_open_ended


def test_no_addendum_asks_the_banned_feelings_question():
    for practice in list_practices():
        assert "how did that make you feel" not in practice.addendum.lower()
