"""A sample reading, built without the model, so anyone can see what the
report looks like before committing an hour to the fourteen questions.

Everything here is invented for one fictional person — "Jordan", who quit a
salaried design job in April to start a one-person woodworking workshop. The
numbers, people, and quotes are hand-written to match the shape of a real
reading and its quality bar: specific people and projects, no platitudes, a
'next' that names an actual thing. It produces a fully populated YearSummary,
a Portrait with every section and the four area scores, and a Deep reading.
Nothing here touches disk or the model; see_demo() in journey.py just drops
these into the report screen and renders it.
"""
from __future__ import annotations

from datetime import date as Date

from journal.portrait import Deep, Portrait, Section
from journal.yearpage import Person, Thread, YearSummary


def _d(month: int, day: int) -> Date:
    return Date(2025, month, day)


def demo_summary() -> YearSummary:
    """The facts, as if aggregated from a real year of answers."""
    s = YearSummary()
    s.days = 14
    s.words = 3480
    s.first = _d(1, 11)
    s.last = _d(12, 19)
    s.people = [
        Person("Ren", 6, _d(1, 11), _d(12, 19)),
        Person("Mum", 4, _d(2, 9), _d(11, 22)),
        Person("Marcus", 3, _d(1, 11), _d(10, 4)),
        Person("Dolores", 3, _d(4, 26), _d(11, 8)),
        Person("Nadia", 2, _d(6, 14), _d(9, 27)),
    ]
    s.places = [
        ("the workshop", 6),
        ("the lido", 3),
        ("Mum's house", 2),
        ("the timber yard", 2),
    ]
    s.threads = [
        Thread("the workshop", 6, 8, [
            (_d(4, 26), "handed in my notice on a Tuesday and threw up on the Wednesday"),
            (_d(6, 14), "the first commission I was allowed to sign my own name to"),
            (_d(11, 8), "past the six-month mark everyone said would close me"),
        ]),
        Thread("money, unlooked at", 4, 6, [
            (_d(5, 3), "the account was a number I stopped opening the app to see"),
            (_d(9, 27), "told Ren we were fine one time too many"),
        ]),
        Thread("Mum's hip", 3, 5, [
            (_d(2, 9), "the surgery, and the drive up every other Saturday after"),
            (_d(11, 22), "she walked me to the car without the stick this time"),
        ]),
        Thread("swimming through winter", 2, 4, [
            (_d(1, 11), "the lido at 7am, cold enough to empty my head"),
        ]),
    ]
    s.circling = [s.threads[0], s.threads[1], s.threads[2]]
    s.energy_weeks = [
        (_d(1, 11), 2.8), (_d(2, 9), 2.0), (_d(4, 26), 1.7),
        (_d(6, 14), 3.6), (_d(8, 2), 2.4), (_d(9, 27), 2.1),
        (_d(11, 8), 3.9), (_d(12, 19), 3.5),
    ]
    s.unresolved = [
        (_d(9, 27), "whether to take on a second pair of hands or stay one person"),
        (_d(10, 4), "the call to Marcus I keep drafting and not sending"),
    ]
    s.unanswered = [
        (_d(5, 3), "Money, honestly. What did it make possible this year, and what "
                   "did it make you avoid looking at?"),
        (_d(10, 4), "What did you lose this year, and what did losing it show you?"),
    ]
    s.in_your_words = [
        (_d(1, 11), "the lido at 7am, cold enough to empty my head"),
        (_d(4, 26), "handed in my notice on a Tuesday and threw up on the Wednesday"),
        (_d(6, 14), "the first commission I was allowed to sign my own name to"),
        (_d(11, 8), "past the six-month mark everyone said would close me"),
        (_d(12, 19), "poorer and more myself than I've ever been"),
    ]
    s.answers = [
        ("What the year consisted of", "the workshop, the lido, and the drive to Mum's"),
        ("Love, kept or lost", "Ren, who paid the rent and didn't hold it over me"),
        ("Who you spent time with", "sawdust and a radio; not enough of Marcus"),
        ("What work asked and gave", "everything, and the first work that was mine"),
        ("Where your body stood", "swimming held; the sleep didn't"),
        ("What you made", "eleven pieces, and a workshop that's still open"),
        ("What you avoided", "the bank balance, and calling Marcus back"),
        ("Where you felt most yourself", "the workshop at dusk, radio on, hands busy"),
        ("The turning point", "the Tuesday I handed in my notice"),
        ("What you're quietly proud of", "I stayed open past the month they gave me"),
        ("The chapter's title", "'First Year, Own Hands', opening on whether to hire"),
        ("Where you stand", "poorer and more myself than I've ever been"),
    ]
    return s


def demo_portrait() -> Portrait:
    """The reading itself — a name, the year read back, the tension, and the
    four generous area scores."""
    p = Portrait()
    p.areas = [
        {
            "area": "Social",
            "score": 55,
            "direction": "steady",
            "working": "Dolores took you under her wing at the timber yard, and the "
                       "maker crowd you fell into is real — Nadia went from a "
                       "customer to someone you'd call.",
            "next": "Send Marcus the message you've drafted four times; his divorce "
                    "is the reason to call, not the reason it's awkward.",
        },
        {
            "area": "Love",
            "score": 74,
            "direction": "rising",
            "working": "Ren carried the rent through the lean months without holding "
                       "it over you, and the September talk turned quiet resentment "
                       "back into a team.",
            "next": "Show Ren the actual numbers before the next quarter, not after; "
                    "being carried without being told is its own kind of debt.",
        },
        {
            "area": "Goals",
            "score": 87,
            "direction": "rising",
            "working": "You walked out of a salaried job and put eleven pieces into "
                       "the world under your own name — the Hartley commission "
                       "delivered on time was proof it wasn't a fluke.",
            "next": "Price the next commission for what the work is worth, not for "
                    "the fear that they'll say no.",
        },
        {
            "area": "Body & self",
            "score": 52,
            "direction": "steady",
            "working": "You swam the lido through the whole winter — the one thing "
                       "that emptied your head on the worst-money mornings, and you "
                       "kept it.",
            "next": "Fix the sleep the way you fixed the swimming: a set time you "
                    "stop working in the workshop, not a time you hope to.",
        },
    ]
    p.sections = [
        Section(
            key="name",
            title="A name for where you stand",
            name="First Year, Own Hands",
            text="You spent the year trading a salary for work that is finally "
                 "yours, and you'd make the same trade again even on the frightened "
                 "days.",
        ),
        Section(
            key="year",
            title="Your year, read back to you",
            text="This was the year you jumped. You spent the first months bracing "
                 "— your mother's surgery in February, the drives up every other "
                 "Saturday — and then in April you did the thing you'd been "
                 "circling for years and handed in your notice, and were sick with "
                 "fear the next morning. What followed wasn't triumph, it was the "
                 "unglamorous middle: tight money you stopped looking at, invoices "
                 "that came late, a partner quietly carrying more than either of "
                 "you named. But the work was real. The Hartley commission in June "
                 "was the first thing you were allowed to sign your own name to, "
                 "and by November you'd passed the six-month mark people had "
                 "written you off at. The hinge was the Tuesday you resigned; what "
                 "it changed is that you now know you can do the frightening thing "
                 "and survive the ordinary weeks that come after it.",
        ),
        Section(
            key="tension",
            title="The tension underneath",
            name="The bench vs. the books",
            text="Underneath half your answers is the same split: you'd rather be "
                 "at the bench than at the books, and the not-looking is the one "
                 "thing that could actually close the workshop. You describe the "
                 "making in loving, present detail and the money in the past tense, "
                 "as a number you 'stopped opening the app to see.' It's the "
                 "self-reliance-versus-asking axis too — you'd sooner absorb the "
                 "stress alone than show Ren the balance or ask Dolores how she "
                 "priced her early work. The craft you can face; the selling of it "
                 "you keep leaving for tomorrow.",
        ),
        Section(
            key="avoiding",
            title="What you are avoiding, and what it costs",
            text="You avoided the numbers all year — the bank balance became an app "
                 "you didn't open — and you avoided calling Marcus back while he "
                 "went through his divorce. They're the same avoidance wearing two "
                 "coats: both are things you'd have to feel if you looked straight "
                 "at them. Not-looking at the money protected you from admitting how "
                 "close some months ran, and it cost you the chance to fix them "
                 "early and cost Ren the honesty of being carried knowingly. "
                 "Not-calling Marcus protected you from your own guilt, and it cost "
                 "you a friend at exactly the year he needed one.",
        ),
        Section(
            key="people",
            title="Your people, read honestly",
            text="Ren is the quiet spine of the year. They paid the rent through "
                 "the lean stretch and didn't hold it over you, and the resentment "
                 "that built by September was less about the money than about not "
                 "being told the truth of it. The love isn't in doubt; the "
                 "transparency is the thing still owed.\n\n"
                 "Mum is where your steadiness came from and went to. The "
                 "fortnightly drives after her surgery were a fixed point in a year "
                 "with few of them, and something in caring for her while building "
                 "the workshop made both feel less impossible.\n\n"
                 "Marcus is the relationship you let slide, and you know it — he's "
                 "the drafted message you never send. The friendship isn't broken, "
                 "but it's running on a credit you keep meaning to repay.",
        ),
        Section(
            key="strengths",
            title="What you are actually good at",
            items=[
                {"name": "Jumped without a net, on a Tuesday",
                 "evidence": "You resigned from a stable job to build the workshop "
                             "instead of waiting for a safe year that was never "
                             "going to arrive."},
                {"name": "Delivered the Hartley piece on time",
                 "evidence": "You finished a real commission to deadline in your "
                             "first months, when a miss would have ended the whole "
                             "thing."},
                {"name": "Drove to Mum's every other Saturday",
                 "evidence": "You kept the fortnightly trips north through your "
                             "busiest, brokest year without once making it her "
                             "problem."},
            ],
        ),
        Section(
            key="pattern",
            title="The pattern to watch",
            name="Says the money's fine when it isn't",
            text="When something's frightening, you tell people it's handled and "
                 "then handle it alone. You told Ren you were fine one time too "
                 "many, and you narrate the workshop's wins while stepping around "
                 "its balance. It shows up with Marcus too — you'd rather be the "
                 "one who's coping than the one who admits he's behind on a friend. "
                 "It costs you the help that's actually on offer, and it trains the "
                 "people closest to you to stop asking how you really are.",
        ),
        Section(
            key="standing",
            title="Where you stand",
            text="You stand poorer and more yourself than you've been, and clear-"
                 "eyed enough to hold both at once. Your own answers already point "
                 "where next: the making is working, so the growth isn't more "
                 "craft — it's the parts you've been avoiding. Look at the numbers "
                 "before they force you to. Tell Ren the truth of them. Send the "
                 "message to Marcus. The workshop survived the year it was supposed "
                 "to fail; what it needs now is a maker who'll also do the books.",
            keep="I stayed open past the month they gave me.",
        ),
    ]
    return p


def demo_deep() -> Deep:
    """The longer reading: a paragraph on a few answers, then a closing letter."""
    d = Deep()
    d.answers = [
        {
            "index": 8,
            "question": "What was the turning point — the moment, conversation, or "
                        "decision the whole year hinges on?",
            "reading": "You point to the Tuesday you handed in your notice, and "
                       "you're right, but notice the detail you chose to keep: being "
                       "sick with fear the next morning. The turning point isn't "
                       "that you were brave — it's that you were terrified and did "
                       "it anyway, and then got up on Wednesday and started. That's "
                       "the version of yourself the rest of the year is built on.",
        },
        {
            "index": 3,
            "question": "What did your work — paid or not — ask of you this year, "
                        "and what did it give back?",
            "reading": "The work asked for everything and most of your sleep, and "
                       "the thing it gave back wasn't money — it was your own name "
                       "on the Hartley piece. You write about the making with a "
                       "present-tense pleasure you give almost nothing else this "
                       "year. Guard that. It's the reason the hard middle was worth "
                       "sitting in.",
        },
        {
            "index": 6,
            "question": "What did you avoid all year — what is the thing you kept "
                        "steering around, and what did steering around it cost?",
            "reading": "The bank balance, and Marcus. You steered around both by "
                       "staying busy at the bench, and the cost is quiet: months "
                       "that ran closer than they needed to, and a friend who "
                       "learned not to expect a call back. Neither is beyond "
                       "repair, but both get more expensive the longer the app "
                       "stays closed.",
        },
    ]
    d.letter = (
        "Jordan,\n\n"
        "Read plainly, your year was this: you jumped, you were sick with fear, "
        "and you built anyway. You put eleven real things into the world with your "
        "name on them, you kept driving to your mother's, and you swam through the "
        "winter when the money was at its worst. That is not the year of someone "
        "who's failing.\n\n"
        "The one thing to carry into January is that you keep facing the hard "
        "things with your hands and avoiding them with your eyes. The bench you "
        "can look at; the books, the balance, the friend you owe a call — those "
        "you leave for a tomorrow that's always one commission away. You've proved "
        "you can do the frightening thing. The next frightening thing is smaller "
        "and duller than resigning: it's opening the app, and telling Ren the "
        "truth of what it says.\n\n"
        "You stayed open past the month they gave you. Now stay honest past it too.\n"
    )
    return d
