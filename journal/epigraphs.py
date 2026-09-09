"""A small, curated book of Stoic epigraphs for the top of the day's page.

All public domain: Marcus Aurelius (*Meditations*), Seneca (*Letters to
Lucilius*, the essays) and Epictetus (*Enchiridion*, *Discourses*). The line
is chosen deterministically from the date, so a given day always greets you
with the same one -- an almanac, not a slot machine. It never touches what you
write and is never saved.
"""
from __future__ import annotations

from datetime import date as Date

# (quote, who). Kept short -- an epigraph is read in a breath, then left behind.
EPIGRAPHS: list[tuple[str, str]] = [
    ("You have power over your mind — not outside events. Realize this, and you will find strength.", "Marcus Aurelius"),
    ("Confine yourself to the present.", "Marcus Aurelius"),
    ("Waste no more time arguing about what a good man should be. Be one.", "Marcus Aurelius"),
    ("The happiness of your life depends upon the quality of your thoughts.", "Marcus Aurelius"),
    ("Very little is needed to make a happy life; it is all within yourself, in your way of thinking.", "Marcus Aurelius"),
    ("When you arise in the morning, think of what a precious privilege it is to be alive.", "Marcus Aurelius"),
    ("Do every act of your life as if it were your last.", "Marcus Aurelius"),
    ("Look well into thyself; there is a source of strength which will always spring up if thou wilt always look there.", "Marcus Aurelius"),
    ("It is not death that a man should fear, but he should fear never beginning to live.", "Marcus Aurelius"),
    ("We suffer more often in imagination than in reality.", "Seneca"),
    ("Luck is what happens when preparation meets opportunity.", "Seneca"),
    ("Every new beginning comes from some other beginning's end.", "Seneca"),
    ("As long as you live, keep learning how to live.", "Seneca"),
    ("He who is brave is free.", "Seneca"),
    ("It is not that we have a short time to live, but that we waste a lot of it.", "Seneca"),
    ("Difficulties strengthen the mind, as labour does the body.", "Seneca"),
    ("Let us prepare our minds as if we'd come to the very end of life.", "Seneca"),
    ("It is the power of the mind to be unconquerable.", "Seneca"),
    ("Make the best use of what is in your power, and take the rest as it happens.", "Epictetus"),
    ("It's not what happens to you, but how you react to it that matters.", "Epictetus"),
    ("No man is free who is not master of himself.", "Epictetus"),
    ("First say to yourself what you would be; and then do what you have to do.", "Epictetus"),
    ("Wealth consists not in having great possessions, but in having few wants.", "Epictetus"),
    ("He is a wise man who does not grieve for the things which he has not, but rejoices for those which he has.", "Epictetus"),
    ("Men are disturbed not by things, but by the views which they take of things.", "Epictetus"),
    ("If you wish to be a writer, write.", "Epictetus"),
]


def for_day(day: Date) -> tuple[str, str]:
    """The (quote, author) for a given day -- stable for that date."""
    return EPIGRAPHS[day.toordinal() % len(EPIGRAPHS)]
